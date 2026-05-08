import os
import httpx
import random

TMDB_BASE = "https://api.themoviedb.org/3"
_client = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=3),
            transport=httpx.AsyncHTTPTransport(retries=2),
        )
    return _client

async def discover_movies(params: dict, limit: int = 5, filters: dict = {}, page: int | None = None) -> list:
    api_key = os.getenv("TMDB_API_KEY")
    gem = params.get("gem_mode")
    genres = params.get("genres", [])

    has_filters = (
        filters.get("original_language") or
        filters.get("exclude_animation") or
        filters.get("min_year")
    )

    if has_filters or gem:
        effective_page = min(page, 2) if page else random.randint(1, 2)
    else:
        effective_page = page if page else random.randint(1, 5)

    query = {
        "api_key": api_key,
        "language": "en-US",
        "page": effective_page,
        "sort_by": params.get("sort_by", "vote_average.desc"),
        "vote_count.gte": 50,
        "vote_average.gte": params.get("vote_floor", 6.5),
        "with_genres": str(genres[0]) if gem and genres else ",".join(str(g) for g in genres),
    }

    if gem:
        query["vote_count.lte"] = 3000
        query["vote_average.gte"] = 7.5

    if filters.get("original_language"):
        query["with_original_language"] = filters["original_language"]

    if filters.get("exclude_animation"):
        existing = query.get("without_genres", "")
        query["without_genres"] = f"{existing},16".strip(",") if existing else "16"

    if filters.get("min_year"):
        query["primary_release_date.gte"] = f"{filters['min_year']}-01-01"

    r = await _get_client().get(f"{TMDB_BASE}/discover/movie", params=query)
    r.raise_for_status()
    results = r.json().get("results", [])[:limit]

    if not results and params.get("gem_mode"):
        params["gem_mode"] = False
        query.pop("vote_count.lte", None)
        query["vote_average.gte"] = params.get("vote_floor", 6.5)
        query["with_genres"] = ",".join(
            str(g) for g in params.get("genres", [])
        )
        query["page"] = 1
        r = await _get_client().get(
            f"{TMDB_BASE}/discover/movie", params=query
        )
        r.raise_for_status()
        results = r.json().get("results", [])[:limit]

    return results

async def get_movie_detail(movie_id: int) -> dict:
    api_key = os.getenv("TMDB_API_KEY")
    r = await _get_client().get(
        f"{TMDB_BASE}/movie/{movie_id}",
        params={"api_key": api_key, "language": "en-US"}
    )
    r.raise_for_status()
    data = r.json()
    return {
        "imdb_id": data.get("imdb_id"),
        "runtime": data.get("runtime"),
        "tagline": data.get("tagline"),
        "genres": [g["name"] for g in data.get("genres", [])],
    }