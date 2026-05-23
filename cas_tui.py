#!/usr/bin/env python3
"""
cas_tui.py — Interactive Textual TUI for CAS Manager.

Run:  python cas_tui.py
Deps: pip install textual

Architecture:
  All business logic is in cas_controller.py.
  This file contains only UI code (screens, widgets, event handlers).
  Replacing this file with a web/Tauri frontend only requires rewriting this
  file — cas_controller.py (the interface layer) stays the same.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
    from textual.screen import ModalScreen, Screen
    from textual.widgets import (
        Button,
        DataTable,
        Footer,
        Header,
        Input,
        Label,
        LoadingIndicator,
        Static,
        TextArea,
    )
    from textual import work
except ImportError:
    sys.exit("Error: pip install textual")

import cas_controller as ctrl

# ══════════════════════════════════════════════════════════════════════════════
# ── Helpers ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _strip_html(html: str) -> str:
    import re, html as _h
    text = _h.unescape(re.sub(r"<[^>]+>", " ", html or ""))
    return " ".join(text.split())


def _strand_icon(strand: str) -> str:
    return {"creativity": "🎨", "action": "🏃", "service": "🤝"}.get(
        (strand or "").lower(), "●"
    )


def _reflection_preview(r: dict) -> str:
    """Return a short human-readable preview for any reflection kind."""
    kind = r.get("kind", "")
    if kind == "album":
        photos = r.get("photos") or []
        n = len(photos)
        caption = photos[0].get("caption", "") if photos else ""
        return f"📷 {n} photo(s)" + (f" — {caption[:40]}" if caption else "")
    body = _strip_html(r.get("body_html") or "")
    return body[:70] if body else "(no text)"


def _copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ── Modal: simple message ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class MessageModal(ModalScreen):
    CSS = """
    MessageModal { align: center middle; }
    #dialog {
        background: $surface; border: solid $primary;
        padding: 1 2; width: 64; height: auto; max-height: 24;
    }
    #title { margin-bottom: 1; }
    #body  { margin-bottom: 1; color: $text-muted; }
    """
    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._t, self._b = title, body

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(f"[bold]{self._t}[/bold]", id="title")
            yield Static(self._b, id="body")
            yield Button("OK", variant="primary", id="ok")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss()


# ══════════════════════════════════════════════════════════════════════════════
# ── Modal: confirm ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class ConfirmModal(ModalScreen[bool]):
    CSS = """
    ConfirmModal { align: center middle; }
    #dialog {
        background: $surface; border: solid $warning;
        padding: 1 2; width: 60; height: auto;
    }
    Horizontal { height: 3; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    """
    def __init__(self, question: str) -> None:
        super().__init__()
        self._q = question

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(self._q)
            with Horizontal():
                yield Button("Yes", variant="warning", id="yes")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


# ══════════════════════════════════════════════════════════════════════════════
# ── Modal: AI Generate (all 3 providers) ──────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class AIGenerateModal(ModalScreen[Optional[str]]):
    """
    Three-provider AI generation modal.

    Provider = anthropic / ollama:
        Step 1 → enter notes → Generate (background thread) → show result → Use
    Provider = prompt:
        Step 1 → enter notes → Build Prompt → show full prompt text + copy to
                 clipboard → user pastes AI response → Use
    """

    CSS = """
    AIGenerateModal { align: center middle; }
    #dialog {
        background: $surface; border: solid $accent;
        padding: 1 2; width: 84; height: 40;
    }
    #step-notes   { display: block; }
    #step-prompt  { display: none;  }
    #step-result  { display: none;  }

    #notes-area   { height: 8; margin-bottom: 1; }
    #prompt-area  { height: 14; margin-bottom: 1; border: solid $panel; }
    #paste-area   { height: 8; margin-bottom: 1; border: solid $success; }
    #result-area  { height: 12; margin-bottom: 1; border: solid $success; padding: 0 1; }
    #provider-badge { color: $text-muted; margin-bottom: 1; }
    #status       { color: $accent; margin-bottom: 1; height: 1; }
    Horizontal    { height: 3; align: right middle; }
    Button        { margin: 0 1; }
    """

    def __init__(self, cas_id: int, kind: str = "reflection") -> None:
        super().__init__()
        self._cas_id = cas_id
        self._kind   = kind
        self._result: Optional[str] = None
        self._provider = ctrl.ctrl_config().get("ai_provider", "prompt")

    def compose(self) -> ComposeResult:
        kind_label = "Final Reflection" if self._kind == "final" else "Session Reflection"
        provider_hint = {
            "anthropic": "Claude API",
            "ollama":    "Ollama (local)",
            "prompt":    "Manual — prompt export → paste",
        }.get(self._provider, self._provider)

        with Container(id="dialog"):
            yield Label(f"[bold]AI Generate — {kind_label}[/bold]")
            yield Label(f"Provider: [italic]{provider_hint}[/italic]",
                        id="provider-badge")
            yield Label("", id="status")

            # ── Step 1: enter notes ───────────────────────────────────────────
            with Container(id="step-notes"):
                yield Label("Notes  (describe what happened, what you felt/learned):")
                yield TextArea("", id="notes-area")
                with Horizontal():
                    if self._provider == "prompt":
                        yield Button("Build Prompt →", variant="primary",
                                     id="build-prompt")
                    else:
                        yield Button("Generate ✨", variant="primary",
                                     id="generate")
                    yield Button("Cancel", variant="default", id="cancel")

            # ── Step 2a: prompt export ────────────────────────────────────────
            with Container(id="step-prompt"):
                yield Label("[bold]Full prompt (copied to clipboard).[/bold]  "
                            "Paste into ChatGPT / Claude.ai / DeepSeek, "
                            "then paste the AI's response below:")
                yield TextArea("", id="prompt-area")
                yield Label("Paste AI response here ↓ (HTML with <p> tags, or plain text):")
                yield TextArea("", id="paste-area")
                with Horizontal():
                    yield Button("Copy Again 📋", variant="default", id="copy-again")
                    yield Button("Use This ✓", variant="success", id="use-paste",
                                 disabled=True)
                    yield Button("← Back", variant="default", id="back-from-prompt")

            # ── Step 2b: AI result ────────────────────────────────────────────
            with Container(id="step-result"):
                yield Label("Generated text:")
                yield Static("", id="result-area")
                with Horizontal():
                    yield Button("Use This ✓", variant="success", id="use-result",
                                 disabled=True)
                    yield Button("← Back", variant="default", id="back-from-result")

    # ── button routing ────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "build-prompt":
            self._do_build_prompt()
        elif bid == "generate":
            self._do_generate()
        elif bid == "copy-again":
            self._copy_prompt_again()
        elif bid == "use-paste":
            raw = self.query_one("#paste-area", TextArea).text.strip()
            if raw:
                self._result = raw
                self.dismiss(raw)
        elif bid == "use-result":
            self.dismiss(self._result)
        elif bid in ("back-from-prompt", "back-from-result"):
            self._show_step("notes")
        elif bid == "cancel":
            self.dismiss(None)

    # ── "prompt" provider flow ────────────────────────────────────────────────

    @work(thread=True)
    def _do_build_prompt(self) -> None:
        notes = self.query_one("#notes-area", TextArea).text.strip()
        if not notes:
            self.app.call_from_thread(self._set_status, "⚠ Enter notes first.")
            return
        self.app.call_from_thread(self._set_status, "Building prompt…")
        try:
            prompt_text = ctrl.ctrl_build_prompt(self._cas_id, notes, self._kind)
            _copy_to_clipboard(prompt_text)
            self.app.call_from_thread(
                lambda: self.query_one("#prompt-area", TextArea).load_text(prompt_text))
            self.app.call_from_thread(self._show_step, "prompt")
            self.app.call_from_thread(self._set_status,
                                      "✓ Prompt copied to clipboard.")
        except Exception as ex:
            self.app.call_from_thread(self._set_status, f"Error: {ex}")

    def _copy_prompt_again(self) -> None:
        text = self.query_one("#prompt-area", TextArea).text
        _copy_to_clipboard(text)
        self._set_status("✓ Copied again.")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "paste-area":
            has_text = bool(event.text_area.text.strip())
            self.query_one("#use-paste", Button).disabled = not has_text

    # ── anthropic / ollama flow ───────────────────────────────────────────────

    @work(thread=True)
    def _do_generate(self) -> None:
        notes = self.query_one("#notes-area", TextArea).text.strip()
        if not notes:
            self.app.call_from_thread(self._set_status, "⚠ Enter notes first.")
            return
        self.app.call_from_thread(self._set_status, "Generating…")
        try:
            result = ctrl.ctrl_generate_ai(self._cas_id, notes, kind=self._kind)
            self._result = result
            display = _strip_html(result)
            self.app.call_from_thread(
                lambda: self.query_one("#result-area", Static).update(display))
            self.app.call_from_thread(
                lambda: self.query_one("#use-result", Button).__setattr__(
                    "disabled", False))
            self.app.call_from_thread(self._show_step, "result")
            self.app.call_from_thread(self._set_status, "✓ Generated.")
        except Exception as ex:
            self.app.call_from_thread(self._set_status, f"Error: {ex}")

    # ── step navigation ───────────────────────────────────────────────────────

    def _show_step(self, step: str) -> None:
        for s in ("notes", "prompt", "result"):
            self.query_one(f"#step-{s}").display = (s == step)

    def _set_status(self, msg: str) -> None:
        self.query_one("#status", Label).update(msg)


# ══════════════════════════════════════════════════════════════════════════════
# ── Modal: Create Journal ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class CreateJournalModal(ModalScreen[Optional[int]]):
    CSS = """
    CreateJournalModal { align: center middle; }
    #dialog {
        background: $surface; border: solid $primary;
        padding: 1 2; width: 80; height: 30;
    }
    #body-area { height: 14; margin-bottom: 1; }
    Horizontal { height: 3; align: right middle; }
    Button { margin: 0 1; }
    #status { color: $text-muted; height: 1; }
    """

    def __init__(self, cas_id: int) -> None:
        super().__init__()
        self._cas_id = cas_id

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("[bold]New Journal Reflection[/bold]")
            yield Label("Body  (HTML with <p> tags, or plain text):")
            yield TextArea("", id="body-area")
            yield Label("", id="status")
            with Horizontal():
                yield Button("AI Assist ✨", variant="default", id="ai")
                yield Button("Post →", variant="success", id="post")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ai":
            self._open_ai()
        elif event.button.id == "post":
            self._post()
        elif event.button.id == "cancel":
            self.dismiss(None)

    def _open_ai(self) -> None:
        def callback(result: Optional[str]) -> None:
            if result:
                if not result.strip().startswith("<"):
                    result = "".join(
                        f"<p>{line.strip()}</p>"
                        for line in result.splitlines() if line.strip()
                    )
                self.query_one("#body-area", TextArea).load_text(result)
        self.app.push_screen(AIGenerateModal(self._cas_id), callback)

    @work(thread=True)
    def _post(self) -> None:
        body = self.query_one("#body-area", TextArea).text.strip()
        if not body:
            self.app.call_from_thread(
                lambda: self.query_one("#status", Label).update("⚠ Body is empty."))
            return
        self.app.call_from_thread(
            lambda: self.query_one("#status", Label).update("Posting…"))
        try:
            if not body.startswith("<"):
                body = "".join(f"<p>{l.strip()}</p>"
                               for l in body.splitlines() if l.strip())
            rid = ctrl.ctrl_create_journal(self._cas_id, body)
            self.app.call_from_thread(lambda: self.dismiss(rid))
        except Exception as ex:
            self.app.call_from_thread(
                lambda: self.query_one("#status", Label).update(f"Error: {ex}"))


# ══════════════════════════════════════════════════════════════════════════════
# ── Modal: Create Album ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class CreateAlbumModal(ModalScreen[Optional[int]]):
    """Upload one or more images as an album reflection."""

    CSS = """
    CreateAlbumModal { align: center middle; }
    #dialog {
        background: $surface; border: solid $primary;
        padding: 1 2; width: 80; height: 34;
    }
    .path-row { height: 3; margin-bottom: 0; }
    .path-input { width: 1fr; }
    #label-input { margin-bottom: 1; }
    #paths-container { height: 14; overflow-y: auto; margin-bottom: 1; }
    Horizontal { height: 3; align: right middle; }
    Button { margin: 0 1; }
    #status { color: $text-muted; height: 1; }
    """

    MAX_PHOTOS = 6

    def __init__(self, cas_id: int) -> None:
        super().__init__()
        self._cas_id = cas_id

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("[bold]New Album Reflection[/bold]")
            yield Label("Caption / label for all photos:")
            yield Input("", id="label-input", placeholder="e.g. 'Week 3 activity'")
            yield Label("Image file paths  (one per row, add rows with + button):")
            with ScrollableContainer(id="paths-container"):
                with Horizontal(classes="path-row", id="path-row-0"):
                    yield Input("", classes="path-input", id="path-0",
                                placeholder="/path/to/photo.jpg")
            yield Label("", id="status")
            with Horizontal():
                yield Button("+ Add row", variant="default", id="add-row")
                yield Button("Upload →", variant="success", id="upload")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-row":
            self._add_row()
        elif event.button.id == "upload":
            self._upload()
        elif event.button.id == "cancel":
            self.dismiss(None)

    def _add_row(self) -> None:
        container = self.query_one("#paths-container", ScrollableContainer)
        idx = len(container.query(".path-row"))
        if idx >= self.MAX_PHOTOS:
            self.query_one("#status", Label).update(
                f"Max {self.MAX_PHOTOS} photos per album.")
            return
        row = Horizontal(classes="path-row", id=f"path-row-{idx}")
        container.mount(row)
        row.mount(Input("", classes="path-input", id=f"path-{idx}",
                        placeholder="/path/to/photo.jpg"))

    @work(thread=True)
    def _upload(self) -> None:
        label = self.query_one("#label-input", Input).value.strip()
        paths = [
            inp.value.strip()
            for inp in self.query(".path-input")
            if inp.value.strip()
        ]
        if not paths:
            self.app.call_from_thread(
                lambda: self.query_one("#status", Label).update(
                    "⚠ Add at least one image path."))
            return
        missing = [p for p in paths if not Path(p).exists()]
        if missing:
            self.app.call_from_thread(
                lambda: self.query_one("#status", Label).update(
                    f"⚠ File not found: {missing[0]}"))
            return
        self.app.call_from_thread(
            lambda: self.query_one("#status", Label).update(
                f"Uploading {len(paths)} photo(s)…"))
        try:
            rid = ctrl.ctrl_create_album(self._cas_id, paths, label=label)
            self.app.call_from_thread(lambda: self.dismiss(rid))
        except Exception as ex:
            self.app.call_from_thread(
                lambda: self.query_one("#status", Label).update(f"Error: {ex}"))


# ══════════════════════════════════════════════════════════════════════════════
# ── Modal: Sync progress ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SyncModal(ModalScreen[dict]):
    CSS = """
    SyncModal { align: center middle; }
    #dialog {
        background: $surface; border: solid $primary;
        padding: 1 2; width: 60; height: 12;
    }
    #progress { color: $text-muted; margin-top: 1; }
    """

    def __init__(self, cas_id: Optional[int] = None) -> None:
        super().__init__()
        self._cas_id = cas_id

    def compose(self) -> ComposeResult:
        label = (f"Syncing experience {self._cas_id}…"
                 if self._cas_id else "Syncing all experiences…")
        with Container(id="dialog"):
            yield Label(f"[bold]{label}[/bold]")
            yield LoadingIndicator()
            yield Static("Starting…", id="progress")

    def on_mount(self) -> None:
        self._run_sync()

    @work(thread=True)
    def _run_sync(self) -> None:
        def on_progress(msg: str) -> None:
            self.app.call_from_thread(
                lambda: self.query_one("#progress", Static).update(msg))
        try:
            if self._cas_id:
                result = ctrl.ctrl_sync_experience(self._cas_id,
                                                   progress_cb=on_progress)
            else:
                results = ctrl.ctrl_sync_all(progress_cb=on_progress)
                result  = {"results": results, "total_exps": len(results)}
            self.app.call_from_thread(lambda: self.dismiss(result))
        except Exception as ex:
            self.app.call_from_thread(lambda: self.dismiss({"error": str(ex)}))


# ══════════════════════════════════════════════════════════════════════════════
# ── Screen: Experience Detail ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class ExperienceScreen(Screen):
    BINDINGS = [
        Binding("escape,q", "pop_screen",        "Back"),
        Binding("r",        "refresh",           "Refresh"),
        Binding("s",        "sync",              "Sync"),
        Binding("j",        "new_journal",       "New Journal"),
        Binding("a",        "new_album",         "New Album"),
        Binding("f",        "final_reflection",  "Final Refl."),
    ]

    CSS = """
    ExperienceScreen { layout: horizontal; }
    #sidebar {
        width: 28; background: $panel; padding: 1;
        border-right: solid $primary;
    }
    #sidebar .section-label { color: $text-muted; margin-top: 1; }
    #sidebar .value         { color: $text; margin-bottom: 0; }
    #main { width: 1fr; layout: vertical; }
    #reflections { height: 1fr; }
    #action-bar {
        height: 5; background: $panel; border-top: solid $primary;
        align: center middle; padding: 0 1;
    }
    Button { margin: 0 1; }
    #statusbar { dock: bottom; height: 1; background: $surface; padding: 0 1; }
    """

    def __init__(self, cas_id: int) -> None:
        super().__init__()
        self._cas_id = cas_id
        self._exp: Optional[dict] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Experience", classes="section-label")
                yield Label("—", id="exp-name", classes="value")
                yield Label("Strand", classes="section-label")
                yield Label("—", id="exp-strand", classes="value")
                yield Label("Learning Outcomes", classes="section-label")
                yield Label("—", id="exp-los", classes="value")
                yield Label("Status", classes="section-label")
                yield Label("—", id="exp-status", classes="value")
                yield Label("CAS ID", classes="section-label")
                yield Label(str(self._cas_id), classes="value")
            with Vertical(id="main"):
                yield DataTable(id="reflections", cursor_type="row",
                                zebra_stripes=True)
                with Horizontal(id="action-bar"):
                    yield Button("↺ Sync", id="btn-sync", variant="default")
                    yield Button("✏ Journal", id="btn-journal", variant="primary")
                    yield Button("🖼 Album",   id="btn-album",   variant="primary")
                    yield Button("🏁 Final",   id="btn-final",   variant="default")
                    yield Button("💾 Draft",   id="btn-draft",   variant="default")
        yield Static("", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#reflections", DataTable)
        t.add_columns("ID", "Kind", "Date", "Preview", "PH")
        self._load_data()

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_data(self) -> None:
        self._exp = ctrl.ctrl_get_experience(self._cas_id)
        if self._exp:
            self.query_one("#exp-name", Label).update(
                self._exp.get("name") or str(self._cas_id))
            strand = self._exp.get("strand", "")
            self.query_one("#exp-strand", Label).update(
                f"{_strand_icon(strand)} {strand.capitalize() or '—'}")
            los = "\n".join(self._exp.get("lo_names") or []) or "—"
            self.query_one("#exp-los", Label).update(los)
            done = "✓ Completed" if self._exp.get("is_completed") else "● Active"
            self.query_one("#exp-status", Label).update(done)

        t = self.query_one("#reflections", DataTable)
        t.clear()
        refs = ctrl.ctrl_list_reflections(self._cas_id)
        for r in refs:
            preview = _reflection_preview(r)
            ph = "✓" if r.get("is_placeholder") else ""
            t.add_row(
                str(r["id"]),
                r.get("kind", ""),
                (r.get("group_date") or "")[:10],
                preview,
                ph,
                key=str(r["id"]),
            )
        name = ((self._exp.get("name") or str(self._cas_id))
                if self._exp else str(self._cas_id))
        self.title = f"CAS — {name}"
        self.query_one("#statusbar", Static).update(
            f"{len(refs)} reflections  |  cas_id={self._cas_id}")

    # ── button routing ────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "btn-sync":    self.action_sync,
            "btn-journal": self.action_new_journal,
            "btn-album":   self.action_new_album,
            "btn-final":   self.action_final_reflection,
            "btn-draft":   self._open_ai_draft,
        }
        fn = mapping.get(event.button.id)
        if fn:
            fn()

    # ── actions ───────────────────────────────────────────────────────────────

    def action_sync(self) -> None:
        def done(result: dict) -> None:
            if "error" in result:
                self.app.push_screen(MessageModal("Sync Error", result["error"]))
            else:
                self._load_data()
                self.query_one("#statusbar", Static).update(
                    f"✓ Synced: {result.get('total', 0)} reflections, "
                    f"{result.get('gone', 0)} purged.")
        self.app.push_screen(SyncModal(self._cas_id), done)

    def action_refresh(self) -> None:
        self._load_data()

    def action_new_journal(self) -> None:
        def done(rid: Optional[int]) -> None:
            if rid:
                self._load_data()
                self.query_one("#statusbar", Static).update(
                    f"✓ Journal posted (rid={rid})")
        self.app.push_screen(CreateJournalModal(self._cas_id), done)

    def action_new_album(self) -> None:
        def done(rid: Optional[int]) -> None:
            if rid:
                self._load_data()
                self.query_one("#statusbar", Static).update(
                    f"✓ Album posted (rid={rid})")
        self.app.push_screen(CreateAlbumModal(self._cas_id), done)

    def action_final_reflection(self) -> None:
        def ai_done(result: Optional[str]) -> None:
            if not result:
                return
            def confirm(yes: bool) -> None:
                if yes:
                    self._post_html_bg(result, "Final reflection")
            self.app.push_screen(
                ConfirmModal("Post this final reflection to ManageBac?"), confirm)
        self.app.push_screen(AIGenerateModal(self._cas_id, kind="final"), ai_done)

    def _open_ai_draft(self) -> None:
        def ai_done(result: Optional[str]) -> None:
            if result:
                draft_id = ctrl.ctrl_add_draft(self._cas_id, "(from TUI)")
                import cas_db
                with cas_db.open_db() as conn:
                    cas_db.update_draft(conn, draft_id,
                                        ai_result=result, status="ready")
                self.query_one("#statusbar", Static).update(
                    f"✓ Draft saved (id={draft_id}). "
                    f"Post with: cas draft post {draft_id}")
        self.app.push_screen(AIGenerateModal(self._cas_id), ai_done)

    @work(thread=True)
    def _post_html_bg(self, html: str, label: str = "") -> None:
        try:
            rid = ctrl.ctrl_create_journal(self._cas_id, html)
            self.app.call_from_thread(self._load_data)
            self.app.call_from_thread(
                lambda: self.query_one("#statusbar", Static).update(
                    f"✓ {label} posted (rid={rid})"))
        except Exception as ex:
            self.app.call_from_thread(
                lambda: self.app.push_screen(
                    MessageModal("Post Error", str(ex))))

    def action_pop_screen(self) -> None:
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════════════════════════
# ── Screen: Settings ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SettingsScreen(Screen):
    BINDINGS = [Binding("escape,q", "pop_screen", "Back")]

    CSS = """
    SettingsScreen { padding: 1 2; }
    .field-label { color: $text-muted; margin-top: 1; }
    Input { margin-bottom: 1; }
    Horizontal { height: 3; align: right middle; margin-top: 1; }
    Button { margin: 0 1; }
    #hint { color: $text-muted; margin-top: 2; }
    """

    def compose(self) -> ComposeResult:
        cfg = ctrl.ctrl_config()
        yield Header()
        yield Label("[bold]Settings[/bold]")
        yield Label("Base URL  (school's ManageBac domain)", classes="field-label")
        yield Input(cfg.get("base", ""), id="base")
        yield Label(
            "AI Provider  [bold]prompt[/bold] | anthropic | ollama",
            classes="field-label")
        yield Input(cfg.get("ai_provider", "prompt"), id="ai_provider")
        yield Label("AI Model  (for Anthropic provider)", classes="field-label")
        yield Input(cfg.get("ai_model", "claude-opus-4-6"), id="ai_model")
        yield Label("Ollama Model  (for Ollama provider)", classes="field-label")
        yield Input(cfg.get("ollama_model", "llama3.2"), id="ollama_model")
        yield Label("Ollama URL", classes="field-label")
        yield Input(cfg.get("ollama_url", "http://localhost:11434"), id="ollama_url")
        yield Static(
            "  prompt  → builds prompt text, copies to clipboard, you paste AI's response\n"
            "  anthropic → uses Claude API (needs ANTHROPIC_API_KEY)\n"
            "  ollama    → uses local Ollama (run: ollama serve)",
            id="hint",
        )
        with Horizontal():
            yield Button("Save", variant="success", id="save")
            yield Button("Cancel", variant="default", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            ctrl.ctrl_save_config({
                "base":         self.query_one("#base", Input).value,
                "ai_provider":  self.query_one("#ai_provider", Input).value,
                "ai_model":     self.query_one("#ai_model", Input).value,
                "ollama_model": self.query_one("#ollama_model", Input).value,
                "ollama_url":   self.query_one("#ollama_url", Input).value,
            })
            self.app.pop_screen()
        elif event.button.id == "cancel":
            self.app.pop_screen()

    def action_pop_screen(self) -> None:
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════════════════════════
# ── Screen: Dashboard ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class DashboardScreen(Screen):
    BINDINGS = [
        Binding("q",     "quit",            "Quit"),
        Binding("r",     "refresh",         "Refresh"),
        Binding("s",     "sync_all",        "Sync All"),
        Binding("enter", "open_experience", "Open"),
        Binding("?",     "help_popup",      "Help"),
    ]

    CSS = """
    DashboardScreen {}
    #toolbar {
        height: 3; background: $panel; border-bottom: solid $primary;
        align: left middle; padding: 0 1;
    }
    Button { margin: 0 1; }
    #banner {
        height: 1; background: $warning; color: $text;
        padding: 0 1; text-align: center; display: none;
    }
    #banner.visible { display: block; }
    #experiences { height: 1fr; }
    #statusbar { dock: bottom; height: 1; background: $surface; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="toolbar"):
            yield Button("↺ Refresh", id="btn-refresh",  variant="default")
            yield Button("⬇ Sync All", id="btn-sync",   variant="primary")
            yield Button("⚙ Settings", id="btn-settings", variant="default")
        yield Static("", id="banner")
        yield DataTable(id="experiences", cursor_type="row", zebra_stripes=True)
        yield Static("Loading…", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#experiences", DataTable)
        t.add_columns("", "Name", "CAS ID", "Strand", "Reflections", "Status")
        self._load_local()
        self._check_login()
        # Auto-sync in background if session is available
        self._auto_sync()

    # ── login check ───────────────────────────────────────────────────────────

    def _check_login(self) -> None:
        ok = ctrl.ctrl_check_login()
        banner = self.query_one("#banner", Static)
        if not ok:
            banner.update(
                "⚠  Not logged in — run [bold]cas login[/bold] in a terminal, "
                "then press [bold]r[/bold] to refresh.")
            banner.add_class("visible")
        else:
            banner.remove_class("visible")

    # ── local DB render ───────────────────────────────────────────────────────

    def _load_local(self) -> None:
        t = self.query_one("#experiences", DataTable)
        t.clear()
        exps = ctrl.ctrl_list_experiences()

        import cas_db
        cas_db.init_db()
        with cas_db.open_db() as conn:
            ref_counts = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT cas_id, COUNT(*) FROM reflections GROUP BY cas_id"
                ).fetchall()
            }

        for exp in exps:
            icon   = _strand_icon(exp.get("strand", ""))
            status = "✓" if exp.get("is_completed") else "●"
            cnt    = ref_counts.get(exp["id"], 0)
            t.add_row(
                icon,
                exp.get("name") or str(exp["id"]),
                str(exp["id"]),
                (exp.get("strand") or "—").capitalize(),
                str(cnt),
                status,
                key=str(exp["id"]),
            )

        stats = ctrl.ctrl_db_stats()
        if not exps:
            self.query_one("#statusbar", Static).update(
                "No experiences in DB — press [s] to sync from ManageBac.")
        else:
            self.query_one("#statusbar", Static).update(
                f"{len(exps)} experiences  |  "
                f"{stats['reflections']} reflections  |  "
                f"{stats['drafts']} drafts")
        self.title = "CAS Manager"

    # ── auto-sync ─────────────────────────────────────────────────────────────

    @work(thread=True)
    def _auto_sync(self) -> None:
        """Silently sync in background on startup if logged in."""
        if not ctrl.ctrl_check_login():
            return
        self.app.call_from_thread(
            lambda: self.query_one("#statusbar", Static).update(
                "Auto-syncing in background…"))
        try:
            results = ctrl.ctrl_sync_all(progress_cb=None)
            n = len(results)
            self.app.call_from_thread(self._load_local)
            self.app.call_from_thread(
                lambda: self.query_one("#statusbar", Static).update(
                    f"✓ Auto-synced {n} experience(s)."))
        except Exception as ex:
            self.app.call_from_thread(
                lambda: self.query_one("#statusbar", Static).update(
                    f"Auto-sync failed: {ex}"))

    # ── buttons ───────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh":
            self.action_refresh()
        elif event.button.id == "btn-sync":
            self.action_sync_all()
        elif event.button.id == "btn-settings":
            self.app.push_screen(SettingsScreen())

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        cas_id = int(event.row_key.value)
        self.app.push_screen(ExperienceScreen(cas_id))

    # ── key actions ───────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._load_local()
        self._check_login()

    def action_sync_all(self) -> None:
        def done(result: dict) -> None:
            if "error" in result:
                self.app.push_screen(MessageModal("Sync Error", result["error"]))
            else:
                self._load_local()
                n = result.get("total_exps", 0)
                self.query_one("#statusbar", Static).update(
                    f"✓ Synced {n} experience(s).")
        self.app.push_screen(SyncModal(cas_id=None), done)

    def action_open_experience(self) -> None:
        t   = self.query_one("#experiences", DataTable)
        idx = t.cursor_row
        if idx is not None:
            row    = t.get_row_at(idx)
            cas_id = int(row[2])  # column index 2 = CAS ID
            self.app.push_screen(ExperienceScreen(cas_id))

    def action_help_popup(self) -> None:
        self.app.push_screen(MessageModal(
            "Keyboard Shortcuts",
            "Dashboard:\n"
            "  [r] Refresh local DB   [s] Sync All from web\n"
            "  [Enter] Open experience  [?] Help  [q] Quit\n\n"
            "Inside an experience:\n"
            "  [j] New Journal   [a] New Album\n"
            "  [f] Final Refl.   [s] Sync   [r] Refresh\n"
            "  [Esc / q] Back to dashboard\n\n"
            "AI Providers (Settings ⚙):\n"
            "  prompt    → exports prompt, you paste AI response\n"
            "  anthropic → Claude API (ANTHROPIC_API_KEY required)\n"
            "  ollama    → local Ollama (ollama serve)"
        ))

    def action_quit(self) -> None:
        self.app.exit()


# ══════════════════════════════════════════════════════════════════════════════
# ── App ────────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class CASApp(App):
    TITLE     = "CAS Manager"
    SUB_TITLE = "ManageBac CAS Manager"
    CSS = "App { background: $background; }"

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen())


def main() -> None:
    CASApp().run()


if __name__ == "__main__":
    main()
