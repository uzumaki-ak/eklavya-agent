"""Liveness and readiness probes.

/health is a readiness check: it returns 503 when a dependency is down, so
Docker/orchestrators actually stop routing traffic here. Returning 200 while
Postgres is unreachable would make the healthcheck decorative.
"""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.cache import get_redis

router = APIRouter()


async def _check_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


@router.get("/health")
async def health(response: Response) -> dict:
    checks = {
        "postgres": "ok" if await _check_postgres() else "error",
        "redis": "ok" if await _check_redis() else "error",
    }
    healthy = all(value == "ok" for value in checks.values())

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if healthy else "degraded", "checks": checks}


@router.get("/health/live")
async def liveness() -> dict:
    """Process is up. No dependency checks — used to decide restarts, not routing."""
    return {"status": "ok"}
