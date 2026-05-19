from pydantic import BaseModel, ConfigDict


class NhlLeagueInfo(BaseModel):
    id: int | None = None
    name: str | None = None
    logo: str | None = None
    season: int | None = None


class NhlLeagueResponse(BaseModel):
    status: str
    source: str
    league: NhlLeagueInfo | None = None
    updatedAt: str | None = None


class NhlTeamScore(BaseModel):
    name: str
    abbreviation: str
    record: str
    standing: str | None = None
    score: int | None = None


class NhlGame(BaseModel):
    id: str
    league: str
    status: str
    periodLabel: str | None = None
    scheduledAt: str | None = None
    venue: str
    awayTeam: NhlTeamScore
    homeTeam: NhlTeamScore

    model_config = ConfigDict(extra="ignore")


class NhlSyncStatus(BaseModel):
    lastStandingsSync: str | None = None
    standingsApiCalls: int | None = None
    lastWindowSync: str | None = None
    windowApiCalls: int | None = None
    lastScoresSync: str | None = None
    minuteApiCalls: int | None = None
    liveGamesPolled: int | None = None

    model_config = ConfigDict(extra="allow")


class NhlScoresResponse(BaseModel):
    status: str
    source: str
    league: NhlLeagueInfo | None = None
    date: str
    message: str
    games: list[NhlGame]
    sync: NhlSyncStatus | None = None


class NhlSyncCacheStatus(BaseModel):
    rawGamesInRedis: int | None = None


class NhlSyncStatusResponse(BaseModel):
    status: str
    sync: NhlSyncStatus
    leagueMetaReady: bool
    cache: NhlSyncCacheStatus
