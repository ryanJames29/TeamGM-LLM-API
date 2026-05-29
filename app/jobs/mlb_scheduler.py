import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.services.mlb_jobs import (
    MLB_SYNC_LOCK_KEY,
    _LOCK_TTL_INITIAL,
    _sync_mlb_games_window,
    _sync_mlb_scores_minute,
    _sync_mlb_standings,
    sync_mlb_games_window,
    sync_mlb_scores_minute,
    sync_mlb_standings,
)
from app.services.redis_store import mlb_sync_lock

logger = logging.getLogger(__name__)


def create_mlb_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        sync_mlb_standings,
        trigger=IntervalTrigger(minutes=settings.mlb_standings_interval_minutes),
        args=[settings],
        id="mlb_standings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_mlb_scores_minute,
        trigger=IntervalTrigger(seconds=settings.mlb_scores_interval_seconds),
        args=[settings],
        id="mlb_scores_minute",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_mlb_games_window,
        trigger=IntervalTrigger(hours=settings.mlb_window_refresh_hours),
        args=[settings],
        id="mlb_games_window",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return scheduler


async def run_initial_mlb_sync(settings: Settings) -> None:
    async with mlb_sync_lock(MLB_SYNC_LOCK_KEY, _LOCK_TTL_INITIAL) as acquired:
        if not acquired:
            logger.info("Skipping initial MLB sync — another API instance is running MLB jobs")
            return
        logger.info("Running initial MLB sync (standings → window → scores)")
        for step_name, step in (
            ("standings", _sync_mlb_standings),
            ("window", _sync_mlb_games_window),
            ("scores", _sync_mlb_scores_minute),
        ):
            try:
                await step(settings)
            except Exception:
                logger.exception("Initial MLB sync step %s failed — continuing", step_name)


def schedule_initial_mlb_sync(settings: Settings) -> None:
    asyncio.create_task(run_initial_mlb_sync(settings))
