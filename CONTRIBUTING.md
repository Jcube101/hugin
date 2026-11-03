# Contributing to Hugin

Hugin is a personal project, but PRs are welcome if you find a bug or have an improvement in mind.

## Local setup

See [README.md](README.md) for full instructions. The short version:

```bash
git clone https://github.com/Jcube101/hugin.git
cd hugin
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest
```

## Environment variables

You need a `.env` file with four keys (plus optional `HUGIN_DOCS=1` to enable `/docs` locally):

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

This calls `load_dotenv()` before reading `HUGIN_SEED`. Do **not** use `python -c "from password import get_today_password; ..."` — that skips `load_dotenv()`, so it fails with "HUGIN_SEED is not set" (it used to silently print a wrong word).

## Tests

Run the full test suite (189 tests, all external APIs mocked):

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

## Deploying

The live service runs from the repo folder on the Pi (`hugin.service`), so work on a branch or git worktree. To deploy: merge to `main`, then `sudo systemctl restart hugin` and check `journalctl -u hugin.service -f`.

Dependencies are pinned in `requirements.txt`. To upgrade one, change the pin, run the tests, then restart the service.

## Frontend

The frontend is a page inside the main job-joseph.com React app (`src/pages/Hugin.tsx`), not part of this codebase. Backend changes should not assume any specific frontend behavior beyond the API contract documented in [SPEC.md](SPEC.md).
