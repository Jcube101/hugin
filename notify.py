"""Emails Job today's word when the raven on the Hugin page is tapped 3 times.

The browser sends nothing. The word is worked out here and posted to the
"Hugin Word Email" n8n workflow, which has Job's address fixed. So whoever
triggers this can only send Job an email: finding the gesture in the page's
code gets a stranger nothing.

The webhook URL (HUGIN_WORD_WEBHOOK_URL in .env) has a random path, which is
its secret. It is never logged.

Limits keep the inbox sane: one email every COOLDOWN and at most DAILY_LIMIT
a day (reset at UTC midnight and on restart, like the OMDb counter). A failed
send frees the cooldown so Job can try again straight away.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from password import get_today_password

log = logging.getLogger("hugin.notify")

COOLDOWN = timedelta(minutes=2)
DAILY_LIMIT = 10
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_state = {"date": None, "count": 0, "last_sent": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _webhook_url() -> str | None:
    return os.getenv("HUGIN_WORD_WEBHOOK_URL") or None


def _make_client() -> httpx.AsyncClient:
    # A fresh client per send: this runs a few times a day at most
    return httpx.AsyncClient(timeout=TIMEOUT)


def reset():
    """Forget today's sends (used by tests)."""
    _state.update(date=None, count=0, last_sent=None)


def reserve_send() -> bool:
    """Claim a send, or return False if this tap should send nothing.

    The slot is claimed before the request goes out, so taps that arrive
    together can't both get through.
    """
    if not _webhook_url():
        log.warning("Raven tapped but HUGIN_WORD_WEBHOOK_URL isn't set; no email sent")
        return False
    now = _now()
    today = now.strftime("%Y-%m-%d")
    if _state["date"] != today:
        _state.update(date=today, count=0)
    if _state["count"] >= DAILY_LIMIT:
        log.warning("Raven tapped but all %d of today's emails are used up", DAILY_LIMIT)
        return False
    if _state["last_sent"] and now - _state["last_sent"] < COOLDOWN:
        log.info("Raven tapped again within %d minutes of the last email; skipped",
                 COOLDOWN.seconds // 60)
        return False
    _state["count"] += 1
    _state["last_sent"] = now
    return True


async def send_today_word() -> bool:
    """Post today's word to the n8n webhook. Never raises."""
    try:
        async with _make_client() as client:
            r = await client.post(_webhook_url(), json={"word": get_today_password()})
        if r.status_code >= 400:
            raise RuntimeError(f"n8n replied {r.status_code}")
    except Exception as e:
        _state["last_sent"] = None
        # Only the error type and status: httpx error messages contain the
        # URL, and the URL is the secret
        detail = str(e) if isinstance(e, RuntimeError) else type(e).__name__
        log.warning("Couldn't send today's word to n8n: %s", detail)
        return False
    log.info("Today's word emailed to Job (%d of %d today)", _state["count"], DAILY_LIMIT)
    return True
