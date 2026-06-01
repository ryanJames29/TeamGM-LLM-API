from pydantic import BaseModel, Field


class BriefingInsight(BaseModel):
    team: str
    summary: str
    context: str


class ConcernLevelInsight(BaseModel):
    level: int = Field(ge=1, le=10)
    description: str


class RecentPerformanceInsight(BaseModel):
    headline: str
    lastGameSummary: str


class TeamHomeInsight(BaseModel):
    teamKey: str
    league: str
    teamName: str
    whyItMatters: list[str]
    briefing: BriefingInsight
    concernLevel: ConcernLevelInsight
    recentPerformance: RecentPerformanceInsight


class NextGameSummary(BaseModel):
    id: int | None = None
    status: str | None = None
    scheduledAt: str | None = None
    periodLabel: str | None = None
    venue: str | None = None
    teamScore: int | None = None
    opponentScore: int | None = None
    opponentName: str | None = None
    opponentAbbreviation: str | None = None
    opponentApiSportsTeamId: int | None = None
    location: str | None = None


class HomeInsightsResponse(BaseModel):
    status: str
    generatedAt: str
    factsAsOf: str | None = None
    source: str
    insight: TeamHomeInsight
    nextGame: NextGameSummary | None = None
