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

Job already built the Word Translator project with FastAPI. Same pattern, same deployment target (Render), minimal learning curve. FastAPI's native async support matters because every request fans out to Claude + TMDb + OMDb.

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

The API only exposes a 16-character hash prefix via `GET /password-hash` — never the seed or the plain password. The frontend independently derives the word using the same seed (hardcoded directly in Hugin.tsx — Lovable personal plan does not support build secrets, so `VITE_HUGIN_SEED` is not read from environment variables) and compares against user input client-side.

## Mood-to-params logic (mood.py)

Claude receives a system prompt defining it as Hugin, a movie mood interpreter. Given a mood string, it returns a JSON object:

| Field | Type | Description |
|-------|------|-------------|
| genres | int[] | TMDb genre IDs (e.g. 35 for Comedy) |
| keywords | string[] | TMDb keyword strings, 2-4 words each |
| vote_floor | float | Minimum vote average, range 5.5-8.0 |
| gem_mode | boolean | True ONLY for explicit hidden/obscure/underrated requests — not mood words like "dark" or "tense" |
| sort_by | string | "vote_average.desc" or "popularity.desc" |

The response is hardened by `_parse_response()`:
- Strips markdown code fences if Claude wraps the JSON
- Maps genre name strings to TMDb IDs via a fallback lookup table
- Filters out any non-integer genre values
- Appends ".desc" to sort_by if Claude omits the suffix

Group mode sends all moods together and asks Claude to find the intersection.

## Gem mode logic (tmdb.py)

When `gem_mode` is true, the TMDb Discover query changes:

| Parameter | Standard | Gem mode |
|-----------|----------|----------|
| vote_count.gte | 50 | 50 |
| vote_count.lte | (none) | 3000 |
| vote_average.gte | vote_floor | 7.5 |
| sort_by | from params | vote_average.desc |
| with_genres | all genre IDs | first genre ID only |
| page range | 1-5 | 1-2 |

Limiting to the first genre and capping the page range prevents empty results on smaller result pools. Pages are also capped to 1–2 when any filter is active (original_language, exclude_animation, or min_year). If gem_mode returns zero results, a fallback retry runs with gem_mode disabled and page=1.

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

- `original_language`: ISO 639-1 code (e.g. "en", "hi", "ko") or null
- `exclude_animation`: boolean, default false — adds `without_genres=16`
- `min_year`: integer year or null — adds `primary_release_date.gte`
- `page`: integer or null — explicit TMDb result page for "try again" cycling

All optional fields are optional. Omitting them produces identical behaviour
to before. Filters pass directly to TMDb Discover, bypassing Claude.

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

- Returns 5 results in solo mode
- `params_used` shows what Claude interpreted so the frontend can display it

### POST /recommend-group

**Request:**
```json
{"moods": ["something scary", "something romantic", "anything with good acting"]}
```

**Response:** Same shape as /recommend, but returns 3 results.

### Input validation

Both endpoints enforce Pydantic Field() constraints:
- `mood`: min 1, max 500 characters
- `moods`: min 1, max 4 items, each min 1 / max 500 characters
- `original_language`: max 10 characters if provided
- Invalid inputs return 422 with Pydantic validation details

### Rate limiting

Per-IP rate limits via slowapi:
- `/recommend`: 10 requests per minute
- `/recommend-group`: 5 requests per minute (stricter because each mood
  hits the Claude API)
- Exceeding the limit returns 429 Too Many Requests

### Error handling

- Unhandled exceptions return `{"error": "Something went wrong. Please try again."}`
  with status 500 — no stack traces, API keys, or internal details
- Validation errors (422) and rate limits (429) use their own handlers

## Frontend (in the main job-joseph.com repo)

Built as a page inside job-joseph.com (existing React app), not a separate Lovable project. File: `src/pages/Hugin.tsx`. Route: `/projects/hugin`.

- **Password gate** — first screen. Single text input, matches against daily word.
- **Primary input** — large free-text mood box. Quick-fill mood chips below (e.g. "cozy rainy day", "intense thriller") as shortcuts, not replacements.
- **Mobile-first** — designed for the couch use case. One thumb, portrait orientation, under 30 seconds from open to first pick.
- **Solo mode** — 5 movie cards (4 standard + 1 gem). Poster, title, year, genres, runtime, IMDb rating, RT score, hidden gem badge.
- **Group mode** — up to 3 people enter moods on the same screen, then 3 shared picks.
- **Design** — follows existing site conventions (Plus Jakarta Sans, teal primary, orange accent, dark mode).
- **Skeleton loading states** — not spinners. Cards render as grey shapes that fill in.
- **"Try again"** — re-queries the API. Uses page randomization for freshness.
- **API target** — calls https://hugin-5i4y.onrender.com directly.
- **Seed handling** — `VITE_HUGIN_SEED` is hardcoded in Hugin.tsx because Lovable personal plan does not support build secrets.
