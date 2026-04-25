# Hugin — Project Brief for Claude Code

## What this is
Hugin is a personal movie recommendation tool built for Job Joseph
(job-joseph.com). It solves decision fatigue when choosing what to watch —
solo or with a group — by interpreting a free-text mood description and
returning curated movie picks using TMDb + OMDb data, with Claude as the
interpretation layer.

Named after Odin's raven — the all-seeing messenger who flies the world
and reports back. Trusted, perceptive, personal.

## How it fits into job-joseph.com
- Lives at job-joseph.com/projects/hugin (card in the projects page)
- The backend (this repo) is standalone — separate from the main site repo
- The frontend will be built separately in Lovable and linked from the
  projects page, same pattern as the Word Translator project
- Future: may redirect to hugin.job-joseph.com via DNS CNAME

## Architecture decisions
- FastAPI backend (Python) — matches the Word Translator pattern Job already knows
- No database, no auth service, no Vercel — intentionally minimal infra
- Password gate is deterministic: SHA-256(HUGIN_SEED + today's UTC date)
  → index into WORD_LIST → today's word. Rotates at UTC midnight.
  The seed lives only in .env (gitignored) and Job's memory/password manager.
  The API never exposes the plain password — only a hash for frontend comparison.
- Claude API is the mood interpreter — free-text in, TMDb params out (JSON)
- TMDb is the primary data source (Discover endpoint)
- OMDb is the enrichment layer (RT score, IMDb rating) via shared imdb_id
- All external calls are async (httpx + asyncio.gather) for speed

## Repo structure
hugin/
├── main.py              ← FastAPI app, routes, CORS
├── mood.py              ← Claude API calls (interpret_mood, interpret_group_mood)
├── tmdb.py              ← TMDb Discover + movie detail
├── omdb.py              ← OMDb enrichment by imdb_id
├── password.py          ← Deterministic daily password logic
├── requirements.txt
├── .env                 ← Gitignored. Contains all API keys + HUGIN_SEED
├── .gitignore
├── CLAUDE.md            ← This file
└── README.md

## API endpoints
- GET  /                   → health check
- GET  /password-hash      → returns today's SHA-256 hash prefix (not the word)
- POST /recommend          → {mood: str} → 5 enriched movie objects
- POST /recommend-group    → {moods: str[]} → 3 enriched movie objects

## Environment variables (.env)
TMDB_API_KEY=
OMDB_API_KEY=
ANTHROPIC_API_KEY=
HUGIN_SEED=          ← secret phrase, never commit this

## Movie result object shape
Each result returned by /recommend or /recommend-group should contain:
- id, title, overview, poster_path, release_date, vote_average (from TMDb)
- imdb_id, runtime, tagline, genres[] (from TMDb detail)
- imdb_rating, rt_score, rated (from OMDb)
- gem_mode flag if the result came from the hidden gem filter

## Key logic — mood interpreter (mood.py)
Claude receives a system prompt defining it as Hugin, a movie mood
interpreter. It returns ONLY a JSON object with:
- genres: TMDb genre IDs (integers)
- keywords: keyword strings
- vote_floor: float (5.5–8.0)
- gem_mode: boolean (true = high vote_average, low vote_count filter)
- sort_by: "vote_average.desc" or "popularity.desc"

Group mode sends all moods together and asks Claude to find the
intersection that satisfies everyone.

## Key logic — hidden gem filter (tmdb.py)
When gem_mode is true:
- vote_count.lte = 3000
- vote_average.gte = 7.5
- sort_by = vote_average.desc
This surfaces high-quality, low-popularity films the algorithms bury.

## Key logic — password (password.py)
- get_today_password() → plain word, for Job's local use only, NEVER via API
- get_today_hash() → short hash prefix, safe to expose via /password-hash
- Frontend independently derives the word using the same seed (stored in
  frontend env) and compares against user input
- WORD_LIST has 30 evocative single words (ember, dusk, reel, etc.)

## Pain points this solves
1. Can't decide what to watch — decision fatigue from too many options
2. Recommendations ignore mood — genre filters can't capture nuance
3. No group watch solution — no tool resolves multi-person preferences
4. Hidden gems stay hidden — algorithms push mainstream, bury quality

## What this is NOT
- Not a product or SaaS — it's a personal tool Job shares selectively
- Not a new destination to visit — it lives on Job's existing site
- Not a mood-tile grid UI — free text is the primary input (tiles are
  just shortcuts)
- Not trying to replace Netflix — just cuts through it

## Owner context
- Job Joseph — RevOps professional, builder mindset, XLRI alumnus
- Windows laptop (FFmpeg, ImageMagick installed), Mac at work
- Comfortable with Python, Google Apps Script, n8n, Claude Code
- Learning AI PM skills by building, not shortcuts
- Other projects: Word Translator (same FastAPI pattern), Freekick Shootout
  (in main site repo), Voyager (meeting intelligence), call analysis pipeline

## Frontend (not in this repo)
- Will be built in Lovable separately
- React app, dark cinematic aesthetic
- Primary input: large free-text mood box, quick-fill chips below
- Mobile-first — couch use case, one thumb, under 30 seconds start to pick
- Password gate screen before anything else
- Solo mode: 5 cards (4 standard + 1 gem)
- Group mode: up to 3 people enter moods → 3 shared picks
- Skeleton loading states, not spinners
- "Try again" re-queries with page+1

## Build sequence
1. ✅ Repo created, files scaffolded
2. [ ] Test /recommend locally with curl
3. [ ] Test /recommend-group locally
4. [ ] Confirm password logic works across UTC midnight
5. [ ] Deploy backend (Railway or Render — same as Word Translator)
6. [ ] Build frontend in Lovable, point at live API URL
7. [ ] Add project card to job-joseph.com/projects
8. [ ] Optional: custom domain hugin.job-joseph.com