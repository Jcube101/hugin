import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

WORD_LIST = [
    "ember", "dusk", "reel", "tide", "prism", "drift", "solace",
    "echo", "fable", "glyph", "haven", "inkling", "journal", "kindle",
    "lucid", "margin", "nebula", "omen", "parchment", "quill", "reverie",
    "signal", "thread", "umbra", "vantage", "wander", "xenon", "yarn", "zenith"
]

# Yesterday's word keeps working this long after UTC midnight, so a session
# that spans the rotation isn't cut off mid-pick.
GRACE_PERIOD = timedelta(hours=1)


def _seed() -> str:
    seed = os.getenv("HUGIN_SEED")
    if not seed:
        # No silent fallback: a default seed would produce a wrong (and guessable) word
        raise RuntimeError("HUGIN_SEED is not set — add it to .env")
    return seed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(day: datetime) -> bytes:
    return hashlib.sha256(f"{_seed()}{day.strftime('%Y-%m-%d')}".encode()).digest()


def _word_for(day: datetime) -> str:
    return WORD_LIST[int.from_bytes(_digest(day)[:4], "big") % len(WORD_LIST)]


def get_today_hash() -> str:
    # Legacy: served by /password-hash until the frontend stops using it.
    # Its first 8 hex chars are the bytes that pick the word, so it gives the word away.
    return _digest(_now()).hex()[:16]


def get_today_password() -> str:
    return _word_for(_now())


def is_valid_password(candidate: str | None) -> bool:
    """True if `candidate` is today's word, or yesterday's just after UTC midnight.

    Case and surrounding spaces are ignored (phone keyboards capitalise).
    """
    now = _now()
    days = [now]
    if now - now.replace(hour=0, minute=0, second=0, microsecond=0) < GRACE_PERIOD:
        days.append(now - timedelta(days=1))
    guess = (candidate or "").strip().lower().encode()
    return any(hmac.compare_digest(guess, _word_for(day).encode()) for day in days)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(get_today_password())
