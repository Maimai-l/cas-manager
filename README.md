# CAS Manager

CAS is supposed to be about Creativity, Activity, and Service. In practice a
lot of it turns into paperwork. This app takes that part off your
plate so the time goes back into the actual experiences.

## Features

- **Placeholders.** Pre-creates the reflection entries for an experience, on a
  schedule or all at once. So the boxes are already there to fill in later.

- **Prompts.** Turns rough notes into a reflection. It builds a prompt with
  the experience's goals and learning outcomes included, copies it for any AI
  tool, and you paste the answer back (or wire up an API and skip the paste).
  Same flow for the Final Reflection and the Self-Assessment questions.

## How it works

The app talks to ManageBac through HTTP requests and
your session cookie, so anything you can do on the site, you can do here. Your
cookie and credentials stay on your machine; nothing leaves it except the
requests to ManageBac and, if you turn it on, your chosen AI provider.

## Data location

All user data lives in `~/Library/Application Support/CAS Manager/` on macOS:

- `cas_data.db` — local cache of your experiences + reflections
- `mb_state.json` — session cookies + ManageBac credentials, kept locally so the app can re-login when the session expires (treat like a password)
- `cas_config.json` — your settings
- `app.log` — runtime log

## License

MIT
