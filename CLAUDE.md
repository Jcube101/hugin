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
- Backend API is served at https://hugin.job-joseph.com (see Deployment)

## Architecture decisions
- FastAPI backend (Python) — matches the Word Translator pattern Job already knows
- No database, no auth service, no Vercel — intentionally minimal infra
- Password gate is deterministic: SHA-256(HUGIN_SEED + today's UTC date)
  → index into WORD_LIST → today's word. Rotates at UTC midnight.
  The seed lives only in .env (gitignored) and Job's memory/password manager.
  The backend checks the word (POST /verify-password, X-Hugin-Password
  header). Rollout in progress — see Key logic — password.
- Claude API is the mood interpreter — free-text in, TMDb params out (JSON).
  Uses Haiku 4.5 (claude-haiku-4-5-20251001) — mood interpretation is a
  lightweight structured extraction task that doesn't require Sonnet.
  Structured outputs (output_config.format json_schema) constrain the reply.
- TMDb is the primary data source (Discover endpoint), called via the
  alternate domain api.tmdb.org — from the Pi's network, TLS handshakes to
  api.themoviedb.org fail ~60% of the time (hostname-based filtering on
  the path). Don't switch it back without re-testing from the Pi.
- OMDb is the enrichment layer (RT score, IMDb rating) via shared imdb_id
- All external calls are async with explicit timeouts: TMDb/OMDb 10s per
  request (TMDb connect 5s), Claude 15s with 1 retry (the SDK default is
  10 minutes).
  TMDb detail calls are sequential (reuses one TLS connection), OMDb
  enrichment is parallel via asyncio.gather. TMDb 429s and 5xx errors
  retry once. Enrichment failures never fail the whole request. If TMDb
  Discover is unreachable, the API returns 503 "try again" (not an empty list).

## Repo structure
hugin/
├── main.py              ← FastAPI app, routes, CORS, error middleware, logging
├── mood.py              ← Claude API calls + output validation (interpret_mood, interpret_group_mood)
├── tmdb.py              ← TMDb Discover with fallback steps + movie detail (timeouts, 429/5xx retry)
├── omdb.py              ← OMDb enrichment by imdb_id over HTTPS (daily cap)
├── password.py          ← Deterministic daily password logic (run: python password.py)
├── requirements.txt     ← Runtime deps, pinned
├── requirements-dev.txt ← + pytest, pytest-asyncio
├── .env                 ← Gitignored. Contains all API keys + HUGIN_SEED
├── .gitignore
├── CLAUDE.md            ← This file
├── README.md
├── SPEC.md
├── ROADMAP.md
├── LEARNINGS.md
├── render.yaml          ← Legacy Render config (Render service is suspended)
├── CONTRIBUTING.md
└── tests/               ← 189 tests, all external APIs mocked (pytest tests/ -v)
    ├── conftest.py      ← Shared fixtures (mock movies, params, responses)
    ├── test_password.py ← Password derivation, validation, grace period (24 tests)
    ├── test_mood.py     ← Claude reply parsing, validation, request shape (35 tests)
    ├── test_tmdb.py     ← Discover queries, fallback steps, paging, retries, outages, detail (46 tests)
    ├── test_omdb.py     ← OMDb enrichment, error handling, daily cap (19 tests)
    └── test_main.py     ← Endpoint tests: validation, CORS on errors, 503, password gate, logging (65 tests)

## API endpoints
- GET/HEAD /               → health check (HEAD for uptime monitors)
- GET  /health             → OMDb daily call count, limit, and date
- POST /verify-password    → {password: str} → 200 {ok: true} | 401 {error} (10/min per IP)
- GET  /password-hash      → legacy hash prefix; 404 once HUGIN_REQUIRE_PASSWORD=1
- POST /recommend          → {mood: str, ...filters} → up to 5 enriched movie objects
- POST /recommend-group    → {moods: str[], ...filters} → up to 3 enriched movie objects

/docs, /redoc and /openapi.json are disabled in production. Set
HUGIN_DOCS=1 to enable /docs and /openapi.json locally.

### Optional fields (both endpoints)
- original_language: 2-letter ISO 639-1 code (e.g. "ko", "hi"). Case and
  spaces are normalised. null, "" and "any" mean no filter.
- exclude_animation: boolean, default false
- min_year: integer 0–2100 or null (e.g. 2010). 0 means no filter.
- page: integer 0–10000 or null — explicit page for "try again" cycling.
  0 means "pick a random page". Pages past the end wrap round (see Paging).

Invalid values return 422. Filters pass directly to TMDb Discover
parameters, bypassing Claude's mood interpretation.

## Environment variables (.env)
TMDB_API_KEY=
OMDB_API_KEY=
ANTHROPIC_API_KEY=
HUGIN_SEED=          ← secret phrase, never commit this
HUGIN_DOCS=          ← optional; "1" turns on /docs locally
HUGIN_REQUIRE_PASSWORD= ← "1" = recommendation endpoints require the
                           X-Hugin-Password header; also retires /password-hash

## Movie result object shape
Each result returned by /recommend or /recommend-group contains the full
TMDb Discover object merged with TMDb Detail and OMDb enrichment:
- id, title, overview, poster_path, release_date, vote_average, vote_count,
  genre_ids, adult, backdrop_path, original_language, original_title,
  popularity, video (from TMDb Discover)
- imdb_id, runtime, tagline, genres[] (genre name strings, from TMDb Detail)
- imdb_rating, rt_score, rated (from OMDb)

Detail and OMDb fields are missing for a movie whose lookup failed.

The gem_mode flag is returned at the response level in params_used, not
per-movie — all movies in a gem_mode request used the hidden gem filter.

## Key logic — mood interpreter (mood.py)
Claude receives a system prompt defining it as Hugin, a movie mood
interpreter. Structured outputs force a JSON object with:
- genres: TMDb genre IDs (integers, from the 18 known IDs)
- keywords: keyword strings
- vote_floor: float (5.5–8.0)
- gem_mode: boolean (true ONLY for explicit hidden/obscure/underrated requests, not mood words like "dark" or "tense")
- sort_by: "vote_average.desc" or "popularity.desc"

The reply is model output shaped by user text, so _clean_params() trusts
nothing: unknown keys are dropped, genres are filtered to known IDs (names
like "Comedy" are mapped), vote_floor is clamped, sort_by falls back to
vote_average.desc, and gem_mode must be the boolean true (the string
"false" is not true). _parse_response() still strips code fences and
surrounding text as a safety net. The text block is found by type, not
position.

Group mode sends all moods together in ONE Claude call and asks Claude to
find the intersection that satisfies everyone.

## Key logic — search fallback steps (tmdb.py)
TMDb reads with_genres="35,18" as "every genre" and "35|18" as "any genre".
discover_movies() tries progressively looser searches and tops up the
results (deduped by id) until it has `limit` films:
1. Every genre, Claude's vote_floor, vote_count.gte=300
2. Any genre (only when there are 2+ genres)
3. Any genre, vote_floor lowered to 6.0, vote_count.gte=100
The user's filters are never dropped. Usually step 1 is enough (one call).

vote_count.gte=300 exists because sorting by rating with a low vote floor
fills the top with obscure films rated 9+ by a few dozen people.

## Key logic — hidden gem filter (tmdb.py)
When gem_mode is true, a gem search runs before the steps above:
- vote_count between 150 and 3000
- vote_average.gte = 7.5
- with_genres limited to the first genre ID only (widens the result pool)
- sort_by is whatever Claude chose (not forced)
- If it finds anything, those results are returned as-is
- If it finds nothing, params["gem_mode"] is set to False (so params_used
  is accurate) and the standard steps run
This surfaces high-quality, low-popularity films the algorithms bury.

## Key logic — paging (tmdb.py)
- No page given: random page 1–5, or 1–2 when filters or gem_mode are
  active (narrow searches have few pages).
- Explicit page: honoured, first wrapped into TMDb's 1–500 range.
- If a page is past the end of the result set, TMDb's total_pages is used
  to wrap round: page 7 of a 2-page set becomes page (7-1) % 2 + 1 = 1.
  So "try again" keeps cycling through real pages.

## Key logic — request timeouts and retries (tmdb.py, omdb.py, mood.py)
- TMDb: all calls go through _get(), 10s timeout (5s to connect). On 429, waits for
  Retry-After (capped at 5s; HTTP-date values fall back to 2s) and retries
  once. On 500/502/503/504, waits 2s and retries once.
  - Discover: network errors (timeouts, refused/reset connections) raise
    TMDbUnavailable and the search stops — looser searches can't help if
    TMDb is down. If earlier steps already found films, those are returned;
    otherwise main.py turns it into 503 {"error": "Couldn't reach the movie
    database. Please try again in a moment."}. An empty list only ever
    means TMDb answered with no matches. Worst case (TMDb not answering at
    all) is ~15s: 5s connect timeout × 3 transport attempts.
  - Discover, other HTTP errors (e.g. 401 bad key): raise → 500.
  - Detail: any failure returns {}.
- OMDb: HTTPS, 10s timeout. Any failure, or a {"Response": "False"} reply,
  returns {}. No retries.
- Claude: 15s timeout, 1 retry (SDK handles retrying 429/5xx/connection errors).

## Key logic — OMDb daily cap (omdb.py)
In-memory counter, cap 950/day (free tier is 1,000), resets at UTC
midnight and on service restart. The counter is incremented before the
request is sent so parallel calls can't overshoot the cap. When the cap is
reached, enrich_with_omdb() returns {} and movies show without ratings.

## Key logic — password (password.py)
- get_today_password() → plain word, for Job's local use only, NEVER via API
- is_valid_password(candidate) → True for today's word, or yesterday's in
  the first hour after UTC midnight (GRACE_PERIOD). Ignores case and
  surrounding spaces (phone keyboards capitalise). Compares with
  hmac.compare_digest on bytes (str compare_digest rejects non-ASCII).
- HUGIN_SEED is required: password.py raises and main.py refuses to start
  without it (the old "default-seed" fallback is gone).
- get_today_hash() → legacy 16-char hex prefix for /password-hash. Its first
  8 hex chars are exactly the bytes that pick the word, so it gives the word
  away. Retired when HUGIN_REQUIRE_PASSWORD=1.
- Gate on the API (main.py):
  - POST /verify-password {password} → 200 {"ok": true} or 401
    {"error": "That's not today's word."}. 10/min per IP.
  - /recommend and /recommend-group check the X-Hugin-Password header when
    HUGIN_REQUIRE_PASSWORD=1 → 401 {"error": "Enter today's word to
    continue."}. The check runs inside the rate-limited endpoint, so wrong
    guesses count toward the limit and never reach Claude.
- Rollout (audit batch 2):
  - Phase A ✅ backend accepts the header and serves /verify-password;
    enforcement off, so the old frontend keeps working.
  - Phase B — Hugin.tsx calls /verify-password, sends the header, re-shows
    the gate on 401, and drops the hardcoded seed + local derivation.
  - Phase C — set HUGIN_REQUIRE_PASSWORD=1, rotate HUGIN_SEED (the old one
    is in the site's public bundle/history), optionally enlarge WORD_LIST
    (safe once the frontend no longer derives the word), then delete
    /password-hash and get_today_hash().
- To get today's password locally: `python password.py` from the hugin/
  directory (or the `hugin-password` alias on the Pi). This calls
  load_dotenv() before reading HUGIN_SEED; without it the script now
  fails loudly instead of printing a wrong word.
- Until Phase B, the frontend derives the word itself using the seed
  hardcoded in Hugin.tsx (Lovable personal plan has no build secrets)
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
- API host must be https://hugin.job-joseph.com — the old Render URL
  (hugin-5i4y.onrender.com) is suspended

## Security
- **CORS** — locked to `["https://job-joseph.com", "https://preview--job-joseph.lovable.app", "http://localhost:5173"]`.
  The Lovable preview and localhost entries are for dev/preview only.
  CORS only stops other websites calling the API from a browser — it does
  not stop scripts or curl.
- **Rate limiting** — slowapi with per-IP limits:
  /recommend: 10 requests/minute, /recommend-group: 5 requests/minute.
  uvicorn trusts X-Forwarded-For from cloudflared on 127.0.0.1, so limits
  apply to real visitor IPs.
- **Input validation** — Pydantic models (shared Filters base):
  mood: 1–500 chars. Group moods: 1–4 items, each 1–500 chars.
  original_language: 2-letter code; min_year 0–2100; page 0–10000.
- **Claude output validation** — see Key logic — mood interpreter.
- **Error middleware** — catch_unhandled_errors() returns
  `{"error": "Something went wrong. Please try again."}` with status 500
  and logs the traceback. It is registered before CORSMiddleware so it runs
  inside it — error responses keep their CORS headers. Validation (422),
  rate limits (429) and TMDb outages (503) keep their own handlers.
- **Logging** — "hugin.*" loggers at INFO, everything else at WARNING
  (httpx logs request URLs containing API keys at INFO). A redacting
  formatter strips api_key/apikey values from every log line.
- **API docs** — disabled in production (HUGIN_DOCS=1 to enable locally).

## Build sequence
1. ✅ Repo created, files scaffolded
2. ✅ Test /recommend locally with curl
3. ✅ Test /recommend-group locally
4. ✅ Confirm password logic works across UTC midnight
5. ✅ Deploy backend to Render (free tier) — since moved to the Pi
6. ✅ Build frontend as page in job-joseph.com (src/pages/Hugin.tsx)
7. ✅ Add project card to job-joseph.com/projects (src/pages/Projects.tsx)
8. ✅ Lock CORS to job-joseph.com + localhost:5173
9. ✅ Input validation, rate limiting, global error handler
10. ✅ Advanced filters (language, exclude animation, min year)
11. ✅ Pytest test suite (all external APIs mocked)
12. ✅ Request timeouts (10s) and TMDb 429/5xx retry logic
13. ✅ Moved hosting to the Pi — https://hugin.job-joseph.com
14. ✅ Audit batch 1 — search fallback steps, quality floor, error
    handling, CORS on errors, Claude output validation, input validation
15. [ ] Audit batch 2 — server-side password check (Phase A ✅ backend;
    Phase B Hugin.tsx; Phase C enforce + rotate seed)
16. [ ] Audit batch 3 — use Claude's keywords (TMDb keyword IDs), cache
    detail/OMDb lookups, consider Haiku 5.5
17. [ ] Behind the Build page at /projects/behind-the-build/hugin
18. [ ] Add Hugin card to GitHub profile README (Jcube101/Jcube101)

## Deployment
- Hosted on the Raspberry Pi (jobpi) as systemd service `hugin.service`:
  `venv/bin/uvicorn main:app --host 127.0.0.1 --port 8004`,
  WorkingDirectory=/home/jcube/projects/hugin
- Exposed at https://hugin.job-joseph.com via the Cloudflare tunnel
  (~/.cloudflared/config.yml → http://localhost:8004)
- THIS FOLDER IS PRODUCTION. Changes go live when the service restarts
  (no --reload): `sudo systemctl restart hugin`. Work on a branch or a git
  worktree and merge to main when ready.
- Logs: `journalctl -u hugin.service -f`
- Health check: GET / returns `{"status": "Hugin is watching"}`
- Env vars come from .env in the repo folder (load_dotenv in main.py)
- Render (hugin-5i4y.onrender.com) is suspended; render.yaml is kept for
  reference only

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
   connection), then OMDb enrichment in parallel via asyncio.gather.
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

## Audit fixes (batch 1, November 2026)
7. **Empty results from AND-ed genres** — comma-joined genres meant "every
   genre"; horror + romance at 7.5 had 2 films on 1 page, so random pages
   2–5 were empty. Fixed with the search fallback steps and total_pages
   wrap-around.
8. **Rating sort surfaced junk** — vote_count.gte=50 let 50-vote films
   rated 9+ dominate. Raised to 300 (gems: 150–3000).
9. **Small failures became 500s** — connection resets, a 404 on one movie,
   a date-style Retry-After, Claude adding a sentence around the JSON, or
   page < 1 / > 500 all crashed the whole request. Fixed via _get(),
   broad error handling in enrichment, and input validation.
10. **Error responses lost CORS headers** — the browser showed a CORS error
    instead of the message, and nothing was logged. Fixed with the error
    middleware + logging.
11. **Unvalidated Claude output** — "gem_mode": "false" turned gem mode on,
    any sort_by reached TMDb, extra keys were echoed in params_used. Fixed
    with structured outputs + _clean_params().
12. **Claude call had no timeout** — SDK default is 10 minutes × 3 attempts.
    Now 15s, 1 retry.
13. **OMDb over plain HTTP** (API key in cleartext) and a daily cap that
    parallel calls could overshoot. Now HTTPS, counter reserved up front.
