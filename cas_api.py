"""
ManageBac CAS HTTP layer.
All request formats verified via network recording 2026-03-19.
"""
import hashlib
import html as _html
import json
import re
import struct
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup

from cas_errors import NetworkError, ScraperError, SessionExpiredError

# ── Constants ────────────────────────────────────────────────────────────────

# BASE is intentionally empty. Every caller (cas_web routes, CLI commands,
# cas_tui) must pass an explicit `base` argument loaded from cfg["base"]
# (which the user configures at login time). The default-arg slots below
# exist only so old direct-function callers don't TypeError; if they
# happen to fall through with base="", URL construction will raise loudly
# rather than silently going to one specific school.
BASE = ""
PLACEHOLDER_TAG = "[CASMGR_PLACEHOLDER]"

# Stealth placeholder marker — hidden span injected into body HTML.
# Invisible when rendered in ManageBac; detectable by searching body_html.
PLACEHOLDER_MARKER = "casmgr-ph"

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
# Matches English dates like "March 17, 2026" or "March 17 2026"
_DATE_EN_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}", re.IGNORECASE
)

CSRF_RE = re.compile(
    r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
S3_RE = re.compile(
    r"https://managebac-cn-prod\.s3\.cn-north-1\.amazonaws\.com\.cn/[^\s\"'<>]+", re.I
)
def _blank_png(width: int = 100, height: int = 100) -> bytes:
    """Generate a valid blank white PNG (ManageBac requires real image size)."""
    row = b"\x00" + b"\xFF\xFF\xFF\xFF" * width   # filter=0, RGBA white opaque
    compressed = zlib.compress(row * height, 6)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Experience:
    cas_id: int
    name: str
    is_completed: bool = False


@dataclass
class Photo:
    id: int
    caption: str
    created_at: str
    s3_url: str = ""


@dataclass
class ReflectionEntry:
    rid: int
    kind: str           # journal | album | file | website | video | unknown
    group_date: str
    page_no: int
    pos: int
    body_html: Optional[str] = None
    photos: list[Photo] = field(default_factory=list)
    lo_ids: list[int] = field(default_factory=list)
    s3_urls: list[str] = field(default_factory=list)
    is_placeholder: Optional[bool] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def mb_date(date_str: Optional[str] = None) -> str:
    """Format date as ManageBac expects: 'March 19, 2026'."""
    dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.today()
    return dt.strftime("%B ") + str(dt.day) + dt.strftime(", %Y")


def _url_list(base: str, cas_id: int, page: int = 1) -> str:
    if page == 1:
        return f"{base}/student/ib/activity/cas/{cas_id}/reflections"
    return f"{base}/student/ib/activity/cas/{cas_id}/reflections/page/{page}"


def _url_edit(base: str, cas_id: int, rid: int) -> str:
    return f"{base}/student/ib/activity/cas/{cas_id}/reflections/{rid}/edit"


def _xhr_headers(base: str, csrf: str, referer: str) -> dict:
    return {
        "Accept": "text/javascript, application/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": csrf,
        "Referer": referer,
        "Origin": base,
    }


def _lo_fields(lo_ids: list[int]) -> list[tuple[str, str]]:
    """Always emit empty string first, then each id."""
    fields = [("evidence[learning_outcome_ids][]", "")]
    for lo in lo_ids:
        fields.append(("evidence[learning_outcome_ids][]", str(lo)))
    return fields


def _kind_from_classes(classes: list) -> str:
    m = {"journal-evidence": "journal", "album-evidence": "album",
         "file-evidence": "file", "website-evidence": "website", "video-evidence": "video"}
    for c in classes:
        if c in m:
            return m[c]
    return "unknown"


# ── Experiences list ─────────────────────────────────────────────────────────

_EXP_ID_RE = re.compile(r"/student/ib/activity/cas/(\d+)$")


def scan_experiences(html: str) -> list[Experience]:
    """Parse the CAS experiences list page → list of Experience."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[Experience] = []
    for card in soup.select("div.fusion-card-item.activity-tile"):
        link = card.select_one("h4.title a[href]")
        if not link:
            continue
        m = _EXP_ID_RE.search(link["href"])
        if not m:
            continue
        cas_id = int(m.group(1))
        name = link.get_text(strip=True)
        is_completed = bool(card.select_one("svg.fi-cas-completed-inverted"))
        results.append(Experience(cas_id=cas_id, name=name, is_completed=is_completed))
    return results


def fetch_experiences(s: "requests.Session", base: str = BASE) -> list[Experience]:
    """GET the experiences list page and return all experiences."""
    url = f"{base}/student/ib/activity/cas"
    r = s.get(url, timeout=30, allow_redirects=True)
    if r.url.endswith("/login"):
        raise SessionExpiredError("Session expired. Run: cas login")
    r.raise_for_status()
    return scan_experiences(r.text)


def fetch_proposal(s: "requests.Session", base: str, cas_id: int) -> dict:
    """GET experience overview page and extract proposal text + LO names.

    Returns dict with keys:
      name          — experience name
      proposal_text — full plain-text proposal (headings preserved)
      lo_names      — list of LO description strings
      strand        — detected strand string or ''
    """
    url = f"{base}/student/ib/activity/cas/{cas_id}"
    r = s.get(url, timeout=30, allow_redirects=True)
    if r.url.endswith("/login"):
        raise SessionExpiredError("Session expired. Run: cas login")
    r.raise_for_status()
    return parse_proposal(r.text)


def parse_proposal(html: str) -> dict:
    """Parse experience overview HTML. Usable offline (e.g. from saved HTML)."""
    soup = BeautifulSoup(html, "html.parser")

    # Experience name: prefer "EXPERIENCE NAME:" line in proposal text
    name = ""
    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True).split("|")[0].strip()
        if raw.lower() not in ("managebac", ""):
            name = raw

    # Proposal text — try multiple selectors ManageBac uses across different page variants
    proposal_text: Optional[str] = None
    for selector in (
        "div.fusion-section-content",
        "div.proposal-body",
        "div.activity-proposal",
        "div.redactor-styles",
    ):
        section = soup.select_one(selector)
        if section:
            parts = []
            for el in section.find_all(["p", "li", "h4"]):
                t = _html.unescape(el.get_text(" ", strip=True))
                if t:
                    parts.append(t)
            text = "\n\n".join(parts)
            if text:
                proposal_text = text
                break

    # LO names — deduplicate (page has two copies of proposal HTML)
    lo_seen: set[str] = set()
    lo_names: list[str] = []
    for li in soup.select("ol.list-unstyled li.fusion-card-item, li.lo-item"):
        t = li.get_text(" ", strip=True)
        t = re.sub(r"^\d+\s*", "", t).strip()
        if t and t not in lo_seen:
            lo_seen.add(t)
            lo_names.append(t)

    # Extract experience name from proposal text if not found in title
    if not name and proposal_text:
        m = re.search(r"EXPERIENCE NAME[:\s]+(.+)", proposal_text)
        if m:
            name = m.group(1).strip()

    # Strand detection from proposal text — collect ALL that appear, not just
    # the first. ManageBac experiences can span multiple strands (e.g.
    # "Creativity, Activity"); we preserve canonical order Creativity →
    # Activity → Service. Stored as a comma-separated string so the existing
    # TEXT column needs no schema migration; single-strand entries remain
    # unchanged (no comma).
    pt_lower = (proposal_text or "").lower()
    strands = [s for s in ("Creativity", "Activity", "Service")
                 if s.lower() in pt_lower]
    strand = ", ".join(strands)

    return {
        "name": name,
        "proposal_text": proposal_text,  # None if not found — DB will keep existing value
        "lo_names": lo_names,
        "strand": strand,
    }


# ── Session ──────────────────────────────────────────────────────────────────

def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        raise FileNotFoundError(f"Session file not found: {state_path}. Run: cas login")
    return json.loads(state_path.read_text(encoding="utf-8"))


def build_session(state: dict, base: str = BASE) -> requests.Session:
    domain = base.split("://", 1)[1].split("/")[0]
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    for c in state.get("cookies") or []:
        dom = (c.get("domain") or "").lstrip(".")
        # Accept cookies with matching domain OR empty domain (browser_cookie3 may omit it)
        if not dom or dom == domain or dom.endswith("." + domain):
            s.cookies.set(c["name"], c["value"],
                          domain=dom or domain, path=c.get("path") or "/")
    return s


def refresh_session(state_path: Path, base: str = BASE) -> dict:
    """
    Use stored auth_token to silently get a fresh session. No password needed.
    Updates state_path in-place and returns new state dict.
    Raises RuntimeError if auth_token is missing or invalid.
    """
    import mb_login
    state = load_state(state_path)
    auth_token = state.get("auth_token", "")
    if not auth_token:
        raise RuntimeError("No auth_token stored. Run: cas login")
    # Merge instead of replace — the state file also carries saved credentials
    # (email/password) that must survive a token refresh.
    state.update(mb_login.refresh_with_token(auth_token, base))
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return state


def check_login(s: requests.Session, base: str = BASE) -> bool:
    try:
        r = s.get(f"{base}/student", allow_redirects=True, timeout=15)
        return not r.url.endswith("/login") and r.status_code < 400
    except Exception:
        return False


def check_login_strict(s: requests.Session, base: str = BASE) -> bool:
    """Like check_login, but raises NetworkError when ManageBac can't be
    reached at all — so callers can tell 'offline' apart from 'logged out'
    instead of treating every network hiccup as an expired session."""
    try:
        r = s.get(f"{base}/student", allow_redirects=True, timeout=15)
    except requests.RequestException as e:
        raise NetworkError(f"ManageBac unreachable: {e}") from e
    return not r.url.endswith("/login") and r.status_code < 400


def get_csrf(s: requests.Session, page_url: str) -> str:
    r = s.get(page_url, timeout=30, allow_redirects=True)
    if r.url.endswith("/login"):
        raise SessionExpiredError("Session expired. Run: cas login")
    r.raise_for_status()
    m = CSRF_RE.search(r.text or "")
    if not m:
        raise RuntimeError("CSRF token not found on page")
    return m.group(1).strip()


# ── Scan / List ──────────────────────────────────────────────────────────────

def scan_page(html: str, page_no: int) -> list[ReflectionEntry]:
    """Parse one page of the CAS experience reflections list.

    Extracts body_html and photos DIRECTLY from the list page —
    no individual edit-page requests needed.

    Journal body:  <div class="fix-body-margins redactor-styles ...">…</div>
    Album photos:  <div class="photo" data-full-url="…" data-bs-title="caption">
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.evidences.activity-evidences") or soup
    entries: list[ReflectionEntry] = []
    current_date = ""
    pos = 0

    for child in container.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        child_classes = child.get("class") or []

        # Date separator (direct child)
        if child.name == "div" and "separated-date" in child_classes:
            span = child.find("span")
            if span:
                current_date = span.get_text(" ", strip=True)
            continue

        # Evidence div may be a direct child OR wrapped in div.fusion-card-list
        if child.name == "div" and "fusion-card-list" in child_classes:
            el = child.find("div", id=lambda x: x and x.startswith("evidence_"))
        elif child.name == "div" and (child.get("id") or "").startswith("evidence_"):
            el = child
        else:
            continue

        if el is None:
            continue
        classes = el.get("class") or []
        el_id = el.get("id") or ""

        try:
            rid = int(el_id.split("_")[-1])
        except ValueError:
            continue
        pos += 1
        kind = _kind_from_classes(classes)

        # ── Extract body_html directly from the list page ──────────────────
        body_html: Optional[str] = None
        rte = el.select_one(".fix-body-margins")
        if rte:
            raw = rte.decode_contents().strip()
            body_html = raw if raw else None

        # ── Extract album photos directly from the list page ───────────────
        photos: list[Photo] = []
        for i, photo_div in enumerate(el.select(".album .photo")):
            url = (photo_div.get("data-full-url")
                   or photo_div.get("data-url") or "")
            title = photo_div.get("data-bs-title") or ""
            # title format: "caption (Mar 19, 2026)" — strip trailing date
            caption = re.sub(r"\s*\(\w+ \d+, \d{4}\)\s*$", "", title).strip()
            created = ""
            # use hash of URL as a stable pseudo-ID (no edit page needed)
            pseudo_id = int(hashlib.md5(url.encode()).hexdigest()[:8], 16) if url else i
            photos.append(Photo(id=pseudo_id, caption=caption,
                                created_at=created, s3_url=url))

        # Detect placeholder from body_html:
        #   - old tag: [CASMGR_PLACEHOLDER]
        #   - stealth text marker: "casmgr-ph" (text inside span, survives ManageBac sanitizer)
        #   - fallback template markers: [Title] or [Date] present in body (unfilled template)
        is_ph: Optional[bool] = None
        if body_html is not None:
            is_ph = (
                PLACEHOLDER_TAG in body_html
                or PLACEHOLDER_MARKER in body_html
                or "[Title]" in body_html
                or "[Date]" in body_html
            )

        entries.append(ReflectionEntry(
            rid=rid, kind=kind,
            group_date=current_date, page_no=page_no, pos=pos,
            body_html=body_html,
            photos=photos,
            is_placeholder=is_ph,
        ))

    return entries


def iter_pages(s: requests.Session, base: str, cas_id: int,
               max_pages: int = 300) -> Iterator[tuple[int, list[ReflectionEntry]]]:
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        url = _url_list(base, cas_id, page)
        r = s.get(url, timeout=30, allow_redirects=True)
        if r.url.endswith("/login"):
            raise SessionExpiredError("Session expired. Run: cas login")
        entries = scan_page(r.text, page)
        new = [e for e in entries if e.rid not in seen]
        if not new:
            break
        for e in new:
            seen.add(e.rid)
        yield page, new


def fetch_edit_html(s: requests.Session, base: str, cas_id: int, rid: int) -> str:
    r = s.get(_url_edit(base, cas_id, rid), timeout=30, allow_redirects=True)
    if r.url.endswith("/login"):
        raise SessionExpiredError("Session expired. Run: cas login")
    r.raise_for_status()
    return r.text


def enrich(entry: ReflectionEntry, edit_html: str,
           placeholder_tag: str = PLACEHOLDER_TAG) -> None:
    """Fill body_html, photos, lo_ids, s3_urls, is_placeholder from edit page HTML."""
    soup = BeautifulSoup(edit_html, "html.parser")
    form = soup.find("form", id="edit_evidence") or soup

    # body — use decode_contents() to preserve inner HTML tags.
    # get_text() would strip <p>/<br> tags if the browser sends them unescaped.
    body_found = False
    for ta in soup.find_all("textarea"):
        if (ta.get("name") or "").endswith("[body]"):
            raw_body = ta.decode_contents().strip()
            # If still empty, fall back to get_text (entity-encoded content)
            if not raw_body:
                raw_body = _html.unescape(ta.get_text()).strip()
            entry.body_html = raw_body or ""
            body_found = True
            break
    if not body_found:
        raise ScraperError(
            f"rid={entry.rid}: body textarea not found, ManageBac DOM may have changed"
        )

    # s3 URLs — collect before photos so we can assign per-photo
    s3_urls = list(dict.fromkeys(S3_RE.findall(edit_html)))
    entry.s3_urls = s3_urls

    # photos (existing ones have an id field)
    raw: dict[int, dict] = {}
    for inp in form.find_all("input"):
        name = inp.get("name") or ""
        m = re.match(r"evidence\[photos_attributes\]\[(\d+)\]\[(\w+)\]", name)
        if m:
            idx, field_name = int(m.group(1)), m.group(2)
            raw.setdefault(idx, {})[field_name] = inp.get("value") or ""
    photo_idx = 0
    for idx in sorted(raw):
        p = raw[idx]
        if p.get("id"):
            # Assign S3 URL by position (one URL per photo, in order)
            s3 = s3_urls[photo_idx] if photo_idx < len(s3_urls) else ""
            entry.photos.append(Photo(
                id=int(p["id"]),
                caption=p.get("caption", ""),
                created_at=p.get("created_at", ""),
                s3_url=s3,
            ))
            photo_idx += 1

    # lo_ids
    for inp in form.find_all("input"):
        if "learning_outcome_ids" in (inp.get("name") or ""):
            v = inp.get("value") or ""
            if v.isdigit():
                entry.lo_ids.append(int(v))

    # placeholder detection — old explicit tag, stealth text marker, or unfilled template
    txt = edit_html
    body = entry.body_html or ""
    is_ph = (placeholder_tag in txt or placeholder_tag in _html.unescape(txt)
             or any(placeholder_tag in p.caption for p in entry.photos)
             or PLACEHOLDER_MARKER in body
             or "[Title]" in body or "[Date]" in body)
    entry.is_placeholder = is_ph


# ── LO constants ─────────────────────────────────────────────────────────────

LO_IDS = {
    "strength_growth":         142285,
    "challenge_skills":        142286,
    "initiative_planning":     142287,
    "commitment_perseverance": 142288,
    "collaborative_skills":    142289,
    "global_engagement":       142290,
    "ethics":                  142291,
}
# Display name fragments → ID (for fuzzy matching)
_LO_KEYWORD_MAP: list[tuple[str, int]] = [
    ("strength",      142285), ("growth",       142285),
    ("challenge",     142286), ("skill",         142286),
    ("initiative",    142287), ("planning",      142287),
    ("commitment",    142288), ("perseverance",  142288),
    ("collaborat",    142289),
    ("global",        142290), ("engagement",    142290),
    ("ethic",         142291),
]

def lo_names_to_ids(names: list[str]) -> list[int]:
    """Convert LO display names to IDs via keyword matching.
    Returns empty list when no name matches — caller decides the default."""
    ids: list[int] = []
    for name in names:
        nl = name.lower()
        for kw, lo_id in _LO_KEYWORD_MAP:
            if kw in nl and lo_id not in ids:
                ids.append(lo_id)
                break
    return ids

SERVICE_ACTION_TYPES = {
    "direct": "1", "indirect": "2", "advocacy": "3", "research": "4",
}

# ── Create experience ─────────────────────────────────────────────────────────

def create_experience(
    s: "requests.Session",
    base: str,
    csrf: str,
    *,
    name: str,
    notes_html: str,
    strand: str,                      # "creativity" | "activity" | "service"
    hours: float = 0.0,
    service_type: Optional[str] = None,   # "direct"|"indirect"|"advocacy"|"research"
    lo_ids: list[int] = (),
    start_date: Optional[str] = None,     # YYYY-MM-DD or None → today
    end_date: Optional[str] = None,
    supervisor_name: str = "",
    supervisor_title: str = "",
    supervisor_email: str = "",
    supervisor_phone: str = "",
    notify_advisor: bool = False,
    is_cas_project: bool = False,
    school_based: bool = False,
    community_based: bool = False,
    individual: bool = False,
    ongoing: bool = False,
) -> int:
    """Create a new CAS experience. Returns the new cas_id."""
    list_url = f"{base}/student/ib/activity/cas"

    start_str = mb_date(start_date)
    end_str   = mb_date(end_date)

    strand_l = strand.lower()
    data: list[tuple[str, str]] = [
        ("authenticity_token", csrf),
        ("cas_activity[name]", name),
        # strand checkboxes (hidden=0 then checkbox=1 if selected)
        ("cas_activity[creativity]", "1" if strand_l == "creativity" else "0"),
        ("cas_activity[creativity_hours]",
         str(hours) if strand_l == "creativity" else "0.0"),
        ("cas_activity[action]", "1" if strand_l == "activity" else "0"),
        ("cas_activity[action_hours]",
         str(hours) if strand_l == "activity" else "0.0"),
        ("cas_activity[service]", "1" if strand_l == "service" else "0"),
        ("cas_activity[service_hours]",
         str(hours) if strand_l == "service" else "0.0"),
        ("cas_activity[start_date]", start_str),
        ("cas_activity[end_date]",   end_str),
        ("cas_activity[supervisor_name]",           supervisor_name),
        ("cas_activity[supervisor_title]",          supervisor_title),
        ("cas_activity[supervisor_email]",          supervisor_email),
        ("cas_activity[supervisor_contact_number]", supervisor_phone),
        ("cas_activity[notes]", notes_html),
        # LO: always send empty first, then checked values
        ("cas_activity[learning_outcome_ids][]", ""),
    ]

    for lo_id in lo_ids:
        data.append(("cas_activity[learning_outcome_ids][]", str(lo_id)))

    if service_type and strand_l == "service":
        data.append(("cas_activity[service_action_type]",
                     SERVICE_ACTION_TYPES.get(service_type, "")))

    for flag, key in [
        (is_cas_project,   "cas_project"),
        (ongoing,          "ongoing_approach"),
        (school_based,     "school_based_approach"),
        (community_based,  "community_based_approach"),
        (individual,       "individual_approach"),
        (notify_advisor,   "notify_cas_advisor_email"),
    ]:
        data.append((f"cas_activity[{key}]", "1" if flag else "0"))

    data.append(("commit", "添加CAS 体验"))

    # Snapshot existing IDs before creating
    before = {e.cas_id for e in fetch_experiences(s, base)}

    r = s.post(list_url,
               headers={
                   "Referer": list_url,
                   "Origin":  base,
                   "X-Requested-With": "XMLHttpRequest",
                   "Accept": "text/javascript, application/javascript, */*",
               },
               data=data,
               allow_redirects=True,
               timeout=60)

    # Try to get new ID from redirect URL
    final_url = r.url
    m = re.search(r"/cas/(\d+)", final_url)
    if m:
        return int(m.group(1))

    # Fallback: poll for new experience ID
    for _ in range(15):
        time.sleep(1)
        after = {e.cas_id for e in fetch_experiences(s, base)}
        new = after - before
        if new:
            return max(new)

    raise RuntimeError(
        f"create_experience: could not detect new CAS ID. "
        f"HTTP {r.status_code}, final URL: {final_url}"
    )


# ── Create reflection ─────────────────────────────────────────────────────────

def _poll_new_rid(s: requests.Session, base: str, cas_id: int,
                  before: set[int], attempts: int = 30, sleep: float = 0.7) -> int:
    for _ in range(attempts):
        time.sleep(sleep)
        current: set[int] = set()
        for _, entries in iter_pages(s, base, cas_id, max_pages=1):
            for e in entries:
                current.add(e.rid)
        new = current - before
        if new:
            return max(new)
    raise RuntimeError("New reflection not detected after polling")


def create_journal(s: requests.Session, base: str, cas_id: int,
                   csrf: str, body_html: str, lo_ids: list[int]) -> int:
    list_url = _url_list(base, cas_id)
    before = {e.rid for _, pg in iter_pages(s, base, cas_id, 1) for e in pg}
    r = s.post(list_url,
               headers=_xhr_headers(base, csrf, list_url),
               data=[("type", "JournalEvidence"),
                     ("evidence[body]", body_html),
                     *_lo_fields(lo_ids),
                     ("commit", "添加新纪录")],
               allow_redirects=False, timeout=60)
    _check(r, "create_journal")
    return _poll_new_rid(s, base, cas_id, before)


def create_album(s: requests.Session, base: str, cas_id: int,
                 csrf: str, lo_ids: list[int],
                 photos: list[tuple[str, bytes, str]],   # (filename, data, caption)
                 date: Optional[str] = None) -> int:
    """photos = list of (filename, bytes, caption). date = YYYY-MM-DD or None for today."""
    list_url = _url_list(base, cas_id)
    date_str = mb_date(date)
    before = {e.rid for _, pg in iter_pages(s, base, cas_id, 1) for e in pg}

    data = [("type", "AlbumEvidence"), *_lo_fields(lo_ids), ("commit", "添加新纪录")]
    files = []
    for i, (fname, fdata, caption) in enumerate(photos):
        ct = "image/png" if fname.lower().endswith(".png") else "image/jpeg"
        files.append((f"evidence[photos_attributes][{i}][file]", (fname, fdata, ct)))
        data += [
            (f"evidence[photos_attributes][{i}][file_cache]", ""),
            (f"evidence[photos_attributes][{i}][caption]", caption),
            (f"evidence[photos_attributes][{i}][created_at]", date_str),
        ]

    r = s.post(list_url, headers=_xhr_headers(base, csrf, list_url),
               data=data, files=files, allow_redirects=False, timeout=180)
    _check(r, "create_album")
    rid = _poll_new_rid(s, base, cas_id, before)

    # Album body can't be set on create — patch it after settle
    time.sleep(4.0)
    return rid


def substitute_date_in_html(body_html: str, new_date_str: str) -> str:
    """Replace the first English date (Month DD, YYYY) in body_html with new_date_str
    (YYYY-MM-DD), then append the invisible stealth placeholder marker.
    If no date pattern is found, the body is returned as-is with the marker appended.

    The marker uses text content ('casmgr-ph') inside the span so it survives
    ManageBac's HTML sanitizer (which strips class/display but keeps font-size and text)."""
    year, month, day = (int(x) for x in new_date_str.split("-"))
    new_date = f"{_MONTH_NAMES[month - 1]} {day}, {year}"
    result, _ = _DATE_EN_RE.subn(new_date, body_html, count=1)
    marker = f'<span style="font-size:0;line-height:0">{PLACEHOLDER_MARKER}</span>'
    return result + marker


def create_stealth_placeholder(s: requests.Session, base: str, cas_id: int,
                                csrf: str, lo_ids: list[int],
                                date: str, template_body_html: str) -> int:
    """Create a stealth placeholder journal by cloning an existing reflection's body
    with the date substituted and a hidden marker injected.  Returns new rid."""
    body = substitute_date_in_html(template_body_html, date)
    return create_journal(s, base, cas_id, csrf, body, lo_ids)


def create_placeholder_pair(s: requests.Session, base: str, cas_id: int,
                             csrf: str, lo_ids: list[int],
                             date: Optional[str] = None,
                             tag: str = PLACEHOLDER_TAG) -> tuple[int, int]:
    date_str = date or time.strftime("%Y-%m-%d")
    label = f"{tag}|{date_str}"
    body = f"<p>{label}</p>"

    j_rid = create_journal(s, base, cas_id, csrf, body, lo_ids)
    a_rid = create_album(s, base, cas_id, csrf, lo_ids,
                         photos=[("placeholder.png", _blank_png(), label)],
                         date=date)
    return j_rid, a_rid


# ── Edit ─────────────────────────────────────────────────────────────────────

def edit_journal(s: requests.Session, base: str, cas_id: int, rid: int,
                 csrf: str, body_html: str, lo_ids: list[int]) -> None:
    edit_url = _url_edit(base, cas_id, rid)
    url = f"{base}/student/ib/activity/cas/{cas_id}/reflections/{rid}"
    r = s.post(url, headers=_xhr_headers(base, csrf, edit_url),
               data=[("_method", "patch"),
                     ("evidence[body]", body_html),
                     *_lo_fields(lo_ids),
                     ("commit", "保存更新")],
               allow_redirects=False, timeout=60)
    _check(r, "edit_journal")


def edit_album_add_photo(s: requests.Session, base: str, cas_id: int, rid: int,
                         csrf: str, photo_path: Path, caption: str = "",
                         date: Optional[str] = None) -> None:
    edit_url = _url_edit(base, cas_id, rid)
    url = f"{base}/student/ib/activity/cas/{cas_id}/reflections/{rid}"
    date_str = mb_date(date)

    entry = ReflectionEntry(rid=rid, kind="album", group_date="", page_no=0, pos=0)
    enrich(entry, fetch_edit_html(s, base, cas_id, rid))

    data: list[tuple[str, str]] = [("_method", "patch")]
    for i, p in enumerate(entry.photos):
        data += [
            (f"evidence[photos_attributes][{i}][caption]", p.caption),
            (f"evidence[photos_attributes][{i}][created_at]", p.created_at),
            (f"evidence[photos_attributes][{i}][_destroy]", "0"),
            (f"evidence[photos_attributes][{i}][id]", str(p.id)),
        ]
    new_idx = len(entry.photos)
    path = Path(photo_path)
    ct = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    files = [(f"evidence[photos_attributes][{new_idx}][file]", (path.name, path.read_bytes(), ct))]
    data += [
        (f"evidence[photos_attributes][{new_idx}][file_cache]", ""),
        (f"evidence[photos_attributes][{new_idx}][caption]", caption),
        (f"evidence[photos_attributes][{new_idx}][created_at]", date_str),
        *_lo_fields(entry.lo_ids),
        ("commit", "保存更新"),
    ]

    r = s.post(url, headers=_xhr_headers(base, csrf, edit_url),
               data=data, files=files, allow_redirects=False, timeout=180)
    _check(r, "edit_album_add_photo")


def delete_photo(s: requests.Session, base: str, cas_id: int, rid: int,
                 csrf: str, photo_id: int) -> None:
    edit_url = _url_edit(base, cas_id, rid)
    url = f"{base}/student/ib/activity/cas/{cas_id}/reflections/{rid}"

    entry = ReflectionEntry(rid=rid, kind="album", group_date="", page_no=0, pos=0)
    enrich(entry, fetch_edit_html(s, base, cas_id, rid))

    data: list[tuple[str, str]] = [("_method", "patch")]
    for i, p in enumerate(entry.photos):
        data += [
            (f"evidence[photos_attributes][{i}][caption]", p.caption),
            (f"evidence[photos_attributes][{i}][created_at]", p.created_at),
            (f"evidence[photos_attributes][{i}][_destroy]", "1" if p.id == photo_id else "0"),
            (f"evidence[photos_attributes][{i}][id]", str(p.id)),
        ]
    data += [*_lo_fields(entry.lo_ids), ("commit", "保存更新")]

    r = s.post(url, headers=_xhr_headers(base, csrf, edit_url),
               data=data, allow_redirects=False, timeout=60)
    _check(r, "delete_photo")


# ── Delete ───────────────────────────────────────────────────────────────────

def delete_reflection(s: requests.Session, base: str, cas_id: int,
                      rid: int, csrf: str) -> None:
    url = f"{base}/student/ib/activity/cas/{cas_id}/reflections/{rid}"
    r = s.delete(url, headers=_xhr_headers(base, csrf, _url_list(base, cas_id)),
                 allow_redirects=False, timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"delete failed: HTTP {r.status_code}: {r.text[:200]}")


# ── Cleanup placeholders ──────────────────────────────────────────────────────

def cleanup_placeholders(s: requests.Session, base: str, cas_id: int,
                          csrf: str, dry_run: bool = False,
                          sleep_s: float = 0.3, tag: str = PLACEHOLDER_TAG) -> list[int]:
    all_rids: list[int] = []
    for _, entries in iter_pages(s, base, cas_id):
        all_rids.extend(e.rid for e in entries)

    to_delete: list[int] = []
    for rid in all_rids:
        try:
            e = ReflectionEntry(rid=rid, kind="unknown", group_date="", page_no=0, pos=0)
            enrich(e, fetch_edit_html(s, base, cas_id, rid), tag)
            if e.is_placeholder:
                to_delete.append(rid)
        except ScraperError:
            # DOM parse failures on a single entry — skip it
            pass
        # Other exceptions (SessionExpiredError, network) bubble up
        if sleep_s:
            time.sleep(sleep_s)

    if not dry_run:
        for rid in to_delete:
            delete_reflection(s, base, cas_id, rid, csrf)
            if sleep_s:
                time.sleep(sleep_s)
    return to_delete


# ── Backup ───────────────────────────────────────────────────────────────────

# ── Self-Assessment (SA) answers ─────────────────────────────────────────────
# ManageBac renders all SA questions for an experience as ONE form on
# /student/ib/activity/cas/<id>/answers, posted whole to .../update_answers.
# We round-trip every form field and only swap the answer textareas we edit,
# so the code stays agnostic to ManageBac's exact field naming.

def _sa_question_label(el, soup) -> str:
    """Best-effort question text for an answer textarea: its <label for=…>,
    else the nearest preceding label/heading text."""
    tid = el.get("id")
    if tid:
        lab = soup.find("label", attrs={"for": tid})
        if lab:
            t = lab.get_text(" ", strip=True)
            if t:
                return t
    for prev in el.find_all_previous(["label", "h1", "h2", "h3", "h4", "h5",
                                      "strong", "legend", "p"], limit=8):
        t = prev.get_text(" ", strip=True)
        if t and len(t) > 3:
            return t
    return el.get("name") or "Question"


def fetch_sa_form(s: requests.Session, base: str, cas_id: int) -> dict:
    """Fetch the Answers page and parse its update_answers form.
    Returns {url, action, fields: [(name, value)], questions: [{name,
    question, answer}]} — `fields` are the non-answer inputs to round-trip."""
    url = f"{base}/student/ib/activity/cas/{cas_id}/answers"
    r = s.get(url, timeout=30, allow_redirects=True)
    if r.url.endswith("/login"):
        raise SessionExpiredError("Session expired. Run: cas login")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    form = None
    for f in soup.find_all("form"):
        if "update_answers" in (f.get("action") or ""):
            form = f
            break
    if form is None:
        raise ScraperError(
            f"cas_id={cas_id}: update_answers form not found on {url} — "
            "ManageBac DOM may have changed (see /api/debug/sa)")

    fields: list[tuple[str, str]] = []
    questions: list[dict] = []
    for el in form.find_all(["input", "textarea", "select"]):
        name = el.get("name")
        if not name:
            continue
        if el.name == "textarea":
            # Rails emits a newline right after <textarea>; browsers drop it
            # but BeautifulSoup keeps it. Strip exactly one, or every save
            # round-trip would prepend a blank line to the stored answer.
            raw = el.get_text() or ""
            if raw.startswith("\r\n"):
                raw = raw[2:]
            elif raw.startswith("\n"):
                raw = raw[1:]
            questions.append({
                "name":     name,
                "question": _sa_question_label(el, soup),
                "answer":   raw,
            })
        elif el.name == "input":
            itype = (el.get("type") or "text").lower()
            if itype in ("checkbox", "radio"):
                if el.has_attr("checked"):
                    fields.append((name, el.get("value", "on")))
            elif itype in ("submit", "button", "image", "file"):
                continue
            else:  # text / hidden / etc.
                fields.append((name, el.get("value", "")))
        else:  # select
            opt = el.find("option", selected=True) or el.find("option")
            fields.append((name, (opt.get("value") or "") if opt else ""))

    action = form.get("action") or f"/student/ib/activity/cas/{cas_id}/answers/update_answers"
    if action.startswith("/"):
        action = base + action
    return {"url": url, "action": action, "fields": fields, "questions": questions}


def save_sa_answers(s: requests.Session, base: str, cas_id: int, csrf: str,
                    answers: dict) -> None:
    """Save SA answers. `answers` maps field name → new text; every other
    answer keeps its current value (whole-page form, per ManageBac)."""
    form = fetch_sa_form(s, base, cas_id)
    data = list(form["fields"])
    for q in form["questions"]:
        data.append((q["name"], answers.get(q["name"], q["answer"])))
    r = s.post(
        form["action"],
        data=data,
        headers=_xhr_headers(base, csrf, form["url"]),
        timeout=30,
    )
    _check(r, f"save SA answers for cas_id={cas_id}")


def backup_all(s: requests.Session, base: str, cas_id: int,
               out_dir: Path, sleep_s: float = 0.15) -> Path:
    cas_dir = out_dir / f"cas_{cas_id}"
    html_dir = cas_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    entries: list[ReflectionEntry] = []
    for _, page_entries in iter_pages(s, base, cas_id):
        entries.extend(page_entries)

    print(f"  Enriching {len(entries)} reflections...")
    for i, e in enumerate(entries, 1):
        try:
            h = fetch_edit_html(s, base, cas_id, e.rid)
            enrich(e, h)
            (html_dir / f"{e.rid}.html").write_text(h, encoding="utf-8")
        except Exception as ex:
            print(f"  Warning: rid={e.rid} enrich failed: {ex}")
        if sleep_s:
            time.sleep(sleep_s)
        if i % 20 == 0:
            print(f"  {i}/{len(entries)}...")

    def _photo_dict(p: Photo) -> dict:
        return {"id": p.id, "caption": p.caption, "created_at": p.created_at, "s3_url": p.s3_url}

    index = {
        "meta": {"base": base, "cas_id": cas_id,
                 "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(entries)},
        "entries": [{
            "rid": e.rid, "kind": e.kind, "group_date": e.group_date,
            "page_no": e.page_no, "pos": e.pos,
            "body_html": e.body_html, "photos": [_photo_dict(p) for p in e.photos],
            "lo_ids": e.lo_ids, "s3_urls": e.s3_urls, "is_placeholder": e.is_placeholder,
        } for e in entries],
    }
    index_path = cas_dir / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


# ── Internal check ───────────────────────────────────────────────────────────

def _check(r: requests.Response, op: str) -> None:
    if r.status_code not in (200, 201, 302):
        raise RuntimeError(f"{op} failed: HTTP {r.status_code}: {r.text[:300]}")
