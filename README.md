# TeamGM LLM API

FastAPI backend for the TeamGM app. NHL scores are fetched in the background and served from Redis — the mobile app never hits API-Sports directly.

---

## Every time you work (do these in order)

Open **three terminals** (or use tabs). Run each block from the repo root shown.

### 1. Start Docker Desktop

Redis runs in Docker. **Open Docker Desktop first** and wait until it says it is running.

If you skip this, `docker compose` will hang or fail.

### 2. Start Redis

```bash
cd TeamGM-LLM-API
docker compose up -d
```

Check it is up:

```bash
docker compose ps
```

You should see `redis` with status `running`.

### 3. Start the API

```bash
cd TeamGM-LLM-API
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Wait for this line in the logs:

```
NHL jobs started (standings every 60m, scores every 60s)
```

If you see `NHL jobs disabled — could not connect to Redis`, Redis is not running. Go back to step 1–2, then **restart uvicorn** (Ctrl+C and run the command again).

Quick check in a browser or curl:

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/hockey/nhl/games
```

The games endpoint may return `503` for the first 30–60 seconds while background jobs fill the cache. Refresh after a minute.

### 4. Start the Expo app

In a **separate** terminal:

```bash
cd TeamGM/TeamGM
npx expo start -c
```

Open the app → **Scores** tab → select **NHL**.

Your `TeamGM/TeamGM/.env` must include:

```env
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

Change the port if you run uvicorn on something other than `8000`, then restart Expo with `-c`.

---

## First-time setup (once)

### API

```bash
cd TeamGM-LLM-API
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
API_SPORTS_KEY=your_key_from_api_sports
```

Get a key at [dashboard.api-sports.io](https://dashboard.api-sports.io/).

Redis URL and job settings in `.env.example` are fine for local dev — no changes needed unless you want to tweak intervals.

### Expo app

```bash
cd TeamGM/TeamGM
cp .env.example .env
```

Set `EXPO_PUBLIC_API_URL` to match the API port (default `8000`).

---

## Useful URLs

| What | URL |
|------|-----|
| API docs | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/api/v1/health |
| NHL games (what the app calls) | http://127.0.0.1:8000/api/v1/hockey/nhl/games |
| Job / cache status | http://127.0.0.1:8000/api/v1/hockey/nhl/sync-status |

---

## When something breaks

### App shows a JSON parse error or “Could not load NHL scores”

Usually Redis or the API is not running, or the API started **before** Redis.

1. Confirm Docker Desktop is running.
2. `docker compose up -d` in `TeamGM-LLM-API`.
3. Restart uvicorn (Ctrl+C, then start again).
4. Pull to refresh in the app.

### `503` on `/hockey/nhl/games`

Cache is empty. Wait ~60 seconds for sync jobs, then retry. Check:

```bash
curl http://127.0.0.1:8000/api/v1/hockey/nhl/sync-status
```

`leagueMetaReady: true` and `rawGamesInRedis` > 0 means you are good.

### `Address already in use` on port 8000

Something else is using the port:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

Or use another port and update `EXPO_PUBLIC_API_URL`:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### Physical iPhone / Android device (not simulator)

Use your Mac’s LAN IP instead of `127.0.0.1`:

```env
EXPO_PUBLIC_API_URL=http://192.168.x.x:8000
```

Find your IP: `ipconfig getifaddr en0` (Wi‑Fi). Phone and Mac must be on the same network.

Android emulator: `http://10.0.2.2:8000`

---

## Optional: Supabase (standings in DB)

Not required for local dev. Standings still cache in Redis without it.

1. Create a project at [supabase.com](https://supabase.com).
2. Run `supabase/migrations/001_nhl_team_records.sql` in the SQL editor.
3. Add to `.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

---

## Tests

```bash
cd TeamGM-LLM-API
source .venv/bin/activate
pytest
```
