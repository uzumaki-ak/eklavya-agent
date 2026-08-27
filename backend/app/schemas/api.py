"""HTTP request/response models."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.content import GeneratorOutput, ReviewerOutput


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=1, max_length=200)


class GenerateResponse(BaseModel):
    job_id: str
    status: str
    cache_hit: bool = False


class JobResponse(BaseModel):
    """All four stages are exposed separately — the UI must show the agent flow,
    not just a final answer."""

    job_id: str
    status: str
    grade: int
    topic: str
    cache_hit: bool

    original_output: GeneratorOutput | None = None
    initial_review: ReviewerOutput | None = None
    refined_output: GeneratorOutput | None = None
    final_review: ReviewerOutput | None = None

    refinement_count: int = 0
    error_code: str | None = None

    @property
    def was_refined(self) -> bool:
        return self.refined_output is not None
