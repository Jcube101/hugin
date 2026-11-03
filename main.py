from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os
import re
from typing import Annotated, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from mood import interpret_mood, interpret_group_mood
from tmdb import TMDbUnavailable, discover_movies, get_movie_detail
from omdb import enrich_with_omdb, get_omdb_call_count
from password import get_today_hash, is_valid_password

# Fail fast: without a seed the password gate can't work
if not os.getenv("HUGIN_SEED"):
    raise RuntimeError("HUGIN_SEED is not set — add it to .env")

# --- Password gate -------------------------------------------------------------
# The frontend sends the typed word in this header on every recommendation call.
# Enforcement is off until the frontend sends it; then set HUGIN_REQUIRE_PASSWORD=1
# in .env and restart. That also retires /password-hash.
PASSWORD_HEADER = "X-Hugin-Password"
REQUIRE_PASSWORD = os.getenv("HUGIN_REQUIRE_PASSWORD") == "1"


class PasswordRequired(Exception):
    """The request needs today's word and didn't have it."""

# --- Logging -----------------------------------------------------------------
# Hugin's own loggers ("hugin.*") log at INFO. Everything else stays at WARNING,
# because httpx logs full request URLs at INFO and those contain API keys.
# Key-looking query params are also redacted from every log line as a backstop.
_SECRET_PARAM = re.compile(r"(api_?key=)[^&\s'\"]+", re.IGNORECASE)


class _RedactingFormatter(logging.Formatter):
    def format(self, record):
        return _SECRET_PARAM.sub(r"\1<redacted>", super().format(record))


_log_handler = logging.StreamHandler()
_log_handler.setFormatter(_RedactingFormatter("%(levelname)s: %(name)s: %(message)s"))
logging.basicConfig(level=logging.WARNING, handlers=[_log_handler])
logging.getLogger("hugin").setLevel(logging.INFO)
log = logging.getLogger("hugin.api")

# --- App ---------------------------------------------------------------------
# Interactive API docs are off in production. Set HUGIN_DOCS=1 to browse /docs locally.
_docs_enabled = os.getenv("HUGIN_DOCS") == "1"

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Hugin API",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(PasswordRequired)
async def password_required(request: Request, exc: PasswordRequired):
    return JSONResponse(
        status_code=401,
        content={"error": str(exc) or "Enter today's word to continue."},
    )


@app.exception_handler(TMDbUnavailable)
async def tmdb_unavailable(request: Request, exc: TMDbUnavailable):
    # Not a bug in Hugin, so no traceback: tmdb.py has already logged the cause
    log.warning("TMDb unreachable; returned 503 for %s", request.url.path)
    return JSONResponse(
        status_code=503,
        content={"error": "Couldn't reach the movie database. Please try again in a moment."},
    )


# Registered before CORSMiddleware so it runs *inside* it: crash responses then
# still carry CORS headers, and the browser shows the message instead of a
# misleading CORS error. Validation (422), rate-limit (429) and TMDb-down (503)
# errors have their own handlers and never reach this.
@app.middleware("http")
async def catch_unhandled_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Something went wrong. Please try again."},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://job-joseph.com",
        "https://preview--job-joseph.lovable.app",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request models -------------------------------------------------------------
class Filters(BaseModel):
    """Optional filters shared by both endpoints. They go straight to TMDb.

    Empty values (0, "", "any") mean "no filter", matching how the API has
    always treated falsy values.
    """
    original_language: str | None = Field(default=None, max_length=10)
    exclude_animation: bool = False
    min_year: int | None = Field(default=None, ge=0, le=2100)
    page: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("original_language")
    @classmethod
    def _language_code(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v in ("", "any"):
            return None
        if not re.fullmatch(r"[a-z]{2}", v):
            raise ValueError("must be a 2-letter ISO 639-1 code, e.g. 'ko'")
        return v

    def as_filters(self) -> dict:
        return {
            "original_language": self.original_language,
            "exclude_animation": self.exclude_animation,
            "min_year": self.min_year or None,
        }


class MoodRequest(Filters):
    mood: str = Field(min_length=1, max_length=500)


class GroupMoodRequest(Filters):
    moods: List[Annotated[str, Field(min_length=1, max_length=500)]] = Field(min_length=1, max_length=4)


class PasswordCheck(BaseModel):
    password: str = Field(min_length=1, max_length=100)


def _check_password(request: Request):
    # Called at the top of rate-limited endpoints (not as a dependency), so wrong
    # guesses count toward the rate limit and never reach Claude.
    if REQUIRE_PASSWORD and not is_valid_password(request.headers.get(PASSWORD_HEADER)):
        raise PasswordRequired()


# --- Routes ----------------------------------------------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "Hugin is watching"}


@app.get("/health")
def health():
    return {"status": "ok", "omdb": get_omdb_call_count()}


@app.post("/verify-password")
@limiter.limit("10/minute")
async def verify_password(request: Request, body: PasswordCheck):
    if not is_valid_password(body.password):
        raise PasswordRequired("That's not today's word.")
    return {"ok": True}


@app.get("/password-hash")
def password_hash():
    # Legacy: gives today's word away (see password.py). Retired once enforcement is on.
    if REQUIRE_PASSWORD:
        raise HTTPException(status_code=404)
    return {"hash": get_today_hash()}


@app.post("/recommend")
@limiter.limit("10/minute")
async def recommend(request: Request, req: MoodRequest):
    _check_password(request)
    params = await interpret_mood(req.mood)
    movies = await discover_movies(params, filters=req.as_filters(), page=req.page or None)
    return {"results": await enrich_all(movies), "params_used": params}


@app.post("/recommend-group")
@limiter.limit("5/minute")
async def recommend_group(request: Request, req: GroupMoodRequest):
    _check_password(request)
    params = await interpret_group_mood(req.moods)
    movies = await discover_movies(params, limit=3, filters=req.as_filters(), page=req.page or None)
    return {"results": await enrich_all(movies), "params_used": params}


async def enrich_all(movies: list) -> list:
    # TMDb details one at a time (reuses one TLS connection), then OMDb in parallel.
    # Both helpers return {} on failure, so a bad lookup only loses that movie's extras.
    details = []
    for m in movies:
        details.append(await get_movie_detail(m["id"]))
    omdb_results = await asyncio.gather(
        *[enrich_with_omdb(d.get("imdb_id")) for d in details]
    )
    return [{**m, **d, **o} for m, d, o in zip(movies, details, omdb_results)]
