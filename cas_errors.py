"""
cas_errors.py — Shared exception hierarchy for CAS Manager.
"""


class CASError(Exception):
    pass


class SessionExpiredError(CASError):
    pass


class NetworkError(CASError):
    """ManageBac is unreachable (offline / DNS / timeout). The user is NOT
    logged out — callers must not treat this as SessionExpiredError, or the
    UI would wrongly ask for the password again."""


class ScraperError(CASError):
    pass
