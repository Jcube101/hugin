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
  The seed is a long random value that exists only in .env on the Pi
  (rotated Nov 2026). The backend checks the word (POST /verify-password, X-Hugin-Password
  header), enforced in production — see Key logic — password.
- Claude API is the mood interpreter — free-text in, TMDb params out (JSON).
  Uses Haiku 5.5 (claude-haiku-5-5) at effort "low" — mood interpretation
  is a lightweight structured extraction task. Chosen from a 10-mood
  comparison (Nov 2026): same picks and speed (~1.8s) as Haiku 4.5 at ~1/7
  the cost, no refusals. Structured outputs (output_config.format
  json_schema) constrain the reply.
- TMDb is the primary data source (Discover endpoint), called via the
  alternate domain api.tmdb.org — from the Pi's network, TLS handshakes to
  api.themoviedb.org fail ~60% of the time (hostname-based filtering on
  the path). Don't switch it back without re-testing from the Pi.
- OMDb is the enrichment layer (RT score, IMDb rating) via shared imdb_id
- All external calls are async with explicit timeouts: TMDb/OMDb 10s per
  request (TMDb connect 5s), Claude 15s with 1 retry (the SDK default is
  10 minutes). TMDb detail calls are sequential (reuses one TLS
  connection), OMDb enrichment is parallel via asyncio.gather. TMDb 429s
  and 5xx errors retry once. Enrichment failures never fail the whole
  request. If TMDb Discover is unreachable, the API returns 503 "try
  again" (not an empty list).
- In-memory caches (cache.py TTLCache, empty after a restart): TMDb movie
  details 7 days, OMDb ratings 3 days, TMDb keyword ids 30 days, Claude's
  mood interpretations 1 hour. Sizes shown on GET /health.

## Repo structure
hugin/
├── main.py              ← FastAPI app, routes, CORS, error middleware, logging
├── cache.py             ← Small in-memory TTL cache used by mood/tmdb/omdb
├── mood.py              ← Claude API calls + output validation (interpret_mood, interpret_group_mood)
├── tmdb.py              ← TMDb search: keywords, search steps, gem slot, ranked paging, movie detail, caches
├── omdb.py              ← OMDb enrichment by imdb_id over HTTPS (daily cap)
├── password.py          ← Daily word + is_valid_password() (run: python password.py)
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
└── tests/               ← 227 tests, all external APIs mocked (pytest tests/ -v)
    ├── conftest.py      ← Shared fixtures; pins env vars and clears caches per test
    ├── test_password.py ← Password derivation, validation, grace period (21 tests)
    ├── test_cache.py    ← TTL cache expiry and eviction (7 tests)
    ├── test_mood.py     ← Claude reply parsing, validation, model choice, refusal fallback, cache (42 tests)
    ├── test_tmdb.py     ← Search steps, keywords, gem slot, ranked paging, retries, outages, detail (70 tests)
    ├── test_omdb.py     ← OMDb enrichment, error handling, daily cap, cache (22 tests)
    └── test_main.py     ← Endpoint tests: validation, CORS on errors, 503, password gate, logging (65 tests)

## API endpoints
- GET/HEAD /               → health check (HEAD for uptime monitors)
- GET  /health             → OMDb daily call count/limit/date + cache sizes
- POST /verify-password    → {password: str} → 200 {ok: true} | 401 {error} (10/min per IP)
- POST /recommend          → {mood: str, ...filters} → up to 5 enriched movie objects
- POST /recommend-group    → {moods: str[], ...filters} → up to 3 enriched movie objects

/docs, /redoc and /openapi.json are disabled in production. Set
HUGIN_DOCS=1 to enable /docs and /openapi.json locally.

### Optional fields (both endpoints)
- original_language: 2-letter ISO 639-1 code (e.g. "ko", "hi"). Case and
  spaces are normalised. null, "" and "any" mean no filter.
- exclude_animation: boolean, default false
- min_year: integer 0–2100 or null (e.g. 2010). 0 means no filter.
- page: integer 0–10000 or null — the page-th batch of results; the
  frontend sends page + 1 for "try again". 0 or null means "pick a random
  start" (see Key logic — paging).

Invalid values return 422. Filters pass directly to TMDb Discover
parameters, bypassing Claude's mood interpretation.

## Environment variables (.env)
TMDB_API_KEY=
OMDB_API_KEY=
ANTHROPIC_API_KEY=
HUGIN_SEED=          ← secret phrase, never commit this
HUGIN_DOCS=          ← optional; "1" turns on /docs locally
HUGIN_REQUIRE_PASSWORD= ← "1" = recommendation endpoints require the
                           X-Hugin-Password header ("1" in production)

## Movie result object shape
Each result returned by /recommend or /recommend-group contains the full
TMDb Discover object merged with TMDb Detail and OMDb enrichment:
- id, title, overview, poster_path, release_date, vote_average, vote_count,
  genre_ids, adult, backdrop_path, original_language, original_title,
  popularity, video (from TMDb Discover)
- imdb_id, runtime, tagline, genres[] (genre name strings, from TMDb Detail)
- imdb_rating, rt_score, rated (from OMDb)
- is_gem: true for a hidden-gem pick (the last solo card, or every card
  when the user asked for gems), false otherwise

Detail and OMDb fields are missing for a movie whose lookup failed.

params_used.gem_mode means "the user asked for hidden gems" (every pick is
a gem); per-movie is_gem is what the badge should use.

## Key logic — mood interpreter (mood.py)
Claude receives a system prompt defining it as Hugin, a movie mood
interpreter. Structured outputs force a JSON object with:
- genres: TMDb genre IDs (integers, from the 18 known IDs)
- keywords: keyword strings, matched to real TMDb keyword tags (see below)
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

Haiku 5.5 runs safety filters that can decline a request (stop_reason
"refusal") and has no server-side fallback, so a declined mood is retried
once on Haiku 4.5 (claude-haiku-4-5-20251001, without the effort setting,
which 4.5 rejects). max_tokens is 1024 because 5.5's thinking counts toward
it. The same mood text (case/spacing ignored) reuses its interpretation for
an hour, so "try again" pages through one consistent search and skips Claude.

The keyword instruction in the prompt was left as it was on purpose: TMDb
has tone tags too ("feel good", "heartwarming", "brutal", "slow burn"), and
in the comparison the original wording matched more real tags (28/34, all
10 moods) than a version asking for concrete nouns only.

## Key logic — keywords (tmdb.py)
Claude's keywords are looked up with TMDb /search/keyword; only exact tag
matches count (case, spaces and hyphens ignored, so "mind bending" matches
"mind-bending"). Lookups are cached for 30 days, misses included; a failed
lookup just drops that keyword. Matched ids are pipe-joined into
with_keywords ("any of these tags").

## Key logic — search steps (tmdb.py)
TMDb reads with_genres="35,18" as "every genre" and "35|18" as "any genre".
Standard picks come from these steps, most specific first:
1. Every genre + matched keywords, rating ≥ max(vote_floor, 7.0)
2. Any genre + matched keywords, same rating (only with 2+ genres)
3. Every genre, Claude's vote_floor
4. Any genre (only with 2+ genres)
5. Any genre, vote_floor lowered to 6.0, vote_count.gte=100
Steps 1–2 only exist when at least one keyword matched. Keyword matches
need 7.0+ to go first, so a mediocre precise match can't outrank a great
broader one. All steps: vote_count.gte=300 (except step 5) and
with_runtime.gte=60 (feature films only — no shorts or music videos).
The user's filters are never dropped. 300 votes exists because sorting by
rating with a low vote floor fills the top with films rated 9+ by a few
dozen people.

## Key logic — hidden gems (tmdb.py)
Gem search: vote_count 300–3000, vote_average ≥ 7.5, released at least a
year ago (new films' early ratings run high), first genre only (keeps the
pool wide), mood keywords first and then without. sort_by is Claude's.
At 150 votes, TMDb rated films 8.3 that IMDb rated 4.7 — hence 300.
- gem_mode (user asked for hidden gems): every pick comes from the gem
  search, all is_gem=true. If no gem exists, params["gem_mode"] becomes
  False (so params_used is accurate) and standard picks are returned.
- Solo mode (gem_slot=True in main.py): 4 standard picks + 1 gem last
  (is_gem=true). Films that the gem search would find are held back from
  the standard picks (_gem_rule mirrors the gem query exactly), so the two
  lists never overlap. If no gem exists, the 5th slot is a standard pick.
- Group mode: no gem slot.

## Key logic — paging (tmdb.py)
`page` means "the page-th batch of films", not a TMDb page. _collect()
treats a search's steps as one ranked list in which each film counts once
(the most specific step's films first, then whatever each looser step
adds). Page 1 starts at the top and each page moves on by the number of
films shown: `limit` (5 gem_mode, 3 group), 4 for solo standard picks
(the gem takes the 5th slot), and 1 for the gem slot. So "try again"
(page + 1) shows new films, best matches first, until the list is used up;
then it wraps round.
- It walks each step from the top so films shared with earlier steps aren't
  counted twice. Deep pages (more than 60 films in) jump straight to the
  right TMDb page instead, accepting the odd repeat.
- No page given: random page 1–3, or 1–2 when filters or gem_mode are on.
- Pages cycle after 100.
- Measured (Nov 2026): 5 presses of "try again" on several moods, including
  a Korean-only filter, showed no repeats; each press took 1.2–2s.

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
- /password-hash was removed: its 16-char hash prefix gave the word away (the
  first 8 hex chars are exactly the bytes that pick it), and the frontend
  never used it.
- Gate on the API (main.py):
  - POST /verify-password {password} → 200 {"ok": true} or 401
    {"error": "That's not today's word."}. 10/min per IP.
  - /recommend and /recommend-group check the X-Hugin-Password header when
    HUGIN_REQUIRE_PASSWORD=1 → 401 {"error": "Enter today's word to
    continue."}. The check runs inside the rate-limited endpoint, so wrong
    guesses count toward the limit and never reach Claude.
- Production runs with HUGIN_REQUIRE_PASSWORD=1 (since 4 Nov 2026). Setting
  it to 0 and restarting turns the check off again (emergency only).
- HUGIN_SEED is a random value that exists only in .env on the Pi; nothing
  else needs it, so it doesn't need remembering. If .env is lost, generate
  a new one. Never put the real seed in tests, docs or the frontend.
- History (audit batch 2, Nov 2026): the gate used to run in the browser,
  deriving the word from a seed hardcoded in Hugin.tsx, and that seed was
  also used as the example seed in tests/test_password.py on the public
  GitHub repo. The seed was rotated when enforcement went on, so those old
  copies are worthless; no history rewrite was needed.
- To get today's password locally: `python password.py` from the hugin/
  directory (or the `hugin-password` alias on the Pi). This calls
  load_dotenv() before reading HUGIN_SEED; without it the script now
  fails loudly instead of printing a wrong word.
- WORD_LIST has 29 evocative single words (ember, dusk, reel, etc.).
  Staying at 29 is a deliberate choice (Job, Nov 2026): Hugin is meant to be
  fun, and guessing the word only gets rate-limited movie picks — the API
  keys never leave the backend. Don't suggest enlarging it.

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
- Password gate: single text input. Calls POST /verify-password, saves the
  word in localStorage ("hugin_password") and sends it as X-Hugin-Password;
  a 401 re-locks the page. On load, a saved word is re-checked; only a 401
  deletes it. The page has no seed and can't work out the word.
- API base: one API_BASE constant = https://hugin.job-joseph.com
- Filters sent: original_language null for "Any"; min_year null, or 2010
  when the switch is on; exclude_animation always a boolean
- page: a new search picks a random page 1–3; "Try again" sends the
  previous page + 1 (see Key logic — paging)
- Errors: shows the JSON "error" field, otherwise "Something went wrong.
  Try again."; network errors and 5xx retry once after 3s ("Retrying...")
- Movie cards render: poster, title, year, genres, runtime, IMDb rating,
  RT score, hidden gem badge
- Hidden gem badge: shown when params_used.gem_mode is true, OR on the last
  card in solo mode. Since batch 3 the backend does put a gem last, so this
  is right whenever a gem exists; switching the page to read movie.is_gem
  makes it exact (pending Hugin.tsx change).
- Group mode: up to 3 people enter moods → 3 shared picks
- Mobile-first — couch use case, one thumb, under 30 seconds start to pick
- Behind the Build write-up: HuginDetail.tsx (/projects/behind-the-build/hugin),
  updated by Job for the server-side gate (Nov 2026)

## Security
- **CORS** — locked to `["https://job-joseph.com", "https://preview--job-joseph.lovable.app", "http://localhost:5173"]`.
  The Lovable preview and localhost entries are for dev/preview only.
  CORS only stops other websites calling the API from a browser — it does
  not stop scripts or curl.
- **Rate limiting** — slowapi with per-IP limits:
  /recommend: 10 requests/minute, /recommend-group: 5 requests/minute,
  /verify-password: 10 requests/minute (so guessing the word is slow).
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
15. ✅ Audit batch 2 — server-side password check: /verify-password,
    X-Hugin-Password enforced, /password-hash removed, seed rotated
16. ✅ Audit batch 3 — keywords in search, real 4 + 1 gem with is_gem,
    ranked paging (no repeats on "try again"), caches, Haiku 5.5
17. ✅ Behind the Build page at /projects/behind-the-build/hugin
18. ✅ Add Hugin card to GitHub profile README (Jcube101/Jcube101)
19. [ ] Optional: Hugin.tsx badges from movie.is_gem (today it badges the
    last solo card, which is right whenever a gem exists)

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
   wrap-around (paging later replaced by the ranked list, batch 3).
8. **Rating sort surfaced junk** — vote_count.gte=50 let 50-vote films
   rated 9+ dominate. Raised to 300 (gems 150–3000, raised to 300–3000
   in batch 3).
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

## Audit fixes (deploy follow-ups and batch 2, November 2026)
14. **The Pi couldn't reliably reach TMDb** — TLS handshakes to
    api.themoviedb.org failed ~60% of the time from the Pi's network
    (hostname-based filtering). Switched to TMDb's alternate api.tmdb.org.
15. **TMDb outages looked like "no matches"** — unreachable TMDb returned an
    empty list. Now 503 "try again", the search stops at the first failed
    call, and connect times out after 5s (worst case ~15s, was ~90s).
16. **/password-hash gave today's word away** — its first 8 hex chars are the
    bytes that pick the word. Removed (the frontend never used it).
17. **The password gate ran only in the browser** — the seed was hardcoded
    in Hugin.tsx and also used as a test value on the public GitHub repo, and
    the API never checked the word. Now /verify-password + X-Hugin-Password
    enforced on the server, seed rotated, seed required at startup.

## Audit fixes (batch 3, November 2026)
18. **Claude's keywords were never used** — now matched to TMDb keyword tags
    and searched first. Heist went from mixed results to The Sting, Rififi,
    Big Deal on Madonna Street.
19. **"Five films, one hidden gem" wasn't real** — the page badged the last
    card regardless. The backend now returns 4 + 1 real gem with is_gem.
20. **Gem quality** — 150-vote films with inflated TMDb ratings, a music
    video, brand-new releases. Now 300+ votes, 60+ minutes, 1+ year old.
21. **"Try again" repeated films** — Claude re-interpreted the mood each
    time and pages were TMDb pages. Now the interpretation is cached for an
    hour and pages walk one deduplicated ranking.
22. **Cost and quota** — Haiku 5.5 (~1/7 the cost), caches for details,
    ratings and keywords (OMDb calls only for films not seen in 3 days).
