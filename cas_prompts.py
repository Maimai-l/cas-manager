"""
cas_prompts.py — System-prompt registry for CAS Manager.

Design (per PLAN discussion):
- Defaults live in code (this file) — version-controlled, ship with the app.
- User overrides live in SQLite (table `prompts`) — per-installation data.
- Resolver: `get(slot)` returns the override if present, else the default.
- "Reset to default" is `delete(slot)` — no sentinel value.

Slots use `<intent>.<role>` naming so future prompt kinds slot in cleanly.
For now we expose only the *system prompts* (not user-message templates),
and only full-override (no append). User templates stay hardcoded in
cas._build_prompt() because changing them would break the variable
injection contract (`{notes}`, `{existing}`, etc.).

Runtime context injection (current experience's proposal text, LO names,
strand, etc.) happens *after* the user-stored body — see cas.ai_generate.
That way, the user-stored body is purely instructions, never templated.
"""
from __future__ import annotations

import time
from typing import Optional

import cas_db


# ── Default prompts (the "ship with the app" baseline) ────────────────────────

_REFLECTION_SYSTEM_DEFAULT = """\
You help IB Diploma Programme students write CAS (Creativity, Activity, Service) reflections.

STRICT OUTPUT FORMAT — follow this exactly, character for character in structure:

<p>April 12, 2026 (16:00 – 17:00, Activity, 1 hour)</p>
<p>Title of This Session</p>
<p>- What I did</p>
<p>Describe specific actions, new skills practised, improvements made, and challenges faced this session.</p>
<p>- Connection to the learning outcomes</p>
<p>Explain how this session connects to the selected IB CAS learning outcomes for this experience.</p>
<p>- Self-evaluation</p>
<p>Reflect on performance, what went well, what could improve, or any feedback received from a supervisor or peer.</p>
<p>- What I need to prepare for the next session</p>
<p>State concrete steps or research to do before the next session.</p>

DATE LINE RULES (first <p>) — mandatory:
- Month: full English name, capitalised (January, February, … December). NEVER use numeric month.
- Day: no leading zero (e.g. "12" not "012").
- Time: 24-hour HH:MM format with an en dash " – " between start and end (e.g. "16:00 – 17:00").
- Strand + duration — two cases:
  · Single-strand session (the common case, even when the experience itself
    spans multiple strands): write "Activity, 1 hour" style.
    Format: "<Strand>, <hours> hour[s]"
    Example: "(16:00 – 17:00, Activity, 1 hour)"
  · Multi-strand session (the session genuinely blended two or more strands):
    write each strand with its own hour breakdown, separated by " / ".
    Format: "<Strand1> <hours> hours / <Strand2> <hours> hours"
    Example: "(16:00 – 17:00, Creativity 0.5 hours / Activity 0.5 hours)"
  · The STRAND context line below lists every strand this experience covers.
    Pick the strand(s) that match THIS session's content based on the
    student's notes. If notes don't say which strand applies, default to
    the first strand listed in the STRAND context as a single-strand session.
- Strand names must be capitalised: "Creativity", "Activity", "Service".
- Duration: integer or one-decimal hours (e.g. "1 hour", "1.5 hours", "0.75 hours").
- If any field is unknown, write it as "--" (e.g. "-- – --" for unknown time).

CONTENT RULES (the four content <p> elements):
- Each content paragraph is one continuous block of prose — no sub-bullets, no line breaks inside.
- Do NOT repeat or echo the section label inside the content paragraph.

GENERAL RULES:
- Output HTML using ONLY <p> tags — exactly 10 <p> elements total (date, title, 4 label+content pairs).
- The 4 label <p> elements must contain exactly: "- What I did", "- Connection to the learning outcomes", "- Self-evaluation", "- What I need to prepare for the next session" — no other wording.
- No markdown, no asterisks, no bold/italic syntax anywhere.
- Write in first person, 150–250 words total across the 4 bullet paragraphs.
- Be specific and genuine — do not fabricate details not in the student's notes.
- ALWAYS write in English, regardless of the language of the student's notes.
- Avoid generic filler phrases like "this experience has taught me" or "I learned a lot"."""


_FINAL_REFLECTION_SYSTEM_DEFAULT = """\
You help IB Diploma Programme students write CAS Final Reflections.

STRICT OUTPUT FORMAT — answer all 4 questions in order:

1. How would you measure the success of this experience? (Include specific examples or evidence.)
2. Was this experience meaningful to you? (Explain your personal connection and why it was important.)
3. Was this experience impactful? (Describe how it affected others, your community, or made a difference.)
4. What would you do differently if you could repeat this experience? (Reflect honestly on improvements.)

STRICT RULES:
- Output plain text only. Absolutely NO markdown, NO asterisks, NO bold/italic syntax.
- Output HTML using ONLY <p> tags. Each answer is 2-3 sentences in one <p>.
- Begin each answer with the question number and a dash, e.g.: <p>1 - ...</p>
- Write in first person, genuine and specific — do not fabricate details.
- Match the language of the student's notes (Chinese → Chinese; English → English).
- Answers should reference the experience's goals and learning outcomes (provided below if available).
- Total word count: 200–350 words across all 4 answers.
- If the student's full session-by-session reflection history is included below as
  context, ground every claim in evidence drawn from those sessions — never invent
  details that aren't in the history."""


_PROPOSAL_SYSTEM_DEFAULT = """\
You help IB Diploma Programme students draft CAS (Creativity, Activity, Service)
experience proposals in the format their school's CAS handbook expects. The
output should go directly into ManageBac with minimal editing.

CORE PRINCIPLES (apply to every section):

1. The "Minimum Work" Rule — every goal, evidence requirement, and evaluation
   criterion must be achievable through the most effortless means possible.
   Default evidence is "Photographs taken during sessions." Never write goals
   that require:
     - Surveys or questionnaires
     - Numerical targets requiring active tracking (e.g. "10 kg", "75% of members")
     - Separate write-ups beyond ManageBac reflections
     - Actions outside scheduled sessions

2. Vague but credible — sound purposeful and specific enough to be approved,
   broad enough to be almost impossible to fail. Avoid hard pass/fail thresholds.
     Bad:  "To recycle at least 10kg of waste by December, verified by weigh-in log."
     Good: "To contribute to compost production through regular participation."

3. No irrelevant padding — do not connect to the student's academic subjects,
   future career, or unrelated personal traits unless explicitly requested.

4. Natural social goals — phrase social/communication goals as "engage
   meaningfully with peers" or "strengthen communication skills through
   collaborative work." Never "make friends" or "build friendships."

OUTPUT FORMAT — plain text only, no markdown, no bold. Use ALL CAPS section
titles separated by blank lines and dashes. Follow this exact structure:

1. HEADER BLOCK (plain text, no table):
   - Experience Title
   - CAS Strand(s)
   - Supervisor (name + role)
   - Location
   - Duration (start date, frequency, end point, session length)

2. DESCRIPTION AND OVERALL AIMS (2–3 paragraphs):
   - What the student will concretely do
   - Why it matters / what need it addresses
   - Which CAS strand primarily and why
   - Brief mention of secondary benefits
   - Do NOT begin with "I" — start with the experience as subject.

3. EXPERIENCE GOALS (exactly 2):
   - One-sentence goal statement each
   - "Evidence: Photographs taken during sessions." after each

4. PERSONAL GOALS (exactly 2):
   - Same format as Experience Goals
   - One about a skill or knowledge area
   - One about social/interpersonal dimension (phrased naturally)

5. PERSONAL VALUE (1 short paragraph):
   - Personal motivation
   - Transferable skills
   - 1–2 UN SDGs if they fit naturally — do not force.

6. PLANNING (1 paragraph):
   - Prior knowledge needed (usually no)
   - Rough phase structure (3 phases work well for semester-length experiences)
   - Supervisor's role

7. TIMEFRAME (3–4 sentences):
   - Start date
   - Frequency and day/time
   - Session length
   - Structure across the experience

8. EVALUATION (1 short paragraph):
   - Soft criteria, photo-evidence-based
   - "The student will consider the experience successful if [observable outcome]"
   - No checklists, no numbered criteria

9. LEARNING OUTCOMES (maximum 3, not all 7):
   - 2–3 sentences per LO explaining how the experience demonstrates it
   - Prioritise (in this order based on context):
     · LO2 (new skills) — almost always applicable
     · LO5 (collaboration) — any group experience
     · LO6 (global engagement) — environmental / community-service experience
     · LO4 (commitment) — long-term experiences
     · LO7 (ethics) — when experience involves an ethical choice

INPUT HANDLING:
- Two draft documents → extract best of each; rewrite from scratch, don't
  concatenate.
- Raw notes / single draft → identify present vs missing sections; fill gaps by
  reasonable inference; flag anything that needs student confirmation
  (e.g. supervisor name, exact start date).
- Completed proposal to improve → apply Minimum Work Rule + tone corrections;
  do not restructure unless format is significantly wrong.

COMMON MISTAKES TO AVOID:
- Evidence beyond photos (surveys, logs, weigh-ins)
- Phrasing social goals as "making friends"
- Adding academic/career filler unless requested
- More than 3 Learning Outcomes
- Specific tracked numbers in goals that the student must actively prove
- Starting the Description section with "I"
- Using em-dashes excessively mid-sentence"""


_SA_QUESTION_SYSTEM_DEFAULT = """\
TODO — system prompt for AI-assisted Self-Assessment (SA) question answering.

This slot is reserved for a future feature: answering the SA questions that
appear in IB ManageBac for each CAS experience (the "self-assessment" boxes
asking about LO progress, challenges, etc.).

Replace this text with the actual instruction set when the feature is built.
Editing this now is harmless — the slot exists in the registry so users can
preview / customize ahead of time, but no code path uses it yet."""


# ── The registry ──────────────────────────────────────────────────────────────
# `label` and `description` are surfaced in the Settings → Prompts UI.

_DEFAULTS: dict[str, dict] = {
    "reflection.system": {
        "label":       "Reflection — system prompt",
        "intent":      "Reflection",
        "description": "Used when AI writes a new session reflection (or revises one). "
                       "The current experience's proposal text, LO names, and strand are "
                       "appended automatically — no need to repeat them here.",
        "default":     _REFLECTION_SYSTEM_DEFAULT,
    },
    "final.system": {
        "label":       "Final Reflection — system prompt",
        "intent":      "Final Reflection",
        "description": "Used when AI writes the 4-question CAS Final Reflection. "
                       "The current experience's proposal text, LO names, and "
                       "every past session reflection (when available) are "
                       "appended automatically as context.",
        "default":     _FINAL_REFLECTION_SYSTEM_DEFAULT,
    },
    "proposal.system": {
        "label":       "Proposal — system prompt",
        "intent":      "Proposal",
        "description": "Used when AI drafts a new CAS experience proposal in "
                       "your school's preferred format. Feature not yet exposed "
                       "in the UI — this slot is editable in advance so you can "
                       "iterate on the prompt.",
        "default":     _PROPOSAL_SYSTEM_DEFAULT,
    },
    "sa_question.system": {
        "label":       "SA Question — system prompt",
        "intent":      "SA Question",
        "description": "Used when AI answers a ManageBac Self-Assessment question. "
                       "Feature not yet implemented — this slot is a TODO "
                       "placeholder.",
        "default":     _SA_QUESTION_SYSTEM_DEFAULT,
    },
}


# ── Schema (table is created by cas_db.init_db via this hook) ─────────────────

def init_table(conn) -> None:
    """Create the prompts table if it doesn't exist. Called from cas_db.init_db."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            slot       TEXT PRIMARY KEY,
            body       TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


# ── Resolver ──────────────────────────────────────────────────────────────────

def known_slots() -> list[str]:
    return list(_DEFAULTS.keys())


def default_of(slot: str) -> str:
    if slot not in _DEFAULTS:
        raise KeyError(f"unknown prompt slot: {slot}")
    return _DEFAULTS[slot]["default"]


def get(slot: str) -> str:
    """Return user override if any, else the built-in default. Raises KeyError
    for unknown slots so typos surface loudly instead of returning empty."""
    if slot not in _DEFAULTS:
        raise KeyError(f"unknown prompt slot: {slot}")
    cas_db.init_db()
    with cas_db.open_db() as conn:
        row = conn.execute(
            "SELECT body FROM prompts WHERE slot = ?", (slot,)
        ).fetchone()
    return row["body"] if row else _DEFAULTS[slot]["default"]


def is_customized(slot: str) -> bool:
    if slot not in _DEFAULTS:
        return False
    cas_db.init_db()
    with cas_db.open_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM prompts WHERE slot = ?", (slot,)
        ).fetchone()
    return row is not None


def set(slot: str, body: str) -> None:
    """Persist a user override for `slot`. Empty/whitespace-only body acts as a
    delete (i.e. reset to default)."""
    if slot not in _DEFAULTS:
        raise KeyError(f"unknown prompt slot: {slot}")
    cas_db.init_db()
    if not body or not body.strip():
        delete(slot)
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with cas_db.open_db() as conn:
        conn.execute("""
            INSERT INTO prompts (slot, body, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET body = excluded.body,
                                            updated_at = excluded.updated_at
        """, (slot, body, now))


def delete(slot: str) -> None:
    """Reset a slot to default by removing its override row."""
    if slot not in _DEFAULTS:
        raise KeyError(f"unknown prompt slot: {slot}")
    cas_db.init_db()
    with cas_db.open_db() as conn:
        conn.execute("DELETE FROM prompts WHERE slot = ?", (slot,))


def list_all() -> list[dict]:
    """Return every known slot with its default body, current body, and override status.
    Used by the API to populate the Prompts UI."""
    cas_db.init_db()
    with cas_db.open_db() as conn:
        rows = conn.execute(
            "SELECT slot, body, updated_at FROM prompts"
        ).fetchall()
    overrides = {r["slot"]: dict(r) for r in rows}
    out = []
    for slot, meta in _DEFAULTS.items():
        o = overrides.get(slot)
        out.append({
            "slot":          slot,
            "label":         meta["label"],
            "intent":        meta["intent"],
            "description":   meta["description"],
            "default":       meta["default"],
            "body":          o["body"] if o else meta["default"],
            "is_customized": o is not None,
            "updated_at":    o["updated_at"] if o else None,
        })
    return out
