import json
import logging

from openai import AsyncOpenAI

from app.config import Settings
from app.schemas.insights import TeamHomeInsight
from app.types import JsonObject

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are TeamGM, a concise sports analyst for casual fans.
Return ONLY valid JSON matching this schema (no markdown):
{
  "upcomingGame": {"team": string, "opponent": string, "time": string, "location": "@" or "vs"},
  "whyItMatters": [string, ...],
  "briefing": {"team": string, "summary": string, "context": string},
  "concernLevel": {"level": integer 1-10, "description": string},
  "playerTrends": {
    "stockUp": [{"name": string, "stat": string}],
    "stockDown": [{"name": string, "stat": string}]
  },
  "recentPerformance": {
    "headline": string,
    "summary": string,
    "wentRight": string,
    "wentWrong": string
  }
}

Rules:
- Use ONLY facts from the user message. Do not invent scores, players, or standings.
- When headToHead is present, use it for whyItMatters, recentPerformance, and concernLevel (series record, recent meetings).
- If player names are not in the data, describe team-level trends instead of naming players.
- whyItMatters: 3-5 short bullets about the next game. Talk about the last 10 games or current series record too so we know why tonight matters.
- concernLevel.level: 1=calm, 10=panic; base it on recent results and standings context, player injuries/trends.
- upcomingGame.time: human-readable (e.g. "Tonight at 7:00 PM" or "Tomorrow at 1:05 PM").
- upcomingGame.location: "@" for away, "vs" for home.
- Keep each text field fan-friendly and under 2 sentences where possible."""


async def generate_team_home_insight(
    settings: Settings,
    facts: JsonObject,
    *,
    team_key: str,
    league: str,
    team_name: str,
) -> TeamHomeInsight:
    if not settings.openai_enabled:
        raise RuntimeError("OpenAI is not configured (OPENAI_API_KEY missing).")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_content = json.dumps(facts, ensure_ascii=True, default=str)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("OpenAI returned an empty response.")

    parsed = json.loads(raw)
    return TeamHomeInsight(
        teamKey=team_key,
        league=league,
        teamName=team_name,
        **parsed,
    )
