"""
cas_errors.py — Shared exception hierarchy for CAS Manager.
"""


class CASError(Exception):
    pass


class SessionExpiredError(CASError):
    pass


class ScraperError(CASError):
    pass
