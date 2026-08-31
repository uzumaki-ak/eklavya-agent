"""Shared request-scoped helpers for the route modules."""

from fastapi import HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from app.schemas.api import UserId
from app.services.submission import (
    EmptyTopic,
    IdempotencyConflict,
    QueueUnavailable,
)

_USER_ID_ADAPTER = TypeAdapter(UserId)


def session_id_of(request: Request) -> str:
    """The anonymous caller. Scopes idempotency keys; never used as an owner."""
    return request.headers.get("x-session-id") or (
        request.client.host if request.client else "anon"
    )


def resolve_user_id(request: Request, body_user_id: str | None) -> str:
    """Body, then `X-User-Id` header, then the anonymous session.

    The spec's `POST /generate` body is `{grade, topic}`, so a caller who follows
    it exactly must still work. Falling back to the session keeps every run
    owned by *something*, which is what lets `GET /history` be a plain indexed
    lookup rather than a query with a null case.
    """
    candidate = body_user_id or request.headers.get("x-user-id") or session_id_of(request)
    try:
        return _USER_ID_ADAPTER.validate_python(candidate)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "user_id must be 1-128 characters using only letters, numbers, "
                "'.', '_', ':', '@', or '-'"
            ),
        ) from exc


def as_http_error(exc: Exception) -> HTTPException:
    """Map a submission failure onto its HTTP shape, in one place."""
    if isinstance(exc, EmptyTopic):
        return HTTPException(status_code=422, detail="topic must contain at least one word")
    if isinstance(exc, IdempotencyConflict):
        return HTTPException(
            status_code=409,
            detail=(
                "This Idempotency-Key was already used with a different "
                "user, grade, or topic."
            ),
        )
    if isinstance(exc, QueueUnavailable):
        return HTTPException(
            status_code=503,
            detail="Could not start the job right now. Please try again in a moment.",
        )
    raise exc
