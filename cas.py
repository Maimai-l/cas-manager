#!/usr/bin/env python3
"""
cas.py — ManageBac CAS Manager CLI

Usage:
  python cas.py login
  python cas.py status
  python cas.py config [--set-cas-id N] [--set-lo IDS] [--show]
  python cas.py list [--cas-id N] [--full] [--json]
  python cas.py show --rid N [--cas-id N]
  python cas.py create journal --body TEXT [--lo IDS] [--cas-id N]
  python cas.py create album PHOTO [PHOTO ...] [--caption TEXT] [--lo IDS] [--date YYYY-MM-DD]
  python cas.py edit --rid N [--body TEXT] [--add-photo FILE] [--caption TEXT] [--lo IDS]
  python cas.py delete --rid N [--yes]
  python cas.py backup [--out DIR] [--cas-id N]
  python cas.py placeholder create [--date YYYY-MM-DD] [--lo IDS] [--cas-id N]
  python cas.py placeholder clean [--dry-run] [--cas-id N]
  python cas.py ai write --rid N --notes TEXT [--cas-id N]
  python cas.py ai draft --notes TEXT
  python cas.py schedule on --time HH:MM [--lo IDS] [--cas-id N]
  python cas.py schedule off
  python cas.py schedule status
"""

import argparse
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from typing import Optional

import cas_api
import cas_db

# ── Config ───────────────────────────────────────────────────────────────────

CONFIG_FILE = Path("cas_config.json")

_CONFIG_DEFAULTS = {
    # base must be set explicitly by the user. CLI users:
    # `cas config --set-base https://yourschool.managebac.cn`.
    "base": "",
    "state": "mb_state.json",
    "cas_id": None,
    "lo_ids": [],
    "ai_provider": "anthropic",      # anthropic | ollama | prompt
    "ai_model": "deepseek-chat",
    "ollama_model": "llama3.2",
    "ollama_url": "http://localhost:11434",
    "backup_dir": "mb_backup_out",
}


def load_config() -> dict:
    cfg = dict(_CONFIG_DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg: dict) -> None:
    # Only save non-default keys that came from user
    out = {k: v for k, v in cfg.items() if k in _CONFIG_DEFAULTS}
    CONFIG_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Config saved → {CONFIG_FILE.resolve()}")


def resolve_cas_id(args, cfg: dict) -> int:
    v = getattr(args, "cas_id", None) or cfg.get("cas_id")
    if not v:
        sys.exit("Error: --cas-id required (or set with: cas config --set-cas-id N)")
    return int(v)


def resolve_lo_ids(args, cfg: dict, cas_id: Optional[int] = None) -> list[int]:
    # 1. Explicit --lo flag
    raw = getattr(args, "lo", None)
    if raw:
        return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
    # 2. Try to use the LOs configured for this experience (from DB)
    eid = cas_id or getattr(args, "cas_id", None) or cfg.get("cas_id")
    if eid:
        try:
            cas_db.init_db()
            with cas_db.open_db() as conn:
                exp = cas_db.get_experience(conn, int(eid))
            if exp and exp.get("lo_names"):
                ids = cas_api.lo_names_to_ids(exp["lo_names"])
                if ids:
                    return ids
        except Exception:
            pass
    # 3. Global config fallback
    configured = list(cfg.get("lo_ids") or [])
    if configured:
        return configured
    # 4. All 7
    return list(cas_api.LO_IDS.values())


class SessionExpiredError(RuntimeError):
    pass


def get_session(args, cfg: dict):
    base = getattr(args, "base", None) or cfg["base"]
    state_path = Path(getattr(args, "state", None) or cfg["state"])
    if not state_path.exists():
        print("No session found. Starting login...\n")
        cmd_login(args, cfg)
        state_path = Path(cfg["state"])
    state = cas_api.load_state(state_path)
    s = cas_api.build_session(state, base)
    if not cas_api.check_login(s, base):
        raise SessionExpiredError(state_path)
    return s, base


def read_body(value: str, html: bool = False) -> str:
    if not value:
        return ""
    if value.startswith("@"):
        text = Path(value[1:]).read_text(encoding="utf-8").strip()
    else:
        text = value.strip()
    if html:
        return text
    # Wrap plain text in <p> tags (split on newlines)
    parts = [f"<p>{line.strip()}</p>" for line in text.splitlines() if line.strip()]
    return "".join(parts) or f"<p>{text}</p>"


# ── Print helpers ─────────────────────────────────────────────────────────────

def print_entry(e: cas_api.ReflectionEntry, full: bool = False) -> None:
    kind_icon = {"journal": "📝", "album": "🖼 ", "file": "📎", "website": "🔗", "video": "🎬"}.get(e.kind, "❓")
    ph = " [placeholder]" if e.is_placeholder else ""
    date = e.group_date or "—"
    print(f"  {kind_icon} #{e.rid:>10}  {e.kind:<8}  {date:<20}{ph}")
    if full and e.body_html:
        import html as _h
        plain = _h.unescape(e.body_html.replace("<br>", "\n").replace("</p>", "\n"))
        import re; plain = re.sub(r"<[^>]+>", "", plain).strip()
        preview = textwrap.shorten(plain, width=80, placeholder="…")
        print(f"             {preview}")
    if full and e.photos:
        for p in e.photos:
            print(f"             📷 id={p.id} caption={p.caption!r}")


# ── Commands ─────────────────────────────────────────────────────────────────

def _prompt(question: str, default: str = "") -> str:
    """Simple prompt with optional default."""
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"{question}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val or default


def cmd_setup(args, cfg):
    """Interactive first-run wizard."""
    print("=" * 55)
    print("  ManageBac CAS Manager — First-time Setup")
    print("=" * 55)
    print()

    # ── Step 1: base URL ──────────────────────────────────
    print("Step 1/5  Base URL")
    print("  Enter your school's ManageBac URL — e.g. https://yourschool.managebac.cn")
    base = _prompt("ManageBac URL", cfg["base"])
    if not base or not base.strip():
        sys.exit("Base URL is required.")
    cfg["base"] = base
    print()

    # ── Step 2: Login ─────────────────────────────────────
    print("Step 2/5  Login")
    state_path = Path(cfg["state"])
    already_ok = False
    if state_path.exists():
        state = cas_api.load_state(state_path)
        s = cas_api.build_session(state, base)
        already_ok = cas_api.check_login(s, base)
        if already_ok:
            print(f"  ✅ Session already valid ({state_path})")

    if not already_ok:
        print("  A browser window will open. Log in to ManageBac,")
        print("  then run in another terminal:")
        print("    touch /tmp/mb_login_ready")
        input("  Press Enter to open the browser...")
        # Reuse cmd_login logic
        class _FakeArgs:
            state = str(state_path)
        cmd_login(_FakeArgs(), cfg)
        state = cas_api.load_state(state_path)
        s = cas_api.build_session(state, base)
    print()

    # ── Step 3: Pick default experience ───────────────────
    print("Step 3/5  Default CAS Experience")
    print("  Fetching your experience list...", flush=True)
    try:
        experiences = cas_api.fetch_experiences(s, base)
    except Exception as ex:
        print(f"  ❌ Could not fetch experiences: {ex}")
        experiences = []

    active = [e for e in experiences if not e.is_completed]
    if active:
        print(f"\n  Active experiences ({len(active)}):")
        for i, e in enumerate(active, 1):
            print(f"    {i:>2}. {e.cas_id}  {e.name}")
        print()
        choice = _prompt("  Enter number or CAS ID to set as default",
                         str(cfg.get("cas_id") or ""))
        if choice.isdigit() and 1 <= int(choice) <= len(active):
            default_exp = active[int(choice) - 1]
        elif choice.isdigit() and int(choice) > 100:
            # Looks like a raw CAS ID
            match = next((e for e in experiences if e.cas_id == int(choice)), None)
            default_exp = match or cas_api.Experience(int(choice), choice, False)
        else:
            default_exp = active[0]
            print(f"  Using first active experience: {default_exp.name}")
        cfg["cas_id"] = default_exp.cas_id
        print(f"  ✅ Default CAS ID: {default_exp.cas_id} ({default_exp.name})")
    else:
        print("  No active experiences found. You can set later with:")
        print("    cas config --set-cas-id N")
    print()

    # ── Step 4: Learning Outcome IDs ──────────────────────
    print("Step 4/5  Learning Outcome IDs (LO IDs)")
    print("  These are sent with every new reflection.")
    print("  Find them by inspecting an existing reflection edit page.")
    current_lo = ",".join(str(x) for x in (cfg.get("lo_ids") or []))
    lo_raw = _prompt("  LO IDs (comma-separated, or leave blank)", current_lo)
    if lo_raw:
        cfg["lo_ids"] = [int(x.strip()) for x in lo_raw.split(",") if x.strip().isdigit()]
        print(f"  ✅ LO IDs: {cfg['lo_ids']}")
    else:
        print("  Skipped. Set later with: cas config --set-lo N,N")
    print()

    # ── Step 5: Save & init DB ────────────────────────────
    print("Step 5/5  Finishing up")
    save_config(cfg)
    cas_db.init_db()
    print("  ✅ Local database initialised")
    print()
    print("=" * 55)
    print("  Setup complete! Try:")
    print(f"    cas sync --all          # sync all experiences")
    print(f"    cas list --local        # browse offline")
    print(f"    cas draft add 'notes'   # quick note → AI reflection")
    print("=" * 55)


def cmd_login(args, cfg):
    """Log in with email + password via mb_login.login_with_password."""
    import getpass
    import mb_login
    state_path = Path(getattr(args, "state", None) or cfg["state"])
    base = getattr(args, "base", None) or cfg["base"]

    email = (getattr(args, "email", None) or "").strip() or input("ManageBac email: ").strip()
    password = getattr(args, "password", None) or getpass.getpass("Password: ")
    if not email or not password:
        sys.exit("❌ Email and password cannot be empty")
    try:
        state = mb_login.login_with_password(email, password, base)
    except RuntimeError as e:
        sys.exit(f"❌ Login failed: {e}")
    mb_login.save_state(state, state_path)
    print(f"✅ Logged in (valid for ~1 year) → {state_path.resolve()}")


def cmd_status(args, cfg):
    base = getattr(args, "base", None) or cfg["base"]
    state_path = Path(getattr(args, "state", None) or cfg["state"])
    if not state_path.exists():
        print(f"❌ Session file not found: {state_path}")
        return
    state = cas_api.load_state(state_path)
    s = cas_api.build_session(state, base)
    ok = cas_api.check_login(s, base)
    mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(state_path.stat().st_mtime))
    print(f"{'✅ Logged in' if ok else '❌ Session expired'}  (saved {mtime})")
    print(f"  base: {base}")
    print(f"  state: {state_path.resolve()}")
    if cfg.get("cas_id"):
        print(f"  cas_id: {cfg['cas_id']}")
    if cfg.get("lo_ids"):
        print(f"  lo_ids: {cfg['lo_ids']}")


def cmd_config(args, cfg):
    changed = False
    if getattr(args, "set_cas_id", None):
        cfg["cas_id"] = args.set_cas_id; changed = True
    if getattr(args, "set_lo", None):
        cfg["lo_ids"] = [int(x.strip()) for x in args.set_lo.split(",") if x.strip().isdigit()]
        changed = True
    if getattr(args, "set_state", None):
        cfg["state"] = args.set_state; changed = True
    if getattr(args, "set_base", None):
        cfg["base"] = args.set_base; changed = True
    if getattr(args, "set_model", None):
        cfg["ai_model"] = args.set_model; changed = True
    if changed:
        save_config(cfg)
    else:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))


def _sync_one(s, base, cas_id: int, name: str, is_completed: bool,
              tag: str, db_path) -> dict:
    """Sync a single experience into the DB. Returns stats dict."""
    all_entries: list[cas_api.ReflectionEntry] = []
    for page_no, page_entries in cas_api.iter_pages(s, base, cas_id):
        all_entries.extend(page_entries)

    total = len(all_entries)
    errors = 0
    for i, entry in enumerate(all_entries, 1):
        try:
            html = cas_api.fetch_edit_html(s, base, cas_id, entry.rid)
            cas_api.enrich(entry, html, tag)
        except Exception as ex:
            errors += 1
            print(f"    Warning: #{entry.rid} enrich failed: {ex}")
        if i % 20 == 0 or i == total:
            print(f"    {i}/{total} enriched", flush=True)
        time.sleep(0.15)

    live_rids = {e.rid for e in all_entries}
    with cas_db.open_db(db_path) as conn:
        cas_db.sync_entries(conn, cas_id, all_entries,
                            name=name, is_completed=is_completed)
        gone = cas_db.purge_deleted(conn, cas_id, live_rids)

    return {"total": total, "gone": gone, "errors": errors}


def cmd_experience(args, cfg):
    cas_db.init_db()

    if args.exp_cmd == "show":
        cas_id = resolve_cas_id(args, cfg)
        as_json = getattr(args, "json", False)

        # Load from DB
        with cas_db.open_db() as conn:
            exp = cas_db.get_experience(conn, cas_id)
            reflections = cas_db.list_reflections(conn, cas_id)

        # Try to fetch proposal from network if not in DB
        if not exp or not exp.get("proposal_text"):
            try:
                s, base = get_session(args, cfg)
                proposal = cas_api.fetch_proposal(s, base, cas_id)
                with cas_db.open_db() as conn:
                    cas_db.upsert_experience(
                        conn, cas_id,
                        name=proposal.get("name", ""),
                        proposal_text=proposal.get("proposal_text"),
                        lo_names=proposal.get("lo_names"),
                        strand=proposal.get("strand", ""),
                    )
                    exp = cas_db.get_experience(conn, cas_id)
            except Exception as ex:
                print(f"Warning: could not fetch proposal: {ex}", file=sys.stderr)

        if as_json:
            out = {
                "cas_id": cas_id,
                "name": exp.get("name") if exp else "",
                "strand": exp.get("strand") if exp else "",
                "lo_names": exp.get("lo_names") if exp else [],
                "proposal_text": exp.get("proposal_text") if exp else "",
                "reflections": reflections,
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return

        # Human-readable structured output
        name = (exp.get("name") or str(cas_id)) if exp else str(cas_id)
        strand = (exp.get("strand") or "—") if exp else "—"
        lo_names = (exp.get("lo_names") or []) if exp else []

        print("=" * 60)
        print(f"  Experience: {name}")
        print(f"  CAS ID:     {cas_id}")
        print(f"  Strand:     {strand}")
        if lo_names:
            print(f"  Learning Outcomes:")
            for i, lo in enumerate(lo_names, 1):
                print(f"    {i}. {lo}")
        print("=" * 60)

        if exp and exp.get("proposal_text"):
            print("\n── PROPOSAL ─────────────────────────────────────────────")
            print(exp["proposal_text"])

        if reflections:
            print(f"\n── REFLECTIONS ({len(reflections)}) ──────────────────────────────────")
            for r in reflections:
                ph = " [placeholder]" if r["is_placeholder"] else ""
                print(f"\n  [{r['group_date']}] #{r['id']} {r['kind']}{ph}")
                if r.get("body_html"):
                    import html as _h, re as _re
                    plain = _h.unescape(
                        _re.sub(r"<[^>]+>", "", r["body_html"].replace("</p>", "\n"))
                    ).strip()
                    print(textwrap.indent(plain, "    "))

    elif args.exp_cmd == "create":
        # AI-powered one-stop experience creation
        _cmd_experience_create(args, cfg)


def _cmd_experience_create(args, cfg):
    """AI generates the full proposal from user's rough idea, then creates the experience."""
    model = cfg.get("ai_model", "deepseek-chat")

    print("── AI-Powered CAS Experience Creator ─────────────────────")
    print("Describe the experience you want to do (Ctrl+D when done):")
    print()
    idea = _read_notes(getattr(args, "idea", None))
    if not idea:
        sys.exit("Error: idea/description is required")

    # Generate full proposal via AI
    print("\nGenerating proposal...", flush=True)
    try:
        import anthropic
    except ImportError:
        sys.exit("Error: pip install anthropic")

    _PROPOSAL_SYSTEM = """\
You help IB Diploma Programme students write CAS (Creativity, Activity, Service) proposals.

STRICT OUTPUT FORMAT — output a JSON object with these exact keys:
{
  "name": "Experience name (concise, descriptive)",
  "strand": "Creativity" | "Activity" | "Service",
  "service_type": "direct" | "indirect" | "advocacy" | "research" | null,
  "description": "DESCRIPTION & OVERALL AIMS paragraph",
  "experience_goals": "EXPERIENCE GOALS (SMART) paragraph — at least 2 SMART goals",
  "personal_goals": "PERSONAL GOALS (SMART) paragraph — at least 2 SMART goals",
  "valuable_outcome": "VALUABLE OUTCOME paragraph",
  "planning": "PLANNING paragraph",
  "timeframe": "TIMEFRAME paragraph",
  "evaluation": "EVALUATION (SELF-ASSESSMENT) paragraph",
  "lo_suggestions": ["LO name 1", "LO name 2"],
  "suggested_start": "YYYY-MM-DD",
  "suggested_end": "YYYY-MM-DD"
}

RULES:
- Output ONLY valid JSON. No markdown, no code fences, no explanation outside JSON.
- All text values are plain text (no HTML, no markdown).
- Select at most 3 LOs from this list:
    1. Identify own strengths and develop areas for growth
    2. Demonstrate that challenges have been undertaken, developing new skills in the process
    3. Initiate and plan a CAS experience
    4. Show commitment to and perseverance in CAS experiences
    5. Demonstrate the skills and recognize the benefits of working collaboratively
    6. Demonstrate engagement with issues of global significance
    7. Recognize and consider the ethics of choices and actions
- Match the strand to the type of activity.
- Dates: use realistic timeframe based on description, anchor near today."""

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=2000,
        system=_PROPOSAL_SYSTEM,
        messages=[{"role": "user",
                   "content": f"My idea:\n{idea}\n\nGenerate the CAS proposal JSON:"}],
    )
    raw = msg.content[0].text.strip()

    try:
        proposal = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON block
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            proposal = json.loads(m.group(0))
        else:
            print("Error: AI returned invalid JSON. Raw output:")
            print(raw)
            sys.exit(1)

    # Show preview
    print("\n── Generated Proposal ─────────────────────────────────────")
    print(f"  Name:    {proposal.get('name')}")
    print(f"  Strand:  {proposal.get('strand')}")
    print(f"  Dates:   {proposal.get('suggested_start')} → {proposal.get('suggested_end')}")
    print(f"  LOs:     {proposal.get('lo_suggestions')}")
    print(f"\n  Description:\n{textwrap.indent(proposal.get('description',''), '    ')}")
    print(f"\n  Experience Goals:\n{textwrap.indent(proposal.get('experience_goals',''), '    ')}")
    print()

    # Confirm or edit
    if not getattr(args, "yes", False):
        try:
            action = input("[P]ost to ManageBac / [S]ave locally / [Q]uit: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return
        if action == "s":
            out_path = Path(f"cas_proposal_{proposal.get('name','draft').replace(' ','_')}.json")
            out_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2))
            print(f"✅ Saved to {out_path}")
            return
        elif action != "p":
            print("Cancelled.")
            return

    # ── Collect supervisor info (required fields) ─────────────
    # Supervisor info — from CLI flags or interactive prompt
    sup_name  = getattr(args, "supervisor_name",  None) or _prompt("  Supervisor name")
    sup_title = getattr(args, "supervisor_title", None) or _prompt("  Supervisor title/role")
    sup_email = getattr(args, "supervisor_email", None) or _prompt("  Supervisor email")
    sup_phone = getattr(args, "supervisor_phone", None) or _prompt("  Supervisor phone", "+1 201-555-0123")

    # ── Build notes HTML from proposal sections ───────────────
    sections = [
        ("EXPERIENCE NAME", proposal.get("name", "")),
        ("DESCRIPTION & OVERALL AIMS OF EXPERIENCE", proposal.get("description", "")),
        ("EXPERIENCE GOALS (SMART)", proposal.get("experience_goals", "")),
        ("PERSONAL GOALS (SMART)", proposal.get("personal_goals", "")),
        ("VALUABLE OUTCOME", proposal.get("valuable_outcome", "")),
        ("PLANNING", proposal.get("planning", "")),
        ("TIMEFRAME", proposal.get("timeframe", "")),
        ("EVALUATION (SELF-ASSESSMENT)", proposal.get("evaluation", "")),
    ]
    notes_html = "".join(
        f"<p>{heading}</p><p>{body}</p>" for heading, body in sections if body
    )

    # ── Map AI LO suggestions → LO IDs ───────────────────────
    lo_name_map = {
        "strength": cas_api.LO_IDS["strength_growth"],
        "growth":   cas_api.LO_IDS["strength_growth"],
        "challenge": cas_api.LO_IDS["challenge_skills"],
        "skill":    cas_api.LO_IDS["challenge_skills"],
        "initiative": cas_api.LO_IDS["initiative_planning"],
        "planning": cas_api.LO_IDS["initiative_planning"],
        "commitment": cas_api.LO_IDS["commitment_perseverance"],
        "perseverance": cas_api.LO_IDS["commitment_perseverance"],
        "collaborat": cas_api.LO_IDS["collaborative_skills"],
        "global":   cas_api.LO_IDS["global_engagement"],
        "engag":    cas_api.LO_IDS["global_engagement"],
        "ethic":    cas_api.LO_IDS["ethics"],
    }
    lo_ids: list[int] = []
    for suggestion in (proposal.get("lo_suggestions") or []):
        s_lower = suggestion.lower()
        for keyword, lo_id in lo_name_map.items():
            if keyword in s_lower and lo_id not in lo_ids:
                lo_ids.append(lo_id)
                break
    # default fallback
    if not lo_ids:
        lo_ids = [cas_api.LO_IDS["challenge_skills"]]

    strand = proposal.get("strand", "activity").lower()
    service_type = proposal.get("service_type") or None

    # ── POST ──────────────────────────────────────────────────
    s, base = get_session(args, cfg)
    csrf = cas_api.get_csrf(s, f"{base}/student/ib/activity/cas/new")
    print("\nCreating experience on ManageBac...", flush=True)
    new_cas_id = cas_api.create_experience(
        s, base, csrf,
        name=proposal["name"],
        notes_html=notes_html,
        strand=strand,
        hours=0.0,
        service_type=service_type,
        lo_ids=lo_ids,
        start_date=proposal.get("suggested_start"),
        end_date=proposal.get("suggested_end"),
        supervisor_name=sup_name,
        supervisor_title=sup_title,
        supervisor_email=sup_email,
        supervisor_phone=sup_phone,
    )
    print(f"✅ Created experience #{new_cas_id}: {proposal['name']}")
    print(f"   {base}/student/ib/activity/cas/{new_cas_id}")

    # Save to local DB
    cas_db.init_db()
    with cas_db.open_db() as conn:
        cas_db.upsert_experience(
            conn, new_cas_id,
            name=proposal["name"],
            proposal_text=notes_html,
            lo_names=proposal.get("lo_suggestions", []),
            strand=proposal.get("strand", ""),
        )
    print("   Saved to local DB.")


def cmd_sync(args, cfg):
    """Traverse ManageBac and write everything to local DB."""
    s, base = get_session(args, cfg)
    tag = cas_api.PLACEHOLDER_TAG
    db_path = cas_db.DEFAULT_DB
    cas_db.init_db(db_path)
    sync_all = getattr(args, "all", False)
    skip_completed = not getattr(args, "include_completed", False)

    if sync_all:
        # Discover all experiences from the list page
        print("Fetching experience list...", flush=True)
        experiences = cas_api.fetch_experiences(s, base)
        if skip_completed:
            active = [e for e in experiences if not e.is_completed]
            skipped = len(experiences) - len(active)
            print(f"Found {len(experiences)} experiences "
                  f"({skipped} completed, skipping)")
            experiences = active
        else:
            print(f"Found {len(experiences)} experiences")
    else:
        cas_id = resolve_cas_id(args, cfg)
        experiences = [cas_api.Experience(cas_id=cas_id, name="", is_completed=False)]

    total_refs = 0
    for exp in experiences:
        status = "completed" if exp.is_completed else "active"
        print(f"\n── {exp.name or exp.cas_id} (id={exp.cas_id}, {status}) ──",
              flush=True)
        # Fetch proposal while we're at it
        try:
            proposal = cas_api.fetch_proposal(s, base, exp.cas_id)
            with cas_db.open_db(db_path) as conn:
                cas_db.upsert_experience(
                    conn, exp.cas_id,
                    name=exp.name or proposal.get("name", ""),
                    is_completed=exp.is_completed,
                    proposal_text=proposal.get("proposal_text"),
                    lo_names=proposal.get("lo_names"),
                    strand=proposal.get("strand", ""),
                )
        except Exception:
            pass
        result = _sync_one(s, base, exp.cas_id, exp.name, exp.is_completed,
                           tag, db_path)
        total_refs += result["total"]
        print(f"  {result['total']} reflections synced"
              + (f", {len(result['gone'])} removed" if result["gone"] else "")
              + (f", {result['errors']} errors" if result["errors"] else ""))

    with cas_db.open_db(db_path) as conn:
        stats = cas_db.db_stats(conn)

    print(f"\n✅ Sync complete — {total_refs} reflections across "
          f"{len(experiences)} experience(s)")
    print(f"  DB totals: reflections={stats['reflections']}  "
          f"photos={stats['photos']}")


def cmd_list(args, cfg):
    cas_id = resolve_cas_id(args, cfg)
    full = getattr(args, "full", False)
    as_json = getattr(args, "json", False)
    kind_filter = getattr(args, "kind", None)
    ph_only = getattr(args, "placeholders", False)
    local = getattr(args, "local", False)

    if local:
        # Read from local DB — no network
        cas_db.init_db()
        with cas_db.open_db() as conn:
            rows = cas_db.list_reflections(
                conn, cas_id,
                kind=kind_filter,
                placeholder=True if ph_only else None,
            )
        if as_json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return
        print(f"\nTotal: {len(rows)} reflections (local DB)\n")
        current_date = None
        for r in rows:
            if r["group_date"] != current_date:
                current_date = r["group_date"]
                print(f"\n── {current_date or 'Unknown date'} ──")
            ph = " [placeholder]" if r["is_placeholder"] else ""
            kind_icon = {"journal": "📝", "album": "🖼 "}.get(r["kind"], "❓")
            print(f"  {kind_icon} #{r['id']:>10}  {r['kind']:<8}  {r['group_date']:<20}{ph}")
            if full and r.get("body_html"):
                import html as _h, re
                plain = _h.unescape(re.sub(r"<[^>]+>", "", r["body_html"].replace("</p>", "\n"))).strip()
                preview = textwrap.shorten(plain, width=80, placeholder="…")
                print(f"             {preview}")
        return

    # Live fetch from ManageBac
    s, base = get_session(args, cfg)
    print(f"Scanning CAS {cas_id}...", flush=True)
    entries: list[cas_api.ReflectionEntry] = []
    for _, page_entries in cas_api.iter_pages(s, base, cas_id):
        entries.extend(page_entries)

    if full or ph_only:
        total = len(entries)
        print(f"Enriching {total} entries...", end="", flush=True)
        for i, e in enumerate(entries):
            try:
                cas_api.enrich(e, cas_api.fetch_edit_html(s, base, cas_id, e.rid))
            except Exception:
                pass
            if (i + 1) % 10 == 0:
                print(f"\r  {i+1}/{total}...", end="", flush=True)
        print()

    if kind_filter:
        entries = [e for e in entries if e.kind == kind_filter]
    if ph_only:
        entries = [e for e in entries if e.is_placeholder]

    if as_json:
        print(json.dumps([{
            "rid": e.rid, "kind": e.kind, "group_date": e.group_date,
            "is_placeholder": e.is_placeholder,
            "body_preview": (e.body_html or "")[:100],
        } for e in entries], ensure_ascii=False, indent=2))
        return

    current_date = None
    print(f"\nTotal: {len(entries)} reflections\n")
    for e in entries:
        if e.group_date != current_date:
            current_date = e.group_date
            print(f"\n── {current_date or 'Unknown date'} ──")
        print_entry(e, full=full)


def cmd_show(args, cfg):
    s, base = get_session(args, cfg)
    cas_id = resolve_cas_id(args, cfg)
    rid = args.rid
    print(f"Fetching reflection #{rid}...", flush=True)
    e = cas_api.ReflectionEntry(rid=rid, kind="unknown", group_date="", page_no=0, pos=0)
    cas_api.enrich(e, cas_api.fetch_edit_html(s, base, cas_id, rid))

    print(f"\nReflection #{rid}")
    print(f"  Kind:     {e.kind}")
    print(f"  LO IDs:   {e.lo_ids}")
    if e.body_html:
        import html as _h, re
        plain = _h.unescape(re.sub(r"<[^>]+>", "", e.body_html.replace("</p>", "\n"))).strip()
        print(f"  Body:\n{textwrap.indent(plain, '    ')}")
    if e.photos:
        print(f"  Photos ({len(e.photos)}):")
        for p in e.photos:
            print(f"    id={p.id}  caption={p.caption!r}  date={p.created_at}")
    if e.s3_urls:
        print(f"  S3 URLs ({len(e.s3_urls)}):")
        for u in e.s3_urls:
            print(f"    {u}")


def cmd_create(args, cfg):
    s, base = get_session(args, cfg)
    cas_id = resolve_cas_id(args, cfg)
    lo_ids = resolve_lo_ids(args, cfg)
    csrf = cas_api.get_csrf(s, cas_api._url_list(base, cas_id))

    if args.create_type == "journal":
        body = read_body(args.body or "", html=getattr(args, "html_mode", False))
        if not body:
            print("Enter body (Ctrl+D to finish):")
            lines = []
            try:
                while True:
                    lines.append(input())
            except EOFError:
                pass
            body = "<br>".join(lines)
        print("Creating journal...", flush=True)
        rid = cas_api.create_journal(s, base, cas_id, csrf, body, lo_ids)
        print(f"✅ Created journal #{rid}")

    elif args.create_type == "album":
        photos = []
        captions = (args.caption or "").split("|")
        for i, p in enumerate(args.photos):
            path = Path(p)
            cap = captions[i] if i < len(captions) else ""
            ct = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            photos.append((path.name, path.read_bytes(), cap))
        date = getattr(args, "date", None) or None
        print("Creating album...", flush=True)
        rid = cas_api.create_album(s, base, cas_id, csrf, lo_ids, photos, date=date)
        print(f"✅ Created album #{rid}")


def cmd_edit(args, cfg):
    s, base = get_session(args, cfg)
    cas_id = resolve_cas_id(args, cfg)
    rid = args.rid
    lo_ids = resolve_lo_ids(args, cfg)

    # Determine what we're editing
    e = cas_api.ReflectionEntry(rid=rid, kind="unknown", group_date="", page_no=0, pos=0)
    cas_api.enrich(e, cas_api.fetch_edit_html(s, base, cas_id, rid))
    csrf = cas_api.get_csrf(s, cas_api._url_edit(base, cas_id, rid))
    lo_ids = lo_ids or e.lo_ids

    if getattr(args, "delete_photo_id", None):
        photo_id = args.delete_photo_id
        if not getattr(args, "yes", False):
            confirm = input(f"Delete photo #{photo_id} from reflection #{rid}? [y/N] ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return
        print(f"Deleting photo #{photo_id} from #{rid}...", flush=True)
        cas_api.delete_photo(s, base, cas_id, rid, csrf, photo_id)
        print(f"✅ Photo #{photo_id} deleted from #{rid}")
    elif getattr(args, "add_photo", None):
        caption = getattr(args, "caption", "") or ""
        date = getattr(args, "date", None) or None
        print(f"Adding photo to album #{rid}...", flush=True)
        cas_api.edit_album_add_photo(s, base, cas_id, rid, csrf, Path(args.add_photo), caption, date)
        print(f"✅ Photo added to #{rid}")
    elif getattr(args, "body", None):
        body = read_body(args.body, html=getattr(args, "html_mode", False))
        print(f"Updating body of #{rid}...", flush=True)
        cas_api.edit_journal(s, base, cas_id, rid, csrf, body, lo_ids)
        print(f"✅ Body updated for #{rid}")
    else:
        print("Nothing to do. Use --body or --add-photo.")


def cmd_delete(args, cfg):
    s, base = get_session(args, cfg)
    cas_id = resolve_cas_id(args, cfg)
    rid = args.rid
    if not getattr(args, "yes", False):
        confirm = input(f"Delete reflection #{rid}? [y/N] ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
    csrf = cas_api.get_csrf(s, cas_api._url_list(base, cas_id))
    cas_api.delete_reflection(s, base, cas_id, rid, csrf)
    # Mirror deletion in local DB if it exists
    if cas_db.DEFAULT_DB.exists():
        with cas_db.open_db() as conn:
            cas_db.delete_reflection_local(conn, rid)
    print(f"✅ Deleted #{rid}")


def cmd_backup(args, cfg):
    s, base = get_session(args, cfg)
    cas_id = resolve_cas_id(args, cfg)
    out_dir = Path(getattr(args, "out", None) or cfg.get("backup_dir") or "mb_backup_out")
    print(f"Backing up CAS {cas_id} → {out_dir}/")
    index_path = cas_api.backup_all(s, base, cas_id, out_dir)
    print(f"✅ Backup complete → {index_path.resolve()}")


def cmd_placeholder(args, cfg):
    s, base = get_session(args, cfg)
    cas_id = resolve_cas_id(args, cfg)
    lo_ids = resolve_lo_ids(args, cfg)

    if args.ph_cmd == "create":
        csrf = cas_api.get_csrf(s, cas_api._url_list(base, cas_id))
        date = getattr(args, "date", None) or None
        tag = cas_api.PLACEHOLDER_TAG
        print(f"Creating placeholder pair (date={date or 'today'})...", flush=True)
        j_rid, a_rid = cas_api.create_placeholder_pair(s, base, cas_id, csrf, lo_ids, date=date, tag=tag)
        print(f"✅ Placeholder created  journal=#{j_rid}  album=#{a_rid}")

    elif args.ph_cmd == "clean":
        dry = getattr(args, "dry_run", False)
        tag = cas_api.PLACEHOLDER_TAG
        csrf = cas_api.get_csrf(s, cas_api._url_list(base, cas_id))
        action = "Would delete" if dry else "Deleting"
        print(f"Scanning for placeholders (tag={tag!r})...", flush=True)
        rids = cas_api.cleanup_placeholders(s, base, cas_id, csrf, dry_run=dry, tag=tag)
        if rids:
            print(f"{action} {len(rids)} placeholders: {rids}")
            if dry:
                print("  (dry-run, nothing deleted — run without --dry-run to delete)")
        else:
            print("No placeholders found.")


# ── AI commands ───────────────────────────────────────────────────────────────

# Prompt construction + API providers live in cas_ai (shared with the web
# GUI). This file keeps only the CLI-interactive copy-paste flow below —
# it blocks on stdin and must never run inside the Flask server.
import cas_ai
from cas_ai import ai_system_with_context as _ai_system_with_context
from cas_ai import build_prompt as _build_prompt
from cas_ai import final_system_with_context as _final_system_with_context


def _ai_via_prompt_export(system: str, user: str) -> str:
    """Export full prompt for manual use, return placeholder."""
    full = f"=== SYSTEM PROMPT ===\n{system}\n\n=== YOUR MESSAGE ===\n{user}"
    # Copy to clipboard
    try:
        subprocess.run(["pbcopy"], input=full.encode(), check=True)
        print("✅ Full prompt copied to clipboard.")
    except Exception:
        pass
    # Also save to file
    out = Path("cas_ai_prompt.txt")
    out.write_text(full, encoding="utf-8")
    print(f"✅ Full prompt saved to: {out.resolve()}")
    print("\nPaste it into ChatGPT, Claude.ai, DeepSeek, or any AI tool.")
    print("Then paste the AI's response below (Ctrl+D to finish):\n")
    lines = []
    try:
        while True:
            lines.append(input())
    except EOFError:
        pass
    return "\n".join(lines).strip()


def ai_generate(notes: str, model: str,
                proposal: Optional[dict] = None,
                cfg: Optional[dict] = None,
                kind: str = "reflection",
                date: Optional[str] = None,
                existing: Optional[str] = None,
                history: Optional[list] = None) -> str:
    """CLI wrapper around cas_ai.ai_generate. The 'prompt' provider is
    handled here because its copy-paste flow is interactive (stdin)."""
    cfg = cfg or {}
    if cfg.get("ai_provider", "anthropic") == "prompt":
        if kind == "final":
            system = _final_system_with_context(proposal)
        else:
            system = _ai_system_with_context(proposal)
        _, user = _build_prompt(notes, system, kind, date=date,
                                existing=existing, history=history)
        return _ai_via_prompt_export(system, user)
    return cas_ai.ai_generate(notes, model, proposal=proposal, cfg=cfg,
                              kind=kind, date=date, existing=existing,
                              history=history)


def ai_generate_final(notes: str, model: str,
                      proposal: Optional[dict] = None,
                      cfg: Optional[dict] = None,
                      history: Optional[list] = None) -> str:
    return ai_generate(notes, model, proposal=proposal, cfg=cfg,
                       kind="final", history=history)


def _load_proposal_for(cas_id: int, s=None, base=None, cfg=None) -> Optional[dict]:
    """Try DB first, then network, return proposal dict or None."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        exp = cas_db.get_experience(conn, cas_id)
    if exp and exp.get("proposal_text"):
        return exp
    # Fetch from network if session available
    if s and base:
        try:
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
            pass
    return None


def cmd_ai(args, cfg):
    model = cfg.get("ai_model", "deepseek-chat")
    notes = _read_notes(getattr(args, "notes", None))

    if args.ai_cmd == "draft":
        cas_id = getattr(args, "cas_id", None) or cfg.get("cas_id")
        proposal = None
        if cas_id:
            try:
                s, base = get_session(args, cfg)
                proposal = _load_proposal_for(int(cas_id), s, base, cfg)
                if proposal:
                    print(f"  Using proposal: {proposal.get('name', cas_id)}")
            except Exception:
                pass
        print("Generating...", flush=True)
        result = ai_generate(notes, model, proposal=proposal)
        print("\n" + result)

    elif args.ai_cmd == "final":
        cas_id = getattr(args, "cas_id", None) or cfg.get("cas_id")
        proposal = None
        if cas_id:
            try:
                s, base = get_session(args, cfg)
                proposal = _load_proposal_for(int(cas_id), s, base, cfg)
                if proposal:
                    print(f"  Using proposal: {proposal.get('name', cas_id)}")
            except Exception:
                pass
        print("Generating final reflection...", flush=True)
        result = ai_generate_final(notes, model, proposal=proposal, cfg=cfg)
        print("\n── Final Reflection ──")
        import html as _h, re
        plain = _h.unescape(re.sub(r"<[^>]+>", "", result.replace("</p>", "\n"))).strip()
        print(plain)
        if getattr(args, "copy", False):
            try:
                subprocess.run(["pbcopy"], input=plain.encode(), check=True)
                print("\n✅ Copied to clipboard")
            except Exception:
                pass

    elif args.ai_cmd == "write":
        s, base = get_session(args, cfg)
        cas_id = resolve_cas_id(args, cfg)
        rid = args.rid
        lo_ids = resolve_lo_ids(args, cfg)

        proposal = _load_proposal_for(cas_id, s, base, cfg)
        if proposal:
            print(f"  Using proposal: {proposal.get('name', cas_id)}")
        print("Generating...", flush=True)
        body_html = ai_generate(notes, model, proposal=proposal)

        print("\n── Generated reflection ──")
        import html as _h, re
        plain = _h.unescape(re.sub(r"<[^>]+>", "", body_html.replace("</p>", "\n"))).strip()
        print(plain)
        print("─" * 40)

        if getattr(args, "copy", False):
            try:
                proc = subprocess.run(["pbcopy"], input=plain.encode(), check=True)
                print("✅ Copied to clipboard")
            except Exception as e:
                print(f"Clipboard copy failed: {e}")
            return

        action = input("\n[P]ost to ManageBac / [C]opy to clipboard / [Q]uit: ").strip().lower()
        if action == "p":
            csrf = cas_api.get_csrf(s, cas_api._url_edit(base, cas_id, rid))
            e = cas_api.ReflectionEntry(rid=rid, kind="unknown", group_date="", page_no=0, pos=0)
            cas_api.enrich(e, cas_api.fetch_edit_html(s, base, cas_id, rid))
            lo_ids = lo_ids or e.lo_ids
            cas_api.edit_journal(s, base, cas_id, rid, csrf, body_html, lo_ids)
            print(f"✅ Posted to reflection #{rid}")
        elif action == "c":
            try:
                subprocess.run(["pbcopy"], input=plain.encode(), check=True)
                print("✅ Copied to clipboard")
            except Exception as ex:
                print(f"Clipboard copy failed: {ex}")
        else:
            print("Cancelled.")


def cmd_draft(args, cfg):
    cas_db.init_db()
    model = cfg.get("ai_model", "deepseek-chat")

    if args.draft_cmd == "add":
        cas_id = resolve_cas_id(args, cfg)
        note = _read_notes(getattr(args, "note", None))
        if not note:
            sys.exit("Error: note text is required")
        with cas_db.open_db() as conn:
            draft_id = cas_db.add_draft(conn, cas_id, note)
        print(f"✅ Draft #{draft_id} saved (status: pending)")

    elif args.draft_cmd == "list":
        cas_id = getattr(args, "cas_id", None) or cfg.get("cas_id")
        status_filter = getattr(args, "status", None)
        with cas_db.open_db() as conn:
            rows = cas_db.list_drafts(conn,
                                      cas_id=int(cas_id) if cas_id else None,
                                      status=status_filter)
        if not rows:
            print("No drafts found.")
            return
        status_icon = {"pending": "⏳", "ready": "✍️ ", "posted": "✅"}
        for r in rows:
            icon = status_icon.get(r["status"], "❓")
            preview = textwrap.shorten(r["note"], width=60, placeholder="…")
            print(f"  {icon} #{r['id']:>4}  cas={r['cas_id']}  [{r['status']}]  {preview}")
            if r.get("ai_result"):
                import html as _h, re
                plain = _h.unescape(re.sub(r"<[^>]+>", "",
                                           r["ai_result"].replace("</p>", " "))).strip()
                ai_preview = textwrap.shorten(plain, width=60, placeholder="…")
                print(f"          AI → {ai_preview}")

    elif args.draft_cmd == "write":
        draft_id = args.id
        with cas_db.open_db() as conn:
            draft = cas_db.get_draft(conn, draft_id)
        if not draft:
            sys.exit(f"Error: draft #{draft_id} not found")
        if draft["status"] == "posted":
            print(f"Draft #{draft_id} is already posted.")
            return

        # Load proposal for context (DB first, then network)
        s_obj = None
        base_obj = None
        try:
            s_obj, base_obj = get_session(args, cfg)
        except SystemExit:
            pass
        proposal = _load_proposal_for(draft["cas_id"], s_obj, base_obj, cfg)
        if proposal:
            print(f"  Using proposal context: {proposal.get('name', draft['cas_id'])}")

        print(f"Generating from draft #{draft_id}...", flush=True)
        body_html = ai_generate(draft["note"], model, proposal=proposal)

        # Show plain-text preview
        import html as _h, re
        plain = _h.unescape(re.sub(r"<[^>]+>", "",
                                   body_html.replace("</p>", "\n"))).strip()
        print(f"\n── AI reflection (draft #{draft_id}) ──")
        print(plain)
        print("─" * 40)

        with cas_db.open_db() as conn:
            cas_db.update_draft(conn, draft_id, ai_result=body_html, status="ready")
        print(f"\n✅ Saved to draft #{draft_id} (status: ready)")
        print(f"   Post with:  cas draft post {draft_id}")

    elif args.draft_cmd == "post":
        draft_id = args.id
        with cas_db.open_db() as conn:
            draft = cas_db.get_draft(conn, draft_id)
        if not draft:
            sys.exit(f"Error: draft #{draft_id} not found")
        if draft["status"] == "posted":
            sys.exit(f"Error: draft #{draft_id} already posted")
        if not draft.get("ai_result"):
            sys.exit(f"Error: draft #{draft_id} has no AI result. Run: cas draft write {draft_id}")

        s, base = get_session(args, cfg)
        cas_id = draft["cas_id"]
        lo_ids = resolve_lo_ids(args, cfg) or cfg.get("lo_ids") or []
        csrf = cas_api.get_csrf(s, cas_api._url_list(base, cas_id))

        print(f"Posting draft #{draft_id} to CAS {cas_id}...", flush=True)
        rid = cas_api.create_journal(s, base, cas_id, csrf, draft["ai_result"], lo_ids)

        with cas_db.open_db() as conn:
            cas_db.update_draft(conn, draft_id, status="posted")
        print(f"✅ Posted as reflection #{rid}")
        print(f"   Draft #{draft_id} marked as posted.")


def _read_notes(value: str | None) -> str:
    if value and value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8").strip()
    if value:
        return value.strip()
    print("Enter rough notes (Ctrl+D to finish):")
    lines = []
    try:
        while True:
            lines.append(input())
    except EOFError:
        pass
    return "\n".join(lines).strip()


# ── Scheduler ─────────────────────────────────────────────────────────────────

PLIST_LABEL = "com.casmgr.placeholder"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "casmgr_placeholder.log"


def _plist_content(hour: int, minute: int, python: str, script: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
        <string>schedule</string>
        <string>run</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_PATH}</string>
    <key>WorkingDirectory</key>
    <string>{Path(script).parent}</string>
</dict>
</plist>"""


def cmd_schedule(args, cfg):
    cas_db.init_db()

    if args.sched_cmd == "set":
        # Configure per-experience schedule
        cas_id = resolve_cas_id(args, cfg)
        interval = getattr(args, "interval", 1) or 1
        lo_ids = resolve_lo_ids(args, cfg)
        enabled = not getattr(args, "disable", False)
        with cas_db.open_db() as conn:
            cas_db.upsert_schedule(conn, cas_id,
                                   enabled=enabled,
                                   interval_days=interval,
                                   lo_ids=lo_ids or None)
        state = "enabled" if enabled else "disabled"
        print(f"✅ Schedule {state}: cas_id={cas_id}  every {interval} day(s)")
        if lo_ids:
            print(f"   LO IDs: {lo_ids}")
        print(f"   Run 'cas schedule install' to activate launchd agent.")

    elif args.sched_cmd == "unset":
        cas_id = resolve_cas_id(args, cfg)
        with cas_db.open_db() as conn:
            cas_db.delete_schedule(conn, cas_id)
        print(f"✅ Schedule removed for cas_id={cas_id}")

    elif args.sched_cmd == "list":
        with cas_db.open_db() as conn:
            rows = cas_db.list_schedules(conn)
        if not rows:
            print("No schedules configured. Use: cas schedule set --cas-id N --interval DAYS")
            return
        print(f"{'CAS ID':<12} {'Name':<35} {'Every':<8} {'Enabled':<8} {'Last run'}")
        print("─" * 80)
        for r in rows:
            enabled = "✅" if r["enabled"] else "⏸ "
            last = r["last_run_date"] or "never"
            name = (r["name"] or "")[:33]
            print(f"  {r['cas_id']:<10} {name:<35} {r['interval_days']}d      "
                  f"{enabled}      {last}")

    elif args.sched_cmd == "install":
        t = getattr(args, "time", None) or "09:00"
        h, m = (int(x) for x in t.split(":"))
        python = sys.executable
        script = str(Path(__file__).resolve())
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_text(_plist_content(h, m, python, script))
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        res = subprocess.run(["launchctl", "load", str(PLIST_PATH)],
                             capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Warning: launchctl load failed: {res.stderr.strip()}")
        else:
            print(f"✅ launchd agent installed — runs daily at {t}")
            print(f"   Checks all schedules configured with 'cas schedule set'")
            print(f"   Log: {LOG_PATH}")

    elif args.sched_cmd == "uninstall":
        if not PLIST_PATH.exists():
            print("Agent not installed.")
            return
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        print("✅ launchd agent removed.")

    elif args.sched_cmd == "status":
        res = subprocess.run(["launchctl", "list", PLIST_LABEL],
                             capture_output=True, text=True)
        agent_ok = res.returncode == 0
        if PLIST_PATH.exists():
            import xml.etree.ElementTree as ET
            tree = ET.parse(str(PLIST_PATH))
            cal: dict = {}
            for d in tree.getroot().iter("dict"):
                keys = [c.text for c in d if c.tag == "key"]
                if "Hour" in keys:
                    children = list(d)
                    for i, c in enumerate(children):
                        if c.tag == "key" and c.text in ("Hour", "Minute"):
                            cal[c.text] = int(children[i + 1].text)
            t = f"{cal.get('Hour', 0):02d}:{cal.get('Minute', 0):02d}"
            print(f"Agent: {'running' if agent_ok else 'installed but not running'}  "
                  f"daily at {t}")
        else:
            print("Agent: not installed  (run: cas schedule install --time HH:MM)")
        with cas_db.open_db() as conn:
            rows = cas_db.list_schedules(conn)
        print(f"\n{len(rows)} experience schedule(s) configured:")
        for r in rows:
            enabled = "✅" if r["enabled"] else "⏸ "
            last = r["last_run_date"] or "never"
            print(f"  {enabled} cas={r['cas_id']}  every {r['interval_days']}d  "
                  f"last={last}  {r['name'] or ''}")

    elif args.sched_cmd == "run":
        # Called by launchd — check all due schedules and create placeholders
        s, base = get_session(args, cfg)
        today = time.strftime("%Y-%m-%d")
        tag = cas_api.PLACEHOLDER_TAG
        global_lo = cfg.get("lo_ids") or []

        with cas_db.open_db() as conn:
            due = cas_db.get_due_schedules(conn, today)

        if not due:
            print(f"[{today}] No schedules due today.")
            return

        print(f"[{today}] {len(due)} experience(s) due:")
        for sched in due:
            cas_id = sched["cas_id"]
            name = sched["name"] or str(cas_id)
            lo_ids = sched["lo_ids"] or global_lo
            print(f"  Creating placeholder for: {name} (cas={cas_id})...", flush=True)
            try:
                csrf = cas_api.get_csrf(s, cas_api._url_list(base, cas_id))
                j_rid, a_rid = cas_api.create_placeholder_pair(
                    s, base, cas_id, csrf, lo_ids, date=today, tag=tag)
                print(f"  ✅ journal=#{j_rid}  album=#{a_rid}")
                with cas_db.open_db() as conn:
                    cas_db.set_schedule_last_run(conn, cas_id, today)
            except Exception as ex:
                print(f"  ❌ Failed for cas={cas_id}: {ex}")


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cas", description="ManageBac CAS Manager")
    p.add_argument("--base", default=None, help="Override base URL")
    p.add_argument("--state", default=None, help="Path to mb_state.json")
    p.add_argument("--cas-id", type=int, default=None, dest="cas_id")

    sub = p.add_subparsers(dest="cmd", required=True)

    # setup
    sub.add_parser("setup", help="Interactive first-run setup wizard")

    # experience
    pexp = sub.add_parser("experience", help="Manage CAS experiences")
    pexp_sub = pexp.add_subparsers(dest="exp_cmd", required=True)

    pexp_show = pexp_sub.add_parser("show",
        help="Show structured content of an experience (proposal + reflections)")
    pexp_show.add_argument("--cas-id", type=int, default=None, dest="cas_id")
    pexp_show.add_argument("--json", action="store_true")

    pexp_create = pexp_sub.add_parser("create",
        help="AI-powered one-stop experience creation")
    pexp_create.add_argument("idea", nargs="?", default=None,
        help="Brief description of your idea (or @file.txt)")
    pexp_create.add_argument("--cas-id", type=int, default=None, dest="cas_id")
    pexp_create.add_argument("--supervisor-name",  default=None, dest="supervisor_name")
    pexp_create.add_argument("--supervisor-title", default=None, dest="supervisor_title")
    pexp_create.add_argument("--supervisor-email", default=None, dest="supervisor_email")
    pexp_create.add_argument("--supervisor-phone", default=None, dest="supervisor_phone")
    pexp_create.add_argument("--yes", action="store_true", help="Skip preview confirmation")

    # sync
    psync = sub.add_parser("sync", help="Sync ManageBac → local DB")
    psync.add_argument("--cas-id", type=int, default=None, dest="cas_id",
                       help="Sync a single experience (default: use config)")
    psync.add_argument("--all", action="store_true",
                       help="Discover and sync ALL experiences")
    psync.add_argument("--include-completed", action="store_true",
                       dest="include_completed",
                       help="Also sync completed/locked experiences")

    # login (email + password via mb_login)
    p_login = sub.add_parser("login", help="Log in with ManageBac email + password")
    p_login.add_argument("--email", default=None, help="ManageBac email (will prompt if omitted)")
    p_login.add_argument("--password", default=None, help="Password (will prompt securely if omitted)")

    # status
    sub.add_parser("status", help="Check session status")

    # config
    pc = sub.add_parser("config", help="Show or set config")
    pc.add_argument("--set-cas-id", type=int, dest="set_cas_id")
    pc.add_argument("--set-lo", dest="set_lo", help="Comma-separated LO IDs")
    pc.add_argument("--set-state", dest="set_state")
    pc.add_argument("--set-base", dest="set_base")
    pc.add_argument("--set-model", dest="set_model", help="Claude model for AI features")

    # list
    pl = sub.add_parser("list", help="List all reflections")
    pl.add_argument("--full", action="store_true", help="Show body preview and photos")
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--kind", choices=["journal", "album", "file", "website", "video"])
    pl.add_argument("--placeholders", action="store_true", help="Show only placeholders")
    pl.add_argument("--local", action="store_true", help="Read from local DB (no network)")

    # show
    ps = sub.add_parser("show", help="Show reflection details")
    ps.add_argument("--rid", type=int, required=True)

    # create
    pcr = sub.add_parser("create", help="Create a reflection")
    pcr_sub = pcr.add_subparsers(dest="create_type", required=True)

    pcr_j = pcr_sub.add_parser("journal")
    pcr_j.add_argument("--body", default="", help="Body text or @file.txt")
    pcr_j.add_argument("--lo", default="", help="LO IDs, comma-separated")
    pcr_j.add_argument("--html", action="store_true", dest="html_mode", help="Body is raw HTML")

    pcr_a = pcr_sub.add_parser("album")
    pcr_a.add_argument("photos", nargs="+", help="Photo file paths")
    pcr_a.add_argument("--caption", default="", help="Caption(s), | separated per photo")
    pcr_a.add_argument("--lo", default="")
    pcr_a.add_argument("--date", default=None, help="YYYY-MM-DD")

    # edit
    pe = sub.add_parser("edit", help="Edit a reflection")
    pe.add_argument("--rid", type=int, required=True)
    pe.add_argument("--body", default=None, help="New body text or @file")
    pe.add_argument("--html", action="store_true", dest="html_mode")
    pe.add_argument("--lo", default=None, help="LO IDs (comma-separated)")
    pe.add_argument("--add-photo", dest="add_photo", default=None, help="Photo file to add")
    pe.add_argument("--delete-photo", type=int, dest="delete_photo_id", default=None,
                    help="Photo ID to delete (see: cas show --rid N)")
    pe.add_argument("--caption", default="")
    pe.add_argument("--date", default=None)
    pe.add_argument("--yes", action="store_true", help="Skip confirmation")

    # delete
    pd = sub.add_parser("delete", help="Delete a reflection")
    pd.add_argument("--rid", type=int, required=True)
    pd.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    # backup
    pb = sub.add_parser("backup", help="Export all reflections")
    pb.add_argument("--out", default=None, help="Output directory")

    # placeholder
    pph = sub.add_parser("placeholder", help="Manage placeholder reflections")
    pph_sub = pph.add_subparsers(dest="ph_cmd", required=True)
    pph_c = pph_sub.add_parser("create")
    pph_c.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    pph_c.add_argument("--lo", default="")
    pph_cl = pph_sub.add_parser("clean")
    pph_cl.add_argument("--dry-run", action="store_true", dest="dry_run")

    # draft
    pdr = sub.add_parser("draft", help="Quick-note → AI draft queue")
    pdr_sub = pdr.add_subparsers(dest="draft_cmd", required=True)

    pdr_add = pdr_sub.add_parser("add", help="Save a quick note as a draft")
    pdr_add.add_argument("note", nargs="?", default=None,
                         help="Your rough notes (or @file.txt). Omit to type interactively.")
    pdr_add.add_argument("--cas-id", type=int, default=None, dest="cas_id")

    pdr_lst = pdr_sub.add_parser("list", help="List drafts")
    pdr_lst.add_argument("--cas-id", type=int, default=None, dest="cas_id")
    pdr_lst.add_argument("--status", choices=["pending", "ready", "posted"], default=None)

    pdr_w = pdr_sub.add_parser("write", help="AI-expand a draft and save result")
    pdr_w.add_argument("id", type=int, help="Draft ID")

    pdr_p = pdr_sub.add_parser("post", help="Post a ready draft to ManageBac")
    pdr_p.add_argument("id", type=int, help="Draft ID")
    pdr_p.add_argument("--lo", default="", help="LO IDs (comma-separated)")

    # ai
    pai = sub.add_parser("ai", help="AI-assisted reflection writing")
    pai_sub = pai.add_subparsers(dest="ai_cmd", required=True)
    pai_d = pai_sub.add_parser("draft", help="Generate reflection, print to stdout")
    pai_d.add_argument("--notes", default=None, help="Rough notes or @file")
    pai_w = pai_sub.add_parser("write", help="Generate and post/copy reflection")
    pai_w.add_argument("--rid", type=int, required=True)
    pai_w.add_argument("--notes", default=None)
    pai_w.add_argument("--lo", default="")
    pai_w.add_argument("--copy", action="store_true", help="Copy to clipboard instead of posting")

    pai_f = pai_sub.add_parser("final", help="Generate Final Reflection (4-question format)")
    pai_f.add_argument("--notes", default=None, help="Summary notes about the experience")
    pai_f.add_argument("--cas-id", type=int, default=None, dest="cas_id")
    pai_f.add_argument("--copy", action="store_true", help="Copy result to clipboard")

    # schedule
    psc = sub.add_parser("schedule", help="Auto-placeholder scheduler (macOS launchd)")
    psc_sub = psc.add_subparsers(dest="sched_cmd", required=True)

    psc_set = psc_sub.add_parser("set", help="Configure schedule for one experience")
    psc_set.add_argument("--cas-id", type=int, default=None, dest="cas_id")
    psc_set.add_argument("--interval", type=int, default=1,
                         help="Create placeholder every N days (default: 1)")
    psc_set.add_argument("--lo", default="", help="LO IDs for this experience")
    psc_set.add_argument("--disable", action="store_true",
                         help="Pause this experience without removing it")

    psc_unset = psc_sub.add_parser("unset", help="Remove schedule for one experience")
    psc_unset.add_argument("--cas-id", type=int, default=None, dest="cas_id")

    psc_sub.add_parser("list", help="Show all per-experience schedules")

    psc_inst = psc_sub.add_parser("install",
                                   help="Install launchd agent (runs cas schedule run daily)")
    psc_inst.add_argument("--time", default="09:00", help="HH:MM (default: 09:00)")

    psc_sub.add_parser("uninstall", help="Remove launchd agent")
    psc_sub.add_parser("status", help="Show agent + schedule status")
    psc_sub.add_parser("run", help="Run dispatcher now (checks all due schedules)")

    return p


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()

    # First-run detection: no config file and not explicitly calling setup/help
    if not CONFIG_FILE.exists() and (len(sys.argv) == 1 or
            (len(sys.argv) > 1 and sys.argv[1] not in ("setup", "-h", "--help"))):
        print("No configuration found. Starting setup wizard...\n")
        cmd_setup(argparse.Namespace(), cfg)
        return

    args = build_parser().parse_args()

    dispatch = {
        "setup": cmd_setup,
        "experience": cmd_experience,
        "sync": cmd_sync,
        "login": cmd_login,
        "status": cmd_status,
        "config": cmd_config,
        "list": cmd_list,
        "show": cmd_show,
        "create": cmd_create,
        "edit": cmd_edit,
        "delete": cmd_delete,
        "backup": cmd_backup,
        "placeholder": cmd_placeholder,
        "draft": cmd_draft,
        "ai": cmd_ai,
        "schedule": cmd_schedule,
    }
    try:
        dispatch[args.cmd](args, cfg)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except SessionExpiredError as e:
        print(f"\nSession expired ({e}).", file=sys.stderr)
        print("Run:  python cas.py login", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        msg = str(e)
        if "session expired" in msg.lower():
            print(f"\n{msg}", file=sys.stderr)
            print("Run:  python cas.py login", file=sys.stderr)
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
