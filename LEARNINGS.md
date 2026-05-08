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
