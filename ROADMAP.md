# Hugin — Roadmap

## Done

- FastAPI backend with two recommendation endpoints (`/recommend`, `/recommend-group`)
- Claude-powered mood interpretation — free text in, TMDb query params out
- TMDb Discover integration with hidden gem mode
- OMDb enrichment (Rotten Tomatoes score, IMDb rating, content rating)
- Deterministic daily password with hash-based gate
- Hardened response parsing (code fence stripping, genre name-to-ID mapping)
- Shared httpx clients with connection pooling and retry logic
- Health check and password-hash endpoints (password-hash since removed)
- Gem mode fix — limited with_genres to first genre ID, capped page to 1–2
- Password CLI fix — `python password.py` calls load_dotenv() before reading seed
- **Backend deployed to Render** (free tier) — https://hugin-5i4y.onrender.com
- **Frontend built** as a page inside job-joseph.com (src/pages/Hugin.tsx), not a separate Lovable project. Password gate, free-text mood input, movie cards with poster/title/year/genres/runtime/ratings/gem badge. Solo and group mode both working.
- **Project card added** to job-joseph.com/projects (src/pages/Projects.tsx)
- **CORS locked** to job-joseph.com + localhost:5173 (dev only)
- **Input validation** — mood min 1 / max 500 chars, group moods min 1 / max 4, each max 500 chars
- **Rate limiting** via slowapi — /recommend 10/min, /recommend-group 5/min per IP
- **Global error handler** — unhandled exceptions return generic 500, no stack traces
- **Group mode abuse cap** — moods array limited to min 1 / max 4 via Pydantic validation
- **Advanced filters** (Phase 1) — original language, exclude animation, min year (backend + frontend)
- **Pytest test suite** — 79 tests across 5 files, all external APIs mocked
- **OMDb daily limit protection** — in-memory counter (950/day cap), resets at UTC midnight, exposed via GET /health
- **CORS updated** — added Lovable preview URL (preview--job-joseph.lovable.app)
- **Page parameter** — optional `page` field on both endpoints for "try again" cycling
- **Page capping** — filters or gem_mode cap pages to 1–2; otherwise 1–5 (explicit-page cap since replaced by wrap-around, see audit batch 1)
- **Gem fallback** — if gem_mode returns empty results, retries with gem_mode disabled
- **gem_mode prompt tightened** — only triggers for explicit hidden/obscure/underrated requests, not mood words
- **Request timeouts** — all httpx .get() calls use explicit 10s timeout; timeouts return empty results instead of raising
- **TMDb retry logic** — 429 (rate limit) retries once after Retry-After header; 500/502/503 retries once after 2s
- **Moved hosting to the Pi** — systemd `hugin.service` behind the Cloudflare tunnel at https://hugin.job-joseph.com; Render suspended
- **Audit batch 1** (November 2026):
  - Search fallback steps — every genre → any genre → lower rating bar, topping up to 5 (or 3) films. Fixes empty results for narrow moods (horror + romance) and group intersections
  - Quality floor — vote_count.gte raised from 50 to 300 (gems 150–3000) so rating sort stops surfacing 50-vote 9.9s
  - Page wrap-around using TMDb's total_pages — "try again" no longer collapses to page 2 when filters are on
  - Enrichment failures (connection resets, 404s, bad JSON) return the movie without extras instead of a 500
  - One `_get()` helper for TMDb retries; Retry-After capped at 5s and date values handled
  - Error middleware inside CORS — 500s keep CORS headers and are logged (API keys redacted)
  - Claude: structured outputs, strict validation of the reply, 15s timeout with 1 retry
  - Input validation for page, min_year and original_language (empty values still mean "no filter")
  - OMDb over HTTPS; daily cap can't be overshot by parallel calls
  - /docs and /openapi.json off in production; HEAD / for uptime monitors
  - Pinned requirements, separate requirements-dev.txt
  - Tests: 79 → 142
- **TMDb via api.tmdb.org** — api.themoviedb.org failed TLS ~60% of the time from the Pi's network
- **TMDb outages return 503 "try again"** instead of an empty list; search stops at the first unreachable call; connect timeout 5s (worst case ~15s, was ~90s). Tests: 155
- **Audit batch 2 — real password gate** (November 2026) — `POST /verify-password` and an `X-Hugin-Password` header checked on every recommendation call (`HUGIN_REQUIRE_PASSWORD=1`); wrong guesses are rate limited and never reach Claude; 1-hour grace after UTC midnight; `/password-hash` removed (it gave the word away); seed required at startup and rotated (the old one was in Hugin.tsx and in a test on the public repo). Hugin.tsx no longer knows the seed. The 29-word list stays — deliberate, it's meant to be fun.
- **Audit batch 3 — recommendation quality and cost** (November 2026):
  - Claude's keywords matched to TMDb tags and searched first (keyword matches need 7.0+)
  - Real "4 picks + 1 hidden gem" in solo mode, per-movie `is_gem`; gem-quality films only appear in the gem slot
  - Better gems: 300–3,000 votes, 7.5+, 1+ year old; all picks 60+ minutes (no shorts or music videos)
  - "Try again" pages through one deduplicated ranking — no repeats across 5 presses in testing; mood interpretation cached for an hour
  - Caches: TMDb details 7 days, OMDb ratings 3 days, keyword ids 30 days (sizes on /health)
  - Haiku 5.5 at low effort (~1/7 the cost of 4.5, same speed); a declined mood falls back to Haiku 4.5
  - Tests: 183 → 227

## Next

- **Hugin.tsx: badge from `is_gem`** — small frontend change; today's last-card rule is right whenever a gem exists, `is_gem` makes it exact.
- **Behind the Build page** — at /projects/behind-the-build/hugin, documenting the project's story and decisions.
- **GitHub profile card** — add Hugin to the GitHub profile README (Jcube101/Jcube101).

## Security & Hardening

The password gate exists only in the frontend — the backend API is
publicly accessible to anyone who knows the URL, and CORS does not stop
scripts. Audit batch 2 (above) closes this.

### Rate limiting (high priority) ✅
- slowapi added — /recommend: 10/min, /recommend-group: 5/min per IP
- Group endpoint stricter because group prompts are longer (it is still one Claude call)
- Through the Cloudflare tunnel, uvicorn reads the visitor IP from X-Forwarded-For, so limits are per visitor
- Tested: 429 returned after threshold

### Input validation (high priority) ✅
- Pydantic Field() constraints on MoodRequest and GroupMoodRequest
- mood: min 1, max 500 chars. Group moods: min 1, max 4 items, each max 500 chars
- Empty mood → 422, oversized → 422, malformed JSON → 422

### CORS lockdown (high priority) ✅
- Locked to `["https://job-joseph.com", "https://preview--job-joseph.lovable.app", "http://localhost:5173"]`
- Lovable preview and localhost entries are for dev/preview only

### Cost protection (medium priority) ✅
- In-memory daily call counter in omdb.py (cap: 950, resets at UTC midnight)
- When limit reached, enrich_with_omdb returns {} — movies still show, just without RT/IMDb ratings
- GET /health endpoint exposes today's call count, date, and limit
- Anthropic is pay-per-use — rate limiting covers this indirectly

### API key safety (medium priority) ✅
- Error middleware catches unhandled errors, returns generic
  `{"error": "Something went wrong. Please try again."}` with 500
  (replaced the global exception handler in audit batch 1; it now keeps
  CORS headers and logs the traceback)
- 422 and 429 keep FastAPI's / slowapi's own handlers
- Log lines have api_key/apikey values redacted
- Tested: deliberate crash returns generic message, no stack traces

### Group mode abuse prevention (medium priority) ✅
- moods array: min_length=1, max_length=4 in GroupMoodRequest
- Each individual mood: min 1, max 500 chars
- Empty array and >4 items both return 422

### Tests to run before Behind the Build page goes live
- [x] Rate limit returns 429 after threshold
- [x] Empty mood returns 422 not 500
- [x] Mood > 500 chars returns 422
- [x] Malformed JSON returns 422
- [x] Group moods array > 4 is rejected
- [x] CORS rejects requests from non job-joseph.com origins (browsers only — not an access control)
- [x] No API keys or stack traces in any error response
- [x] OMDb daily limit has a protection mechanism
- [x] python password.py returns correct word after 5:30 AM IST

## Later / maybe

- **Streaming provider filter** — use TMDb's `watch/providers` endpoint to filter by where the user can actually watch (Netflix, Prime, etc.). Would require a provider selector in the frontend.
- **Try again page cycling** — ✅ optional `page` parameter added to both endpoints; frontend can pass explicit page numbers on re-query.
- **Watchlist via localStorage** — let users save picks to a local watchlist without needing a database. Persists in the browser, exportable as a list.
- **Director/actor mood inputs** — extend the mood interpreter to handle inputs like "something by Denis Villeneuve" or "anything with Florence Pugh." Would add TMDb person search to the pipeline.
- **Shareable pick links** — generate a short URL or encoded query string that recreates a specific set of results, so users can text a friend "here's what Hugin picked for us."

## Advanced Filters

Allow users to optionally refine results beyond mood. All filters
are additive — mood interpretation remains the primary input.
Filters pass directly to TMDb Discover parameters, bypassing Claude.

### Phase 1 — High value, low complexity ✅

**Original language filter** ✅
- ✅ Frontend: dropdown (Any, English, Hindi, Korean, Japanese, French, Spanish, Tamil)
- ✅ Backend: adds with_original_language=XX to TMDb Discover query

**Exclude animation toggle** ✅
- ✅ Frontend: toggle — "Exclude animated films"
- ✅ Backend: when true, adds without_genres=16 to TMDb Discover query

**Min year filter** ✅
- ✅ Frontend: year input
- ✅ Backend: adds primary_release_date.gte to TMDb Discover query

### Phase 2 — Useful, slightly more work (build later)

**Release decade filter**
- Frontend: pill selector — Any, 2020s, 2010s, 2000s, 90s, 80s & older
- Backend: maps to primary_release_date.gte and .lte
- E.g. "2010s" → gte=2010-01-01, lte=2019-12-31

**Minimum runtime filter**
- Frontend: pill selector — Any, 90+ mins, 2hrs+
- Backend: maps to with_runtime.gte (90 or 120)

### Phase 3 — Complex, defer until needed

**Streaming provider filter**
- Requires TMDb watch_providers endpoint + watch_region
- Needs a separate API call to get provider list per region
- High complexity for a personal tool — defer

### API notes
- TMDb with_original_language accepts ISO 639-1 codes:
  en, hi, ko, ja, fr, es, ta, te, ml, kn
- TMDb without_genres=16 excludes ALL animation including Pixar/Ghibli
  — should be presented as "Exclude animated films" not "No anime"
  so the user understands the full scope
- OMDb is enrichment only — no filters apply there
- All filter params are optional — default behaviour unchanged
  when no filters are set

### Implementation order
1. ✅ Update MoodRequest and GroupMoodRequest Pydantic models
2. ✅ Update tmdb.py discover_movies() to accept and apply filter params
3. ✅ Update Hugin.tsx frontend to show filter UI
4. ✅ Test that filtered and unfiltered queries both return valid results
