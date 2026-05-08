# Hugin — Roadmap

## Done

- FastAPI backend with two recommendation endpoints (`/recommend`, `/recommend-group`)
- Claude-powered mood interpretation — free text in, TMDb query params out
- TMDb Discover integration with hidden gem mode
- OMDb enrichment (Rotten Tomatoes score, IMDb rating, content rating)
- Deterministic daily password with hash-based gate
- Hardened response parsing (code fence stripping, genre name-to-ID mapping)
- Shared httpx clients with connection pooling and retry logic
- Health check and password-hash endpoints
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
- **Page capping** — filters or gem_mode cap pages to 1–2; otherwise 1–5
- **Gem fallback** — if gem_mode returns empty results, retries with gem_mode disabled
- **gem_mode prompt tightened** — only triggers for explicit hidden/obscure/underrated requests, not mood words

## Next

- **Behind the Build page** — at /projects/behind-the-build/hugin, documenting the project's story and decisions.
- **GitHub profile card** — add Hugin to the GitHub profile README (Jcube101/Jcube101).
- **Custom domain** (optional) — hugin.job-joseph.com via DNS CNAME to Render.

## Security & Hardening

The password gate exists only in the frontend — the backend API is
publicly accessible to anyone who knows the URL. The following work
is needed before this is considered production-hardened.

### Rate limiting (high priority) ✅
- slowapi added — /recommend: 10/min, /recommend-group: 5/min per IP
- Group endpoint stricter because each mood hits Claude API
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
- Global exception handler catches unhandled errors, returns generic
  `{"error": "Something went wrong. Please try again."}` with 500
- Re-raises HTTPException, RequestValidationError, RateLimitExceeded
  so FastAPI's built-in handlers still work
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
- [x] CORS rejects requests from non job-joseph.com origins
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
