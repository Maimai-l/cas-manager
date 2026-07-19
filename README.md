# CAS Manager

CAS is supposed to be about Creativity, Activity, and Service. In practice, a
lot of it turns into paperwork — logging into ManageBac, writing the same kind
of reflection over and over, filling boxes so a coordinator can tick them off.

This is a small desktop app that takes that busywork off your plate, so the
hours go back into the things CAS is actually for.

It does two things:

- **Placeholders.** Pre-creates the reflection entries for an experience — on a
  schedule, or all at once — so the boxes are already there. Fill them in when
  you actually have something to say, instead of scrambling before a deadline.

- **AI prompts.** Turns your rough notes into a proper reflection. It builds a
  prompt with the experience's goals and learning outcomes already baked in,
  copies it to your clipboard for any AI tool, and you paste the answer back.
  (Or wire up an API and skip the copy-paste.) Same flow for the Final
  Reflection and the Self-Assessment questions.

That's it. It's not trying to write your CAS *for* you — you still decide what
you did and what it meant. It just removes the clicking, the reformatting, and
the blank-page friction between a real experience and a filed reflection.

## How it works

The app talks to ManageBac the same way the website does — HTTP requests and
your session cookie — so anything you can do on the site, you can do here. Your
cookie and credentials stay on your machine; nothing leaves it except the
requests to ManageBac and, if you turn it on, your chosen AI provider.

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
4. Click Login → the app syncs your experiences automatically

## Data location

All user data lives in `~/Library/Application Support/CAS Manager/` on macOS:

- `cas_data.db` — local cache of your experiences + reflections
- `mb_state.json` — session cookies + your ManageBac credentials, kept locally so the app can re-login automatically when the session expires (treat like a password)
- `cas_config.json` — your settings
- `app.log` — runtime log (helpful for bug reports)

## License

MIT
