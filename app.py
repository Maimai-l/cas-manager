"""
app.py — Desktop app entry point for CAS Manager.

Starts the Flask backend in a daemon thread, then opens a native WebView
window pointing at it. Closing the window exits the process.

Logging:
    All startup events + Flask access logs + uncaught exceptions go to:
        dev mode:    ./app.log   (next to this file)
        frozen mode: ~/Library/Application Support/CAS Manager/app.log
    The log path is also printed to stderr on startup so you can `tail -f`.

Debug tools (the app is localhost-only):
    - GET /api/debug/reflections/<cas_id>  — raw DB rows
    - GET /api/debug/scan/<cas_id>         — live ManageBac HTML scrape diagnostics
    - GET /api/debug/sa/<cas_id>           — parsed Self-Assessment form dump
    - WebKit inspector: opt-in via CAS_DEBUG=1 (off by default — debug mode
      auto-opens the DevTools window on some platforms)

Run (dev mode):
    pip install pywebview
    python app.py

Build (macOS .app):
    pip install pyinstaller
    pyinstaller build.spec
    open "dist/CAS Manager.app"
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path


# ── Logging — set this up FIRST so import failures get captured ───────────────

def _setup_logging() -> logging.Logger:
    import cas_paths
    log_path = cas_paths.LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cas_app")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    # Also stderr (visible when running from terminal, hidden in .app double-click)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    # Wire Werkzeug + Flask loggers through the same handlers
    for name in ("werkzeug", "flask.app"):
        existing = logging.getLogger(name)
        existing.handlers = [fh, sh]
        existing.setLevel(logging.INFO)
    sys.stderr.write(f"[CAS Manager] log → {log_path}\n")
    return logger


def _find_free_port(preferred: int = 5173, max_tries: int = 20) -> int:
    for p in range(preferred, preferred + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"No free port in [{preferred}, {preferred + max_tries})")


def _wait_for_http(port: int, timeout: float = 15.0, log=None) -> bool:
    """Block until Flask actually serves a 200 on /, not just TCP accept."""
    import urllib.request
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    if log:
                        log.info("Flask responded 200 on /")
                    return True
        except Exception as e:
            last_err = e
        time.sleep(0.15)
    if log:
        log.error(f"Flask did not respond on port {port} within {timeout}s "
                  f"(last error: {last_err})")
    return False


def _sanity_check_bundle(log: logging.Logger) -> bool:
    """Verify bundled assets exist where we expect. Returns False on missing."""
    import cas_paths
    log.info(f"FROZEN mode: {cas_paths.FROZEN}")
    log.info(f"BUNDLE_DIR:  {cas_paths.BUNDLE_DIR}")
    log.info(f"DATA_BASE:   {cas_paths.DB_PATH.parent}")
    ok = True
    if not cas_paths.TEMPLATES_DIR.is_dir():
        log.error(f"missing templates dir: {cas_paths.TEMPLATES_DIR}")
        ok = False
    else:
        idx = cas_paths.TEMPLATES_DIR / "index.html"
        log.info(f"templates dir OK; index.html exists: {idx.exists()}")
    if not cas_paths.STATIC_DIR.is_dir():
        log.error(f"missing static dir: {cas_paths.STATIC_DIR}")
        ok = False
    else:
        jsx_dir = cas_paths.STATIC_DIR / "jsx"
        jsx_files = sorted(p.name for p in jsx_dir.glob("*")) if jsx_dir.exists() else []
        log.info(f"static dir OK; jsx/ has {len(jsx_files)} files: {jsx_files}")
    return ok


def main():
    log = _setup_logging()
    log.info(f"=== CAS Manager starting · python={sys.version.split()[0]} "
             f"· platform={sys.platform} ===")

    try:
        import cas_paths
    except Exception:
        log.error("failed to import cas_paths:\n" + traceback.format_exc())
        sys.exit(1)

    if not _sanity_check_bundle(log):
        log.error("bundle sanity check failed — templates or static dir missing. "
                  "Check build.spec `datas` and rebuild.")
        # Continue anyway — surface a partial page rather than silently dying.

    try:
        import webview
    except ImportError:
        log.error("pywebview not installed. Run: pip install pywebview")
        sys.exit("Error: pip install pywebview")

    try:
        import cas_web
        log.info("cas_web imported; routes registered")
    except Exception:
        log.error("failed to import cas_web:\n" + traceback.format_exc())
        sys.exit(1)

    try:
        port = _find_free_port(5173)
        log.info(f"selected port: {port}")
    except Exception as e:
        log.error(f"could not find free port: {e}")
        sys.exit(1)

    # Scheduler thread (same as cas_web.main starts) — non-fatal if it crashes
    def _scheduler_wrapped():
        try:
            cas_web._schedule_runner()
        except Exception:
            log.exception("scheduler thread crashed")
    threading.Thread(target=_scheduler_wrapped, daemon=True).start()

    # Flask thread
    def _flask_wrapped():
        try:
            cas_web.app.run(
                host="127.0.0.1", port=port,
                debug=False, use_reloader=False,
                threaded=True,
            )
        except Exception:
            log.exception("Flask thread crashed")
    threading.Thread(target=_flask_wrapped, daemon=True).start()

    if not _wait_for_http(port, timeout=15.0, log=log):
        log.error("aborting webview launch — Flask never became reachable")
        sys.exit(1)

    log.info("opening WebView window")
    webview.create_window(
        "CAS Manager",
        f"http://127.0.0.1:{port}",
        width=1280, height=820,
        min_size=(900, 600),
        confirm_close=False,
        text_select=True,
    )
    # debug=True enables the WebKit inspector, but on several platforms it
    # also AUTO-OPENS the DevTools window on launch — so it's opt-in now:
    #     CAS_DEBUG=1 python app.py     (or set it before opening the .app)
    debug = os.environ.get("CAS_DEBUG") == "1"
    log.info(f"webview debug (inspector): {debug}")
    # Window icon: the macOS .app takes its icon from the bundle (build.spec),
    # but the GTK backend can set one at runtime. icon= is unsupported on some
    # backends/versions, so fall back to a plain start if it's rejected.
    icon_png = cas_paths.STATIC_DIR / "img" / "facet-icon-1024.png"
    try:
        webview.start(debug=debug, icon=str(icon_png))
    except TypeError:
        try:
            webview.start(debug=debug)
        except Exception:
            log.exception("webview.start() raised")
            sys.exit(1)
    except Exception:
        log.exception("webview.start() raised")
        sys.exit(1)
    log.info("window closed; exiting")


if __name__ == "__main__":
    main()
