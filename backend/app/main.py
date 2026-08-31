"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import generate, health, jobs, pipeline

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
    description=(
        "Governed Generator, Reviewer, Refiner, and Tagger pipeline for "
        "grade-appropriate learning content"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# No CORS middleware: the frontend container reverse-proxies /api to this
# service, so every request is same-origin.
app.include_router(health.router, tags=["health"])

# The Part 2 required surface, unprefixed exactly as specified.
app.include_router(pipeline.router, tags=["pipeline"])

# Part 1's asynchronous surface, kept for the streaming UI. Same submission path,
# same worker — see app/services/submission.py.
app.include_router(generate.router, prefix="/api", tags=["jobs"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
