import os
import httpx
from datetime import datetime, timezone

OMDB_BASE = "http://www.omdbapi.com"
OMDB_DAILY_LIMIT = 950
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
    global _call_count
    if not imdb_id:
        return {}
    _reset_if_new_day()
    if _call_count >= OMDB_DAILY_LIMIT:
        return {}
    api_key = os.getenv("OMDB_API_KEY")
    try:
        r = await _get_client().get(OMDB_BASE, params={
            "i": imdb_id,
            "apikey": api_key,
            "tomatoes": "true"
        }, timeout=10.0)
    except httpx.TimeoutException:
        return {}
    _call_count += 1
    if r.status_code != 200:
        return {}
    data = r.json()
    rt_score = next(
        (x["Value"] for x in data.get("Ratings", [])
         if x["Source"] == "Rotten Tomatoes"), None
    )
    return {
        "imdb_rating": data.get("imdbRating"),
        "rt_score": rt_score,
        "rated": data.get("Rated"),
    }