import os
import hashlib
from datetime import datetime, timezone

WORD_LIST = [
    "ember", "dusk", "reel", "tide", "prism", "drift", "solace",
    "echo", "fable", "glyph", "haven", "inkling", "journal", "kindle",
    "lucid", "margin", "nebula", "omen", "parchment", "quill", "reverie",
    "signal", "thread", "umbra", "vantage", "wander", "xenon", "yarn", "zenith"
]

def get_today_hash() -> str:
    seed = os.getenv("HUGIN_SEED", "default-seed")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = hashlib.sha256(f"{seed}{today}".encode()).hexdigest()
    # Return the hash — frontend uses same logic to derive the word
    return raw[:16]  # short hash, enough for comparison

def get_today_password() -> str:
    seed = os.getenv("HUGIN_SEED", "default-seed")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = hashlib.sha256(f"{seed}{today}".encode()).digest()
    idx = int.from_bytes(raw[:4], "big") % len(WORD_LIST)
    return WORD_LIST[idx]