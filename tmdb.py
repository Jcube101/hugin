import os
import httpx
import random

TMDB_BASE = "https://api.themoviedb.org/3"

async def discover_movies(params: dict, limit: int = 5) -> list:
    api_key = os.getenv("TMDB_API_KEY")
    page = random.randint(1, 3)  # freshness

    query = {
        "api_key": api_key,
        "language": "en-US",
        "page": page,
        "sort_by": params.get("sort_by", "vote_average.desc"),
        "vote_count.gte": 50,
        "vote_average.gte": params.get("vote_floor", 6.5),
        "with_genres": ",".join(str(g) for g in params.get("genres", [])),
    }

    if params.get("gem_mode"):
        query["vote_count.lte"] = 3000
        query["vote_average.gte"] = 7.5

    async with httpx.AsyncClient() as client:
        r = await client.get(f"{TMDB_BASE}/discover/movie", params=query)
        r.raise_for_status()
        results = r.json().get("results", [])
        return results[:limit]

async def get_movie_detail(movie_id: int) -> dict:
    api_key = os.getenv("TMDB_API_KEY")
    async with httpx.AsyncClient() as client:
        r = await client.get(
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