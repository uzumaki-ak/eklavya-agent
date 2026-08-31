"""HTTP request/response models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.artifact import RunArtifact
from app.schemas.content import GeneratorOutput
from app.schemas.review import ReviewerOutput
from app.schemas.tags import ContentTags

# An explicit, validated owner — not an IP address wearing a user's name.
# Constrained rather than free text because it is a lookup key: `GET /history`
# filters on it, so it must be something a caller can reproduce exactly, and
# nothing that could arrive with control characters or surrounding whitespace.
UserId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$"),
]


class GenerateRequest(BaseModel):
    """The spec's input, plus the optional owner.

    `user_id` may also arrive as an `X-User-Id` header. When neither is given the
    run is attributed to the anonymous session, and `GET /history` for a real
    user id will not return it — which is the honest outcome, since nobody
    claimed it.
    """

    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=1, max_length=200)
    user_id: UserId | None = None


class GenerateResponse(BaseModel):
    """Part 1's asynchronous acknowledgement, used by the streaming UI."""

    job_id: str
    status: str
    cache_hit: bool = False


class JobResponse(BaseModel):
    """Live view of one run, for the UI's stage-by-stage display.

    A fixed-width summary of the trail: the first draft and its review, the final
    content and its review. The complete ordered history — including the middle
    of a two-refinement run — is in the RunArtifact.
    """

    job_id: str
    status: str
    grade: int
    topic: str
    cache_hit: bool

    original_output: GeneratorOutput | None = None
    initial_review: ReviewerOutput | None = None
    refined_output: GeneratorOutput | None = None
    final_review: ReviewerOutput | None = None
    tags: ContentTags | None = None

    refinement_count: int = 0
    error_code: str | None = None

    @property
    def was_refined(self) -> bool:
        return self.refined_output is not None


class HistoryResponse(BaseModel):
    """Stored artifacts for one user, newest first.

    `legacy_excluded` counts terminal runs with no artifact plus stored payloads
    that no longer validate. Reporting it distinguishes "no earlier runs" from
    "earlier runs exist but this endpoint cannot represent them".
    """

    user_id: str
    count: int
    legacy_excluded: int = 0
    artifacts: list[RunArtifact] = Field(default_factory=list)
