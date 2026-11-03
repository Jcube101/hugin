import logging
import os
from datetime import datetime, timezone

import httpx

log = logging.getLogger("hugin.omdb")

OMDB_BASE = "https://www.omdbapi.com/"
OMDB_DAILY_LIMIT = 950       # free tier allows 1,000/day; keep a margin
_client = None
_call_count = 0
_call_date = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client


def _reset_if_new_day():
    global _call_count, _call_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _call_date != today:
        _call_count = 0
        _call_date = today


def get_omdb_call_count() -> dict:
    _reset_if_new_day()
    return {"date": _call_date, "calls": _call_count, "limit": OMDB_DAILY_LIMIT}


async def enrich_with_omdb(imdb_id: str) -> dict:
    """IMDb rating, Rotten Tomatoes score and content rating.

    Returns {} on any failure or once the daily cap is reached — ratings are
    nice-to-have, so the movie still shows without them.
    """
    global _call_count
    if not imdb_id:
        return {}
    _reset_if_new_day()
    if _call_count >= OMDB_DAILY_LIMIT:
        return {}
    # Count before the await so calls running in parallel can't overshoot the cap
    _call_count += 1
    try:
        r = await _get_client().get(OMDB_BASE, params={
            "i": imdb_id,
            "apikey": os.getenv("OMDB_API_KEY"),
            "tomatoes": "true",
        }, timeout=10.0)
        data = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OMDb lookup for %s failed: %s", imdb_id, type(e).__name__)
        return {}
    if not isinstance(data, dict) or data.get("Response") == "False":
        return {}
    rt_score = next(
        (x.get("Value") for x in data.get("Ratings") or []
         if x.get("Source") == "Rotten Tomatoes"), None
    )
    return {
        "imdb_rating": data.get("imdbRating"),
        "rt_score": rt_score,
        "rated": data.get("Rated"),
    }
