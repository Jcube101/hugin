from dotenv import load_dotenv
load_dotenv()

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
    enriched = await enrich_all(movies)
    return {"results": enriched, "params_used": params}

@app.post("/recommend-group")
async def recommend_group(req: GroupMoodRequest):
    params = await interpret_group_mood(req.moods)
    movies = await discover_movies(params, limit=3)
    enriched = await enrich_all(movies)
    return {"results": enriched, "params_used": params}

async def enrich_all(movies: list) -> list:
    details = []
    for m in movies:
        details.append(await get_movie_detail(m["id"]))
    omdb_results = await asyncio.gather(
        *[enrich_with_omdb(d.get("imdb_id")) for d in details]
    )
    return [{**m, **d, **o} for m, d, o in zip(movies, details, omdb_results)]