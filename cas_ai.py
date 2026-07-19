"""
cas_ai.py — AI prompt construction + provider calls for CAS Manager.

Pure library module: no argparse, no print(), no sys.exit(), no stdin.
Used by cas_controller (web GUI) and cas.py (CLI). The CLI-only interactive
copy-paste flow (_ai_via_prompt_export) stays in cas.py — it blocks on stdin
and must never run inside the Flask server.

System prompts are managed by cas_prompts (registry + DB overrides). The
*static* baseline is owned by cas_prompts._DEFAULTS; the per-experience
context (proposal text + LOs + strand) is appended here at runtime — that
context is dynamic and never user-editable.
"""

from __future__ import annotations

from typing import Optional

import cas_prompts


# ── System prompts with per-experience context ───────────────────────────────

def ai_system_with_context(proposal: Optional[dict]) -> str:
    base = cas_prompts.get("reflection.system")
    if not proposal or not proposal.get("proposal_text"):
        return base
    lo_text = ""
    if proposal.get("lo_names"):
        lo_text = "\n".join(f"  - {lo}" for lo in proposal["lo_names"])
        lo_text = f"\n\nSELECTED LEARNING OUTCOMES FOR THIS EXPERIENCE:\n{lo_text}"
    # `strand` may hold multiple comma-separated strands (e.g.
    # "Creativity, Activity"). Pass through as-is — the system prompt
    # instructs the AI to handle single vs multi correctly.
    strand_text = (f"\n\nSTRAND: {proposal['strand']}" if proposal.get("strand") else "")
    return (
        base
        + f"\n\n{'='*60}"
        + f"\nEXPERIENCE PROPOSAL (for context — align reflection to these goals):"
        + f"\n{proposal['proposal_text'][:2000]}"
        + lo_text
        + strand_text
    )


def sa_system_with_context(proposal: Optional[dict]) -> str:
    base = cas_prompts.get("sa_question.system")
    if not proposal or not proposal.get("proposal_text"):
        return base
    lo_text = ""
    if proposal.get("lo_names"):
        lo_text = "\n".join(f"  - {lo}" for lo in proposal["lo_names"])
        lo_text = f"\n\nSELECTED LEARNING OUTCOMES:\n{lo_text}"
    return (
        base
        + f"\n\n{'='*60}"
        + f"\nEXPERIENCE PROPOSAL (context):\n{proposal['proposal_text'][:2000]}"
        + lo_text
    )


def final_system_with_context(proposal: Optional[dict]) -> str:
    base = cas_prompts.get("final.system")
    if not proposal or not proposal.get("proposal_text"):
        return base
    lo_text = ""
    if proposal.get("lo_names"):
        lo_text = "\n".join(f"  - {lo}" for lo in proposal["lo_names"])
        lo_text = f"\n\nSELECTED LEARNING OUTCOMES:\n{lo_text}"
    return (
        base
        + f"\n\n{'='*60}"
        + f"\nEXPERIENCE PROPOSAL (context):\n{proposal['proposal_text'][:1500]}"
        + lo_text
    )


# ── User-message construction ─────────────────────────────────────────────────

def format_history_block(history: Optional[list]) -> str:
    """Format past reflections as a context block for the AI. `history` is a
    list of dicts with at least `group_date` and `body_text` (or `body_html`)
    keys, chronologically ordered (oldest first)."""
    if not history:
        return ""
    parts = ["", "MY FULL SESSION-BY-SESSION HISTORY FOR THIS EXPERIENCE:"]
    # Cap total length at ~30k chars to stay within typical context windows.
    budget = 30000
    used = 0
    for i, h in enumerate(history, 1):
        date = (h.get("group_date") or "?").strip()
        body = h.get("body_text") or ""
        # Strip HTML if only body_html is available
        if not body and h.get("body_html"):
            import html as _html_mod
            import re as _re
            decoded = _html_mod.unescape(h["body_html"])
            body = " ".join(_re.sub(r"<[^>]+>", " ", decoded).split())
        chunk = f"\n--- Session {i} ({date}) ---\n{body}\n"
        if used + len(chunk) > budget:
            parts.append(f"\n[... {len(history) - i + 1} earlier session(s) truncated to keep context manageable ...]")
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def build_prompt(notes: str, system: str, kind: str = "reflection",
                 date: Optional[str] = None,
                 existing: Optional[str] = None,
                 history: Optional[list] = None,
                 question: Optional[str] = None) -> tuple[str, str]:
    """Return (system_prompt, user_message) for any provider.
    kind = 'reflection' | 'final' | 'edit' | 'sa_question'.
    For 'edit', `existing` is the current reflection text and `notes` are the
    user's modification instructions.
    For 'final', `history` (if provided) is included as session-by-session
    context so the summary can be grounded in real evidence.
    For 'sa_question', `question` is the ManageBac Self-Assessment question
    text, `existing` the current answer (if any), and `history` is included
    as evidence."""
    history_block = format_history_block(history)
    if kind == "sa_question":
        existing_block = (
            "\nMY CURRENT ANSWER (revise it according to my notes; keep what works):\n"
            f"{existing}\n"
        ) if (existing or "").strip() else ""
        notes_block = f"\nMy notes on what to say:\n{notes}\n" if (notes or "").strip() else ""
        user = (
            "THE SELF-ASSESSMENT QUESTION TO ANSWER:\n"
            f"{question or ''}\n"
            f"{existing_block}"
            f"{notes_block}"
            f"{history_block}\n\n"
            "Write the answer to this question:"
        )
    elif kind == "final":
        user = (
            f"Notes / themes I'd like the final reflection to emphasize:\n{notes}\n"
            f"{history_block}\n\n"
            f"Write the CAS Final Reflection (4 questions):"
        )
    elif kind == "edit":
        user = (
            "Here is my existing CAS session reflection:\n"
            "<<<EXISTING>>>\n"
            f"{existing or ''}\n"
            "<<<END>>>\n\n"
            "Please revise it based on the following changes/instructions:\n"
            f"{notes}\n\n"
            "Output the revised reflection only — same language, same overall structure, "
            "no commentary, no markdown. Keep what still works and only change what the "
            "instructions ask to change."
        )
    else:
        date_line = f"Date of this session: {date}\n" if date else ""
        user = f"{date_line}My rough notes for this session:\n{notes}\n\nWrite the CAS session reflection:"
    return system, user


# ── Providers ─────────────────────────────────────────────────────────────────

def _ai_via_anthropic(system: str, user: str, model: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Anthropic provider needs the SDK: pip install anthropic")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=900, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


def _ai_via_deepseek(system: str, user: str, model: str, api_key: str = "") -> str:
    """Call DeepSeek's OpenAI-compatible chat endpoint. The API key comes
    from Settings (stored in config); falls back to DEEPSEEK_API_KEY env."""
    import json as _json
    import os
    import urllib.request
    key = (api_key or "").strip() or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Add your DeepSeek API key in Settings → AI provider")
    payload = _json.dumps({
        "model": model or "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as ex:
        raise RuntimeError(f"DeepSeek error: {ex}")


def _ai_via_ollama(system: str, user: str, model: str, url: str) -> str:
    import json as _json
    import urllib.request
    payload = _json.dumps({
        "model": model,
        "system": system,
        "prompt": user,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
        return data.get("response", "").strip()
    except Exception as ex:
        raise RuntimeError(f"Ollama error: {ex} — make sure Ollama is running (ollama serve)")


# ── Generation entry points ───────────────────────────────────────────────────

def ai_generate(notes: str, model: str,
                proposal: Optional[dict] = None,
                cfg: Optional[dict] = None,
                kind: str = "reflection",
                date: Optional[str] = None,
                existing: Optional[str] = None,
                history: Optional[list] = None,
                question: Optional[str] = None) -> str:
    cfg = cfg or {}
    provider = cfg.get("ai_provider", "deepseek")
    # "edit" reuses the regular reflection system prompt (LO context etc.)
    if kind == "final":
        system = final_system_with_context(proposal)
    elif kind == "sa_question":
        system = sa_system_with_context(proposal)
    else:
        system = ai_system_with_context(proposal)
    _, user = build_prompt(notes, system, kind, date=date,
                           existing=existing, history=history,
                           question=question)

    if provider == "ollama":
        return _ai_via_ollama(system, user,
                              cfg.get("ollama_model", "llama3.2"),
                              cfg.get("ollama_url", "http://localhost:11434"))
    if provider == "prompt":
        raise RuntimeError(
            "Provider 'prompt' is the manual copy-paste flow — build the prompt "
            "with build_prompt() and let the user paste the AI's answer back."
        )
    if provider == "anthropic":
        return _ai_via_anthropic(system, user, model)
    return _ai_via_deepseek(system, user, model or "deepseek-chat",
                            cfg.get("deepseek_api_key", ""))


def ai_generate_final(notes: str, model: str,
                      proposal: Optional[dict] = None,
                      cfg: Optional[dict] = None,
                      history: Optional[list] = None) -> str:
    return ai_generate(notes, model, proposal=proposal, cfg=cfg,
                       kind="final", history=history)
