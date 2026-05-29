from pydantic import BaseModel, ConfigDict


class MlbLeagueInfo(BaseModel):
    id: int | None = None
    name: str | None = None
    logo: str | None = None
    season: int | None = None


class MlbLeagueResponse(BaseModel):
    status: str
    source: str
    league: MlbLeagueInfo | None = None
    updatedAt: str | None = None


class MlbTeamScore(BaseModel):
    name: str
    abbreviation: str
    record: str
    standing: str | None = None
    score: int | None = None


class MlbGame(BaseModel):
    id: str
    league: str
    status: str
    periodLabel: str | None = None
    scheduledAt: str | None = None
    venue: str
    awayTeam: MlbTeamScore
    homeTeam: MlbTeamScore

    model_config = ConfigDict(extra="ignore")


class MlbSyncStatus(BaseModel):
    lastStandingsSync: str | None = None
    standingsApiCalls: int | None = None
    lastWindowSync: str | None = None
    windowApiCalls: int | None = None
    lastScoresSync: str | None = None
    minuteApiCalls: int | None = None
    liveGamesPolled: int | None = None

    model_config = ConfigDict(extra="allow")


class MlbScoresResponse(BaseModel):
    status: str
    source: str
    league: MlbLeagueInfo | None = None
    date: str
    message: str
    games: list[MlbGame]
    sync: MlbSyncStatus | None = None


class MlbSyncCacheStatus(BaseModel):
    rawGamesInRedis: int | None = None


class MlbSyncStatusResponse(BaseModel):
    status: str
    sync: MlbSyncStatus
    leagueMetaReady: bool
    cache: MlbSyncCacheStatus
