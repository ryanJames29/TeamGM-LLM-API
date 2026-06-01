from pydantic import BaseModel, Field


class UpcomingGameInsight(BaseModel):
    team: str
    opponent: str
    time: str
    location: str


class BriefingInsight(BaseModel):
    team: str
    summary: str
    context: str


class ConcernLevelInsight(BaseModel):
    level: int = Field(ge=1, le=10)
    description: str


class PlayerTrendItem(BaseModel):
    name: str
    stat: str


class PlayerTrendsInsight(BaseModel):
    stockUp: list[PlayerTrendItem]
    stockDown: list[PlayerTrendItem]


class RecentPerformanceInsight(BaseModel):
    headline: str
    summary: str
    wentRight: str
    wentWrong: str


class TeamHomeInsight(BaseModel):
    teamKey: str
    league: str
    teamName: str
    upcomingGame: UpcomingGameInsight
    whyItMatters: list[str]
    briefing: BriefingInsight
    concernLevel: ConcernLevelInsight
    playerTrends: PlayerTrendsInsight
    recentPerformance: RecentPerformanceInsight


class HomeInsightsResponse(BaseModel):
    status: str
    generatedAt: str
    factsAsOf: str | None = None
    source: str
    insight: TeamHomeInsight
