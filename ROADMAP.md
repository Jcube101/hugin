# Hugin — Roadmap

## Now (built and working)

- FastAPI backend with two recommendation endpoints (`/recommend`, `/recommend-group`)
- Claude-powered mood interpretation — free text in, TMDb query params out
- TMDb Discover integration with hidden gem mode
- OMDb enrichment (Rotten Tomatoes score, IMDb rating, content rating)
- Deterministic daily password with hash-based gate
- Hardened response parsing (code fence stripping, genre name-to-ID mapping)
- Shared httpx clients with connection pooling and retry logic
- Health check and password-hash endpoints

## Next

- **Deploy backend** — Railway or Render, same pattern as the Word Translator project. Set env vars, confirm endpoints work from a public URL.
- **Build frontend in Lovable** — React app with dark cinematic aesthetic. Password gate, free-text mood input, quick-fill chips, movie card results. Mobile-first for the couch use case.
- **Add project card** — to job-joseph.com/projects, same pattern as other projects.
- **Custom domain** (optional) — hugin.job-joseph.com via DNS CNAME to the deployment platform.

## Later / maybe

- **Streaming provider filter** — use TMDb's `watch/providers` endpoint to filter by where the user can actually watch (Netflix, Prime, etc.). Would require a provider selector in the frontend.
- **Watchlist via localStorage** — let users save picks to a local watchlist without needing a database. Persists in the browser, exportable as a list.
- **Director/actor mood inputs** — extend the mood interpreter to handle inputs like "something by Denis Villeneuve" or "anything with Florence Pugh." Would add TMDb person search to the pipeline.
- **Shareable pick links** — generate a short URL or encoded query string that recreates a specific set of results, so users can text a friend "here's what Hugin picked for us."
