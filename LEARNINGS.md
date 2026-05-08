# Hugin — Learning Log

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

## Page state sync: random isn't "try again"

The "try again" button re-queried the API, but `discover_movies()` picked a random TMDb page each time (`random.randint(1, 3)`). This meant "try again" sometimes returned the same page, and the user saw identical results — or it jumped to a page they'd already seen. There was no way for the frontend to say "I've seen page 2, give me page 3."

The fix was adding an optional `page` parameter to both endpoints. When the frontend sends `page`, the backend uses it directly instead of rolling the dice. The frontend can now increment the page on each "try again" tap, guaranteeing fresh results every time. When `page` is omitted (first load), the backend still randomizes — but now across a wider range (1–5 instead of 1–3) for more variety on the initial query.

The lesson: randomization is fine for a first impression, but any "give me something different" interaction needs deterministic pagination the client controls. If the client can't tell the server what it's already seen, the server can't avoid repeating itself.

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

## CORS cold start false positive

When testing from the Lovable preview deployment (`preview--job-joseph.lovable.app`), API requests silently failed. The browser showed a CORS error. Initial instinct was that Render's free tier had cold-started and the request timed out — the classic Render spin-down problem where the first request after idle takes 30+ seconds.

But the health check endpoint responded fine from the browser's address bar. The issue was that the CORS `allow_origins` list only included `job-joseph.com` and `localhost:5173`. The Lovable preview URL was a legitimate origin that simply wasn't in the list. The browser was blocking the response at the CORS preflight level, before the request even reached the backend logic.

The fix was adding `https://preview--job-joseph.lovable.app` to the allow_origins list.

The lesson: CORS failures and timeout failures look identical from the frontend — the request "doesn't work" and you get no useful error in the response body. When a new deployment environment silently fails, check CORS before debugging cold starts, network issues, or backend bugs. The browser's Network tab shows the difference (a CORS error has no response body and usually a specific console warning), but it's easy to miss if you're looking at the wrong place. Any time you add a new frontend deployment target (preview URLs, staging, new domain), update CORS first — it's the most likely thing to break and the easiest to miss.
