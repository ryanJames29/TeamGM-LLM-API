import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    logger.info("Health check — request received from client")
    return {
        "status": "ok",
        "message": "Got it — TeamGM API received your request.",
    }
