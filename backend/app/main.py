"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import generate, health, jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger(__name__).info("api starting")
    yield
    from app.db.session import engine

    await engine.dispose()


app = FastAPI(
    title="Eklavya Agent Pipeline",
    description="Generator + Reviewer agents producing grade-appropriate learning content",
    version="0.1.0",
    lifespan=lifespan,
)

# No CORS middleware: the frontend container reverse-proxies /api to this
# service, so every request is same-origin.
app.include_router(health.router, tags=["health"])
app.include_router(generate.router, prefix="/api", tags=["pipeline"])
app.include_router(jobs.router, prefix="/api", tags=["pipeline"])
