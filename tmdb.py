import asyncio
import logging
import os
import random

import httpx

log = logging.getLogger("hugin.tmdb")

# TMDb's alternate API domain. From the Pi's network, TLS handshakes to
# api.themoviedb.org fail ~60% of the time; api.tmdb.org serves the same API reliably.
TMDB_BASE = "https://api.tmdb.org/3"
TMDB_MAX_PAGE = 500          # TMDb rejects page numbers above this
REQUEST_TIMEOUT = 10.0
CONNECT_TIMEOUT = 5.0        # a healthy connect takes ~0.3s; fail fast if TMDb is down
RETRY_STATUSES = {500, 502, 503, 504}
MAX_RETRY_AFTER = 5.0        # cap on how long a 429 can make us wait

DEFAULT_RATING = 6.5
MIN_VOTES = 300              # below this, rating-sorted results fill up with obscure 9.9s
GEM_MIN_VOTES = 150
GEM_MAX_VOTES = 3000
GEM_MIN_RATING = 7.5
RELAXED_MIN_VOTES = 100      # last-resort search for very narrow mood + filter combos
RELAXED_RATING = 6.0

_client = None


class TMDbUnavailable(Exception):
    """TMDb couldn't be reached (timeouts, refused or reset connections)."""


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=3),
            transport=httpx.AsyncHTTPTransport(retries=2),
        )
    return _client


def _retry_after_seconds(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", 2))
    except (TypeError, ValueError):
        seconds = 2.0  # header was an HTTP date or junk
    return max(0.0, min(seconds, MAX_RETRY_AFTER))


async def _get(path: str, params: dict) -> httpx.Response:
    """GET from TMDb, retrying once on a 429 or 5xx. Raises httpx errors."""
    url = f"{TMDB_BASE}{path}"
    params = {"api_key": os.getenv("TMDB_API_KEY"), **params}
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
    r = await _get_client().get(url, params=params, timeout=timeout)
    if r.status_code == 429:
        await asyncio.sleep(_retry_after_seconds(r))
        r = await _get_client().get(url, params=params, timeout=timeout)
    elif r.status_code in RETRY_STATUSES:
        await asyncio.sleep(2)
        r = await _get_client().get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def _has_filters(filters: dict) -> bool:
    return bool(
        filters.get("original_language")
        or filters.get("exclude_animation")
        or filters.get("min_year")
    )


def _base_query(params: dict, filters: dict) -> dict:
    query = {
        "language": "en-US",
        "sort_by": params.get("sort_by", "vote_average.desc"),
        "vote_count.gte": MIN_VOTES,
    }
    if filters.get("original_language"):
        query["with_original_language"] = filters["original_language"]
    if filters.get("exclude_animation"):
        query["without_genres"] = "16"
    if filters.get("min_year"):
        query["primary_release_date.gte"] = f"{int(filters['min_year']):04d}-01-01"
    return query


def _standard_steps(base: dict, genres: list, floor: float) -> list[dict]:
    """Searches to try in order, each looser than the last.

    TMDb reads "35,18" as "every genre" and "35|18" as "any genre". Requiring every
    genre is the most faithful match but can leave only a handful of films.
    """
    every = {**base, "vote_average.gte": floor}
    any_ = dict(every)
    if genres:
        every["with_genres"] = ",".join(str(g) for g in genres)
        any_["with_genres"] = "|".join(str(g) for g in genres)
    steps = [every]
    if len(genres) > 1:
        steps.append(any_)
    steps.append({
        **any_,
        "vote_average.gte": min(floor, RELAXED_RATING),
        "vote_count.gte": RELAXED_MIN_VOTES,
    })
    return steps


async def _discover(query: dict, page: int) -> dict:
    """One Discover call. Raises TMDbUnavailable if TMDb can't be reached."""
    try:
        r = await _get("/discover/movie", {**query, "page": page})
    except httpx.TransportError as e:  # timeouts, connection resets, refused connections
        log.warning("TMDb discover unreachable: %s", type(e).__name__)
        raise TMDbUnavailable from e
    return r.json()


async def _discover_page(query: dict, page: int) -> list:
    """Results for `page`, wrapping round to a page that exists if it's past the end."""
    data = await _discover(query, page)
    results = data.get("results", [])
    total_pages = min(data.get("total_pages") or 0, TMDB_MAX_PAGE)
    if not results and 0 < total_pages < page:
        data = await _discover(query, (page - 1) % total_pages + 1)
        results = data.get("results", [])
    return results


async def discover_movies(
    params: dict, limit: int = 5, filters: dict | None = None, page: int | None = None
) -> list:
    """Up to `limit` movies matching Claude's params and the user's filters.

    Gem mode tries a hidden-gem search first. If that finds nothing,
    params["gem_mode"] is set to False so the response reports what was used.
    Standard mode tops up from progressively looser searches until it has
    `limit` films. The user's filters are never dropped.

    If TMDb becomes unreachable partway, whatever was already found is
    returned. If nothing was found, TMDbUnavailable is raised so the user
    is told to try again rather than shown an empty list.
    """
    filters = filters or {}
    genres = params.get("genres") or []
    floor = params.get("vote_floor", DEFAULT_RATING)

    if page:
        page = (page - 1) % TMDB_MAX_PAGE + 1
    else:
        # Narrow searches have few pages, so start near the front
        narrow = params.get("gem_mode") or _has_filters(filters)
        page = random.randint(1, 2 if narrow else 5)

    base = _base_query(params, filters)

    if params.get("gem_mode"):
        gem_query = {
            **base,
            "vote_count.gte": GEM_MIN_VOTES,
            "vote_count.lte": GEM_MAX_VOTES,
            "vote_average.gte": GEM_MIN_RATING,
        }
        if genres:
            gem_query["with_genres"] = str(genres[0])  # one genre keeps the gem pool wide enough
        results = await _discover_page(gem_query, page)
        if results:
            return results[:limit]
        log.info("Gem search empty, falling back to standard search")
        params["gem_mode"] = False

    found, seen = [], set()
    try:
        for step in _standard_steps(base, genres, floor):
            for movie in await _discover_page(step, page):
                if movie.get("id") not in seen:
                    seen.add(movie.get("id"))
                    found.append(movie)
            if len(found) >= limit:
                break
    except TMDbUnavailable:
        # Looser searches won't help if TMDb is down, so stop here
        if not found:
            raise
        log.info("TMDb dropped out mid-search; returning %d films found so far", len(found))
    return found[:limit]


async def get_movie_detail(movie_id: int) -> dict:
    """IMDb id, runtime, tagline and genre names.

    Returns {} on any failure: details are nice-to-have, so one bad lookup
    must not sink the whole request.
    """
    try:
        r = await _get(f"/movie/{movie_id}", {"language": "en-US"})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("TMDb detail for movie %s failed: %s", movie_id, type(e).__name__)
        return {}
    return {
        "imdb_id": data.get("imdb_id"),
        "runtime": data.get("runtime"),
        "tagline": data.get("tagline"),
        "genres": [g["name"] for g in data.get("genres") or [] if g.get("name")],
    }
