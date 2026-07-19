#!/usr/bin/env python3
"""
cas_web.py — Local web GUI server for CAS Manager.

Run:   python cas_web.py
Opens: http://localhost:5173

All business logic delegates to cas_controller.py.
The frontend (templates/index.html) is a single-page Apple-Notes-style app.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import webbrowser
from pathlib import Path

try:
    from flask import Flask, jsonify, render_template, request
except ImportError:
    sys.exit("Error: pip install flask")

import cas_api
import cas_controller as ctrl
import cas_db
import cas_paths
from cas_errors import NetworkError, ScraperError, SessionExpiredError

app = Flask(
    __name__,
    template_folder=str(cas_paths.TEMPLATES_DIR),
    static_folder=str(cas_paths.STATIC_DIR),
)
app.config["JSON_AS_ASCII"] = False


# ── helpers ───────────────────────────────────────────────────────────────────

def _ok(data=None, **kwargs):
    return jsonify({"ok": True, "data": data, **kwargs})


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode entities to plain text.
    Must unescape entities FIRST (e.g. &lt;p&gt; → <p>), then strip tags.
    Also drops the hidden stealth-placeholder marker so it never surfaces in
    previews or copied text."""
    import html as _h
    decoded = _h.unescape(html or "")            # &lt;p&gt; → <p>
    decoded = decoded.replace(cas_api.PLACEHOLDER_MARKER, "")
    text    = re.sub(r"<[^>]+>", " ", decoded)   # <p> → space
    return " ".join(text.split())


def _html_to_text(html: str) -> str:
    """HTML → plain text, PRESERVING paragraph and line breaks.

    Used to seed the edit box and the copy button: ManageBac stores journals as
    <p>…</p> paragraphs with <br> soft breaks, and collapsing those to spaces
    (like _strip_html does) is what made edited entries come back as one blob.
    Block-closing tags become blank lines, <br> becomes a single newline."""
    import html as _h
    s = _h.unescape(html or "")
    s = s.replace(cas_api.PLACEHOLDER_MARKER, "")
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|blockquote|ul|ol)\s*>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)                    # strip remaining tags
    # Collapse inline whitespace per line, keep the newline structure.
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s)                 # at most one blank line
    return s.strip()


def _plain_to_html(text: str) -> str:
    """Plain text → ManageBac redactor HTML. Blank lines split paragraphs;
    single newlines within a paragraph become <br>. HTML-escapes content so
    stray <, >, & don't corrupt the markup. Text that already looks like HTML
    (starts with '<') is passed through untouched."""
    import html as _h
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return ""
    if t.startswith("<"):
        return t
    paras = re.split(r"\n{2,}", t)
    out = []
    for para in paras:
        lines = [_h.escape(ln.strip()) for ln in para.split("\n") if ln.strip()]
        if lines:
            out.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(out)


# LO ID → display string (LO# · Title)
_LO_DISPLAY: dict[int, str] = {
    142285: "LO1 · Strengths & Growth",
    142286: "LO2 · Challenge & Skills",
    142287: "LO3 · Initiative & Planning",
    142288: "LO4 · Commitment & Perseverance",
    142289: "LO5 · Collaborative Skills",
    142290: "LO6 · Global Engagement",
    142291: "LO7 · Ethics",
}


def _lo_display_from_ids(lo_ids) -> list[str]:
    """Map a list of LO IDs (ints or strings) to display strings, preserving LO# order."""
    seen: list[int] = []
    for x in lo_ids or []:
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v in _LO_DISPLAY and v not in seen:
            seen.append(v)
    # Sort by canonical LO# order
    return [_LO_DISPLAY[lid] for lid in sorted(seen)]


def _lo_display_from_names(lo_names) -> list[str]:
    """Map a list of LO display names (free-form strings) to canonical LO# display strings."""
    import cas_api as _cas_api
    ids = _cas_api.lo_names_to_ids(list(lo_names or []))
    return _lo_display_from_ids(ids)


_MONTH_TO_NUM = {
    "jan":  1, "january":   1,
    "feb":  2, "february":  2,
    "mar":  3, "march":     3,
    "apr":  4, "april":     4,
    "may":  5,
    "jun":  6, "june":      6,
    "jul":  7, "july":      7,
    "aug":  8, "august":    8,
    "sep":  9, "sept":      9, "september": 9,
    "oct": 10, "october":  10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_DATE_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")


def _date_iso(group_date: str) -> str:
    """Convert 'March 17, 2026' / 'Jan 9, 2026' → '2026-03-17'. Returns '' if unparseable."""
    if not group_date:
        return ""
    m = _DATE_RE.match(group_date.strip())
    if not m:
        return ""
    month = _MONTH_TO_NUM.get(m.group(1).lower(), 0)
    if not month:
        return ""
    return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"


def _body_preview(body_html: str, max_chars: int = 150) -> str:
    text = _strip_html(body_html or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _enrich_reflection(r: dict) -> dict:
    """Add display-friendly fields to a reflection dict."""
    photos = r.get("photos") or []
    body_html = r.get("body_html") or ""
    r["body_text"]    = _html_to_text(body_html)   # keeps paragraph/line breaks
    r["body_preview"] = _body_preview(body_html)
    r["date_iso"]     = _date_iso(r.get("group_date", ""))
    r["lo_display"]   = _lo_display_from_ids(r.get("lo_ids") or [])
    r["file_list"]    = r.get("files") or []
    r["photo_list"]   = [
        {
            "id":      p["id"],
            "caption": p.get("caption", ""),
            "s3_url":  p.get("s3_url", ""),
            "url":     p.get("s3_url", ""),  # legacy alias for older clients
        }
        for p in photos
    ]
    return r


_STRAND_CANONICAL = ("creativity", "activity", "service")


def _split_strands(raw) -> list[str]:
    """Parse the DB's strand column (comma-separated or single value) into a
    canonical-order list of lowercased strand names. Handles legacy single-
    value rows (e.g. "Activity") and the new multi-strand format
    (e.g. "Creativity, Activity")."""
    if not raw:
        return []
    parts = {p.strip().lower() for p in str(raw).split(",") if p.strip()}
    # Re-order into Creativity → Activity → Service so UI is consistent
    return [s for s in _STRAND_CANONICAL if s in parts]


def _enrich_experience(e: dict) -> dict:
    """Add display-friendly fields to an experience dict."""
    strands = _split_strands(e.get("strand"))
    e["strands"]    = strands                        # new: array, canonical order
    e["strand"]     = strands[0] if strands else ""  # keep single-value compat
    e["lo_display"] = _lo_display_from_names(e.get("lo_names") or [])
    return e


# ── Unified error handlers ────────────────────────────────────────────────────

@app.errorhandler(SessionExpiredError)
def handle_session_expired(e):
    # Drop the cached session — the retried request then walks the full
    # recovery chain (cookies → token refresh → saved-credential re-login).
    ctrl.ctrl_invalidate_session()
    return jsonify({"ok": False, "error": "session_expired"}), 401


@app.errorhandler(NetworkError)
def handle_network_error(e):
    # Offline is not logged-out: 503 keeps the frontend from asking for the
    # password again when the network blips.
    return jsonify({"ok": False, "error": "offline", "detail": str(e)}), 503


@app.errorhandler(ScraperError)
def handle_scraper_error(e):
    return jsonify({"ok": False, "error": "scraper_failed", "detail": str(e)}), 502


@app.errorhandler(Exception)
def handle_generic_error(e):
    return jsonify({"ok": False, "error": "internal", "detail": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# ── Frontend ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    # No favicon shipped — return 204 so browser requests don't 500 the log.
    return "", 204


# ══════════════════════════════════════════════════════════════════════════════
# ── API: system ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/status")
def api_status():
    logged_in = ctrl.ctrl_check_login()
    cfg       = ctrl.ctrl_config()
    stats     = ctrl.ctrl_db_stats()
    return _ok({
        "logged_in":   logged_in,
        "ai_provider": cfg.get("ai_provider", "prompt"),
        "ai_model":    cfg.get("ai_model", "deepseek-chat"),
        "stats":       stats,
    })


@app.route("/api/config", methods=["GET"])
def api_config_get():
    return _ok(ctrl.ctrl_config())


@app.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.get_json(force=True) or {}
    ctrl.ctrl_save_config(data)
    return _ok()


# ── API: prompts (system-prompt slot management) ──────────────────────────────

@app.route("/api/prompts", methods=["GET"])
def api_prompts_list():
    """All known prompt slots with default, current body, and override status."""
    import cas_prompts
    return _ok(cas_prompts.list_all())


@app.route("/api/prompts/<slot>", methods=["GET"])
def api_prompt_get(slot: str):
    import cas_prompts
    try:
        return _ok({
            "slot":          slot,
            "default":       cas_prompts.default_of(slot),
            "body":          cas_prompts.get(slot),
            "is_customized": cas_prompts.is_customized(slot),
        })
    except KeyError:
        return _err("unknown slot", 404)


@app.route("/api/prompts/<slot>", methods=["PUT"])
def api_prompt_set(slot: str):
    import cas_prompts
    data = request.get_json(silent=True) or {}
    body = data.get("body", "")
    try:
        cas_prompts.set(slot, body)
    except KeyError:
        return _err("unknown slot", 404)
    return _ok({"slot": slot, "is_customized": cas_prompts.is_customized(slot)})


@app.route("/api/prompts/<slot>", methods=["DELETE"])
def api_prompt_reset(slot: str):
    """Reset a slot to its built-in default (delete the override row)."""
    import cas_prompts
    try:
        cas_prompts.delete(slot)
    except KeyError:
        return _err("unknown slot", 404)
    return _ok({"slot": slot, "is_customized": False})


# ══════════════════════════════════════════════════════════════════════════════
# ── API: experiences ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/experiences")
def api_experiences():
    return _ok([_enrich_experience(e) for e in ctrl.ctrl_list_experiences()])


@app.route("/api/experiences/<int:cas_id>")
def api_experience_detail(cas_id: int):
    exp = ctrl.ctrl_get_experience(cas_id)
    if not exp:
        return _err("Experience not found", 404)
    return _ok(_enrich_experience(exp))


@app.route("/api/experiences/<int:cas_id>/reflections")
def api_reflections(cas_id: int):
    refs = ctrl.ctrl_list_reflections(cas_id)
    return _ok([_enrich_reflection(r) for r in refs])


# ══════════════════════════════════════════════════════════════════════════════
# ── API: sync ─────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/sync/experiences", methods=["POST"])
def api_sync_experiences():
    """Fast path: fetch + cache just the experience LIST (no reflections),
    so the sidebar can populate immediately after login."""
    return _ok(ctrl.ctrl_fetch_experiences_from_web())


@app.route("/api/sync/all", methods=["POST"])
def api_sync_all():
    return _ok(ctrl.ctrl_sync_all(include_completed=True))


@app.route("/api/sync/<int:cas_id>", methods=["POST"])
def api_sync_one(cas_id: int):
    return _ok(ctrl.ctrl_sync_experience(cas_id))


# ══════════════════════════════════════════════════════════════════════════════
# ── API: create / edit reflections ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/experiences/<int:cas_id>/journal", methods=["POST"])
def api_create_journal(cas_id: int):
    data     = request.get_json(force=True) or {}
    body     = data.get("body_html") or ""
    lo_ids   = data.get("lo_ids") or None
    if not body.strip():
        return _err("body_html is required")
    body = _plain_to_html(body)   # no-op if already HTML; keeps line breaks
    rid = ctrl.ctrl_create_journal(cas_id, body, lo_ids=lo_ids)
    return _ok({"rid": rid})


def _parse_lo_ids_form(raw: str | None) -> list[int] | None:
    """Parse a JSON-encoded lo_ids list from a form field. Returns None if missing/empty."""
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return [int(x) for x in v] if isinstance(v, list) else None
    except (ValueError, TypeError):
        return None


@app.route("/api/experiences/<int:cas_id>/album", methods=["POST"])
def api_create_album(cas_id: int):
    # Multipart: files in "photos[]" or "photos", parallel captions in "captions"
    files = request.files.getlist("photos")
    if not files:
        # back-compat for clients still sending JSON {image_paths}
        if request.is_json:
            data  = request.get_json(silent=True) or {}
            paths = data.get("image_paths") or []
            label = data.get("label", "")
            lo_ids = data.get("lo_ids") or None
            if not paths:
                return _err("Please select at least one image", 400)
            for path in paths:
                if not Path(path).exists():
                    return jsonify({"ok": False, "error": "file_not_found", "path": path}), 400
            rid = ctrl.ctrl_create_album(cas_id, paths, label=label, lo_ids=lo_ids)
            return _ok({"rid": rid})
        return _err("Please select at least one image", 400)

    captions = request.form.getlist("captions")
    lo_ids   = _parse_lo_ids_form(request.form.get("lo_ids"))
    label    = request.form.get("label", "")
    date     = request.form.get("date") or None

    photos: list[tuple[str, bytes, str]] = []
    for i, f in enumerate(files):
        cap = captions[i] if i < len(captions) else label
        photos.append((f.filename or f"photo_{i}.jpg", f.read(), cap or ""))

    rid = ctrl.ctrl_create_album_bytes(cas_id, photos, lo_ids=lo_ids,
                                       date_str=date)
    return _ok({"rid": rid})


@app.route("/api/experiences/<int:cas_id>/file", methods=["POST"])
def api_create_file(cas_id: int):
    # Multipart: one or more attachments in "files" (each becomes its own
    # FileEvidence), optional "body" text applied to each.
    uploaded = request.files.getlist("files")
    if not uploaded:
        return _err("Please select at least one file", 400)
    lo_ids    = _parse_lo_ids_form(request.form.get("lo_ids"))
    body      = request.form.get("body", "")
    body_html = _plain_to_html(body) if body.strip() else ""
    files: list[tuple[str, bytes]] = [
        (f.filename or f"file_{i}", f.read()) for i, f in enumerate(uploaded)
    ]
    rids = ctrl.ctrl_create_file_evidence(cas_id, files, lo_ids=lo_ids,
                                          body_html=body_html)
    return _ok({"rids": rids})


@app.route("/api/reflections/<int:rid>/album/photos", methods=["GET"])
def api_album_get_photos(rid: int):
    cas_id = request.args.get("cas_id", type=int)
    if not cas_id:
        return _err("cas_id required")
    return _ok(ctrl.ctrl_get_album_photos(cas_id, rid))


@app.route("/api/reflections/<int:rid>/album/photos", methods=["POST"])
def api_album_add_photos(rid: int):
    # Multipart: "photos" file field(s), "cas_id" + optional "caption" form fields
    files = request.files.getlist("photos")
    if files:
        cas_id  = request.form.get("cas_id", type=int)
        caption = request.form.get("caption", "")
        if not cas_id:
            return _err("cas_id required", 400)
        ctrl.ctrl_add_photo_bytes_to_album(
            cas_id, rid,
            [(f.filename or "photo.jpg", f.read()) for f in files],
            caption=caption,
        )
        return _ok()

    # back-compat JSON path-based form
    data    = request.get_json(silent=True) or {}
    cas_id  = data.get("cas_id")
    paths   = data.get("image_paths") or []
    caption = data.get("caption", "")
    if not cas_id:
        return _err("cas_id required", 400)
    if not paths:
        return _err("Please select at least one image", 400)
    ctrl.ctrl_add_photos_to_album(int(cas_id), rid, paths, caption=caption)
    return _ok()


@app.route("/api/reflections/<int:rid>/album/photos/<int:photo_id>", methods=["DELETE"])
def api_album_delete_photo(rid: int, photo_id: int):
    cas_id = request.args.get("cas_id", type=int)
    if not cas_id:
        return _err("cas_id required")
    ctrl.ctrl_delete_photo(cas_id, rid, photo_id)
    return _ok()


@app.route("/api/reflections/<int:rid>/edit", methods=["POST"])
def api_edit_reflection(rid: int):
    data    = request.get_json(force=True) or {}
    cas_id  = data.get("cas_id")
    body    = data.get("body_html") or ""
    lo_ids  = data.get("lo_ids") or None
    if not cas_id:
        return _err("cas_id required")
    if not body.strip():
        return _err("body_html required")
    body = _plain_to_html(body)   # no-op if already HTML; keeps line breaks
    ctrl.ctrl_edit_journal(int(cas_id), rid, body, lo_ids=lo_ids)
    return _ok()


@app.route("/api/reflections/<int:rid>", methods=["DELETE"])
def api_delete_reflection(rid: int):
    cas_id = request.args.get("cas_id", type=int)
    if not cas_id:
        return _err("cas_id required", 400)
    if not ctrl.ctrl_config().get("danger_zone_enabled", False):
        return _err("Delete is disabled — enable Danger Zone in Settings first", 403)
    ctrl.ctrl_delete_reflection(cas_id, rid)
    return _ok()


# ══════════════════════════════════════════════════════════════════════════════
# ── API: Self-Assessment answers ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/experiences/<int:cas_id>/sa")
def api_sa_questions(cas_id: int):
    """The experience's SA questions + current answers (live from ManageBac)."""
    return _ok(ctrl.ctrl_get_sa_questions(cas_id))


@app.route("/api/experiences/<int:cas_id>/sa", methods=["POST"])
def api_sa_save(cas_id: int):
    data = request.get_json(force=True) or {}
    name = data.get("name") or ""
    text = data.get("text") or ""
    if not name:
        return _err("name required")
    ctrl.ctrl_save_sa_answer(cas_id, name, text)
    return _ok()


@app.route("/api/ai/sa_prompt", methods=["POST"])
def api_ai_sa_prompt():
    """Copy-paste prompt for one SA question (proposal + history attached)."""
    data = request.get_json(force=True) or {}
    cas_id   = data.get("cas_id")
    question = (data.get("question") or "").strip()
    if not cas_id or not question:
        return _err("cas_id and question required")
    prompt = ctrl.ctrl_build_sa_prompt(int(cas_id), question,
                                       notes=data.get("notes", "") or "",
                                       existing=data.get("existing") or None)
    return _ok({"prompt": prompt})


@app.route("/api/ai/sa_generate", methods=["POST"])
def api_ai_sa_generate():
    data = request.get_json(force=True) or {}
    cas_id   = data.get("cas_id")
    question = (data.get("question") or "").strip()
    if not cas_id or not question:
        return _err("cas_id and question required")
    try:
        ans = ctrl.ctrl_generate_sa(int(cas_id), question,
                                    notes=data.get("notes", "") or "",
                                    existing=data.get("existing") or None)
        return _ok({"result": ans})
    except Exception as e:
        return _err(str(e))


@app.route("/api/debug/sa/<int:cas_id>")
def api_debug_sa(cas_id: int):
    """Dump the parsed update_answers form — for diagnosing DOM changes."""
    s, base = ctrl.ctrl_session()
    form = cas_api.fetch_sa_form(s, base, cas_id)
    return _ok({
        "url":    form["url"],
        "action": form["action"],
        "fields": form["fields"],
        "questions": [
            {"name": q["name"], "question": q["question"],
             "answer_preview": (q["answer"] or "")[:120]}
            for q in form["questions"]
        ],
    })


# ══════════════════════════════════════════════════════════════════════════════
# ── API: AI ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _validate_ai_request(data: dict) -> tuple[int, str, str, str, str, bool] | tuple[None, str]:
    """Return (cas_id, notes, kind, date, existing, include_history) on success,
    or (None, error_message) on validation failure."""
    cas_id          = data.get("cas_id")
    notes           = data.get("notes", "") or ""
    kind            = data.get("kind", "reflection")
    date            = data.get("date") or None
    existing        = data.get("existing") or None
    include_history = bool(data.get("include_history"))
    if not cas_id:
        return None, "cas_id required"
    # Notes are only mandatory for the "reflection" / "edit" flows. Final
    # reflections can legitimately have no themes — the session history alone
    # is enough context.
    if not notes.strip():
        if kind == "final" and include_history:
            notes = "Summarize the experience based on the session history below."
        else:
            return None, "notes required"
    return int(cas_id), notes, kind, date, existing, include_history


@app.route("/api/ai/prompt", methods=["POST"])
def api_ai_prompt():
    """Build and return the full prompt text (for manual copy-paste flow)."""
    data = request.get_json(force=True) or {}
    result = _validate_ai_request(data)
    if result[0] is None:
        return _err(result[1])
    cas_id, notes, kind, date, existing, include_history = result
    try:
        prompt = ctrl.ctrl_build_prompt(cas_id, notes, kind,
                                         date=date, existing=existing,
                                         include_history=include_history)
        return _ok({"prompt": prompt})
    except Exception as e:
        return _err(str(e))


@app.route("/api/ai/generate", methods=["POST"])
def api_ai_generate():
    """Call AI directly (anthropic or ollama provider)."""
    data = request.get_json(force=True) or {}
    result = _validate_ai_request(data)
    if result[0] is None:
        return _err(result[1])
    cas_id, notes, kind, date, existing, include_history = result
    try:
        ans = ctrl.ctrl_generate_ai(cas_id, notes,
                                     kind=kind, date=date, existing=existing,
                                     include_history=include_history)
        return _ok({"result": ans})
    except Exception as e:
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/debug/experiences")
def api_debug_experiences():
    """Fetch the experiences list page live and show what the scraper sees —
    for diagnosing an empty sidebar. No DB writes."""
    import cas_api
    s, base = ctrl.ctrl_session()
    url = f"{base}/student/ib/activity/cas"
    r = s.get(url, timeout=30, allow_redirects=True)
    exps = cas_api.scan_experiences(r.text)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    return _ok({
        "url":               url,
        "status_code":       r.status_code,
        "redirected_to":     r.url,
        "tile_selector_hits": len(soup.select("div.fusion-card-item.activity-tile")),
        "cas_link_hits":     len(soup.select('a[href*="/student/ib/activity/cas/"]')),
        "parsed_count":      len(exps),
        "parsed":            [{"cas_id": e.cas_id, "name": e.name,
                               "is_completed": e.is_completed} for e in exps],
        "html_len":          len(r.text),
    })


@app.route("/api/debug/reflections/<int:cas_id>")
def api_debug_reflections(cas_id: int):
    """Raw DB dump for diagnosing missing body_html / photos."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        rows = conn.execute(
            "SELECT id, kind, group_date, "
            "  CASE WHEN body_html IS NULL THEN 'NULL' "
            "       WHEN body_html = ''    THEN 'EMPTY' "
            "       ELSE substr(body_html,1,80) END AS body_preview, "
            "  (SELECT COUNT(*) FROM photos WHERE reflection_id = reflections.id) AS photo_count "
            "FROM reflections WHERE cas_id = ? ORDER BY id DESC",
            (cas_id,)
        ).fetchall()
    return _ok([dict(r) for r in rows])


@app.route("/api/debug/scan/<int:cas_id>")
def api_debug_scan(cas_id: int):
    """Fetch page 1 live and show what scan_page() extracts — no DB writes.
    Also dumps a snippet of raw HTML around the first evidence div for selector debugging."""
    import cas_api
    try:
        s, base = ctrl.ctrl_session()
    except ctrl.SessionError as e:
        return _err(str(e), 401)

    url = f"{base}/student/ib/activity/cas/{cas_id}/reflections"
    r = s.get(url, timeout=30)
    raw_html = r.text

    entries = cas_api.scan_page(raw_html, 1)

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw_html, "html.parser")
    container = soup.select_one("div.evidences.activity-evidences")
    container_found = bool(container)
    fix_body_found  = bool(soup.select_one(".fix-body-margins"))

    # List first 30 direct children with their id + classes
    child_info = []
    if container:
        for child in list(container.children)[:30]:
            if not hasattr(child, "name") or child.name is None:
                continue
            child_info.append({
                "tag":     child.name,
                "id":      child.get("id", ""),
                "classes": " ".join(child.get("class") or []),
            })

    # Show outerHTML of first two fusion-card-list divs (up to 1500 chars each)
    card_samples = []
    if container:
        for child in container.children:
            if hasattr(child, "get") and "fusion-card-list" in (child.get("class") or []):
                card_samples.append(str(child)[:1500])
            if len(card_samples) >= 2:
                break

    return _ok({
        "url": url,
        "status_code": r.status_code,
        "container_found": container_found,
        "fix_body_margins_found": fix_body_found,
        "entries_count": len(entries),
        "entries": [
            {
                "rid":       e.rid,
                "kind":      e.kind,
                "body_html": e.body_html[:120] if e.body_html else None,
                "photos":    len(e.photos),
            }
            for e in entries
        ],
    })


# ══════════════════════════════════════════════════════════════════════════════
# ── API: login ────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/login/status")
def api_login_status():
    return _ok({"logged_in": ctrl.ctrl_check_login()})


@app.route("/api/login/start", methods=["POST"])
def api_login_start():
    import mb_login
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""
    # `base` may be sent by the login form for first-time users. If absent,
    # fall back to the configured value (re-login flow).
    raw_base = (data.get("base") or ctrl.ctrl_config().get("base") or "").strip()

    if not raw_base:
        return _err("Please enter your school's ManageBac URL (e.g. https://yourschool.managebac.cn)", 400)
    # Normalize: prepend https://, strip trailing slash
    base = raw_base
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    base = base.rstrip("/")
    if "managebac." not in base:
        return _err(f"That URL doesn't look right: {base!r} — expected something like https://<school>.managebac.{{cn|com}}", 400)

    if not email or not password:
        return _err("Please enter your email and password", 400)

    try:
        # state includes the credentials — saved locally so the app can
        # re-login automatically when both cookie and auth_token expire.
        state = mb_login.login_with_password(email, password, base)
        mb_login.save_state(state)
        ctrl.ctrl_invalidate_session()
    except RuntimeError as e:
        return _err(str(e), 401)
    except Exception as e:
        return _err(f"Login failed: {e}", 401)

    # Persist the (possibly new) base URL only after login succeeds — so a typo
    # doesn't overwrite a working config.
    if base != ctrl.ctrl_config().get("base"):
        ctrl.ctrl_save_config({"base": base})

    return _ok({"message": "Logged in (session valid for ~1 year)", "base": base})


# ══════════════════════════════════════════════════════════════════════════════
# ── API: schedules & placeholders ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/schedules")
def api_schedules_list():
    return _ok(ctrl.ctrl_list_schedules())


@app.route("/api/schedules/<int:cas_id>", methods=["POST"])
def api_schedule_upsert(cas_id: int):
    data = request.get_json(force=True) or {}
    ctrl.ctrl_upsert_schedule(
        cas_id,
        enabled=bool(data.get("enabled", True)),
        interval_days=int(data.get("interval_days", 1)),
        lo_ids=data.get("lo_ids") or None,
    )
    return _ok()


@app.route("/api/schedules/<int:cas_id>", methods=["DELETE"])
def api_schedule_delete(cas_id: int):
    ctrl.ctrl_delete_schedule(cas_id)
    return _ok()


@app.route("/api/queue")
def api_queue():
    """Return all placeholder journal reflections across all experiences."""
    return _ok(ctrl.ctrl_list_placeholder_queue())


@app.route("/api/placeholder/run", methods=["POST"])
def api_placeholder_run():
    data   = request.get_json(force=True) or {}
    cas_id = data.get("cas_id")
    if cas_id:
        j_rid, a_rid = ctrl.ctrl_create_placeholder_for(int(cas_id))
        return _ok({"j_rid": j_rid, "a_rid": a_rid})
    else:
        return _ok(ctrl.ctrl_run_due_schedules())


def _open_browser(port: int = 5173):
    import time; time.sleep(0.8)
    webbrowser.open(f"http://localhost:{port}")


def _schedule_runner():
    """Background thread: auto-run due placeholder schedules every hour.
    Also runs once at startup (after a 30-second warmup delay)."""
    import time
    time.sleep(30)          # wait for server to finish starting up
    while True:
        try:
            results = ctrl.ctrl_run_due_schedules()
            ok  = [r for r in results if r.get("ok")]
            err = [r for r in results if not r.get("ok")]
            if ok:
                names = ", ".join(str(r.get("name") or r["cas_id"]) for r in ok)
                print(f"[scheduler] Created {len(ok)} placeholder(s): {names}")
            if err:
                for r in err:
                    print(f"[scheduler] Error for {r.get('cas_id')}: {r.get('error')}")
        except Exception as ex:
            print(f"[scheduler] {ex}")
        time.sleep(3600)    # check again in 1 hour


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CAS Manager web GUI")
    parser.add_argument("--port", type=int, default=5173,
                        help="HTTP port to listen on (default: 5173)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open the browser at startup")
    args = parser.parse_args()

    print(f"CAS Manager GUI — http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(args.port,), daemon=True).start()
    threading.Thread(target=_schedule_runner, daemon=True).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
