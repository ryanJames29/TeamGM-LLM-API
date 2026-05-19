import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.services.nhl_jobs import (
    NHL_SYNC_LOCK_KEY,
    _LOCK_TTL_INITIAL,
    _sync_nhl_games_window,
    _sync_nhl_scores_minute,
    _sync_nhl_standings,
)
from app.services.redis_store import nhl_sync_lock

logger = logging.getLogger(__name__)


def create_nhl_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        sync_nhl_standings,
        trigger=IntervalTrigger(minutes=settings.nhl_standings_interval_minutes),
        args=[settings],
        id="nhl_standings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_nhl_scores_minute,
        trigger=IntervalTrigger(seconds=settings.nhl_scores_interval_seconds),
        args=[settings],
        id="nhl_scores_minute",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_nhl_games_window,
        trigger=IntervalTrigger(hours=settings.nhl_window_refresh_hours),
        args=[settings],
        id="nhl_games_window",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return scheduler


async def run_initial_nhl_sync(settings: Settings) -> None:
    """Populate cache on startup so the first client request is not empty."""
    async with nhl_sync_lock(NHL_SYNC_LOCK_KEY, _LOCK_TTL_INITIAL) as acquired:
        if not acquired:
            logger.info("Skipping initial NHL sync — another API instance is running NHL jobs")
            return
        logger.info("Running initial NHL sync (standings → window → scores)")
        for step_name, step in (
            ("standings", _sync_nhl_standings),
            ("window", _sync_nhl_games_window),
            ("scores", _sync_nhl_scores_minute),
        ):
            try:
                await step(settings)
            except Exception:
                logger.exception("Initial NHL sync step %s failed — continuing", step_name)


def schedule_initial_sync(settings: Settings) -> None:
    asyncio.create_task(run_initial_nhl_sync(settings))
