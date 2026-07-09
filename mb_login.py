"""
mb_login.py — Login flow for CAS Manager.

Flow:
  1. POST /sessions.json with email + password
  2. Get 1-year session cookie + auth_token
  3. Save to mb_state.json

Usage:
  python mb_login.py
  # or from code:
  from mb_login import login_with_password, save_state
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

import requests

import cas_paths

# BASE is intentionally empty — every caller passes the user-configured URL.
# See note on the same constant in cas_api.py.
BASE = ""
STATE_PATH = cas_paths.STATE_PATH


def login_with_password(email: str, password: str, base: str = BASE) -> dict:
    """
    Authenticate with email + password via POST /sessions.json.
    Returns state dict {"cookies": [...], "auth_token": "...", "email": ...,
    "password": ...} ready to save. Credentials are kept in the state file so
    the app can re-login automatically when both the session cookie and the
    auth_token have expired (mb_state.json is local-only and already holds a
    year-long session cookie — treat the whole file like a password).
    Raises RuntimeError on failure.
    """
    r = requests.post(
        f"{base}/sessions.json",
        json={
            "auth_type": "password",
            "login": email,
            "password": password,
            "client_type": "ios",
            "app_version": "2.20.2",
            "lang": "zh",
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()

    body = r.json()
    if body.get("status") == 401 or "error" in body:
        raise RuntimeError(body.get("error", "Login failed"))

    auth_token = body.get("share_auth_token", "")
    domain = base.split("://", 1)[1].split("/")[0]
    cookies = [
        {"name": name, "value": value, "domain": domain, "path": "/"}
        for name, value in r.cookies.items()
    ]

    if not any(c["name"] == "_managebac_session" for c in cookies):
        raise RuntimeError("Login succeeded but no session cookie was returned — please try again")

    return {"cookies": cookies, "auth_token": auth_token,
            "email": email, "password": password}


def refresh_with_token(auth_token: str, base: str = BASE) -> dict:
    """
    Use stored auth_token to silently get a fresh session. No password needed.
    Raises RuntimeError if token is invalid.
    """
    r = requests.post(
        f"{base}/sessions.json",
        json={
            "auth_type": "share_session",
            "auth_token": auth_token,
            "client_type": "ios",
            "app_version": "2.20.2",
            "lang": "zh",
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") == 401 or "error" in body:
        raise RuntimeError("auth_token has expired — please log in again")

    domain = base.split("://", 1)[1].split("/")[0]
    cookies = [
        {"name": name, "value": value, "domain": domain, "path": "/"}
        for name, value in r.cookies.items()
    ]
    return {"cookies": cookies, "auth_token": body.get("share_auth_token", auth_token)}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    print("=== CAS Manager Login ===")
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    try:
        state = login_with_password(email, password)
        save_state(state)
        print("✅ Logged in (session valid for ~1 year)")
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
