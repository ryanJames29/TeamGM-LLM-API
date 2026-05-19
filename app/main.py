import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.jobs.scheduler import create_nhl_scheduler, schedule_initial_sync
from app.routers import health, hockey
from app.services.redis_store import connect_redis, disconnect_redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    scheduler = None

    if settings.enable_nhl_jobs:
        try:
            await connect_redis(settings)
            scheduler = create_nhl_scheduler(settings)
            scheduler.start()
            schedule_initial_sync(settings)
            logger.info(
                "NHL jobs started (standings every %sm, scores every %ss)",
                settings.nhl_standings_interval_minutes,
                settings.nhl_scores_interval_seconds,
            )
        except Exception:
            logger.exception(
                "NHL jobs disabled — could not connect to Redis at %s. "
                "Run: docker compose up -d",
                settings.redis_url,
            )
    else:
        logger.info("NHL background jobs disabled (ENABLE_NHL_JOBS=false)")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
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

    return application


app = create_app()
