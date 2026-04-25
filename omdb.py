import os
import httpx

OMDB_BASE = "http://www.omdbapi.com"
_client = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client

async def enrich_with_omdb(imdb_id: str) -> dict:
    if not imdb_id:
        return {}
    api_key = os.getenv("OMDB_API_KEY")
    r = await _get_client().get(OMDB_BASE, params={
        "i": imdb_id,
        "apikey": api_key,
        "tomatoes": "true"
    })
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