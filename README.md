# CAS Manager

A desktop app for IB Diploma Programme students to manage their CAS (Creativity, Activity, Service) reflections on ManageBac. Lets you draft, edit, and post reflections — with optional AI assistance — from a local app instead of clicking through the ManageBac web UI.

## Features

- View all your CAS experiences and reflections in one place
- Create new journal / album reflections from the desktop app
- AI-assisted reflection writing (Claude API, Ollama, or copy-paste flow)
- AI-assisted Final Reflection that grounds the 4-question answer in your entire session history
- Auto-detect multi-strand experiences (e.g. Creativity + Activity)
- Customizable system prompts — full-override editor in Settings
- Local SQLite cache so the UI stays fast offline
- Placeholder Hub for scheduled "fill later" reflections

## How it works

The app talks to ManageBac the same way the website does (HTTP requests + session cookies), so anything you can do on the website you can do here. Your ManageBac session cookie lives only on your machine; nothing is sent anywhere except ManageBac and (optionally) your chosen AI provider.

## Quick start (developers)

```bash
pip install flask requests beautifulsoup4 pywebview pyinstaller platformdirs
python app.py     # dev mode, opens a native window
```

For a packaged `.app` build:

```bash
pyinstaller build.spec
open "dist/CAS Manager.app"
```

## First-time setup

1. Open the app → Settings → Account
2. Enter your school's ManageBac URL (e.g. `https://yourschool.managebac.cn`)
3. Enter your ManageBac email + password
4. Click Login → app syncs your experiences automatically

## Data location

All user data lives in `~/Library/Application Support/CAS Manager/` on macOS:

- `cas_data.db` — local cache of your experiences + reflections
- `mb_state.json` — session cookies + your ManageBac credentials, kept locally so the app can re-login automatically when the session expires (treat like a password)
- `cas_config.json` — your settings
- `app.log` — runtime log (helpful for bug reports)

## License

MIT
