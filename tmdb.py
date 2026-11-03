import asyncio
import logging
import os
import random
import re
from datetime import date, timedelta

import httpx

from cache import MISSING, TTLCache

log = logging.getLogger("hugin.tmdb")

# TMDb's alternate API domain. From the Pi's network, TLS handshakes to
# api.themoviedb.org fail ~60% of the time; api.tmdb.org serves the same API reliably.
TMDB_BASE = "https://api.tmdb.org/3"
TMDB_MAX_PAGE = 500          # TMDb rejects page numbers above this
TMDB_PAGE_SIZE = 20          # results per TMDb page
MAX_PAGE = 100               # our pages (batches of `limit` films) cycle after this
WALK_LIMIT = 60              # skip up to this many films by walking; deeper pages jump
REQUEST_TIMEOUT = 10.0
CONNECT_TIMEOUT = 5.0        # a healthy connect takes ~0.3s; fail fast if TMDb is down
RETRY_STATUSES = {500, 502, 503, 504}
MAX_RETRY_AFTER = 5.0        # cap on how long a 429 can make us wait

DEFAULT_RATING = 6.5
MIN_VOTES = 300              # below this, rating-sorted results fill up with obscure 9.9s
MIN_RUNTIME = 60             # feature films only: no shorts or music videos
KEYWORD_MIN_RATING = 7.0     # keyword matches jump the queue only if they're also good
GEM_MIN_VOTES = 300          # at 150, TMDb rated some 8.3 that IMDb rated 4.7
GEM_MAX_VOTES = 3000
GEM_MIN_RATING = 7.5
GEM_MIN_AGE_DAYS = 365       # brand-new films' early ratings come from fans and run high
RELAXED_MIN_VOTES = 100      # last-resort search for very narrow mood + filter combos
RELAXED_RATING = 6.0

DAY = 24 * 60 * 60
_detail_cache = TTLCache(ttl=7 * DAY, maxsize=2000)     # movie id -> detail dict
_keyword_cache = TTLCache(ttl=30 * DAY, maxsize=5000)   # normalised word -> keyword id or None

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


def cache_sizes() -> dict:
    return {"movie_details": len(_detail_cache), "keywords": len(_keyword_cache)}


def clear_caches():
    _detail_cache.clear()
    _keyword_cache.clear()


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


# --- Keywords --------------------------------------------------------------------
def _normalise(word: str) -> str:
    # "Mind Bending" and "mind-bending" should both match TMDb's "mind-bending"
    return re.sub(r"[\s\-_]+", " ", word.strip().lower())


async def _keyword_id(word: str) -> int | None:
    """TMDb keyword id for an exact tag match, or None. Lookups are cached."""
    key = _normalise(word)
    if not key:
        return None
    cached = _keyword_cache.get(key)
    if cached is not MISSING:
        return cached
    try:
        r = await _get("/search/keyword", {"query": key})
        hits = r.json().get("results") or []
    except (httpx.HTTPError, ValueError) as e:
        log.warning("TMDb keyword lookup failed: %s", type(e).__name__)
        return None  # not cached, so the next request tries again
    kid = next(
        (h.get("id") for h in hits
         if isinstance(h, dict) and _normalise(str(h.get("name", ""))) == key),
        None,
    )
    _keyword_cache.set(key, kid)
    return kid


async def resolve_keywords(words: list[str]) -> list[int]:
    """TMDb keyword ids for Claude's keywords. Words with no exact TMDb tag are dropped."""
    ids = await asyncio.gather(*[_keyword_id(w) for w in words])
    found = list(dict.fromkeys(i for i in ids if i))  # dedupe, keep order
    if words:
        log.info("Keywords matched %d/%d", len(found), len(words))
    return found


# --- Discover ----------------------------------------------------------------------
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
        "with_runtime.gte": MIN_RUNTIME,
    }
    if filters.get("original_language"):
        query["with_original_language"] = filters["original_language"]
    if filters.get("exclude_animation"):
        query["without_genres"] = "16"
    if filters.get("min_year"):
        query["primary_release_date.gte"] = f"{int(filters['min_year']):04d}-01-01"
    return query


def _standard_steps(base: dict, genres: list, floor: float, keyword_ids: list[int]) -> list[dict]:
    """Searches to try in order, each looser than the last.

    TMDb reads "35,18" as "every genre" and "35|18" as "any genre". Keywords are
    always pipe-joined ("any of these tags"). The keyword steps come first because
    they carry the mood's specifics ("heist", "twist ending"); the plain genre
    steps top up when they run short.
    """
    every = {**base, "vote_average.gte": floor}
    any_ = dict(every)
    if genres:
        every["with_genres"] = ",".join(str(g) for g in genres)
        any_["with_genres"] = "|".join(str(g) for g in genres)
    steps = []
    if keyword_ids:
        tags = "|".join(str(k) for k in keyword_ids)
        good = max(floor, KEYWORD_MIN_RATING)
        steps.append({**every, "with_keywords": tags, "vote_average.gte": good})
        if len(genres) > 1:
            steps.append({**any_, "with_keywords": tags, "vote_average.gte": good})
    steps.append(every)
    if len(genres) > 1:
        steps.append(any_)
    steps.append({
        **any_,
        "vote_average.gte": min(floor, RELAXED_RATING),
        "vote_count.gte": RELAXED_MIN_VOTES,
    })
    return steps


def _gem_cutoff() -> str:
    return (date.today() - timedelta(days=GEM_MIN_AGE_DAYS)).isoformat()


def _gem_rule(genres: list):
    """True for a Discover result that the gem search would also find.

    In solo mode these films are held back from the four standard picks and
    only shown in the gem slot, so the two lists never overlap. Mirrors
    _gem_steps exactly (its keyword step is a subset of its plain step).
    """
    cutoff = _gem_cutoff()

    def is_gem(movie: dict) -> bool:
        return (
            GEM_MIN_VOTES <= (movie.get("vote_count") or 0) <= GEM_MAX_VOTES
            and (movie.get("vote_average") or 0) >= GEM_MIN_RATING
            and "" < (movie.get("release_date") or "") <= cutoff
            and (not genres or genres[0] in (movie.get("genre_ids") or []))
        )
    return is_gem


def _gem_steps(base: dict, genres: list, keyword_ids: list[int]) -> list[dict]:
    """Hidden-gem searches: well rated, but too few votes to trend.

    One genre keeps the gem pool wide enough. Mood keywords first, then without.
    """
    gem = {
        **base,
        "vote_count.gte": GEM_MIN_VOTES,
        "vote_count.lte": GEM_MAX_VOTES,
        "vote_average.gte": GEM_MIN_RATING,
        "primary_release_date.lte": _gem_cutoff(),
    }
    if genres:
        gem["with_genres"] = str(genres[0])
    steps = []
    if keyword_ids:
        steps.append({**gem, "with_keywords": "|".join(str(k) for k in keyword_ids)})
    steps.append(gem)
    return steps


async def _discover(query: dict, page: int) -> dict:
    """One Discover call. Raises TMDbUnavailable if TMDb can't be reached."""
    try:
        r = await _get("/discover/movie", {**query, "page": page})
    except httpx.TransportError as e:  # timeouts, connection resets, refused connections
        log.warning("TMDb discover unreachable: %s", type(e).__name__)
        raise TMDbUnavailable from e
    return r.json()


def _total(data: dict, tmdb_page: int, results: list) -> int:
    total = data.get("total_results")
    if total is None:  # always sent by TMDb; inferred so a partial reply can't break paging
        total = (tmdb_page - 1) * TMDB_PAGE_SIZE + len(results)
    return min(total, TMDB_MAX_PAGE * TMDB_PAGE_SIZE)


async def _walk(step: dict, skip: int, want: int, found: list, known: set,
                held_back=None) -> tuple[int, int]:
    """Go down one step's ranking from the top. Films already met in an earlier
    step (`known`) don't count, the first `skip` new films are passed over, and
    the rest go into `found` until it has `want`. Films matching `held_back`
    are left out entirely. Returns (films still to skip, this step's total)."""
    tmdb_page = 1
    data = await _discover(step, tmdb_page)
    results = data.get("results") or []
    total = _total(data, tmdb_page, results)
    while True:
        for movie in results:
            movie_id = movie.get("id")
            if movie_id in known or (held_back and held_back(movie)):
                continue
            known.add(movie_id)
            if skip:
                skip -= 1
                continue
            found.append(movie)
            if len(found) >= want:
                return skip, total
        if not results or tmdb_page * TMDB_PAGE_SIZE >= total:
            return skip, total
        tmdb_page += 1
        results = (await _discover(step, tmdb_page)).get("results") or []


async def _jump(step: dict, skip: int, want: int, found: list, known: set,
                held_back=None) -> tuple[int, int]:
    """Like _walk, but jumps straight to the TMDb page holding position `skip`.
    For deep pages only: films shared with earlier steps may count twice."""
    tmdb_page = skip // TMDB_PAGE_SIZE + 1
    data = await _discover(step, tmdb_page)
    results = data.get("results") or []
    total = _total(data, tmdb_page, results)
    if skip >= total:
        return skip - total, total
    return await _walk_from(step, tmdb_page, results[skip % TMDB_PAGE_SIZE:], total,
                            want, found, known, held_back)


async def _walk_from(step, tmdb_page, results, total, want, found, known, held_back) -> tuple[int, int]:
    while True:
        for movie in results:
            if held_back and held_back(movie):
                continue
            if movie.get("id") not in known:
                known.add(movie.get("id"))
                found.append(movie)
                if len(found) >= want:
                    return 0, total
        if not results or tmdb_page * TMDB_PAGE_SIZE >= total:
            return 0, total
        tmdb_page += 1
        results = (await _discover(step, tmdb_page)).get("results") or []


async def _pass(steps: list[dict], skip: int, want: int, found: list, known: set,
                held_back=None) -> int:
    """One pass down the combined ranking. Returns the sum of the steps' totals."""
    grand_total = 0
    for step in steps:
        if len(found) >= want:
            break
        go = _walk if skip <= WALK_LIMIT else _jump
        skip, total = await go(step, skip, want, found, known, held_back)
        grand_total += total
    return grand_total


async def _collect(steps: list[dict], page: int, want: int, stride: int | None = None,
                   exclude: set = frozenset(), held_back=None) -> list:
    """The films for `page` from the steps' combined ranking.

    Think of the steps' results as one ranked list, each film counted once: the
    most specific step's films first, then the films each looser step adds.
    Page 1 starts at the top and each page moves `stride` films down (default:
    `want`), so "try again" (page + 1) keeps showing new films, best matches
    first. Past the end of the whole list it wraps round. `exclude` films and
    films matching `held_back` are never returned.

    If TMDb becomes unreachable partway, returns what was already found;
    if nothing was found, raises TMDbUnavailable.
    """
    start = (page - 1) * (stride or want)
    found: list = []
    try:
        grand_total = await _pass(steps, start, want, found, set(exclude), held_back)
        if len(found) < want and grand_total > len(found):
            # Ran off the end: wrap round. If nothing was found yet, resume where
            # this page would fall on a second lap; then top up from the very start.
            for skip in ([start % grand_total, 0] if not found else [0]):
                if len(found) >= want:
                    break
                known = set(exclude) | {m.get("id") for m in found}
                await _pass(steps, skip, want, found, known, held_back)
    except TMDbUnavailable:
        # Looser searches won't help if TMDb is down, so stop here
        if not found:
            raise
        log.info("TMDb dropped out mid-search; returning %d films found so far", len(found))
    return found[:want]


def _tag(movies: list, is_gem: bool) -> list:
    return [{**m, "is_gem": is_gem} for m in movies]


async def discover_movies(
    params: dict,
    limit: int = 5,
    filters: dict | None = None,
    page: int | None = None,
    gem_slot: bool = False,
) -> list:
    """Up to `limit` movies for Claude's params and the user's filters, each tagged
    with is_gem. The user's filters are never dropped.

    - gem_mode (the user asked for hidden gems): every pick is a gem. If no gems
      exist, params["gem_mode"] is set to False and standard picks are returned.
    - gem_slot (solo mode): limit-1 standard picks, then one hidden gem last.
      If no gem is found, the last slot is a standard pick instead.
    - Raises TMDbUnavailable if TMDb can't be reached and nothing was found.
    """
    filters = filters or {}
    genres = params.get("genres") or []
    floor = params.get("vote_floor", DEFAULT_RATING)

    if page:
        page = (page - 1) % MAX_PAGE + 1
    else:
        # No page from the frontend: start somewhere near the top for variety
        narrow = params.get("gem_mode") or _has_filters(filters)
        page = random.randint(1, 2 if narrow else 3)

    base = _base_query(params, filters)
    keyword_ids = await resolve_keywords(params.get("keywords") or [])

    if params.get("gem_mode"):
        gems = await _collect(_gem_steps(base, genres, keyword_ids), page, limit)
        if gems:
            return _tag(gems, True)
        log.info("Gem search empty, falling back to standard search")
        params["gem_mode"] = False

    # With a gem slot only limit-1 standard picks show per page, so pages move on
    # by that many; the extra one fills the last slot if no gem turns up.
    with_slot = gem_slot and limit > 1
    standard = await _collect(_standard_steps(base, genres, floor, keyword_ids), page, limit,
                              stride=limit - 1 if with_slot else limit,
                              held_back=_gem_rule(genres) if with_slot else None)
    if not with_slot or not standard:
        return _tag(standard, False)

    picks = standard[:limit - 1]
    try:
        gem = await _collect(_gem_steps(base, genres, keyword_ids), page, 1,
                             exclude={m.get("id") for m in picks})
    except TMDbUnavailable:
        gem = []
    if gem:
        return _tag(picks, False) + _tag(gem, True)
    return _tag(standard, False)


# --- Detail --------------------------------------------------------------------------
async def get_movie_detail(movie_id: int) -> dict:
    """IMDb id, runtime, tagline and genre names. Cached for a week.

    Returns {} on any failure: details are nice-to-have, so one bad lookup
    must not sink the whole request.
    """
    cached = _detail_cache.get(movie_id)
    if cached is not MISSING:
        return dict(cached)
    try:
        r = await _get(f"/movie/{movie_id}", {"language": "en-US"})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("TMDb detail for movie %s failed: %s", movie_id, type(e).__name__)
        return {}
    detail = {
        "imdb_id": data.get("imdb_id"),
        "runtime": data.get("runtime"),
        "tagline": data.get("tagline"),
        "genres": [g["name"] for g in data.get("genres") or [] if g.get("name")],
    }
    _detail_cache.set(movie_id, detail)
    return dict(detail)
