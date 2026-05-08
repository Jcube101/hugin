from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field
from typing import List, Annotated
import asyncio

from mood import interpret_mood, interpret_group_mood
from tmdb import discover_movies, get_movie_detail
from omdb import enrich_with_omdb
from password import get_today_hash

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Hugin API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://job-joseph.com",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

class MoodRequest(BaseModel):
    mood: str = Field(min_length=1, max_length=500)
    original_language: str | None = Field(default=None, max_length=10)
    exclude_animation: bool = False
    min_year: int | None = None

class GroupMoodRequest(BaseModel):
    moods: List[Annotated[str, Field(min_length=1, max_length=500)]] = Field(min_length=1, max_length=4)
    original_language: str | None = Field(default=None, max_length=10)
    exclude_animation: bool = False
    min_year: int | None = None

@app.get("/")
def root():
    return {"status": "Hugin is watching"}

@app.get("/password-hash")
def password_hash():
    # Returns today's hash only — never the seed or plain password
    return {"hash": get_today_hash()}

@app.post("/recommend")
@limiter.limit("10/minute")
async def recommend(request: Request, req: MoodRequest):
    params = await interpret_mood(req.mood)
    filters = {
        "original_language": req.original_language,
        "exclude_animation": req.exclude_animation,
        "min_year": req.min_year,
    }
    movies = await discover_movies(params, filters=filters)
    enriched = await enrich_all(movies)
    return {"results": enriched, "params_used": params}

@app.post("/recommend-group")
@limiter.limit("5/minute")
async def recommend_group(request: Request, req: GroupMoodRequest):
    params = await interpret_group_mood(req.moods)
    filters = {
        "original_language": req.original_language,
        "exclude_animation": req.exclude_animation,
        "min_year": req.min_year,
    }
    movies = await discover_movies(params, limit=3, filters=filters)
    enriched = await enrich_all(movies)
    return {"results": enriched, "params_used": params}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (HTTPException, RequestValidationError, RateLimitExceeded)):
        raise exc
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong. Please try again."}
    )

async def enrich_all(movies: list) -> list:
    details = []
    for m in movies:
        details.append(await get_movie_detail(m["id"]))
    omdb_results = await asyncio.gather(
        *[enrich_with_omdb(d.get("imdb_id")) for d in details]
    )
    return [{**m, **d, **o} for m, d, o in zip(movies, details, omdb_results)]