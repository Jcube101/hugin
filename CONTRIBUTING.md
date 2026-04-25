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

## Tests

No test suite yet. For now, test manually with curl:

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"mood": "something funny but not dumb"}'
```

## Frontend

The frontend lives in a separate Lovable repo and is not part of this codebase. Backend changes should not assume any specific frontend behavior beyond the API contract documented in [SPEC.md](SPEC.md).
