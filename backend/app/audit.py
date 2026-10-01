"""Security audit trail (BIO2 8.15): who did what, when, from where.

One line per event on the dedicated "audit" logger, so a log shipper can route
it separately from diagnostic logging:

    2026-10-01 10:00:00 | INFO | audit | event=login.success user=<uuid> ip=10.0.0.5

Rules for callers:
- identifiers only (user id, session id, counts, reason codes) — never
  transcript text, filenames chosen by users, passwords or tokens;
- an email address that matches no account is logged as a short hash, so
  repeated guessing against one address is visible without storing it.

Retention, protection and central collection of these logs are deployment
requirements; see DEPLOYMENT-SECURITY.md.
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import Request

_log = logging.getLogger("audit")


def audit(event: str, request: Request | None = None, **fields: object) -> None:
    parts = [f"event={event}"]
    parts += [f"{k}={v}" for k, v in fields.items() if v is not None]
    if request is not None and request.client is not None:
        parts.append(f"ip={request.client.host}")
    _log.info(" ".join(parts))


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]
