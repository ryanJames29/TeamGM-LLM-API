import json
import logging

from openai import AsyncOpenAI

from app.config import Settings
from app.prompts.home_insights import build_system_prompt
from app.schemas.insights import TeamHomeInsight
from app.types import JsonObject

logger = logging.getLogger(__name__)


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
            {"role": "system", "content": build_system_prompt()},
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
