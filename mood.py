import os
import json
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are Hugin, a movie mood interpreter.
Given a mood description, return ONLY a valid JSON object with:
- genres: array of TMDb genre IDs (integers)
- keywords: array of TMDb keyword strings (2-4 words max each)
- vote_floor: float between 5.5 and 8.0
- gem_mode: boolean (true if mood suggests niche/unusual/underrated)
- sort_by: one of "vote_average.desc" or "popularity.desc"

TMDb genre IDs reference:
28=Action, 12=Adventure, 16=Animation, 35=Comedy, 80=Crime,
99=Documentary, 18=Drama, 10751=Family, 14=Fantasy, 36=History,
27=Horror, 10402=Music, 9648=Mystery, 10749=Romance,
878=Science Fiction, 53=Thriller, 10770=TV Movie, 37=Western

Return only JSON. No preamble, no explanation."""

async def interpret_mood(mood: str) -> dict:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Mood: {mood}"}]
    )
    return json.loads(response.content[0].text)

async def interpret_group_mood(moods: list[str]) -> dict:
    combined = "\n".join([f"Person {i+1}: {m}" for i, m in enumerate(moods)])
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Find the intersection for this group:\n{combined}"}]
    )
    return json.loads(response.content[0].text)