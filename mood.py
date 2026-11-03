import copy
import json
import logging
import math
import os
import re

from anthropic import AsyncAnthropic

from cache import MISSING, TTLCache

log = logging.getLogger("hugin.mood")

# Haiku 5.5 at low effort: in a 10-mood comparison (Nov 2026) it matched Haiku 4.5's
# picks and speed (~1.8s) at ~1/7 the cost. Its thinking counts toward max_tokens,
# hence 1024. It can decline a request (stop_reason "refusal") and has no
# server-side fallback, so a declined mood is retried once on Haiku 4.5.
MODEL = "claude-haiku-5-5"
FALLBACK_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

# The same mood text gets the same interpretation for an hour, so "try again"
# pages through one consistent search (page + 1) and skips a Claude call.
_cache = TTLCache(ttl=60 * 60, maxsize=500)


def cache_size() -> int:
    return len(_cache)


def clear_cache():
    _cache.clear()

# The SDK default is a 10-minute timeout with 2 retries; a mood lookup should never take that long
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=15.0, max_retries=1)

GENRE_NAME_TO_ID = {
    "action": 28, "adventure": 12, "animation": 16, "comedy": 35,
    "crime": 80, "documentary": 99, "drama": 18, "family": 10751,
    "fantasy": 14, "history": 36, "horror": 27, "music": 10402,
    "mystery": 9648, "romance": 10749, "science fiction": 878,
    "thriller": 53, "tv movie": 10770, "western": 37,
}
VALID_GENRE_IDS = sorted(set(GENRE_NAME_TO_ID.values()))
SORT_OPTIONS = ("vote_average.desc", "popularity.desc")
DEFAULT_SORT = "vote_average.desc"
DEFAULT_VOTE_FLOOR = 6.5
VOTE_FLOOR_MIN, VOTE_FLOOR_MAX = 5.5, 8.0
MAX_KEYWORDS = 5

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

# Structured outputs: the API constrains Claude's reply to this schema
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "genres": {"type": "array", "items": {"type": "integer", "enum": VALID_GENRE_IDS}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "vote_floor": {"type": "number"},
        "gem_mode": {"type": "boolean"},
        "sort_by": {"type": "string", "enum": list(SORT_OPTIONS)},
    },
    "required": ["genres", "keywords", "vote_floor", "gem_mode", "sort_by"],
    "additionalProperties": False,
}


def _clean_params(raw) -> dict:
    """Keep only the fields Hugin uses, with types and ranges enforced.

    The reply is model output shaped by user text, so nothing in it is trusted:
    unknown keys are dropped and every value is checked before it reaches TMDb.
    """
    if not isinstance(raw, dict):
        raise ValueError("Claude's reply was not a JSON object")

    genres = []
    for g in raw.get("genres") or []:
        if isinstance(g, str):
            g = GENRE_NAME_TO_ID.get(g.strip().lower())
        if type(g) is int and g in VALID_GENRE_IDS and g not in genres:
            genres.append(g)

    keywords = [
        k.strip()[:50] for k in raw.get("keywords") or []
        if isinstance(k, str) and k.strip()
    ][:MAX_KEYWORDS]

    try:
        floor = float(raw.get("vote_floor", DEFAULT_VOTE_FLOOR))
    except (TypeError, ValueError):
        floor = DEFAULT_VOTE_FLOOR
    if not math.isfinite(floor):
        floor = DEFAULT_VOTE_FLOOR
    floor = min(max(floor, VOTE_FLOOR_MIN), VOTE_FLOOR_MAX)

    sort_by = raw.get("sort_by")
    if isinstance(sort_by, str) and "." not in sort_by:
        sort_by += ".desc"
    if sort_by not in SORT_OPTIONS:
        sort_by = DEFAULT_SORT

    return {
        "genres": genres,
        "keywords": keywords,
        "vote_floor": floor,
        "gem_mode": raw.get("gem_mode") is True,  # the string "false" must not count as true
        "sort_by": sort_by,
    }


def _parse_response(text: str) -> dict:
    """Turn Claude's reply into safe TMDb params.

    Structured outputs should guarantee clean JSON. This is the safety net for
    a reply wrapped in code fences or surrounded by a sentence.
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    elif not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    return _clean_params(json.loads(text))


async def _call(model: str, user_content: str, effort: str | None):
    output_config = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    if effort:
        output_config["effort"] = effort  # Haiku 4.5 rejects the effort setting
    return await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_config=output_config,
    )


async def _ask_claude(user_content: str) -> dict:
    key = " ".join(user_content.lower().split())
    cached = _cache.get(key)
    if cached is not MISSING:
        return copy.deepcopy(cached)  # callers may modify params (e.g. gem_mode)
    params = await _interpret(user_content)
    _cache.set(key, copy.deepcopy(params))
    return params


async def _interpret(user_content: str) -> dict:
    response = await _call(MODEL, user_content, effort="low")
    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        log.warning("Mood declined by %s (%s); retrying on %s", MODEL, category, FALLBACK_MODEL)
        response = await _call(FALLBACK_MODEL, user_content, effort=None)
    # Read the text block by type: replies can start with a thinking block
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _parse_response(text)


async def interpret_mood(mood: str) -> dict:
    return await _ask_claude(f"Mood: {mood}")


async def interpret_group_mood(moods: list[str]) -> dict:
    combined = "\n".join(f"Person {i+1}: {m}" for i, m in enumerate(moods))
    return await _ask_claude(f"Find the intersection for this group:\n{combined}")
