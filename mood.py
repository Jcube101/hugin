import os
import json
import re
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

GENRE_NAME_TO_ID = {
    "action": 28, "adventure": 12, "animation": 16, "comedy": 35,
    "crime": 80, "documentary": 99, "drama": 18, "family": 10751,
    "fantasy": 14, "history": 36, "horror": 27, "music": 10402,
    "mystery": 9648, "romance": 10749, "science fiction": 878,
    "thriller": 53, "tv movie": 10770, "western": 37,
}

SYSTEM_PROMPT = """You are Hugin, a movie mood interpreter.
Given a mood description, return ONLY a valid JSON object with:
- genres: array of TMDb genre IDs as integers (e.g. [35, 18], NOT strings)
- keywords: array of TMDb keyword strings (2-4 words max each)
- vote_floor: float between 5.5 and 8.0
- gem_mode: boolean — set to true ONLY when the user explicitly asks for hidden, obscure, underrated, or unknown films. Do NOT set gem_mode for mood descriptions like 'mind bending', 'psychological', 'tense', or 'dark' — these are moods, not requests for obscure films.
- sort_by: exactly one of "vote_average.desc" or "popularity.desc"

TMDb genre IDs reference:
28=Action, 12=Adventure, 16=Animation, 35=Comedy, 80=Crime,
99=Documentary, 18=Drama, 10751=Family, 14=Fantasy, 36=History,
27=Horror, 10402=Music, 9648=Mystery, 10749=Romance,
878=Science Fiction, 53=Thriller, 10770=TV Movie, 37=Western

Return ONLY the raw JSON object. No markdown, no code fences, no explanation."""


def _parse_response(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    params = json.loads(text)
    params["genres"] = [
        GENRE_NAME_TO_ID.get(g.lower(), g) if isinstance(g, str) else g
        for g in params.get("genres", [])
    ]
    params["genres"] = [g for g in params["genres"] if isinstance(g, int)]
    if params.get("sort_by") and ".desc" not in params["sort_by"] and ".asc" not in params["sort_by"]:
        params["sort_by"] = params["sort_by"] + ".desc"
    return params


async def interpret_mood(mood: str) -> dict:
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Mood: {mood}"}]
    )
    return _parse_response(response.content[0].text)

async def interpret_group_mood(moods: list[str]) -> dict:
    combined = "\n".join([f"Person {i+1}: {m}" for i, m in enumerate(moods)])
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Find the intersection for this group:\n{combined}"}]
    )
    return _parse_response(response.content[0].text)