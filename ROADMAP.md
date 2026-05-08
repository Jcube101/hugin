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

## Next

- **Lock CORS** — main.py currently has `allow_origins=["*"]`. Lock to `["https://job-joseph.com"]`.
- **Behind the Build page** — at /projects/behind-the-build/hugin, documenting the project's story and decisions.
- **GitHub profile card** — add Hugin to the GitHub profile README (Jcube101/Jcube101).
- **Custom domain** (optional) — hugin.job-joseph.com via DNS CNAME to Render.

## Security & Hardening

The password gate exists only in the frontend — the backend API is
publicly accessible to anyone who knows the URL. The following work
is needed before this is considered production-hardened.

### Rate limiting (high priority)
- Add slowapi to the backend (same pattern as Word Translator)
- Limit /recommend and /recommend-group to 10 requests per minute per IP
- Limit /recommend-group specifically to prevent Claude API abuse
- Test: hammer the endpoint in a loop and confirm 429 is returned

### Input validation (high priority)
- Test empty mood string — confirm graceful error not 500
- Test mood string over 500 characters — should be rejected with 400
- Test malformed JSON body — confirm FastAPI handles cleanly
- Test /recommend-group with moods array longer than 4 — should be capped
- Add max_length validation to MoodRequest and GroupMoodRequest models

### CORS lockdown (high priority)
- Change allow_origins=["*"] to allow_origins=["https://job-joseph.com"]
- Test that direct curl calls from other origins are rejected
- Test that the frontend still works after the change

### Cost protection (medium priority)
- OMDb free tier is 1,000 calls/day — add a daily call counter
  or cache responses by imdb_id in memory
- Anthropic is pay-per-use — rate limiting covers this indirectly
- Add a /health endpoint response that shows today's OMDb call count

### API key safety (medium priority)
- Audit all error responses — confirm no stack traces leak to client
- Add a global exception handler in main.py that returns generic
  500 messages without internal details
- Test what a deliberate crash returns to the caller

### Group mode abuse prevention (medium priority)
- Cap moods array at 4 in GroupMoodRequest Pydantic model
- Each mood triggers a Claude API call in the interpreter —
  unbounded arrays are a cost vector

### Tests to run before Behind the Build page goes live
- [ ] Rate limit returns 429 after threshold
- [ ] Empty mood returns 400 not 500
- [ ] Mood > 500 chars returns 400
- [ ] Malformed JSON returns 422
- [ ] Group moods array > 4 is rejected
- [ ] CORS rejects requests from non job-joseph.com origins
- [ ] No API keys or stack traces in any error response
- [ ] OMDb daily limit has a protection mechanism
- [ ] python password.py returns correct word after 5:30 AM IST

## Later / maybe

- **Streaming provider filter** — use TMDb's `watch/providers` endpoint to filter by where the user can actually watch (Netflix, Prime, etc.). Would require a provider selector in the frontend.
- **Try again page cycling** — properly cycle through TMDb result pages on re-query instead of random page selection.
- **Watchlist via localStorage** — let users save picks to a local watchlist without needing a database. Persists in the browser, exportable as a list.
- **Director/actor mood inputs** — extend the mood interpreter to handle inputs like "something by Denis Villeneuve" or "anything with Florence Pugh." Would add TMDb person search to the pipeline.
- **Shareable pick links** — generate a short URL or encoded query string that recreates a specific set of results, so users can text a friend "here's what Hugin picked for us."

## Advanced Filters

Allow users to optionally refine results beyond mood. All filters
are additive — mood interpretation remains the primary input.
Filters pass directly to TMDb Discover parameters, bypassing Claude.

### Phase 1 — High value, low complexity (build next)

**Original language filter**
- Frontend: a dropdown with common options:
  Any (default), English, Hindi, Korean, Japanese, French, Spanish, Tamil
- Backend: adds with_original_language=XX to TMDb Discover query
- MoodRequest and GroupMoodRequest models: add optional
  original_language: str = None field
- tmdb.py: if original_language is set, add to query params

**Exclude animation toggle**
- Frontend: a simple toggle — "Exclude animated films"
- Backend: when true, adds without_genres=16 to TMDb Discover query
- MoodRequest and GroupMoodRequest models: add optional
  exclude_animation: bool = False field
- tmdb.py: if exclude_animation is true, add without_genres=16

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
1. Update MoodRequest and GroupMoodRequest Pydantic models
2. Update tmdb.py discover_movies() to accept and apply filter params
3. Update Hugin.tsx frontend to show filter UI
4. Test that filtered and unfiltered queries both return valid results
