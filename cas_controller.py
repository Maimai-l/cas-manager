"""
cas_controller.py — Business logic layer for CAS Manager.

This is the single interface point that all frontends should use.
  - cas.py (CLI)   → can call these directly
  - cas_tui.py     → uses these exclusively
  - Future GUI     → swap this module for an HTTP client pointing at a
                     local Flask/FastAPI server, and the UI code stays the same.

Design rules:
  - No argparse, no sys.exit, no print() side-effects.
  - All errors raise ValueError or RuntimeError with user-readable messages.
  - All returns are plain dicts / lists / primitives (JSON-serialisable).
  - Long-running operations accept an optional progress_cb(msg: str) callback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import cas_api
import cas_db
import cas_paths
from cas_errors import NetworkError
from cas_errors import SessionExpiredError as _SessionExpiredError

# ── Re-export config helpers (avoids importing cas.py directly) ───────────────

CONFIG_FILE = cas_paths.CONFIG_PATH

_CONFIG_DEFAULTS = {
    # base must be set explicitly by the user via Settings → Account before
    # any ManageBac calls — never hardcode a specific school here.
    "base": "",
    "state": "mb_state.json",
    "cas_id": None,
    "lo_ids": [],
    "ai_provider": "prompt",
    "ai_model": "deepseek-chat",
    "ollama_model": "llama3.2",
    "ollama_url": "http://localhost:11434",
    "backup_dir": "mb_backup_out",
    "danger_zone_enabled": False,
}


# ── Config ────────────────────────────────────────────────────────────────────

def ctrl_config() -> dict:
    cfg = dict(_CONFIG_DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    return cfg


def ctrl_save_config(updates: dict) -> None:
    cfg = ctrl_config()
    cfg.update(updates)
    out = {k: v for k, v in cfg.items() if k in _CONFIG_DEFAULTS}
    CONFIG_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── Session ───────────────────────────────────────────────────────────────────

class SessionError(_SessionExpiredError):
    """Raised when session is missing or expired."""


# Cache the last successfully-verified session so we don't hit /student on
# every single API call. Re-verified after _SESSION_TTL seconds or whenever
# ctrl_invalidate_session() is called (e.g. a request hit a login redirect).
_session_cache: dict = {"s": None, "base": None, "ts": 0.0}
_SESSION_TTL = 600  # seconds


def ctrl_invalidate_session() -> None:
    """Drop the cached session so the next ctrl_session() re-verifies."""
    _session_cache.update(s=None, base=None, ts=0.0)


def _logged_in_with_retry(s, base: str, attempts: int = 3) -> bool:
    """check_login with retry/backoff on transient network errors.
    Returns True/False only for a definitive answer; raises NetworkError
    when ManageBac stays unreachable — being offline is NOT being logged out."""
    import time
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return cas_api.check_login_strict(s, base)
        except NetworkError as e:
            last = e
            if i < attempts - 1:
                time.sleep(min(2 ** i, 4))
    raise NetworkError(str(last))


def ctrl_session():
    """Return (requests.Session, base_url).

    Recovery chain before giving up:
      1. stored cookies          (mb_state.json)
      2. silent auth_token refresh
      3. full re-login with saved email/password
    Raises SessionError only when all three fail with a definitive "logged
    out" answer; raises NetworkError when ManageBac is unreachable."""
    import time
    cfg = ctrl_config()
    base = cfg["base"]
    if not base:
        raise SessionError("No school URL configured. Open Settings → Account.")

    now = time.time()
    if (_session_cache["s"] is not None and _session_cache["base"] == base
            and now - _session_cache["ts"] < _SESSION_TTL):
        return _session_cache["s"], base

    # Always use the canonical state path from cas_paths — never trust
    # cfg["state"] for this, since it was historically a relative path
    # ("mb_state.json") and would resolve against CWD, which in frozen mode
    # is not the user-data directory where mb_login.save_state() actually
    # writes the cookies.
    state_path = cas_paths.STATE_PATH
    if not state_path.exists():
        raise SessionError("No session file found. Run: cas login")
    state = cas_api.load_state(state_path)

    # 1. Stored cookies
    s = cas_api.build_session(state, base)
    if _logged_in_with_retry(s, base):
        _session_cache.update(s=s, base=base, ts=now)
        return s, base

    # 2. Silent refresh via stored auth_token
    try:
        state = cas_api.refresh_session(state_path, base)
        s = cas_api.build_session(state, base)
        if _logged_in_with_retry(s, base):
            _session_cache.update(s=s, base=base, ts=now)
            return s, base
    except NetworkError:
        raise
    except Exception:
        pass  # token expired/invalid — fall through to credential re-login

    # 3. Full re-login with saved credentials
    email, password = state.get("email"), state.get("password")
    if email and password:
        import requests as _requests

        import mb_login
        try:
            new_state = mb_login.login_with_password(email, password, base)
            mb_login.save_state(new_state)
            s = cas_api.build_session(new_state, base)
            if _logged_in_with_retry(s, base):
                _session_cache.update(s=s, base=base, ts=now)
                return s, base
        except _requests.RequestException as e:
            raise NetworkError(f"ManageBac unreachable: {e}") from e
        except RuntimeError:
            pass  # wrong/changed password — genuine re-login needed

    raise SessionError("Session expired. Run: cas login")


def ctrl_check_login() -> bool:
    """Return True if session is valid, False otherwise. When ManageBac is
    unreachable we optimistically report the stored state — offline must not
    bounce the user back to the password form."""
    try:
        ctrl_session()
        return True
    except SessionError:
        return False
    except NetworkError:
        return cas_paths.STATE_PATH.exists()


# ── Experiences ───────────────────────────────────────────────────────────────

def ctrl_list_experiences() -> list[dict]:
    """Return all experiences cached in local DB, with reflection_count."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        exps = cas_db.list_experiences(conn)
        counts = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT cas_id, COUNT(*) FROM reflections GROUP BY cas_id"
            ).fetchall()
        }
    for e in exps:
        e["reflection_count"] = counts.get(e["id"], 0)
    return exps


def ctrl_get_experience(cas_id: int) -> Optional[dict]:
    """Return experience dict from DB, or None."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        return cas_db.get_experience(conn, cas_id)


def ctrl_fetch_experiences_from_web() -> list[dict]:
    """Fetch live experience list from ManageBac and cache in DB.
    Returns list of {cas_id, name, is_completed}."""
    s, base = ctrl_session()
    exps = cas_api.fetch_experiences(s, base)
    cas_db.init_db()
    with cas_db.open_db() as conn:
        for exp in exps:
            cas_db.upsert_experience(
                conn,
                exp.cas_id,
                name=exp.name,
                is_completed=exp.is_completed,
            )
    return [{"cas_id": e.cas_id, "name": e.name, "is_completed": e.is_completed}
            for e in exps]


# ── Sync ──────────────────────────────────────────────────────────────────────

def ctrl_sync_experience(
    cas_id: int,
    progress_cb: Optional[Callable[[str], None]] = None,
    is_completed: bool = False,
    _session=None,   # pass (s, base) from caller to avoid re-checking login
) -> dict:
    """Sync one experience into DB.  Returns {total, gone, errors}.

    Body HTML and photos are extracted directly from the list page by
    scan_page(), so no individual edit-page fetches are needed.
    """
    s, base = _session if _session else ctrl_session()
    db_path = cas_db.DEFAULT_DB

    # Seed name from DB first — so if proposal fetch fails, we keep the existing name
    cas_db.init_db()
    with cas_db.open_db() as conn:
        existing = cas_db.get_experience(conn, cas_id)
    name = (existing or {}).get("name") or str(cas_id)

    # Fetch proposal for richer info (strand, LOs, proposal text, authoritative name)
    proposal_errors: list[str] = []
    try:
        proposal = cas_api.fetch_proposal(s, base, cas_id)
        fetched_name = proposal.get("name", "")
        if fetched_name:
            name = fetched_name
        with cas_db.open_db() as conn:
            cas_db.upsert_experience(
                conn, cas_id,
                name=name,
                is_completed=is_completed,
                proposal_text=proposal.get("proposal_text"),
                lo_names=proposal.get("lo_names"),
                strand=proposal.get("strand", ""),
            )
    except Exception as ex:
        proposal_errors.append(f"proposal: {ex}")
        if progress_cb:
            progress_cb(f"⚠ Could not fetch proposal: {ex}")

    # Collect all reflections — body_html and photos already populated by scan_page()
    all_entries: list[cas_api.ReflectionEntry] = []
    for page_no, page_entries in cas_api.iter_pages(s, base, cas_id):
        all_entries.extend(page_entries)
        if progress_cb:
            progress_cb(f"Fetched page {page_no} ({len(all_entries)} reflections so far)…")

    total = len(all_entries)
    if progress_cb:
        progress_cb(f"Syncing {total} reflections to DB…")

    live_rids = {e.rid for e in all_entries}
    with cas_db.open_db(db_path) as conn:
        cas_db.sync_entries(conn, cas_id, all_entries,
                            name=name, is_completed=is_completed)
        gone = cas_db.purge_deleted(conn, cas_id, live_rids)

    all_errors = proposal_errors
    return {"cas_id": cas_id, "name": name, "total": total,
            "gone": len(gone), "errors": len(all_errors), "error_details": all_errors}


def ctrl_sync_all(
    include_completed: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """Sync all experiences.  Returns list of per-experience result dicts."""
    s, base = ctrl_session()
    exps = cas_api.fetch_experiences(s, base)

    # Store names and completion status immediately so they survive proposal failures
    cas_db.init_db()
    live_ids = {exp.cas_id for exp in exps}
    with cas_db.open_db() as conn:
        for exp in exps:
            cas_db.upsert_experience(conn, exp.cas_id,
                                     name=exp.name,
                                     is_completed=exp.is_completed)
        # Flip is_deleted based on what came back this sync
        newly_del, restored = cas_db.mark_experiences_deletion_state(conn, live_ids)
        if progress_cb and (newly_del or restored):
            if newly_del:
                progress_cb(f"⚠ {len(newly_del)} experience(s) no longer on ManageBac — moved to Deleted")
            if restored:
                progress_cb(f"✓ {len(restored)} experience(s) reappeared — restored")

    results = []
    for exp in exps:
        if exp.is_completed and not include_completed:
            continue
        if progress_cb:
            progress_cb(f"Syncing: {exp.name or exp.cas_id}…")
        try:
            result = ctrl_sync_experience(exp.cas_id, progress_cb=progress_cb,
                                          is_completed=exp.is_completed,
                                          _session=(s, base))
            results.append(result)
        except Exception as ex:
            results.append({"cas_id": exp.cas_id, "name": exp.name,
                            "error": str(ex)})
    return results


# ── Reflections ───────────────────────────────────────────────────────────────

def ctrl_list_reflections(
    cas_id: int,
    kind: Optional[str] = None,
    placeholder: Optional[bool] = None,
) -> list[dict]:
    cas_db.init_db()
    with cas_db.open_db() as conn:
        return cas_db.list_reflections(conn, cas_id, kind=kind,
                                       placeholder=placeholder)


def ctrl_lo_ids_for(cas_id: int) -> list[int]:
    """Return the LO IDs for this experience (from DB), or all 7 as fallback."""
    exp = ctrl_get_experience(cas_id)
    if exp and exp.get("lo_names"):
        ids = cas_api.lo_names_to_ids(exp["lo_names"])
        if ids:
            return ids
    cfg = ctrl_config()
    return list(cfg.get("lo_ids") or cas_api.LO_IDS.values())


def ctrl_create_journal(
    cas_id: int,
    body_html: str,
    lo_ids: Optional[list[int]] = None,
    date_str: Optional[str] = None,  # kept for API compat; not sent to ManageBac
) -> int:
    """Create a journal reflection.  Returns new reflection ID."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    if lo_ids is None:
        lo_ids = ctrl_lo_ids_for(cas_id)
    rid = cas_api.create_journal(s, base, cas_id, csrf, body_html, lo_ids)
    return rid


def ctrl_create_album(
    cas_id: int,
    image_paths: list[str],
    label: str = "",
    lo_ids: Optional[list[int]] = None,
    date_str: Optional[str] = None,
) -> int:
    """Upload photos as an album reflection.  Returns new reflection ID."""
    photos = [(Path(p).name, Path(p).read_bytes(), label) for p in image_paths]
    return ctrl_create_album_bytes(cas_id, photos, lo_ids=lo_ids,
                                   date_str=date_str)


def ctrl_create_album_bytes(
    cas_id: int,
    photos: list[tuple[str, bytes, str]],   # (filename, data, caption)
    lo_ids: Optional[list[int]] = None,
    date_str: Optional[str] = None,
) -> int:
    """Upload in-memory photos (e.g. multipart uploads) as an album
    reflection.  Returns new reflection ID."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    if lo_ids is None:
        lo_ids = ctrl_lo_ids_for(cas_id)
    return cas_api.create_album(s, base, cas_id, csrf, lo_ids, photos,
                                date=date_str)


def ctrl_get_album_photos(cas_id: int, rid: int) -> list[dict]:
    """Fetch real photo list from ManageBac edit page (includes true photo IDs)."""
    s, base = ctrl_session()
    html = cas_api.fetch_edit_html(s, base, cas_id, rid)
    entry = cas_api.ReflectionEntry(rid=rid, kind="album",
                                    group_date="", page_no=0, pos=0)
    cas_api.enrich(entry, html)
    return [{"id": p.id, "caption": p.caption, "s3_url": p.s3_url}
            for p in entry.photos]


def ctrl_delete_photo(cas_id: int, rid: int, photo_id: int) -> None:
    """Delete a single photo from an album reflection."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    cas_api.delete_photo(s, base, cas_id, rid, csrf, photo_id)


def ctrl_add_photos_to_album(
    cas_id: int,
    rid: int,
    image_paths: list[str],
    caption: str = "",
) -> None:
    """Add one or more photos to an existing album reflection."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    for path in image_paths:
        cas_api.edit_album_add_photo(s, base, cas_id, rid, csrf,
                                     Path(path), caption=caption)


def ctrl_add_photo_bytes_to_album(
    cas_id: int,
    rid: int,
    photos: list[tuple[str, bytes]],   # (filename, data)
    caption: str = "",
) -> None:
    """Add in-memory photos (e.g. multipart uploads) to an existing album."""
    from tempfile import NamedTemporaryFile
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    for filename, data in photos:
        suffix = Path(filename or "photo.jpg").suffix or ".jpg"
        with NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            cas_api.edit_album_add_photo(s, base, cas_id, rid, csrf,
                                         tmp_path, caption=caption)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def ctrl_edit_journal(
    cas_id: int,
    rid: int,
    body_html: str,
    lo_ids: Optional[list[int]] = None,
) -> None:
    """Edit an existing journal reflection body."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    if lo_ids is None:
        lo_ids = ctrl_lo_ids_for(cas_id)
    cas_api.edit_journal(s, base, cas_id, rid, csrf, body_html, lo_ids)


def ctrl_delete_reflection(cas_id: int, rid: int) -> None:
    """Delete a reflection from ManageBac and drop the local DB row."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    cas_api.delete_reflection(s, base, cas_id, rid, csrf)
    cas_db.init_db()
    with cas_db.open_db() as conn:
        cas_db.delete_reflection_local(conn, rid)


# ── AI generation ─────────────────────────────────────────────────────────────

def ctrl_load_proposal(cas_id: int) -> Optional[dict]:
    """Return proposal dict from DB; try network if missing."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        exp = cas_db.get_experience(conn, cas_id)
    if exp and exp.get("proposal_text"):
        return exp
    try:
        s, base = ctrl_session()
        proposal = cas_api.fetch_proposal(s, base, cas_id)
        with cas_db.open_db() as conn:
            cas_db.upsert_experience(
                conn, cas_id,
                name=proposal.get("name", ""),
                proposal_text=proposal.get("proposal_text"),
                lo_names=proposal.get("lo_names"),
                strand=proposal.get("strand", ""),
            )
        return proposal
    except Exception:
        return None


def _load_history_for(cas_id: int) -> list[dict]:
    """Pull all non-placeholder reflections for `cas_id` from the local DB,
    oldest first, with body_text + group_date. Used as AI context for final
    reflections."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        rows = cas_db.list_reflections(conn, cas_id, placeholder=False)
    # list_reflections returns DESC by id; we want oldest first for the AI
    out = []
    import html as _html_mod, re as _re
    for r in reversed(rows):
        body_html = r.get("body_html") or ""
        body_text = " ".join(_re.sub(r"<[^>]+>", " ", _html_mod.unescape(body_html)).split())
        if not body_text:
            continue
        out.append({
            "group_date": r.get("group_date", ""),
            "body_text":  body_text,
            "kind":       r.get("kind", ""),
        })
    return out


def ctrl_build_prompt(cas_id: int, notes: str, kind: str = "reflection",
                      date: Optional[str] = None,
                      existing: Optional[str] = None,
                      include_history: bool = False) -> str:
    """Build the full prompt text (system + user) without calling any AI.
    kind = 'reflection' | 'final' | 'edit'.

    System prompts come from cas_prompts (user override or built-in default)
    with the current experience's proposal context appended automatically.
    When `include_history=True` (typically for final reflections), every
    non-placeholder past reflection is loaded from the local DB and inserted
    as session-by-session context."""
    import cas_ai
    proposal = ctrl_load_proposal(cas_id)
    history = _load_history_for(cas_id) if include_history else None
    if kind == "final":
        system = cas_ai.final_system_with_context(proposal)
    else:
        system = cas_ai.ai_system_with_context(proposal)
    _, user = cas_ai.build_prompt(notes, system, kind,
                                  date=date, existing=existing, history=history)
    return f"=== SYSTEM PROMPT ===\n{system}\n\n=== YOUR MESSAGE ===\n{user}"


def ctrl_generate_ai(
    cas_id: int,
    notes: str,
    kind: str = "reflection",
    date: Optional[str] = None,
    existing: Optional[str] = None,
    include_history: bool = False,
) -> str:
    """Generate AI text. kind = 'reflection' | 'final' | 'edit'.
    Uses provider from config (anthropic / ollama). The 'prompt' provider is
    copy-paste-only and raises — callers should use ctrl_build_prompt instead.
    When `include_history=True`, past reflections are pulled from local DB
    and passed to the AI as additional context."""
    import cas_ai

    cfg = ctrl_config()
    model = cfg.get("ai_model", "deepseek-chat")
    proposal = ctrl_load_proposal(cas_id)
    history = _load_history_for(cas_id) if include_history else None

    return cas_ai.ai_generate(notes, model, proposal=proposal, cfg=cfg,
                              kind=kind, date=date, existing=existing,
                              history=history)


# ── Drafts ────────────────────────────────────────────────────────────────────

def ctrl_list_drafts(
    cas_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict]:
    cas_db.init_db()
    with cas_db.open_db() as conn:
        return cas_db.list_drafts(conn, cas_id=cas_id, status=status)


def ctrl_add_draft(cas_id: int, note: str) -> int:
    """Save a quick note as a pending draft.  Returns draft id."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        return cas_db.add_draft(conn, cas_id, note)


def ctrl_write_draft(draft_id: int) -> str:
    """Run AI on a pending draft, save result, return generated text."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        draft = cas_db.get_draft(conn, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")
    result = ctrl_generate_ai(draft["cas_id"], draft["note"])
    with cas_db.open_db() as conn:
        cas_db.update_draft(conn, draft_id, ai_result=result, status="ready")
    return result


def ctrl_post_draft(
    draft_id: int,
    lo_ids: Optional[list[int]] = None,
) -> int:
    """Post a ready draft as a journal reflection.  Returns new rid."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        draft = cas_db.get_draft(conn, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")
    if not draft.get("ai_result"):
        raise ValueError("Draft has no AI result yet. Run write first.")
    rid = ctrl_create_journal(draft["cas_id"], draft["ai_result"],
                              lo_ids=lo_ids)
    with cas_db.open_db() as conn:
        cas_db.update_draft(conn, draft_id, status="posted")
    return rid


# ── Schedules ─────────────────────────────────────────────────────────────────

def ctrl_list_schedules() -> list[dict]:
    cas_db.init_db()
    with cas_db.open_db() as conn:
        return cas_db.list_schedules(conn)


def ctrl_upsert_schedule(cas_id: int, enabled: bool = True,
                         interval_days: int = 1,
                         lo_ids: Optional[list[int]] = None) -> None:
    cas_db.init_db()
    with cas_db.open_db() as conn:
        cas_db.upsert_schedule(conn, cas_id, enabled=enabled,
                               interval_days=interval_days, lo_ids=lo_ids)


def ctrl_delete_schedule(cas_id: int) -> None:
    cas_db.init_db()
    with cas_db.open_db() as conn:
        cas_db.delete_schedule(conn, cas_id)


# ── Self-Assessment (SA) answers ──────────────────────────────────────────────

def ctrl_get_sa_questions(cas_id: int) -> list[dict]:
    """Fetch the experience's Self-Assessment questions + current answers
    live from ManageBac. Returns [{name, question, answer}]."""
    s, base = ctrl_session()
    form = cas_api.fetch_sa_form(s, base, cas_id)
    return form["questions"]


def ctrl_save_sa_answer(cas_id: int, name: str, text: str) -> None:
    """Save one SA answer (the rest of the page's answers are re-submitted
    unchanged — ManageBac saves the whole form at once)."""
    s, base = ctrl_session()
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas/{cas_id}/answers")
    cas_api.save_sa_answers(s, base, cas_id, csrf, {name: text})


def ctrl_build_sa_prompt(cas_id: int, question: str, notes: str = "",
                         existing: Optional[str] = None) -> str:
    """Copy-paste prompt for answering one SA question. Proposal + LOs and
    the full session history are always attached as evidence."""
    import cas_ai
    proposal = ctrl_load_proposal(cas_id)
    history = _load_history_for(cas_id)
    system = cas_ai.sa_system_with_context(proposal)
    _, user = cas_ai.build_prompt(notes, system, "sa_question",
                                  existing=existing, history=history,
                                  question=question)
    return f"=== SYSTEM PROMPT ===\n{system}\n\n=== YOUR MESSAGE ===\n{user}"


def ctrl_generate_sa(cas_id: int, question: str, notes: str = "",
                     existing: Optional[str] = None) -> str:
    """Direct AI answer for one SA question (anthropic / ollama providers)."""
    import cas_ai
    cfg = ctrl_config()
    proposal = ctrl_load_proposal(cas_id)
    history = _load_history_for(cas_id)
    return cas_ai.ai_generate(notes, cfg.get("ai_model", "deepseek-chat"),
                              proposal=proposal, cfg=cfg, kind="sa_question",
                              existing=existing, history=history,
                              question=question)


# ── Placeholders ──────────────────────────────────────────────────────────────

def ctrl_list_placeholder_queue() -> list[dict]:
    """All pending placeholder journal reflections across active experiences.
    Completed experiences are locked on ManageBac (their reflections can't be
    edited anymore) and deleted ones are gone — skip both."""
    cas_db.init_db()
    items = []
    with cas_db.open_db() as conn:
        for exp in cas_db.list_experiences(conn):
            if exp.get("is_completed") or exp.get("is_deleted"):
                continue
            cas_id = exp["id"]
            for ph in cas_db.list_reflections(conn, cas_id,
                                              kind="journal", placeholder=True):
                items.append({
                    "rid":        ph["id"],
                    "cas_id":     cas_id,
                    "name":       exp.get("name", ""),
                    "group_date": ph.get("group_date", ""),
                    "body_html":  ph.get("body_html", ""),
                })
    return items



def ctrl_create_placeholder_for(cas_id: int,
                                 date_str: Optional[str] = None) -> tuple[int, Optional[int]]:
    """Create a stealth placeholder for one experience by cloning an existing journal.
    Returns (journal_rid, None).  Falls back to old explicit tag pair if no template."""
    import time as _t

    # Completed experiences are locked on ManageBac — refuse instead of
    # posting a placeholder the user can never fill.
    exp = ctrl_get_experience(cas_id)
    if exp and exp.get("is_completed"):
        raise RuntimeError(
            f"Experience {exp.get('name') or cas_id} is completed — "
            "placeholders can't be created on locked experiences.")

    s, base = ctrl_session()
    csrf   = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas")
    lo_ids = ctrl_lo_ids_for(cas_id)
    date   = date_str or _t.strftime("%Y-%m-%d")

    # Use an existing non-placeholder journal as template
    cas_db.init_db()
    with cas_db.open_db() as conn:
        journals = cas_db.list_reflections(conn, cas_id, kind="journal", placeholder=False)
    template_body = next(
        (j["body_html"] for j in journals if j.get("body_html")), None
    )

    if template_body:
        rid = cas_api.create_stealth_placeholder(
            s, base, cas_id, csrf, lo_ids, date, template_body
        )
        return rid, None
    else:
        # No existing journal to clone — create a minimal stealth placeholder.
        # Use a real English date so substitute_date_in_html can match and replace it.
        from datetime import date as _date
        year, month, day = (int(x) for x in date.split("-"))
        en_date = f"{cas_api._MONTH_NAMES[month - 1]} {day}, {year}"
        rid = cas_api.create_stealth_placeholder(
            s, base, cas_id, csrf, lo_ids, date,
            template_body_html=(
                f"<p>{en_date} (--:-- – --:--, [strand], [hours])</p>"
                "<p>[Title]</p><p>-</p><p>-</p><p>-</p><p>-</p>"
            ),
        )
        return rid, None


def ctrl_run_due_schedules(today: Optional[str] = None) -> list[dict]:
    """Run placeholder creation for all due schedules.
    Returns list of per-experience result dicts."""
    import time as _t
    today = today or _t.strftime("%Y-%m-%d")
    cas_db.init_db()
    with cas_db.open_db() as conn:
        due = cas_db.get_due_schedules(conn, today)
    results = []
    for sched in due:
        cas_id = sched["cas_id"]
        if sched.get("is_completed"):
            continue
        try:
            j_rid, a_rid = ctrl_create_placeholder_for(cas_id, date_str=today)
            with cas_db.open_db() as conn:
                cas_db.set_schedule_last_run(conn, cas_id, today)
            results.append({"cas_id": cas_id, "name": sched.get("name", ""),
                            "j_rid": j_rid, "a_rid": a_rid, "ok": True})
        except Exception as ex:
            results.append({"cas_id": cas_id, "name": sched.get("name", ""),
                            "error": str(ex), "ok": False})
    return results


# ── DB stats ──────────────────────────────────────────────────────────────────

def ctrl_db_stats() -> dict:
    cas_db.init_db()
    with cas_db.open_db() as conn:
        return cas_db.db_stats(conn)
