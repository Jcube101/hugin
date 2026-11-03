# Hugin — Product Spec

## Problem statement

Choosing what to watch is harder than it should be. Streaming platforms offer thousands of options but no way to say "I'm in a weird mood, something dark but funny, nothing too long." Genre filters are too coarse. Algorithms optimize for engagement, not for what you actually feel like watching right now. And when you're watching with other people, there's no tool that resolves multiple preferences into a shared pick.

Hugin solves this by turning a free-text mood description into a curated shortlist of movies, using Claude to interpret nuance and TMDb/OMDb for the actual data.

## Pain points solved

1. **Decision fatigue** — too many options, no clear starting point. Hugin returns exactly 5 picks (solo) or 3 picks (group), not a scrollable grid.
2. **Recommendations ignore mood** — genre dropdowns can't capture "something cozy but not boring" or "I want to feel unsettled." Free text can.
3. **No group watch solution** — no existing tool takes 3 people's moods and finds the intersection. Hugin's group mode does exactly this.
4. **Hidden gems stay hidden** — algorithms push popular content. Hugin's gem mode (vote_count.lte=3000, vote_average.gte=7.5) surfaces high-quality films that never trend.

## Architecture decisions

### Why FastAPI

Job already built the Word Translator project with FastAPI. Same pattern, same deployment target (Render at the time; Hugin now runs on the Pi behind a Cloudflare tunnel), minimal learning curve. FastAPI's native async support matters because every request fans out to Claude + TMDb + OMDb.

### Why no database

There's nothing to persist. No user accounts, no watch history, no saved preferences. The password rotates deterministically from a seed. Adding a database would be pure overhead for this use case.

### Why TMDb + OMDb

TMDb has the best Discover API — it supports filtering by genre, vote average, vote count, and keyword in a single call. But TMDb doesn't expose Rotten Tomatoes scores. OMDb does, via the shared imdb_id. The two APIs complement each other: TMDb for discovery, OMDb for the ratings people actually care about.

### Why Claude as the interpreter

The core insight: mood-to-query translation is a natural language understanding problem. "Something funny but not dumb" needs to become `{genres: [35], vote_floor: 7.0, sort_by: "vote_average.desc"}`. Rule-based keyword matching would be brittle. Claude handles nuance, slang, and multi-mood group intersections natively.

## Password mechanic

Hugin is gated by a daily password that rotates at UTC midnight:

1. `SHA-256(HUGIN_SEED + "2026-04-25")` produces a hash
2. First 4 bytes of the hash are converted to an integer
3. `integer % 29` indexes into WORD_LIST (29 words: ember, dusk, reel, etc.)
4. The resulting word is today's password

The backend checks the password: `POST /verify-password` for the gate, and an `X-Hugin-Password` header on every recommendation call (enforced when `HUGIN_REQUIRE_PASSWORD=1`). Yesterday's word is accepted for the first hour after UTC midnight; case and spaces are ignored. Wrong guesses are rate limited and never reach Claude.

The legacy `GET /password-hash` prefix gave the word away (its first 8 hex characters are the bytes that pick it), so it is retired once enforcement is on. Until the frontend switches over, the frontend independently derives the word using the same seed (hardcoded directly in Hugin.tsx — Lovable personal plan does not support build secrets, so `VITE_HUGIN_SEED` is not read from environment variables) and compares against user input client-side.

## Mood-to-params logic (mood.py)

Claude receives a system prompt defining it as Hugin, a movie mood interpreter. Given a mood string, it returns a JSON object. Structured outputs (`output_config.format` with a JSON schema) constrain the reply to this shape:

| Field | Type | Description |
|-------|------|-------------|
| genres | int[] | TMDb genre IDs (e.g. 35 for Comedy) |
| keywords | string[] | TMDb keyword strings, 2-4 words each |
| vote_floor | float | Minimum vote average, range 5.5-8.0 |
| gem_mode | boolean | True ONLY for explicit hidden/obscure/underrated requests — not mood words like "dark" or "tense" |
| sort_by | string | "vote_average.desc" or "popularity.desc" |

The reply is model output shaped by user text, so it is never trusted. `_parse_response()` and `_clean_params()`:
- Strip markdown code fences or a sentence around the JSON (safety net — structured outputs should prevent both)
- Map genre name strings to TMDb IDs and drop anything not in the 18 known genre IDs
- Clamp vote_floor to 5.5–8.0 (non-numbers fall back to 6.5)
- Fall back to "vote_average.desc" for any other sort_by (after appending a missing ".desc")
- Treat gem_mode as true only for the boolean `true` (the string "false" is not true)
- Drop any keys outside the five above, so `params_used` can't carry arbitrary text

Group mode sends all moods together in a single Claude call and asks Claude to find the intersection.

## Search logic (tmdb.py)

TMDb reads `with_genres=35,18` as "every genre" and `35|18` as "any genre". Requiring every genre is the most faithful match, but narrow combinations can leave only a handful of films (horror + romance rated 7.5+ is 2 films). So discover_movies() tops up results, deduped by id, from progressively looser searches until it has enough:

| Step | Genres | vote_average.gte | vote_count.gte |
|------|--------|------------------|----------------|
| 1 | every genre (`,`) | vote_floor | 300 |
| 2 (2+ genres only) | any genre (`\|`) | vote_floor | 300 |
| 3 | any genre (`\|`) | min(vote_floor, 6.0) | 100 |

The user's filters (language, animation, year) are never dropped. Usually step 1 is enough. The 300-vote floor stops rating-sorted results filling up with obscure films rated 9+ by a few dozen people.

## Gem mode logic (tmdb.py)

When `gem_mode` is true, a gem search runs before the steps above:

| Parameter | Standard | Gem mode |
|-----------|----------|----------|
| vote_count.gte | 300 | 150 |
| vote_count.lte | (none) | 3000 |
| vote_average.gte | vote_floor | 7.5 |
| sort_by | from params | from params |
| with_genres | see search steps | first genre ID only |

If the gem search finds anything, those results are returned. If it finds nothing, `gem_mode` is set to false in `params_used` and the standard search steps run.

## Paging (tmdb.py)

- No `page`: random page 1–5, or 1–2 when filters or gem mode are active.
- Explicit `page`: honoured. It is first wrapped into TMDb's 1–500 range; if it is past the last page of results, it wraps round using TMDb's `total_pages` (page 7 of a 2-page set becomes page 1). So "try again" keeps cycling through pages that exist.

## Endpoint contracts

### POST /recommend

**Request:**
```json
{"mood": "something funny but not dumb"}
```

**Optional filter fields (both endpoints):**
```json
{
  "mood": "feel good",
  "original_language": "ko",
  "exclude_animation": true,
  "min_year": 2010
}
```

- `original_language`: 2-letter ISO 639-1 code (e.g. "en", "hi", "ko"). Case and spaces are normalised; null, "" and "any" mean no filter
- `exclude_animation`: boolean, default false — adds `without_genres=16`
- `min_year`: integer 0–2100 or null — adds `primary_release_date.gte`; 0 means no filter
- `page`: integer 0–10000 or null — explicit page for "try again" cycling; 0 means random (see Paging)

All optional fields are optional. Filters pass directly to TMDb Discover, bypassing Claude.

**Response:**
```json
{
  "results": [
    {
      "id": 914,
      "title": "The Great Dictator",
      "overview": "...",
      "poster_path": "/1QpO9wo7JWecZ4NiBuu625FiY1j.jpg",
      "release_date": "1940-10-15",
      "vote_average": 8.28,
      "vote_count": 3677,
      "genre_ids": [35, 10752],
      "backdrop_path": "/c8Pi8F1FzpNebtgXcSjC9nWCdSW.jpg",
      "original_language": "en",
      "original_title": "The Great Dictator",
      "popularity": 6.88,
      "adult": false,
      "video": false,
      "imdb_id": "tt0032553",
      "runtime": 125,
      "tagline": "Once again - the whole world laughs!",
      "genres": ["Comedy", "War"],
      "imdb_rating": "8.4",
      "rt_score": "92%",
      "rated": "G"
    }
  ],
  "params_used": {
    "genres": [35],
    "keywords": ["smart comedy", "witty dialogue"],
    "vote_floor": 7.0,
    "gem_mode": false,
    "sort_by": "vote_average.desc"
  }
}
```

- Returns up to 5 results in solo mode (fewer only if even the loosest search step finds fewer)
- `params_used` shows what Claude interpreted so the frontend can display it
- If a movie's TMDb detail or OMDb lookup fails, the movie is still returned without those fields

### POST /recommend-group

**Request:**
```json
{"moods": ["something scary", "something romantic", "anything with good acting"]}
```

**Response:** Same shape as /recommend, but returns 3 results.

### Input validation

Both endpoints share a Pydantic `Filters` base model:
- `mood`: min 1, max 500 characters
- `moods`: min 1, max 4 items, each min 1 / max 500 characters
- `original_language`: 2-letter code (see above)
- `min_year`: 0–2100; `page`: 0–10000
- Invalid inputs return 422 with Pydantic validation details

### Rate limiting

Per-IP rate limits via slowapi:
- `/recommend`: 10 requests per minute
- `/recommend-group`: 5 requests per minute (stricter because group
  prompts are longer)
- Exceeding the limit returns 429 Too Many Requests

### Error handling

- Unhandled exceptions return `{"error": "Something went wrong. Please try again."}`
  with status 500 — no stack traces, API keys, or internal details. The
  traceback is logged on the server (API keys redacted).
- If TMDb can't be reached, the response is 503
  `{"error": "Couldn't reach the movie database. Please try again in a moment."}`
  instead of an empty list. If TMDb drops out partway through the search
  steps, the films already found are returned.
- The error middleware runs inside CORSMiddleware, so 500 responses keep
  their CORS headers and the browser can read the message (503s do too)
- Validation errors (422) and rate limits (429) use their own handlers
- Failed enrichment lookups (TMDb detail, OMDb) never fail the request

## Frontend (in the main job-joseph.com repo)

Built as a page inside job-joseph.com (existing React app), not a separate Lovable project. File: `src/pages/Hugin.tsx`. Route: `/projects/hugin`.

- **Password gate** — first screen. Single text input, matches against daily word.
- **Primary input** — large free-text mood box. Quick-fill mood chips below (e.g. "cozy rainy day", "intense thriller") as shortcuts, not replacements.
- **Mobile-first** — designed for the couch use case. One thumb, portrait orientation, under 30 seconds from open to first pick.
- **Solo mode** — 5 movie cards (4 standard + 1 gem). Poster, title, year, genres, runtime, IMDb rating, RT score, hidden gem badge.
- **Group mode** — up to 3 people enter moods on the same screen, then 3 shared picks.
- **Design** — follows existing site conventions (Plus Jakarta Sans, teal primary, orange accent, dark mode).
- **Skeleton loading states** — not spinners. Cards render as grey shapes that fill in.
- **"Try again"** — re-queries the API. Can pass an incrementing `page`; the backend wraps it round to pages that exist.
- **API target** — calls https://hugin.job-joseph.com directly (the old Render URL is suspended).
- **Seed handling** — `VITE_HUGIN_SEED` is hardcoded in Hugin.tsx because Lovable personal plan does not support build secrets.
