# Hugin

Hugin is a mood-based movie recommender. Describe how you feel in a sentence — or let everyone in the room describe theirs — and it comes back with a short list of films that fit, instead of an endless grid. Named after Odin's all-seeing raven. Built as a personal tool for [job-joseph.com](https://job-joseph.com).

**Try it:** [job-joseph.com/projects/hugin](https://job-joseph.com/projects/hugin) (password-gated; the word changes daily).

## How it works

1. **You describe a mood** — "a clever heist movie with great banter", or one line per person in group mode.
2. **Claude reads it** and turns it into a movie search: genres, keywords like "heist" or "slow burn", how well rated the films should be, and whether you want hidden gems.
3. **TMDb finds the films**, most precise matches first, and **OMDb adds** IMDb and Rotten Tomatoes ratings.
4. **You get 5 picks** — 4 strong matches and 1 hidden gem — or 3 shared picks for a group. "Try again" shows the next ones, without repeats.

How the pieces fit, the search rules and the full API are in [SPEC.md](SPEC.md).

## Tech stack

Python 3.11+ and FastAPI · Claude API (Haiku 5.5) · TMDb and OMDb · runs on a Raspberry Pi behind a Cloudflare tunnel · no database

## Running it locally

```bash
git clone https://github.com/Jcube101/hugin.git
cd hugin
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
```

Create a `.env` file in the project root:

```
TMDB_API_KEY=your_tmdb_api_key
OMDB_API_KEY=your_omdb_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
HUGIN_SEED=any_long_random_string   # e.g. python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Start the server — it runs at `http://127.0.0.1:8000`:

```bash
uvicorn main:app --reload
```

Ask for a recommendation:

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -H "X-Hugin-Password: $(python password.py)" \
  -d '{"mood": "something funny but not dumb"}'
```

Optional settings for `.env`, all filters, the response format and error codes are in the [API reference](SPEC.md#api-reference).

## Today's password

```bash
python password.py      # or, on the Pi: hugin-password
```

Away from a terminal, tap the raven on the Hugin page 3 times quickly: it flies off and emails you the word, with a link that opens Hugin unlocked ([how it works](SPEC.md#post-send-word)).

The word changes at UTC midnight (5:30 AM IST). Run it as a script: `python -c "from password import ..."` skips loading `.env` and fails with "HUGIN_SEED is not set".

## Tests

```bash
pytest tests/ -v
```

243 tests. Claude, TMDb and OMDb are all mocked, so no API keys are needed.

## Live deployment

The backend runs on a Raspberry Pi as the `hugin.service` systemd service at https://hugin.job-joseph.com. The repo folder on the Pi is the live code: merge to `main`, then `sudo systemctl restart hugin`, and watch `journalctl -u hugin.service -f`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

The old Render deployment is suspended; `render.yaml` is kept for reference.

## Docs

| File | What's in it |
|------|--------------|
| [SPEC.md](SPEC.md) | Architecture diagram, how mood becomes picks, hidden gems, paging, password gate, API reference |
| [ROADMAP.md](ROADMAP.md) | What's next, ideas, and everything done so far |
| [LEARNINGS.md](LEARNINGS.md) | Lessons from building and auditing it |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, tests and deploying |
| [CLAUDE.md](CLAUDE.md) | Project brief for Claude Code |

The frontend is a page inside the main job-joseph.com React app (`src/pages/Hugin.tsx`) and isn't part of this repository.
