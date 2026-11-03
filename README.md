# Hugin

Hugin is a mood-based movie recommendation API. You describe how you feel in free text, and it returns curated movie picks — powered by Claude as the mood interpreter, TMDb for discovery, and OMDb for enrichment (Rotten Tomatoes scores, IMDb ratings). Named after Odin's all-seeing raven. Built as a personal tool for [job-joseph.com](https://job-joseph.com).

## Tech stack

- **Python 3.11+** / **FastAPI** — async API server
- **Claude API** (Anthropic) — interprets free-text mood into TMDb query parameters, using structured outputs
- **TMDb API** — movie discovery and detail
- **OMDb API** — Rotten Tomatoes scores, IMDb ratings, content ratings
- **httpx** — async HTTP client with connection pooling
- **slowapi** — rate limiting (10/min solo, 5/min group per IP)
- **pytest** / **pytest-asyncio** — 183 tests, all external APIs mocked

## Live deployment

The backend runs on a Raspberry Pi as the systemd service `hugin.service`, exposed through a Cloudflare tunnel:

- **URL:** https://hugin.job-joseph.com
- **Health check:** `curl https://hugin.job-joseph.com/` → `{"status": "Hugin is watching"}`
- **Logs:** `journalctl -u hugin.service -f`
- **Deploy:** the repo folder on the Pi is the live code. Merge to `main`, then `sudo systemctl restart hugin`.
- **Frontend:** lives at [job-joseph.com/projects/hugin](https://job-joseph.com/projects/hugin) (built as a page in the main site repo)

The old Render deployment (`hugin-5i4y.onrender.com`) is suspended; `render.yaml` is kept for reference.

## Local setup

```bash
git clone https://github.com/Jcube101/hugin.git
cd hugin
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt   # runtime deps + pytest
```

Create a `.env` file in the project root:

```
TMDB_API_KEY=your_tmdb_api_key
OMDB_API_KEY=your_omdb_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
HUGIN_SEED=your_secret_seed_phrase
HUGIN_DOCS=1          # optional: enables /docs locally (off in production)
HUGIN_REQUIRE_PASSWORD=1   # recommendation calls need the X-Hugin-Password header (on in production)
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

To get today's password locally via alias anywhere on the pi:
```bash
hugin-password
```

This calls `load_dotenv()` before reading `HUGIN_SEED`. Do **not** use `python -c "from password import get_today_password; print(get_today_password())"` — that skips `load_dotenv()`, so it fails with "HUGIN_SEED is not set" (it used to silently print a wrong word).

## API endpoints

### GET / (and HEAD /)

Health check. `HEAD` is supported for uptime monitors.

```bash
curl http://127.0.0.1:8000/
```

```json
{"status": "Hugin is watching"}
```

### GET /health

Returns OMDb daily call count, limit, and date. Useful for monitoring cost protection.

```bash
curl http://127.0.0.1:8000/health
```

```json
{"status": "ok", "omdb": {"date": "2026-05-08", "calls": 42, "limit": 950}}
```

### POST /verify-password

Checks a typed password against today's word (rotates at UTC midnight; yesterday's word still works for the first hour). Case and surrounding spaces are ignored. Rate limited to 10/min per IP.

```bash
curl -X POST http://127.0.0.1:8000/verify-password \
  -H "Content-Type: application/json" \
  -d '{"password": "ember"}'
```

`200 {"ok": true}` or `401 {"error": "That's not today's word."}`.

Recommendation requests send the word in an `X-Hugin-Password` header. With `HUGIN_REQUIRE_PASSWORD=1` in `.env`, a missing or wrong header gets `401 {"error": "Enter today's word to continue."}`.

### POST /recommend

Solo mode. Send a mood description (1–500 chars), get up to 5 enriched movie picks.

Optional filters:

| Field | Type | Notes |
|-------|------|-------|
| `original_language` | 2-letter ISO 639-1 code | e.g. `"ko"`. `null`, `""` or `"any"` mean no filter |
| `exclude_animation` | boolean | default `false` |
| `min_year` | integer 0–2100 | `0` or `null` mean no filter |
| `page` | integer 0–10000 | for "try again" cycling. `0` or `null` pick a random page; pages past the end wrap round |

Invalid values return 422.

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

If a movie's detail or OMDb lookup fails, the movie is still returned without those fields.

### POST /recommend-group

Group mode. Send 1–4 moods (each 1–500 chars), get up to 3 shared picks. Same optional filters apply.

```bash
curl -X POST http://127.0.0.1:8000/recommend-group \
  -H "Content-Type: application/json" \
  -d '{"moods": ["something scary", "something romantic", "anything with good acting"]}'
```

Response shape is the same as `/recommend`, with 3 results instead of 5.

### Errors

- `422` — invalid input (Pydantic validation details in the body)
- `429` — rate limit exceeded
- `503` — `{"error": "Couldn't reach the movie database. Please try again in a moment."}` when TMDb can't be reached. An empty `results` list only ever means TMDb found no matches.
- `500` — `{"error": "Something went wrong. Please try again."}`. The traceback goes to the server log, never to the client. CORS headers are kept so the browser can read the message.

## Running Tests

```bash
source venv/bin/activate   # Windows: venv\Scripts\activate
pytest tests/ -v
```

All external API calls (Claude, TMDb, OMDb) are mocked — no API keys needed for tests.

## Frontend

The frontend is built as a page inside the main [job-joseph.com](https://job-joseph.com) React app — not a separate Lovable project. It lives at `src/pages/Hugin.tsx` in the main site repo and is accessible at [job-joseph.com/projects/hugin](https://job-joseph.com/projects/hugin). The frontend is not part of this repository.
