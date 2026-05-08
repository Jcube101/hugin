# Contributing to Hugin

Hugin is a personal project, but PRs are welcome if you find a bug or have an improvement in mind.

## Local setup

See [README.md](README.md) for full instructions. The short version:

```bash
git clone https://github.com/yourusername/hugin.git
cd hugin
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

You need a `.env` file with four keys:

| Variable | Source |
|----------|--------|
| `TMDB_API_KEY` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |
| `OMDB_API_KEY` | [omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) |
| `HUGIN_SEED` | Any secret string (used for daily password generation) |

## Running the server

```bash
uvicorn main:app --reload
```

## Getting today's password

```bash
python password.py
```

This calls `load_dotenv()` before reading `HUGIN_SEED`. Do **not** use `python -c "from password import get_today_password; ..."` — that skips `load_dotenv()` and silently produces the wrong password (falls back to `"default-seed"`).

## Tests

Run the full test suite (79 tests, all external APIs mocked):

```bash
pytest tests/ -v
```

No API keys are needed for tests. All Claude, TMDb, and OMDb calls are mocked.

To test manually with curl:

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"mood": "something funny but not dumb"}'
```

Note: the server has rate limits (10/min for `/recommend`, 5/min for `/recommend-group`).

## Frontend

The frontend is a page inside the main job-joseph.com React app (`src/pages/Hugin.tsx`), not part of this codebase. Backend changes should not assume any specific frontend behavior beyond the API contract documented in [SPEC.md](SPEC.md).
