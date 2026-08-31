"""Builds the RunArtifact from a run's envelope.

The single place a RunArtifact is constructed. Everything that stores one — the
worker, the cache-reuse path, the synchronous endpoint — comes through here, so
"the artifact and the summary columns agree" is a property of there being one
derivation rather than of three call sites being kept in step.

The attempt chain falls straight out of the two parallel lists:

    attempt i:  draft = drafts[i], review = reviews[i], refined = drafts[i + 1]

`refined` is absent on the last attempt, because either the review passed or the
refinement budget was spent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from app.schemas.artifact import (
    Attempt,
    FinalDecision,
    RunArtifact,
    RunInput,
    RunProvenance,
    RunTimestamps,
)
from app.services.envelope import approved


@dataclass
class ArtifactMeta:
    """Identity and provenance for one run — the parts an envelope cannot carry.

    A reused envelope is another run's content; the metadata below is always this
    run's own, which is why a cache hit still produces an honest artifact rather
    than a copy of the leader's.
    """

    run_id: str
    user_id: str
    grade: int
    topic: str
    started_at: datetime
    finished_at: datetime | None = None
    pipeline_status: str = "completed_fail"
    reason_code: str | None = None
    cache_hit: bool = False
    provider: str = ""
    generator_model: str | None = None
    reviewer_model: str | None = None
    tagger_model: str | None = None
    prompt_versions: dict[str, str] = field(default_factory=dict)
    schema_version: str | None = None
    logical_llm_calls: int = 0
    schema_repair_attempts: int = 0
    transport_attempts_total: int = 0


def _attempts(envelope: dict) -> list[Attempt]:
    drafts = envelope.get("drafts") or []
    reviews = envelope.get("reviews") or []
    withheld = {
        int(match.group(1))
        for key, result in (envelope.get("moderation_results") or {}).items()
        if (match := re.fullmatch(r"draft_(\d+)", key))
        and result.get("outcome") in {"blocked", "error"}
    }
    count = max([len(drafts), *withheld], default=0)
    return [
        Attempt(
            attempt=index + 1,
            draft=drafts[index] if index < len(drafts) else None,
            review=reviews[index] if index < len(reviews) else None,
            # Present only when a further draft exists to point at.
            refined=drafts[index + 1] if index + 1 < len(drafts) else None,
            content_withheld=index + 1 in withheld,
        )
        # A draft whose Reviewer failed still belongs in the lifecycle. Its
        # review is null and final.pipeline_status explains the technical stop.
        for index in range(count)
    ]


def _final(envelope: dict, meta: ArtifactMeta) -> FinalDecision:
    is_approved = meta.pipeline_status == "completed_pass" and approved(envelope)
    drafts = envelope.get("drafts") or []
    return FinalDecision(
        status="approved" if is_approved else "rejected",
        content=drafts[-1] if is_approved and drafts else None,
        tags=envelope.get("tags") if is_approved else None,
        pipeline_status=meta.pipeline_status,
        reason_code=meta.reason_code,
    )


def build_artifact(envelope: dict, meta: ArtifactMeta) -> RunArtifact:
    """Assemble the complete audit record for one run."""
    return RunArtifact(
        run_id=meta.run_id,
        user_id=meta.user_id,
        input=RunInput(grade=meta.grade, topic=meta.topic),
        attempts=_attempts(envelope),
        moderation_results=envelope.get("moderation_results") or {},
        final=_final(envelope, meta),
        timestamps=RunTimestamps(
            started_at=meta.started_at,
            finished_at=meta.finished_at or datetime.now(timezone.utc),
        ),
        provenance=RunProvenance(
            provider=meta.provider,
            generator_model=meta.generator_model,
            reviewer_model=meta.reviewer_model,
            tagger_model=meta.tagger_model,
            prompt_versions=meta.prompt_versions,
            schema_version=meta.schema_version,
            cache_hit=meta.cache_hit,
            refinement_count=envelope.get("refinement_count", 0) or 0,
            logical_llm_calls=meta.logical_llm_calls,
            schema_repair_attempts=meta.schema_repair_attempts,
            transport_attempts_total=meta.transport_attempts_total,
        ),
    )


def artifact_json(artifact: RunArtifact) -> dict:
    """JSON-mode dump, ready for JSONB. `by_alias` keeps the review's "pass" key."""
    return artifact.model_dump(mode="json", by_alias=True)


def meta_for_run(
    *,
    run_id: str,
    user_id: str,
    grade: int,
    topic: str,
    started_at: datetime,
    pipeline_status: str,
    reason_code: str | None = None,
    cache_hit: bool = False,
    state: dict | None = None,
) -> ArtifactMeta:
    """Fill in provenance from the running configuration.

    Imported lazily so this module stays importable without provider
    credentials — the schema tests exercise artifact construction directly.
    """
    from app.agents.prompts import PROMPT_VERSIONS
    from app.agents.providers import GENERATOR_CONFIG, REVIEWER_CONFIG, TAGGER_CONFIG
    from app.core.config import settings

    counters = state or {}
    return ArtifactMeta(
        run_id=run_id,
        user_id=user_id,
        grade=grade,
        topic=topic,
        started_at=started_at,
        pipeline_status=pipeline_status,
        reason_code=reason_code,
        cache_hit=cache_hit,
        provider=settings.llm_provider,
        generator_model=GENERATOR_CONFIG.model_id,
        reviewer_model=REVIEWER_CONFIG.model_id,
        tagger_model=TAGGER_CONFIG.model_id,
        prompt_versions=dict(PROMPT_VERSIONS),
        schema_version=settings.schema_version,
        logical_llm_calls=counters.get("logical_llm_calls", 0),
        schema_repair_attempts=counters.get("schema_repair_attempts", 0),
        transport_attempts_total=counters.get("transport_attempts_total", 0),
    )


def envelope_from_artifact(payload: dict) -> dict:
    """The inverse of `build_artifact`'s attempt chain.

    A single-flight follower reuses the leader's *content*, and the leader's
    complete trail survives only in its artifact — the four summary columns
    cannot represent a two-refinement run. Reading it back here keeps one
    representation of the trail rather than adding a second stored copy.
    """
    attempts = payload.get("attempts") or []
    drafts = [attempt["draft"] for attempt in attempts if attempt.get("draft") is not None]
    reviews = [attempt["review"] for attempt in attempts if attempt.get("review")]

    final = payload.get("final") or {}
    provenance = payload.get("provenance") or {}
    return {
        "drafts": drafts,
        "reviews": reviews,
        "tags": final.get("tags"),
        "refinement_count": provenance.get("refinement_count", 0) or 0,
        "moderation_results": payload.get("moderation_results") or {},
    }
