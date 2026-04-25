from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import asyncio

from mood import interpret_mood, interpret_group_mood
from tmdb import discover_movies, get_movie_detail
from omdb import enrich_with_omdb
from password import get_today_hash

app = FastAPI(title="Hugin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock this down once frontend URL is known
    allow_methods=["*"],
    allow_headers=["*"],
)

class MoodRequest(BaseModel):
    mood: str

class GroupMoodRequest(BaseModel):
    moods: List[str]

@app.get("/")
def root():
    return {"status": "Hugin is watching"}

@app.get("/password-hash")
def password_hash():
    # Returns today's hash only — never the seed or plain password
    return {"hash": get_today_hash()}

@app.post("/recommend")
async def recommend(req: MoodRequest):
    params = await interpret_mood(req.mood)
    movies = await discover_movies(params)
    enriched = await asyncio.gather(*[enrich(m) for m in movies])
    return {"results": enriched, "params_used": params}

@app.post("/recommend-group")
async def recommend_group(req: GroupMoodRequest):
    params = await interpret_group_mood(req.moods)
    movies = await discover_movies(params, limit=3)
    enriched = await asyncio.gather(*[enrich(m) for m in movies])
    return {"results": enriched, "params_used": params}

async def enrich(tmdb_movie: dict) -> dict:
    detail = await get_movie_detail(tmdb_movie["id"])
    omdb_data = await enrich_with_omdb(detail.get("imdb_id"))
    return {**tmdb_movie, **detail, **omdb_data}