# TeamGM API

FastAPI backend for the [TeamGM app](https://github.com/ryanJames29/TeamGM). It fetches NHL and MLB data on a schedule, serves it from a Redis cache, and generates AI game briefings, so the mobile app never calls the paid sports data provider directly.

> 🚧 **In development**, alongside the TeamGM app.

## How it works

- **Scheduled sync**: APScheduler jobs pull from [API-Sports](https://api-sports.io): standings every 60 minutes, live scores every 60 seconds, and a rolling window of recent and upcoming games.
- **Redis cache**: every read endpoint is served from Redis. The provider is only called by the background jobs, which keeps the app fast and the API quota predictable.
- **AI briefings**: OpenAI generates a structured JSON briefing for a user's favorite team (why the next game matters, team snapshot, concern level, recent form). The prompt only allows facts from the fetched data: no invented scores or standings.
- **Supabase**: stores users' favorite teams and saved briefings, plus optional standings history.

```
Scheduled jobs → API-Sports → Redis ← FastAPI endpoints ← TeamGM app
                                        ↓
                         OpenAI (briefings) · Supabase (user data)
```

## Tech stack

Python · FastAPI · Pydantic · Redis · APScheduler · httpx · OpenAI · Supabase · pytest · Docker (local Redis)

## API

All routes are under `/api/v1`. Interactive docs at `/docs`.

| Method | Route | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/hockey/nhl/league` | NHL league info and standings |
| GET | `/hockey/nhl/games` | NHL scoreboard |
| GET | `/hockey/nhl/games/{game_id}` | NHL game detail and box score |
| GET | `/hockey/nhl/sync-status` | Cache and job status |
| GET | `/baseball/mlb/league` | MLB league info and standings |
| GET | `/baseball/mlb/games` | MLB scoreboard |
| GET | `/baseball/mlb/games/{game_id}` | MLB game detail and box score |
| GET | `/baseball/mlb/sync-status` | Cache and job status |
| GET | `/insights/home` | Latest saved briefing |
| POST | `/insights/home/generate` | Generate a fresh briefing |

## Running locally

### First-time setup

```bash
cd TeamGM-LLM-API
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at minimum `API_SPORTS_KEY` in `.env` (get one at [dashboard.api-sports.io](https://dashboard.api-sports.io/)). The Redis URL and job intervals in `.env.example` work for local dev.

For AI briefings, also set `OPENAI_API_KEY`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY`.

### Every time you work

1. **Start Docker Desktop** and wait until it's running (Redis runs in Docker).
2. **Start Redis:**
   ```bash
   docker compose up -d
   docker compose ps   # redis should be "running"
   ```
3. **Start the API:**
   ```bash
   source .venv/bin/activate
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   Wait for `NHL jobs started (standings every 60m, scores every 60s)`. If you see `NHL jobs disabled — could not connect to Redis`, Redis isn't running; start it and restart uvicorn.
4. **Start the app:** see the [TeamGM app README](https://github.com/ryanJames29/TeamGM).

The scoreboard endpoints can return `503` for the first 30–60 seconds while the jobs fill the cache.

### Useful URLs

| What | URL |
|---|---|
| API docs | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/api/v1/health |
| NHL games | http://127.0.0.1:8000/api/v1/hockey/nhl/games |
| Job / cache status | http://127.0.0.1:8000/api/v1/hockey/nhl/sync-status |

## Troubleshooting

**App shows a JSON parse error or "Could not load NHL scores"**: Redis or the API isn't running, or the API started before Redis. Start Docker, run `docker compose up -d`, restart uvicorn, then pull to refresh in the app.

**`503` on `/hockey/nhl/games`**: the cache is still empty. Wait about 60 seconds and check `/hockey/nhl/sync-status`: `leagueMetaReady: true` and `rawGamesInRedis` above 0 means it's ready.

**`Address already in use` on port 8000**: find and stop the other process (`lsof -nP -iTCP:8000 -sTCP:LISTEN`, then `kill <PID>`), or run on another port and update `EXPO_PUBLIC_API_URL` in the app.

**Physical phone**: use your computer's LAN IP (`ipconfig getifaddr en0`) instead of `127.0.0.1`; phone and computer must be on the same network. Android emulator: `http://10.0.2.2:8000`.

## Optional: standings in Supabase

Standings are cached in Redis without this. To also store them in Postgres:

1. Create a project at [supabase.com](https://supabase.com).
2. Run `supabase/migrations/001_nhl_team_records.sql` in the SQL editor.
3. Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env`.

## Tests

```bash
source .venv/bin/activate
pytest
```

Covers the NHL/MLB data mappers, box scores, standings parsing, scoreboard sorting and filtering, cache behavior, head-to-head, and the briefing prompts.
