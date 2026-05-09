# Hugin — Project Brief for Claude Code

## What this is
Hugin is a personal movie recommendation tool built for Job Joseph
(job-joseph.com). It solves decision fatigue when choosing what to watch —
solo or with a group — by interpreting a free-text mood description and
returning curated movie picks using TMDb + OMDb data, with Claude as the
interpretation layer.

Named after Odin's raven — the all-seeing messenger who flies the world
and reports back. Trusted, perceptive, personal.

## How it fits into job-joseph.com
- Lives at job-joseph.com/projects/hugin (page in the main site repo)
- The backend (this repo) is standalone — separate from the main site repo
- Frontend is built as a page inside the main job-joseph.com React app
  (src/pages/Hugin.tsx), NOT a separate Lovable project
- Project card added to src/pages/Projects.tsx in the main site repo
- Future: may redirect to hugin.job-joseph.com via DNS CNAME

## Architecture decisions
- FastAPI backend (Python) — matches the Word Translator pattern Job already knows
- No database, no auth service, no Vercel — intentionally minimal infra
- Password gate is deterministic: SHA-256(HUGIN_SEED + today's UTC date)
  → index into WORD_LIST → today's word. Rotates at UTC midnight.
  The seed lives only in .env (gitignored) and Job's memory/password manager.
  The API never exposes the plain password — only a hash for frontend comparison.
- Claude API is the mood interpreter — free-text in, TMDb params out (JSON).
  Uses Haiku 4.5 (claude-haiku-4-5-20251001) — mood interpretation is a
  lightweight structured extraction task that doesn't require Sonnet.
- TMDb is the primary data source (Discover endpoint)
- OMDb is the enrichment layer (RT score, IMDb rating) via shared imdb_id
- All external calls are async (httpx). TMDb detail calls are sequential
  (to avoid TLS connection storms), OMDb enrichment is parallel via
  asyncio.gather (OMDb uses plain HTTP, no TLS pressure)

## Repo structure
hugin/
├── main.py              ← FastAPI app, routes, CORS
├── mood.py              ← Claude API calls (interpret_mood, interpret_group_mood)
├── tmdb.py              ← TMDb Discover + movie detail
├── omdb.py              ← OMDb enrichment by imdb_id
├── password.py          ← Deterministic daily password logic (run: python password.py)
├── requirements.txt
├── .env                 ← Gitignored. Contains all API keys + HUGIN_SEED
├── .gitignore
├── CLAUDE.md            ← This file
├── README.md
├── SPEC.md
├── ROADMAP.md
├── LEARNINGS.md
├── render.yaml          ← Render deployment config
├── CONTRIBUTING.md
└── tests/               ← 79 tests, all external APIs mocked (pytest tests/ -v)
    ├── conftest.py      ← Shared fixtures (mock movies, params, responses)
    ├── test_password.py ← Password derivation and hash tests (10 tests)
    ├── test_mood.py     ← Claude response parsing and mood interpretation (17 tests)
    ├── test_tmdb.py     ← TMDb discover query construction and detail (18 tests)
    ├── test_omdb.py     ← OMDb enrichment and error handling (8 tests)
    └── test_main.py     ← FastAPI endpoint integration tests (21 tests)

## API endpoints
- GET  /                   → health check
- GET  /health             → OMDb daily call count, limit, and date
- GET  /password-hash      → returns today's SHA-256 hash prefix (not the word)
- POST /recommend          → {mood: str, ...filters} → 5 enriched movie objects
- POST /recommend-group    → {moods: str[], ...filters} → 3 enriched movie objects

### Optional fields (both endpoints)
- original_language: ISO 639-1 code string or null (e.g. "ko", "hi")
- exclude_animation: boolean, default false
- min_year: integer year or null (e.g. 2010)
- page: integer or null — explicit TMDb page number for "try again" cycling

All optional fields are optional — omitting them produces identical
behaviour to before. Filters pass directly to TMDb Discover parameters,
bypassing Claude's mood interpretation.

## Environment variables (.env)
TMDB_API_KEY=
OMDB_API_KEY=
ANTHROPIC_API_KEY=
HUGIN_SEED=          ← secret phrase, never commit this

## Movie result object shape
Each result returned by /recommend or /recommend-group contains the full
TMDb Discover object merged with TMDb Detail and OMDb enrichment:
- id, title, overview, poster_path, release_date, vote_average, vote_count,
  genre_ids, adult, backdrop_path, original_language, original_title,
  popularity, video (from TMDb Discover)
- imdb_id, runtime, tagline, genres[] (genre name strings, from TMDb Detail)
- imdb_rating, rt_score, rated (from OMDb)

The gem_mode flag is returned at the response level in params_used, not
per-movie — all movies in a gem_mode request used the hidden gem filter.

## Key logic — mood interpreter (mood.py)
Claude receives a system prompt defining it as Hugin, a movie mood
interpreter. It returns ONLY a JSON object with:
- genres: TMDb genre IDs (integers)
- keywords: keyword strings
- vote_floor: float (5.5–8.0)
- gem_mode: boolean (true ONLY for explicit hidden/obscure/underrated requests, not mood words like "dark" or "tense")
- sort_by: "vote_average.desc" or "popularity.desc"

Group mode sends all moods together and asks Claude to find the
intersection that satisfies everyone.

## Key logic — hidden gem filter (tmdb.py)
When gem_mode is true:
- vote_count.lte = 3000
- vote_average.gte = 7.5
- sort_by = vote_average.desc
- with_genres limited to the first genre ID only (widens the result pool)
- page capped at 1–2 (avoids empty pages on smaller sets)
- If gem_mode returns zero results, retries once with gem_mode disabled
  and page=1 as a fallback (ensures the user always gets recommendations)
This surfaces high-quality, low-popularity films the algorithms bury.

## Key logic — page capping (tmdb.py)
When filters are active (original_language, exclude_animation, or min_year)
OR gem_mode is true, pages are capped to 1–2 to avoid requesting pages
beyond the smaller filtered result set. Without filters, pages range 1–5
for more variety. An explicit page parameter (from "try again") is also
capped to 2 when filters/gem are active.

## Key logic — request timeouts and retries (tmdb.py, omdb.py)
- All httpx .get() calls use an explicit timeout of 10 seconds.
- TMDb (tmdb.py): on timeout, returns [] (discover) or {} (detail)
  instead of raising. On 429, reads the Retry-After header and retries
  once after sleeping. On 500/502/503, waits 2 seconds and retries once.
  If the retry also fails, the error is raised.
- OMDb (omdb.py): on timeout, returns {} instead of raising. No retry
  logic (OMDb errors already return {} via status code check).

## Key logic — password (password.py)
- get_today_password() → plain word, for Job's local use only, NEVER via API
- get_today_hash() → short hash prefix, safe to expose via /password-hash
- To get today's password locally: `python password.py` from the hugin/
  directory. This calls load_dotenv() before reading HUGIN_SEED.
  DO NOT use `python -c "from password import ..."` — that skips
  load_dotenv() and silently falls back to "default-seed", producing
  the wrong password.
- Frontend independently derives the word using the same seed (hardcoded
  in Hugin.tsx — Lovable personal plan does not support build secrets)
  and compares against user input
- WORD_LIST has 29 evocative single words (ember, dusk, reel, etc.)

## Pain points this solves
1. Can't decide what to watch — decision fatigue from too many options
2. Recommendations ignore mood — genre filters can't capture nuance
3. No group watch solution — no tool resolves multi-person preferences
4. Hidden gems stay hidden — algorithms push mainstream, bury quality

## What this is NOT
- Not a product or SaaS — it's a personal tool Job shares selectively
- Not a new destination to visit — it lives on Job's existing site
- Not a mood-tile grid UI — free text is the primary input (tiles are
  just shortcuts)
- Not trying to replace Netflix — just cuts through it

## Owner context
- Job Joseph — RevOps professional, builder mindset, XLRI alumnus
- Windows laptop (FFmpeg, ImageMagick installed), Mac at work
- Comfortable with Python, Google Apps Script, n8n, Claude Code
- Learning AI PM skills by building, not shortcuts
- Other projects: Word Translator (same FastAPI pattern), Freekick Shootout
  (in main site repo), Voyager (meeting intelligence), call analysis pipeline

## Frontend (in the main job-joseph.com repo)
- Built as a page inside job-joseph.com (existing React site), NOT a
  separate Lovable project
- File: src/pages/Hugin.tsx in the main site repo
- Route: /projects/hugin
- Project card added to src/pages/Projects.tsx
- Design follows existing site conventions (Plus Jakarta Sans, teal
  primary, orange accent, dark mode)
- VITE_HUGIN_SEED is hardcoded directly in Hugin.tsx (Lovable personal
  plan does not support build secrets)
- Password gate working — single text input, matches against daily word
- Movie cards render: poster, title, year, genres, runtime, IMDb rating,
  RT score, hidden gem badge
- Solo mode: 5 cards (4 standard + 1 gem)
- Group mode: up to 3 people enter moods → 3 shared picks
- Mobile-first — couch use case, one thumb, under 30 seconds start to pick
- API calls go directly to https://hugin-5i4y.onrender.com

## Security
- **CORS** — locked to `["https://job-joseph.com", "https://preview--job-joseph.lovable.app", "http://localhost:5173"]`.
  The Lovable preview and localhost entries are for dev/preview only.
- **Rate limiting** — slowapi with per-IP limits:
  /recommend: 10 requests/minute, /recommend-group: 5 requests/minute.
  Group endpoint is stricter because each mood hits the Claude API.
- **Input validation** — Pydantic Field() constraints:
  mood: min 1, max 500 chars. Group moods: min 1, max 4 items, each
  min 1 / max 500 chars. original_language: max 10 chars if provided.
- **Global error handler** — unhandled exceptions return
  `{"error": "Something went wrong. Please try again."}` with status 500.
  No stack traces, API keys, or internal details leak to the client.
  FastAPI's built-in handlers for validation (422) and rate limits (429)
  are preserved.

## Build sequence
1. ✅ Repo created, files scaffolded
2. ✅ Test /recommend locally with curl
3. ✅ Test /recommend-group locally
4. ✅ Confirm password logic works across UTC midnight
5. ✅ Deploy backend to Render (free tier) — https://hugin-5i4y.onrender.com
6. ✅ Build frontend as page in job-joseph.com (src/pages/Hugin.tsx)
7. ✅ Add project card to job-joseph.com/projects (src/pages/Projects.tsx)
8. ✅ Lock CORS to job-joseph.com + localhost:5173
9. ✅ Input validation, rate limiting, global error handler
10. ✅ Advanced filters (language, exclude animation, min year)
11. ✅ Pytest test suite (79 tests, all external APIs mocked)
12. [ ] Behind the Build page at /projects/behind-the-build/hugin
13. [ ] Add Hugin card to GitHub profile README (Jcube101/Jcube101)
14. [ ] Optional: custom domain hugin.job-joseph.com

## Deployment
- Hosted on Render (free tier)
- Live URL: https://hugin-5i4y.onrender.com
- Config: render.yaml in repo root
- Health check: GET / returns `{"status": "Hugin is watching"}`
- Env vars (TMDB_API_KEY, OMDB_API_KEY, ANTHROPIC_API_KEY, HUGIN_SEED)
  set in Render dashboard, not in render.yaml

## Bugs fixed (during initial build)
1. **Missing load_dotenv** — main.py never called load_dotenv(), so all
   API keys read from os.getenv() returned None. Fixed by adding
   `from dotenv import load_dotenv; load_dotenv()` at the very top of
   main.py, before any module imports that read env vars at import time.
2. **Fragile JSON parsing in mood.py** — Claude sometimes wraps responses
   in markdown code fences or returns genre names ("Comedy") instead of
   TMDb IDs (35). Fixed with _parse_response(): strips code fences via
   regex, maps genre name strings to IDs via GENRE_NAME_TO_ID lookup,
   filters out any remaining non-integer genres, and appends ".desc" to
   sort_by when Claude omits the suffix.
3. **httpx connection storm in tmdb.py/omdb.py** — each function created
   and destroyed its own httpx.AsyncClient. With 5 concurrent
   get_movie_detail calls, this opened 5 simultaneous TLS handshakes to
   TMDb's CDN (CloudFront), triggering connection resets. Fixed by using
   a lazily-initialized shared AsyncClient per module with connection
   limits (max_connections=3) and transport-level retries.
4. **Sequential TMDb + parallel OMDb pattern** — the original
   asyncio.gather over all enrich() calls ran TMDb detail + OMDb
   enrichment concurrently for all movies. Refactored enrich_all() to
   call TMDb detail sequentially (reuses the shared client's keepalive
   connection), then OMDb enrichment in parallel via asyncio.gather
   (OMDb uses HTTP, no TLS pressure).
5. **Gem mode empty results** — gem_mode stacked all genre IDs into the
   with_genres filter, producing overly narrow queries that returned
   zero results. Fixed by limiting with_genres to genres[0] only and
   capping random page selection to 1–2 when gem_mode is true.
6. **password.py silent wrong password** — calling get_today_password()
   via `python -c` or importing without load_dotenv() caused HUGIN_SEED
   to fall back to "default-seed", producing the wrong daily password
   silently. Fixed by adding a CLI entrypoint (`if __name__ == "__main__"`)
   that calls load_dotenv() before printing the password. Correct usage:
   `python password.py` from the hugin/ directory.