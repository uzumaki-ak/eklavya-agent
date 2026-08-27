"""Reviewer Agent — evaluates the Generator's output.

Responsibility: judge age appropriateness, conceptual correctness, clarity,
topic coverage, and question quality.
Structured input: the Generator's content JSON. Structured output: ReviewerOutput.

Note on grade and topic: the spec's Reviewer input contract is content-only, but
neither age appropriateness nor topic coverage can be judged without them. The
formal schema is kept exactly as specified; both are injected as prompt context.

The model answers into ReviewerJudgement, which carries one extra internal field
(`addresses_requested_topic`). Code enforces the model's self-report of drift,
then drops that field when projecting to the public {status, feedback} shape.
"""

import json
import logging

from pydantic import ValidationError

from app.agents.client import REVIEWER_CONFIG, call_llm
from app.agents.prompts import (
    REVIEWER_SYSTEM,
    REVIEWER_USER,
    escape_topic,
    grade_band_guidance,
)
from app.core.config import settings
from app.core.exceptions import LLMStructuredOutputError
from app.schemas.content import GeneratorOutput, ReviewerJudgement, ReviewerOutput

logger = logging.getLogger(__name__)


class ReviewerAgent:
    async def run(
        self,
        content: GeneratorOutput,
        grade: int,
        topic: str,
        deadline: float,
        counters: dict | None = None,
    ) -> ReviewerOutput:
        """The spec-shaped call: content in, {status, feedback} out."""
        judgement = await self.judge(content, grade, topic, deadline, counters)
        return judgement.to_output()

    async def judge(
        self,
        content: GeneratorOutput,
        grade: int,
        topic: str,
        deadline: float,
        counters: dict | None = None,
    ) -> ReviewerJudgement:
        """The full judgement, including the internal topic-coverage flag.

        Exposed separately so the evaluation harness can score topic-drift
        detection, which the public shape deliberately hides.
        """
        system = REVIEWER_SYSTEM.format(band=grade_band_guidance(grade))
        user = REVIEWER_USER.format(
            grade=grade,
            topic=escape_topic(topic),
            content=json.dumps(content.model_dump(), indent=2, ensure_ascii=False),
        )

        runtime_counters = counters if counters is not None else {}
        repair_feedback = ""
        max_repairs = settings.schema_repair_max_attempts

        for attempt in range(max_repairs + 1):
            try:
                judgement = await call_llm(
                    config=REVIEWER_CONFIG,
                    system=system,
                    user=user + repair_feedback,
                    output_format=ReviewerJudgement,
                    deadline=deadline,
                    counters=runtime_counters,
                )
                runtime_counters["schema_repair_attempts"] = attempt
                break
            except (ValidationError, LLMStructuredOutputError):
                runtime_counters["schema_repair_attempts"] = attempt
                if attempt == max_repairs:
                    logger.warning("reviewer schema repair exhausted after %d attempts", attempt)
                    raise
                logger.info("reviewer output failed validation, repairing (%d)", attempt + 1)
                repair_feedback = (
                    "\n\nYour previous review failed the required output schema. "
                    "Return the complete review again. Include status, feedback, and "
                    "addresses_requested_topic. A fail status requires at least one "
                    "specific feedback item; a pass requires an empty feedback list."
                )
        else:  # pragma: no cover - the bounded loop always returns or raises
            raise AssertionError("unreachable")

        if not judgement.addresses_requested_topic:
            # Worth its own log line: this is the pipeline catching the model
            # approving a lesson on the wrong subject.
            logger.warning("reviewer flagged topic drift for %r", topic[:60])

        logger.info(
            "reviewer verdict=%s on_topic=%s feedback_items=%d",
            judgement.status,
            judgement.addresses_requested_topic,
            len(judgement.feedback),
        )
        return judgement
