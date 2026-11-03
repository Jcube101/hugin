# Hugin — Roadmap

Hugin is live at [job-joseph.com/projects/hugin](https://job-joseph.com/projects/hugin), with its backend on the Pi at https://hugin.job-joseph.com. The three audit batches are done; what's left is one small frontend change and a list of ideas.

## Next

- **Hugin.tsx: badge from `is_gem`** (optional) — the page badges the last solo card, which is right whenever a gem exists; reading the backend's per-movie `is_gem` makes it exact.

## Ideas (later / maybe)

- **Release decade filter** — pill selector (Any, 2020s, 2010s, 2000s, 90s, 80s & older), mapped to `primary_release_date.gte` and `.lte` (e.g. "2010s" → 2010-01-01 to 2019-12-31).
- **Minimum runtime filter** — pill selector (Any, 90+ mins, 2hrs+), mapped to `with_runtime.gte` (90 or 120), replacing the fixed 60-minute minimum every search already applies.
- **Streaming provider filter** — filter by where the user can actually watch (Netflix, Prime, etc.) using TMDb's `watch/providers` and a `watch_region`. Needs a provider list per region and a selector in the frontend; high complexity for a personal tool.
- **Watchlist via localStorage** — save picks to a local watchlist without a database; persists in the browser, exportable as a list.
- **Director/actor mood inputs** — handle moods like "something by Denis Villeneuve" or "anything with Florence Pugh" by adding TMDb person search.
- **Shareable pick links** — a short URL or encoded query string that recreates a set of results, so users can text a friend "here's what Hugin picked for us".

## Done

### Initial build — April 2026
- FastAPI backend with two recommendation endpoints (`/recommend`, `/recommend-group`)
- Claude-powered mood interpretation — free text in, TMDb query params out
- TMDb Discover integration with hidden gem mode; OMDb enrichment (Rotten Tomatoes, IMDb rating, content rating)
- Deterministic daily password (checked in the browser at first; on the server since audit batch 2)
- Hardened response parsing (code fence stripping, genre name-to-ID mapping)
- Shared httpx clients with connection pooling and retry logic
- Health check endpoint (and a `/password-hash` endpoint, since removed)
- Gem mode fix — first genre ID only, pages capped to 1–2
- Password CLI fix — `python password.py` calls `load_dotenv()` before reading the seed

### Launch — 8–9 May 2026
- **Deployed to Render** (free tier); frontend built as a page inside job-joseph.com (`src/pages/Hugin.tsx`) with password gate, free-text mood input, movie cards and gem badge; project card added to job-joseph.com/projects
- **Security hardening** — CORS locked to job-joseph.com + localhost:5173 (Lovable preview added later), input validation (mood 1–500 chars; group moods 1–4, each up to 500 chars), rate limiting (`/recommend` 10/min, `/recommend-group` 5/min per IP), global error handler
- **Advanced filters, phase 1** — original language, exclude animation, minimum year (backend + frontend)
- **Pytest test suite** — 79 tests across 5 files, all external APIs mocked
- **OMDb daily limit** — in-memory counter (950/day cap) shown on `GET /health`
- **"Try again" support** — optional `page` field; pages capped to 1–2 for filtered or gem searches (later replaced by ranked paging)
- **Gem mode fixes** — fallback to standard picks when gems come back empty; prompt tightened so only explicit "hidden / obscure / underrated" requests trigger it
- **Request timeouts and retries** — explicit 10s timeouts; TMDb 429 and 5xx retried once

### Moved to the Pi — May 2026
- systemd `hugin.service` on the Raspberry Pi, behind the Cloudflare tunnel at https://hugin.job-joseph.com; Render suspended
- `hugin-password` alias for today's word (June 2026)

### Audit batch 1 — reliability and quality — November 2026
- Search fallback steps (every genre → any genre → lower rating bar), topping up to 5 (or 3) films — fixes empty results for narrow moods and group intersections
- Quality floor: `vote_count.gte` raised from 50 to 300, so rating sort stops surfacing 50-vote 9.9s
- Enrichment failures (connection resets, 404s, bad JSON) return the movie without extras instead of a 500
- One `_get()` helper for TMDb retries; Retry-After capped at 5s, date values handled
- Error middleware inside CORS — 500s keep CORS headers and are logged, with API keys redacted
- Claude: structured outputs, strict validation of the reply, 15s timeout with 1 retry
- Input validation for `page`, `min_year` and `original_language` (empty values still mean "no filter")
- OMDb over HTTPS; the daily cap can't be overshot by parallel calls
- `/docs` and `/openapi.json` off in production; `HEAD /` for uptime monitors
- Pinned requirements, separate `requirements-dev.txt`
- Tests: 79 → 142

### Deploy follow-ups — November 2026
- **TMDb via `api.tmdb.org`** — TLS to `api.themoviedb.org` failed ~60% of the time from the Pi's network
- **TMDb outages return 503 "try again"** instead of an empty list; the search stops at the first failed call; 5s connect timeout (worst case ~15s, was ~90s). Tests: 155

### Audit batch 2 — real password gate — November 2026
- `POST /verify-password` for the page's gate, and an `X-Hugin-Password` header checked on every recommendation call (`HUGIN_REQUIRE_PASSWORD=1`)
- Wrong guesses are rate limited and never reach Claude; 1-hour grace after UTC midnight
- `/password-hash` removed — its prefix gave the word away
- Seed required at startup and rotated (the old one was in Hugin.tsx and in a test on the public repo); Hugin.tsx no longer knows the seed
- The 29-word list stays — deliberate, it's meant to be fun
- Tests: 183

### Audit batch 3 — recommendation quality and cost — November 2026
- Claude's keywords matched to TMDb tags and searched first (keyword matches need 7.0+)
- Real "4 picks + 1 hidden gem" in solo mode with per-movie `is_gem`; gem-quality films only appear in the gem slot
- Better gems: 300–3,000 votes, 7.5+, at least a year old; every pick 60+ minutes (no shorts or music videos)
- "Try again" pages through one deduplicated ranking — no repeats across 5 presses in testing; mood interpretation cached for an hour
- Caches: TMDb details 7 days, OMDb ratings 3 days, keyword ids 30 days (sizes on `/health`)
- Haiku 5.5 at low effort (~1/7 the cost of 4.5, same speed); a declined mood falls back to Haiku 4.5
- Tests: 183 → 227

### Write-ups — November 2026
- **Behind the Build page** — /projects/behind-the-build/hugin (HuginDetail.tsx), updated for the server-side gate
- **GitHub profile card** — Hugin added to the GitHub profile README (Jcube101/Jcube101)

## Security and hardening

Everything below is in place. The biggest gap — a password gate that existed only in the browser while the API was open to anyone — was closed in audit batch 2. CORS only stops other websites in a browser, not scripts; the server-side password check and the rate limits are what protect the API.

| Area | Status |
|------|--------|
| Password gate | `POST /verify-password`; `X-Hugin-Password` checked on every recommendation call; wrong guesses get 401, count toward the rate limit and never reach Claude; seed is a random value only in `.env`; the page has no seed |
| Rate limiting | Per visitor IP (read from the Cloudflare tunnel's `X-Forwarded-For`): `/recommend` 10/min, `/recommend-group` 5/min (longer prompts), `/verify-password` 10/min |
| Input validation | Shared Pydantic `Filters` model: mood 1–500 chars; group moods 1–4, each 1–500; `original_language` 2-letter code; `min_year` 0–2100; `page` 0–10000. Claude's reply is validated too: unknown keys dropped, values clamped |
| CORS | `https://job-joseph.com`, `https://preview--job-joseph.lovable.app`, `http://localhost:5173` (the last two for preview and dev) |
| Errors | Generic 500 message, traceback logged with API keys redacted; error responses keep CORS headers; no stack traces or keys reach the client |
| Cost | OMDb capped at 950/day and cached for 3 days; Haiku 5.5; mood interpretations cached for an hour; wrong passwords never reach Claude |

Pre-launch checks (all passed):
- [x] Rate limit returns 429 after the threshold
- [x] Empty mood, mood over 500 chars, and malformed JSON return 422, not 500
- [x] Group moods array over 4 is rejected
- [x] CORS rejects other origins (browsers only — not an access control)
- [x] No API keys or stack traces in any error response
- [x] OMDb daily limit has a protection mechanism
- [x] `python password.py` returns the right word after 5:30 AM IST (UTC midnight)
- [x] Recommendation calls without today's word return 401 and never reach Claude
- [x] Error responses keep CORS headers, so the page can show the message

## Advanced filters reference

Filters refine results beyond mood. They pass straight to TMDb Discover, bypassing Claude, and are all optional.

| Filter | Frontend | Backend |
|--------|----------|---------|
| Original language ✅ | Dropdown: Any, English, Hindi, Korean, Japanese, French, Spanish, Tamil | `with_original_language` |
| Exclude animation ✅ | Toggle: "Exclude animated films" | `without_genres=16` |
| Minimum year ✅ | Switch (sends 2010) | `primary_release_date.gte` |

Notes:
- `with_original_language` takes ISO 639-1 codes: en, hi, ko, ja, fr, es, ta, te, ml, kn.
- `without_genres=16` excludes all animation, Pixar and Ghibli included, so the toggle says "Exclude animated films", not "No anime".
- OMDb is enrichment only; no filters apply there.
- Phase 2 (decade, minimum runtime) and phase 3 (streaming provider) are under Ideas above.
