"""
cas_paths.py — Canonical filesystem paths for runtime state.

Dev mode (`python cas_web.py` / `python app.py`):
    Paths resolve to the project directory — same as the historical behavior.

Frozen mode (PyInstaller .app bundle):
    User-writable paths resolve to the OS-standard user data directory
    (e.g. ~/Library/Application Support/CAS Manager/ on macOS).
    The bundle itself is read-only.

Bundled-asset paths (templates/, static/) always resolve to the running
location — sys._MEIPASS when frozen, project root in dev.
"""
from __future__ import annotations

import sys
from pathlib import Path


_FROZEN = getattr(sys, "frozen", False)
FROZEN = _FROZEN   # public alias


def _user_data_base() -> Path:
    """Where to put writable runtime files (DB, cookies, config)."""
    try:
        from platformdirs import user_data_dir
        return Path(user_data_dir("CAS Manager", "CASManager"))
    except ImportError:
        # Fallback: macOS-style location, works for macOS specifically
        import os
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "CAS Manager"
        if sys.platform == "win32":
            return Path(os.environ.get("APPDATA", Path.home())) / "CAS Manager"
        return Path.home() / ".local" / "share" / "cas-manager"


if _FROZEN:
    _DATA_BASE = _user_data_base()
    _DATA_BASE.mkdir(parents=True, exist_ok=True)
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    # Dev: keep everything in the project directory (so existing workflows
    # and the gitignored cas_data.db, mb_state.json, cas_config.json work).
    _DATA_BASE = Path(__file__).parent
    BUNDLE_DIR = Path(__file__).parent


# Writable runtime files
DB_PATH     = _DATA_BASE / "cas_data.db"
STATE_PATH  = _DATA_BASE / "mb_state.json"
CONFIG_PATH = _DATA_BASE / "cas_config.json"
LOG_PATH    = _DATA_BASE / "app.log"   # frozen-mode log; dev mode just lives next to project

# Bundled (read-only) assets
TEMPLATES_DIR = BUNDLE_DIR / "templates"
STATIC_DIR    = BUNDLE_DIR / "static"
