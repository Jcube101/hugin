# Hugin

Hugin is a mood-based movie recommendation API. You describe how you feel in free text, and it returns curated movie picks — powered by Claude as the mood interpreter, TMDb for discovery, and OMDb for enrichment (Rotten Tomatoes scores, IMDb ratings). Named after Odin's all-seeing raven. Built as a personal tool for [job-joseph.com](https://job-joseph.com).

## Tech stack

- **Python 3.11+** / **FastAPI** — async API server
- **Claude API** (Anthropic) — interprets free-text mood into TMDb query parameters
- **TMDb API** — movie discovery and detail
- **OMDb API** — Rotten Tomatoes scores, IMDb ratings, content ratings
- **httpx** — async HTTP client with connection pooling
- **slowapi** — rate limiting (10/min solo, 5/min group per IP)
- **pytest** / **pytest-asyncio** — 74 tests, all external APIs mocked

## Live deployment

The backend is deployed on Render (free tier):

- **URL:** https://hugin-5i4y.onrender.com
- **Health check:** `curl https://hugin-5i4y.onrender.com/` → `{"status": "Hugin is watching"}`
- **Frontend:** lives at [job-joseph.com/projects/hugin](https://job-joseph.com/projects/hugin) (built as a page in the main site repo)

## Local setup

```bash
git clone https://github.com/yourusername/hugin.git
cd hugin
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
TMDB_API_KEY=your_tmdb_api_key
OMDB_API_KEY=your_omdb_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
HUGIN_SEED=your_secret_seed_phrase
```

Start the server:

```bash
uvicorn main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

To get today's password locally:

```bash
python password.py
```

This calls `load_dotenv()` before reading `HUGIN_SEED`. Do **not** use `python -c "from password import get_today_password; print(get_today_password())"` — that skips `load_dotenv()` and silently produces the wrong password.

## API endpoints

### GET /

Health check.

```bash
curl http://127.0.0.1:8000/
```

```json
{"status": "Hugin is watching"}
```

### GET /password-hash

Returns today's SHA-256 hash prefix (rotates daily at UTC midnight). The frontend uses this for its password gate.

```bash
curl http://127.0.0.1:8000/password-hash
```

```json
{"hash": "a3f1b9c2e7d04518"}
```

### POST /recommend

Solo mode. Send a mood description (1–500 chars), get 5 enriched movie picks. Optional filters: `original_language` (ISO 639-1 code), `exclude_animation` (boolean), `min_year` (integer).

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"mood": "something funny but not dumb"}'
```

With filters:

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"mood": "feel good", "original_language": "ko", "exclude_animation": true, "min_year": 2010}'
```

```json
{
  "results": [
    {
      "id": 914,
      "title": "The Great Dictator",
      "overview": "Dictator Adenoid Hynkel tries to expand his empire...",
      "poster_path": "/1QpO9wo7JWecZ4NiBuu625FiY1j.jpg",
      "release_date": "1940-10-15",
      "vote_average": 8.28,
      "vote_count": 3677,
      "genre_ids": [35, 10752],
      "backdrop_path": "/c8Pi8F1FzpNebtgXcSjC9nWCdSW.jpg",
      "popularity": 6.88,
      "imdb_id": "tt0032553",
      "runtime": 125,
      "tagline": "Once again - the whole world laughs!",
      "genres": ["Comedy", "War"],
      "imdb_rating": "8.4",
      "rt_score": "92%",
      "rated": "G"
    }
  ],
  "params_used": {
    "genres": [35],
    "keywords": ["smart comedy", "witty dialogue"],
    "vote_floor": 7.0,
    "gem_mode": false,
    "sort_by": "vote_average.desc"
  }
}
```

### POST /recommend-group

Group mode. Send 1–4 moods (each 1–500 chars), get 3 shared picks. Same optional filters apply.

```bash
curl -X POST http://127.0.0.1:8000/recommend-group \
  -H "Content-Type: application/json" \
  -d '{"moods": ["something scary", "something romantic", "anything with good acting"]}'
```

Response shape is the same as `/recommend`, with 3 results instead of 5.

## Running Tests

```bash
source .venv/Scripts/activate  # Windows
pytest tests/ -v
```

All external API calls (Claude, TMDb, OMDb) are mocked — no API keys needed for tests.

## Frontend

The frontend is built as a page inside the main [job-joseph.com](https://job-joseph.com) React app — not a separate Lovable project. It lives at `src/pages/Hugin.tsx` in the main site repo and is accessible at [job-joseph.com/projects/hugin](https://job-joseph.com/projects/hugin). The frontend is not part of this repository.
