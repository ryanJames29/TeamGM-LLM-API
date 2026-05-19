# TeamGM LLM API

FastAPI backend for TeamGM. **NHL only** — API-Sports is called by background jobs, not on every app request.

## Architecture

| Data | Refresh | Storage | API-Sports calls |
|------|---------|---------|------------------|
| Standings + league metadata | Hourly | Supabase `nhl_team_records` + Redis | 2 / hour |
| Scores window (7 days back, 3 ahead) | Daily | Redis hash `nhl:raw_games` | 11 / day |
| Today + yesterday scores | Every minute | Redis | 2 / minute |
| Live game statistics | Every minute (live only) | Redis per game | up to ~12 / minute |

**Client requests** (`GET /api/v1/hockey/nhl/games`) read **Redis only** — zero upstream calls.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set API_SPORTS_KEY, REDIS_URL, optional SUPABASE_* in .env
```

### Redis (free, local)

```bash
docker compose up -d
```

Uses `redis://localhost:6379/0` by default.

### Supabase (standings)

1. Create a project at [supabase.com](https://supabase.com) (free tier).
2. Run `supabase/migrations/001_nhl_team_records.sql` in the SQL editor.
3. Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env`.

If Supabase is not configured, standings still cache in Redis; only DB persistence is skipped.

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On startup the API connects to Redis, starts scheduled jobs, and runs an initial sync.

- Docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health
- NHL games (mobile): http://127.0.0.1:8000/api/v1/hockey/nhl/games
- Job status (dev): http://127.0.0.1:8000/api/v1/hockey/nhl/sync-status

## Test with Expo

1. Start Redis + API.
2. In `TeamGM/TeamGM/.env`: `EXPO_PUBLIC_API_URL=http://127.0.0.1:8000`
3. `npx expo start -c` → Scores tab → NHL

## Tests

```bash
pytest
```
