# TeamGM LLM API

FastAPI backend for TeamGM.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run locally

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

## Test with Expo

1. Start the API (`uvicorn` above).
2. In `TeamGM/.env`, set `EXPO_PUBLIC_API_URL=http://127.0.0.1:8000` (Android emulator: `http://10.0.2.2:8000`).
3. Restart Expo, open **Profile**, tap **Check API health**.
