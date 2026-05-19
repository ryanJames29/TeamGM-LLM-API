import logging
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import Settings

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def _parse_api_sports_errors(payload: dict[str, Any]) -> str | None:
    errors = payload.get("errors")
    if not errors:
        return None
    if isinstance(errors, dict):
        messages = [str(v) for v in errors.values() if v]
        return "; ".join(messages) if messages else "API-Sports returned an error."
    if isinstance(errors, list):
        messages = [str(item) for item in errors if item]
        return "; ".join(messages) if messages else "API-Sports returned an error."
    return str(errors)


class ApiSportsClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _require_key(self) -> str:
        key = self._settings.api_sports_key
        if not key or not key.strip():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API_SPORTS_KEY is not configured on the server.",
            )
        return key.strip()

    async def get_hockey(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        api_key = self._require_key()
        base = self._settings.api_sports_hockey_base_url.rstrip("/")
        url = f"{base}/{path.lstrip('/')}"
        headers = {"x-apisports-key": api_key}

        try:
            response = await _get_http_client().get(url, headers=headers, params=params)
        except httpx.RequestError as exc:
            logger.exception("API-Sports request failed: %s", url)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not reach API-Sports.",
            ) from exc

        if response.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="API-Sports rejected the key (check API_SPORTS_KEY).",
            )

        if response.status_code >= 400:
            logger.warning(
                "API-Sports error %s for %s: %s",
                response.status_code,
                url,
                response.text[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"API-Sports returned {response.status_code}.",
            )

        payload = response.json()
        api_error = _parse_api_sports_errors(payload)
        if api_error:
            logger.warning("API-Sports logical error for %s: %s", url, api_error)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=api_error,
            )

        return payload
