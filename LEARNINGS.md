# Hugin — Learning Log

Entries are in the order they happened and describe the code at that time. Where a later change replaced the fix, the entry ends with an **Update** note pointing to what happens now.

## The httpx connection storm

This was the most surprising bug. Each function in `tmdb.py` and `omdb.py` created its own `httpx.AsyncClient` inside an `async with` block — seemed clean, seemed right. But when `asyncio.gather` fired 5 `get_movie_detail` calls concurrently, that meant 5 brand-new TLS handshakes hitting TMDb's CDN (CloudFront) at the same instant. CloudFront started resetting connections with `WinError 10054`.

The fix was a lazily-initialized shared `AsyncClient` per module. One client, one connection pool, connections get reused. I also added `max_connections=3` and `retries=2` on the transport layer. The key insight: creating an async HTTP client is not free — it allocates a connection pool, and each new TLS handshake is expensive. You want one long-lived client, not many short-lived ones.

I also learned that creating the `AsyncClient` at module import time (before uvicorn's event loop starts) can cause issues on Windows. The lazy `_get_client()` pattern avoids this by deferring creation until the first actual request, when the event loop is already running.

## Why Claude responses need hardened parsing

I initially trusted that Claude would return raw JSON as instructed by the system prompt. It mostly does — but "mostly" isn't good enough for a production API. Two failure modes showed up:

1. **Markdown code fences** — Claude sometimes wraps the JSON in ` ```json ... ``` ` blocks despite "no code fences" in the prompt. This causes `json.loads()` to fail on the backticks.
2. **Genre names instead of IDs** — the system prompt says "return TMDb genre IDs as integers" and provides the full reference table, but Claude occasionally returns `["Comedy"]` instead of `[35]`. Not every time — just often enough to break things.

The fix was `_parse_response()`: regex to strip code fences, a `GENRE_NAME_TO_ID` dictionary for fallback mapping, and a filter to drop anything that's still not an integer. I also added a suffix check for `sort_by` because Claude sometimes returns `"vote_average"` without `.desc`.

The lesson: when an LLM is generating structured data that feeds directly into an API call, always validate and coerce on the receiving end. The system prompt is a strong hint, not a contract.

## The load_dotenv ordering trap

This one was embarrassing in hindsight. `main.py` imported `mood.py`, which creates an `AsyncAnthropic` client at the module level using `os.getenv("ANTHROPIC_API_KEY")`. But `load_dotenv()` was never called anywhere, so `os.getenv` returned `None`, and the Anthropic client was initialized without an API key.

The fix was adding `load_dotenv()` at the very top of `main.py`, before any other imports. The ordering matters because Python executes module-level code at import time — if `mood.py` reads the env var when it's imported, dotenv needs to have already loaded the `.env` file.

I now think of `load_dotenv()` as something that belongs on line 1-2 of the entrypoint, before anything else. Not in a utility function, not in a config module — right at the top where it can't be preceded by anything that needs the values.

## Sequential TMDb + parallel OMDb

The original code used `asyncio.gather` to run all enrichment calls (TMDb detail + OMDb) concurrently for every movie. This contributed to the connection storm problem — 5 movies meant 5 TMDb HTTPS calls + 5 OMDb HTTP calls all at once.

The fix was to split the enrichment into two phases:
1. TMDb detail calls run sequentially — they all hit the same HTTPS host, so the shared client reuses its keepalive connection. No new TLS handshakes after the first one.
2. OMDb calls run in parallel via `asyncio.gather` — OMDb uses plain HTTP (no TLS), so concurrent connections don't cause the same pressure.

This ended up being barely slower in practice. The TMDb sequential calls take advantage of HTTP keepalive, so the connection overhead after the first request is just a round trip, not a full TLS handshake. And the OMDb calls — which are the slower ones because they hit a different server — still run in parallel.

The broader lesson: `asyncio.gather` everything is not always the right move. Think about what each external service can handle and whether connection reuse gives you most of the speed benefit without the concurrency risk.

> **Update (November 2026):** OMDb now uses HTTPS (plain HTTP sent the API key unencrypted). The parallel OMDb calls are still fine, because they share one pooled client. TMDb is now called at `api.tmdb.org`; see "When TCP connects but TLS doesn't, suspect the hostname".

## The load_dotenv CLI trap (password.py)

`get_today_password()` reads `HUGIN_SEED` via `os.getenv()` with a fallback to `"default-seed"`. If you call it without `load_dotenv()` first — e.g., via `python -c "from password import get_today_password; print(get_today_password())"` — the `.env` file is never loaded, `os.getenv("HUGIN_SEED")` returns `None`, and the function silently falls back to `"default-seed"`. The password it produces is valid but wrong — it doesn't match what the frontend expects, because the frontend uses the real seed.

This failed silently because the fallback is by design (so the code doesn't crash without a seed), but it means wrong passwords with no error message.

The fix was adding a `if __name__ == "__main__"` block at the bottom of `password.py` that calls `load_dotenv()` before printing the password. The correct way to get today's password is now:

```bash
python password.py
```

The broader lesson: any Python script that reads from `.env` needs `load_dotenv()` called before the read — and if the function has a silent fallback default, you won't know it's missing until the output is wrong. For CLI entrypoints that read env vars, always gate `load_dotenv()` behind `__main__` so it works both as an import (where the caller is responsible for dotenv) and as a standalone script.

## Global exception handlers eat everything (including validation)

FastAPI has built-in handlers for `RequestValidationError` (422) and `HTTPException`. When I added a global `@app.exception_handler(Exception)` to catch unhandled errors and return a generic 500 message, it intercepted *everything* — including Pydantic validation failures. Empty mood strings that should have returned 422 were getting swallowed into a generic 500.

The fix was adding an isinstance check at the top of the global handler to re-raise exceptions that FastAPI already knows how to handle: `HTTPException`, `RequestValidationError`, and `RateLimitExceeded`. Only truly unexpected exceptions (network failures, bad API responses, bugs) fall through to the generic message.

The lesson: a global exception handler in FastAPI is a catch-all in the literal sense. If you want it to coexist with FastAPI's built-in error handling, you need to explicitly exclude the exception types that already have handlers. The alternative is registering handlers for specific exception types instead of the base `Exception` class, but that requires knowing every possible unhandled exception in advance — the isinstance re-raise pattern is more defensive.

The broader point: stack traces should never reach the client in a production API. They leak internal paths, library versions, and sometimes env var names. A global handler is the last line of defense, but it needs to be surgically scoped so it doesn't break the framework's own error semantics.

> **Update (November 2026):** the isinstance re-raise turned out to be dead code: those exceptions have their own handlers, which run first. The global handler was replaced by a middleware that also keeps CORS headers and logs the traceback. See "Error responses need CORS headers too".

## Page state sync: random isn't "try again"

The "try again" button re-queried the API, but `discover_movies()` picked a random TMDb page each time (`random.randint(1, 3)`). This meant "try again" sometimes returned the same page, and the user saw identical results — or it jumped to a page they'd already seen. There was no way for the frontend to say "I've seen page 2, give me page 3."

The fix was adding an optional `page` parameter to both endpoints. When the frontend sends `page`, the backend uses it directly instead of rolling the dice. The frontend can now increment the page on each "try again" tap, guaranteeing fresh results every time. When `page` is omitted (first load), the backend still randomizes — but now across a wider range (1–5 instead of 1–3) for more variety on the initial query.

The lesson: randomization is fine for a first impression, but any "give me something different" interaction needs deterministic pagination the client controls. If the client can't tell the server what it's already seen, the server can't avoid repeating itself.

> **Update (November 2026):** `page` now means "the page-th batch of films" from one deduplicated ranking, not a TMDb page, and the mood's interpretation is cached for an hour. See "'Try again' needs one ranking, not pages of several searches".

## Gem mode over-triggering

Users describing intense moods — "mind bending," "psychological," "dark and tense" — were getting gem_mode=true results: low-popularity, niche films with vote_count under 3000. The movies were technically good but not what anyone meant by "something dark." They wanted *Zodiac*, not a Lithuanian arthouse film with 200 votes.

The root cause was the system prompt. It told Claude to set gem_mode when the mood "suggests niche/unusual/underrated" — but "unusual" is subjective, and Claude interpreted intense or unconventional mood descriptions as requests for obscure content. "Mind bending" felt unusual to the model, so gem_mode flipped on.

The fix was making the prompt explicit: gem_mode is true ONLY when the user literally asks for hidden, obscure, underrated, or unknown films. Mood words like "dark," "tense," "psychological," or "mind bending" are moods — they describe the feeling the user wants, not the popularity tier. The prompt now calls this out with specific negative examples.

The lesson: when an LLM controls a boolean that changes the entire query strategy, the prompt needs to define both what triggers it AND what doesn't. Positive-only definitions ("set to true when...") leave a gray zone that the model fills with its own judgment. Adding explicit "do NOT set for..." examples collapses that gray zone. This is the same principle as _parse_response() — LLM outputs that feed directly into API parameters need tight guardrails, not just hints.

## Filters collapse result pools at higher pages

After widening the random page range to 1–5 for more variety, filtered queries started returning empty results. A query like `original_language=ko, min_year=2015, exclude_animation=true` might have 40 total results on TMDb — barely two pages. Requesting page 4 returned nothing.

Gem mode had the same problem from day one (result pools of a few hundred films at most), which is why it was already capped at page 1–2. But the same logic applied to any combination of filters that narrows the pool significantly.

The fix was a unified page-capping rule: if any filter is active OR gem_mode is true, cap to pages 1–2. Otherwise, allow 1–5. An explicit `page` parameter from the frontend is also capped (`min(page, 2)`) when filters are in play, so the frontend can't accidentally request a page that doesn't exist.

I also added a fallback for gem_mode specifically: if the query returns zero results, retry once with gem_mode disabled and page=1. This handles the edge case where even pages 1–2 are empty for a very narrow gem query — the user still gets recommendations, just not hidden gems.

The lesson: any feature that narrows a result set (filters, niche modes, strict thresholds) needs to account for pagination. A page range that works for an unfiltered query of 10,000 results will overshoot a filtered query of 50. When you add filters, audit every place in the code that assumes "there are enough pages."

> **Update (November 2026):** page capping was replaced first by wrap-around using TMDb's `total_pages`, then by the ranked list, which never requests a page that doesn't exist. See "'Try again' needs one ranking, not pages of several searches".

## Per-request timeouts vs client-level timeouts

The shared `AsyncClient` in both `tmdb.py` and `omdb.py` was initialized with `timeout=15.0` at the client level. This works as a default, but it's invisible at the call site — a reader scanning `await client.get(url, params=query)` has no idea there's a timeout at all. It also means every call shares the same budget, which isn't always right: a TMDb Discover call that fans out to CDN might deserve more time than an OMDb lookup over plain HTTP.

The fix was adding explicit `timeout=10.0` to every `.get()` call. The per-request timeout overrides the client default, so each call site documents its own expectation. The value was tightened from 15s to 10s — if an external API hasn't responded in 10 seconds on a simple lookup, waiting longer rarely helps and just delays the user's response.

The more important change was handling timeout failures gracefully. Before, a timeout would bubble up as an unhandled `httpx.TimeoutException`, which the global error handler would catch and return as a generic 500. Now, timeouts in `discover_movies()` return `[]` and in `get_movie_detail()` / `enrich_with_omdb()` return `{}`. The user might get fewer results or missing ratings, but they get a response instead of an error.

The lesson: client-level timeouts are a safety net; per-request timeouts are documentation. Use both. And when an external API timeout doesn't represent a fatal error for the user's request, catch it and degrade gracefully rather than failing the whole request.

> **Update (November 2026):** an empty list turned out to be misleading when TMDb was actually down: users saw "no matches". Discover now raises when TMDb can't be reached, and the API answers 503 "Couldn't reach the movie database. Please try again in a moment." Detail and OMDb lookups still return `{}` on failure.

## TMDb 429 and 5xx retries

TMDb's API returns 429 with a `Retry-After` header when you hit their rate limit, and occasionally returns 500/502/503 during transient outages. Before adding retry logic, both cases would raise through the global error handler as a 500 to the user — even though a simple retry a few seconds later would succeed.

The fix was a single-retry pattern for both cases:
- **429**: read the `Retry-After` header (defaulting to 2 seconds if missing), sleep, retry once. If the retry also fails, raise — persistent rate limiting means something is genuinely wrong.
- **500/502/503**: wait 2 seconds, retry once. Server errors on CDN-backed APIs like TMDb are almost always transient (edge node restart, deploy in progress). One retry catches the majority of these.

The retry is intentionally limited to one attempt — not exponential backoff, not a retry loop. This is a user-facing API where latency matters. One retry adds 2-3 seconds; a retry loop could add 30+. If TMDb is genuinely down, no amount of retrying from a single request handler will fix it.

The lesson: for user-facing APIs that depend on external services, one retry with a short sleep handles most transient failures without meaningfully degrading response time. Save exponential backoff for batch jobs and background workers where latency doesn't matter.

## CORS cold start false positive

When testing from the Lovable preview deployment (`preview--job-joseph.lovable.app`), API requests silently failed. The browser showed a CORS error. Initial instinct was that Render's free tier had cold-started and the request timed out — the classic Render spin-down problem where the first request after idle takes 30+ seconds.

But the health check endpoint responded fine from the browser's address bar. The issue was that the CORS `allow_origins` list only included `job-joseph.com` and `localhost:5173`. The Lovable preview URL was a legitimate origin that simply wasn't in the list. The browser was blocking the response at the CORS preflight level, before the request even reached the backend logic.

The fix was adding `https://preview--job-joseph.lovable.app` to the allow_origins list.

The lesson: CORS failures and timeout failures look identical from the frontend — the request "doesn't work" and you get no useful error in the response body. When a new deployment environment silently fails, check CORS before debugging cold starts, network issues, or backend bugs. The browser's Network tab shows the difference (a CORS error has no response body and usually a specific console warning), but it's easy to miss if you're looking at the wrong place. Any time you add a new frontend deployment target (preview URLs, staging, new domain), update CORS first — it's the most likely thing to break and the easiest to miss.

## A comma in TMDb means "every genre"

TMDb's `with_genres=27,10749` means horror AND romance; `27|10749` means horror OR romance. Hugin always joined with commas, so every extra genre Claude added made the pool smaller. Horror + romance rated 7.5+ was 2 films on 1 page — with a random page from 1–5, the user got nothing 80% of the time. Group mode was hit hardest, because "find the intersection" invites Claude to list several genres.

The fix was a ladder of searches, each looser than the last: every genre → any genre → lower rating bar. Results are topped up (deduped by id) until there are enough films, so the most faithful matches come first. The user's own filters are never relaxed — only Claude's guesses are.

The lesson: when an LLM's output becomes query parameters, check what the API does with *combinations* of them, not just single values. One genre worked fine in testing; three genres quietly collapsed the pool.

## Sorting by rating needs a real vote floor

With `sort_by=vote_average.desc` and `vote_count.gte=50`, TMDb's top comedies were films like "The Way to the Heart" (143 votes, 9.9). A film rated 9.9 by 143 people isn't better than Parasite at 8.5 from 21,000 — it just has a small, enthusiastic audience. Raising the floor to 300 votes put Parasite, Pulp Fiction and Forrest Gump at the top, and pools stayed large (1,000+ comedies). Gem mode keeps its own band (150–3,000 votes) so hidden gems are still possible without the noise.

The lesson: an average is only meaningful with enough samples behind it. Any "sort by rating" needs a minimum count, and the right minimum is found by looking at what actually comes back, not by picking a round number.

## Error responses need CORS headers too

The global `@app.exception_handler(Exception)` returned a friendly 500, but in Starlette that handler runs in the outermost layer — outside CORSMiddleware. So crash responses had no `Access-Control-Allow-Origin` header, and the browser blocked them. The frontend saw a "CORS error", never the message. That's probably part of why the "CORS cold start false positive" earlier felt so confusing: real crashes looked like CORS failures too.

The fix was a small middleware registered *before* CORSMiddleware (Starlette wraps later middleware around earlier ones, so it runs inside CORS). It catches the exception, logs the traceback, and returns the friendly 500, which then gets CORS headers on the way out. The old isinstance re-raise for HTTPException / validation / rate-limit errors turned out to be dead code — those exceptions have their own handlers that run first.

The lesson: check what headers your *error* responses carry, not just your successful ones. And a handler that swallows exceptions must log them, or production failures disappear without a trace.

## Never trust LLM output, even as JSON

`_parse_response()` checked the JSON shape but not the values. `"gem_mode": "false"` — a string — is truthy in Python, so it switched gem mode on. Any `sort_by` went straight to TMDb. Extra keys were echoed back in `params_used`, so a crafted mood could make the API return whatever text it liked.

Two layers fixed it. Structured outputs (`output_config.format` with a JSON schema) make the API constrain Claude's reply to the right shape. Then `_clean_params()` rebuilds the params from scratch: only known keys, genres from the known list, vote_floor clamped, sort_by from an allow-list, and gem_mode only if it is literally `true`.

The lesson: an LLM's reply is user input with extra steps. A schema guarantees the shape; your own validation guarantees the meaning. Build the output from what you allow, rather than passing through what you were given.

## A truncated hash can still give away the secret

`/password-hash` returned the first 16 hex characters of `SHA-256(seed + date)`, on the assumption that a hash reveals nothing. But the password is chosen from the first 4 bytes of that same hash — which are the first 8 hex characters of the prefix. Anyone could take the public prefix, do `int(prefix[:8], 16) % 29`, and look up the word in the public word list. Confirmed against the live server.

The lesson: hashing isn't hiding if you publish the exact bits your secret is derived from. When something is "safe to expose", trace exactly which bits it shares with the secret. The real fix (audit batch 2) is to check the password on the server so nothing derived from the seed needs to leave it.

> **Update (November 2026):** done. The backend now checks the word (`/verify-password` and the `X-Hugin-Password` header), `/password-hash` is gone, and the seed was rotated to a random value that exists only on the Pi.

## When TCP connects but TLS doesn't, suspect the hostname

Right after deploying audit batch 1, a live request returned zero films. The new logging showed why: all three TMDb searches failed with `ConnectError`. Before the batch, the same failure would have been an unlogged 500. Testing from the Pi with curl, the TCP connection to TMDb succeeded every time, but the TLS handshake failed 6 times in 10 (curl exit 35), on IPv4 and IPv6 alike. TMDb's alternate API domain, `api.tmdb.org`, served the same API 25/25 times from the same machine at the same moment.

Same CDN, same API, different hostname — so something on the network path is interfering based on the name in the TLS handshake (SNI). Some Indian ISPs are known to do this to themoviedb.org. It never showed on Render, because Render's servers were in Oregon, on a different network.

The fix was one line: `TMDB_BASE = "https://api.tmdb.org/3"`.

The lesson: when a service moves to a new network, re-test every outbound dependency from that network. And "connection reset" errors that come and go aren't always the remote server's fault. If TCP connects but TLS fails, compare a second hostname for the same service before blaming load or rate limits. It also explains some of the earlier "connection storm" resets: they may have been this all along.

## Measure before changing a prompt

The plan for using Claude's keywords included rewording the prompt to ask for "concrete" TMDb tags ("heist", "time travel") instead of tone words ("witty", "feel good"). Before shipping it, I ran 10 real moods through both prompts and checked every keyword against TMDb's `/search/keyword`. The original prompt won: 23 of 33 keywords were real TMDb tags, versus 17 of 23 for the reworded one. TMDb turns out to have plenty of tone tags — "feel good", "heartwarming", "brutal", "slow burn", "mind-bending" — and the rewording threw those away.

The same 30-call run (a few cents) settled the model question. Haiku 5.5 at low effort gave the same picks at the same speed as Haiku 4.5, for about a seventh of the cost, and refused none of the dark moods (revenge, serial killer).

The lesson: a prompt change that sounds obviously better can be worse. When an LLM's output feeds an API, measure against that API, on a handful of real inputs, before deciding.

## "Try again" needs one ranking, not pages of several searches

After keywords went in, "try again" started repeating films by the third press. Three causes stacked up:
1. Claude re-interpreted the mood on every press, with slightly different keywords, so page 2 belonged to a different search than page 1.
2. A "page" was a TMDb page of one step. Small precise steps (8 heist films) ran out and wrapped round to the same films.
3. The search steps overlap: every heist crime-comedy is also in the plain crime-comedy search, so walking one step after another met the same films twice.

The fix treats each search as one ranked list where every film counts once: precise matches first, then whatever each broader step adds. Page N is simply the N-th batch from that list. The mood's interpretation is cached for an hour, so every press walks the same list. Gem-quality films are held out of the standard list entirely and only appear in the gem slot. After that, five presses on several moods — including a Korean-only filter with a small pool — showed no repeats.

The lesson: pagination over a cascade of fallback queries isn't pagination over any one query. Define the ranking the user is actually paging through, then page that.

## Hidden gems need a credibility floor

With a 150-vote floor, the "hidden gem horror" search returned films TMDb rated 8.3 that IMDb rated 4.7–5.8, plus Michael Jackson's *Thriller* music video. A few hundred votes from enthusiastic fans can push an average very high. Raising the floor to 300, requiring 60+ minutes, and requiring a year since release turned the same search into Come and See, The Cabinet of Dr. Caligari and What Ever Happened to Baby Jane?.

The lesson: "high rating, few votes" is exactly where averages are least reliable. A hidden-gem filter needs a minimum sample size, not just a maximum.

## An easter egg is safe when finding it gets you nothing

The raven (3 taps emails Job the word) lives in a public page's JavaScript, so anyone can read how to trigger it. That's fine because the secret was never the gesture: `/send-word` takes no input, and the n8n workflow has Job's address fixed. The worst a stranger can do is send Job an email, and the rate limits cap that at 10 a day. If the call had taken an email address, or returned the word, hiding the gesture would have been the only protection, and that's no protection.

The lesson: when something has to be reachable from a public page, design it so that discovering it is harmless, rather than relying on it staying hidden.

## "Respond immediately" webhooks hide failures

The first live test logged "Today's word emailed to Job" but no email arrived. The n8n webhook was set to answer as soon as it received the request, so it said 200 before the Gmail step ran, and Gmail then failed: the saved Google login had expired ("refresh token is invalid, expired, revoked"). Switching the webhook to answer after the last node means a Gmail failure comes back as a 500, which Hugin logs and which frees the 2-minute wait so Job can tap again.

The fix for the login itself was to reconnect it in n8n and move the Google Cloud app from "Testing" to "In production". The same login sends Sentinel's alerts, so those had been failing silently too.

The lesson: if the caller's log line claims an outcome ("emailed"), the webhook has to wait for that outcome. And Google logins saved in n8n can expire. A Google Cloud app left in "Testing" mode issues logins that last 7 days.
