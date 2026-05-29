import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.jobs.mlb_scheduler import create_mlb_scheduler, schedule_initial_mlb_sync
from app.jobs.scheduler import create_nhl_scheduler, schedule_initial_sync
from app.routers import baseball, health, hockey
from app.services.api_sports import close_api_sports_client
from app.services.redis_store import connect_redis, disconnect_redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    schedulers = []

    if settings.enable_nhl_jobs or settings.enable_mlb_jobs:
        try:
            await connect_redis(settings)
        except Exception:
            logger.exception(
                "Background jobs disabled — could not connect to Redis at %s. "
                "Run: docker compose up -d",
                settings.redis_url,
            )
        else:
            if settings.enable_nhl_jobs:
                nhl_scheduler = create_nhl_scheduler(settings)
                nhl_scheduler.start()
                schedulers.append(nhl_scheduler)
                schedule_initial_sync(settings)
                logger.info(
                    "NHL jobs started (standings every %sm, scores every %ss)",
                    settings.nhl_standings_interval_minutes,
                    settings.nhl_scores_interval_seconds,
                )
            else:
                logger.info("NHL background jobs disabled (ENABLE_NHL_JOBS=false)")

            if settings.enable_mlb_jobs:
                mlb_scheduler = create_mlb_scheduler(settings)
                mlb_scheduler.start()
                schedulers.append(mlb_scheduler)
                schedule_initial_mlb_sync(settings)
                logger.info(
                    "MLB jobs started (standings every %sm, scores every %ss)",
                    settings.mlb_standings_interval_minutes,
                    settings.mlb_scores_interval_seconds,
                )
            else:
                logger.info("MLB background jobs disabled (ENABLE_MLB_JOBS=false)")
    else:
        logger.info("All background jobs disabled (ENABLE_NHL_JOBS and ENABLE_MLB_JOBS false)")

    yield

    for scheduler in schedulers:
        scheduler.shutdown(wait=False)
    await close_api_sports_client()
    await disconnect_redis()


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="TeamGM LLM API",
        description="Backend for TeamGM.",
        version="0.2.0",
        lifespan=lifespan,
    )

    if settings.app_env == "development":
        application.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.include_router(health.router, prefix="/api/v1")
    application.include_router(hockey.router, prefix="/api/v1")
    application.include_router(baseball.router, prefix="/api/v1")

    return application


app = create_app()
