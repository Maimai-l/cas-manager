# Building CAS Manager as a desktop app

The repo is dual-purpose: you can run it as a Flask dev server (`python
cas_web.py`) or as a packaged desktop app via PyWebView (`python app.py`,
or the built `CAS Manager.app`).

## Run from source as a desktop app

```bash
pip install pywebview platformdirs
python app.py
```

Opens a native WebView window (macOS WKWebView, Windows Edge WebView2,
Linux GTK WebKit). Closes cleanly when you click the window's close
button — the Flask backend is a daemon thread, so it dies with the
process.

In dev mode all runtime files (`cas_data.db`, `mb_state.json`,
`cas_config.json`) stay in the project directory — same as
`python cas_web.py`.

## Build a distributable macOS .app

```bash
pip install pyinstaller pywebview platformdirs
pyinstaller build.spec
open "dist/CAS Manager.app"
```

The bundle contains its own Python runtime and all dependencies. Users
do not need Python installed.

### Where user data lives in the .app

The packaged build detects `sys.frozen` and stores writable files in the
OS user-data directory:

| OS     | Path                                                  |
|--------|-------------------------------------------------------|
| macOS  | `~/Library/Application Support/CAS Manager/`          |
| Windows| `%APPDATA%\CAS Manager\`                              |
| Linux  | `~/.local/share/cas-manager/`                         |

That dir contains:
- `cas_data.db` — local SQLite cache of experiences, reflections, photos
- `mb_state.json` — ManageBac session cookies + auth_token
- `cas_config.json` — UI/AI preferences

Uninstalling the `.app` does **not** delete that directory — delete it
manually if you want a clean slate.

### What the .app does **not** contain

- Your ManageBac account / password (the user logs in at first launch)
- Any cached reflections or photos (the DB is built locally on first sync)
- The `archive/`, `_DELETE/`, `New_design_interface/`, `New_idea_design/`
  directories (they're excluded by `build.spec`'s `datas` list)

This means the built `.app` and the source repo are safe to distribute
or open-source without exposing personal data.

## First-build troubleshooting

- **"No module named 'cas'"** during launch: the static hidden-imports
  list in `build.spec` got out of sync with the codebase. Add the missing
  module name to `hiddenimports`.
- **Blank window**: Flask probably failed to bind. Check the port logic
  in `app.py:_find_free_port`. Run from terminal to see Python tracebacks:
  `dist/CAS\ Manager.app/Contents/MacOS/CAS\ Manager`.
- **"App is damaged, can't be opened"**: macOS Gatekeeper blocks
  unsigned binaries. Right-click the .app → Open → Open. To distribute
  to others, you'll need an Apple Developer signing cert and
  `codesign_identity` in `build.spec`.
- **Anthropic provider doesn't work**: install `anthropic` in the build
  environment before running `pyinstaller build.spec`, then rebuild. The
  spec lists it as a hidden import but PyInstaller can only bundle it if
  it's importable from the build environment.

## Adding an app icon

Drop a 1024×1024 PNG, convert to .icns:

```bash
mkdir icon.iconset
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
cp icon.png       icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset
```

Then in `build.spec`, set `icon='icon.icns'` in the `BUNDLE(...)` call
and rebuild.
