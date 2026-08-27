"""Generator Agent — drafts explanation + MCQs for a (grade, topic) pair.

Responsibility: produce grade-appropriate, factually correct draft content.
Structured input: GeneratorInput. Structured output: GeneratorOutput.

The public contract is exactly the spec's: GeneratorInput -> GeneratorOutput.
Execution concerns (deadline, retry counters) travel in a separate context object
so they never pollute the declared agent interface.
"""

import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.agents.client import GENERATOR_CONFIG, call_llm
from app.agents.option_order import balanced_options
from app.agents.prompts import (
    escape_topic,
    GENERATOR_REFINE_USER,
    GENERATOR_SYSTEM,
    GENERATOR_USER,
    grade_band_guidance,
)
from app.core.config import settings
from app.core.exceptions import LLMStructuredOutputError
from app.schemas.content import GeneratorInput, GeneratorOutput

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Runtime concerns, deliberately separate from the agent's I/O contract."""

    deadline: float
    feedback: list[str] | None = None  # set for the refinement pass
    schema_repair_attempts: int = 0  # written back by the agent
    counters: dict = field(default_factory=dict)  # transport_attempts, written back


def _spread_answer_positions(output: GeneratorOutput) -> GeneratorOutput:
    """Reorder options so the answer is not predictably first.

    Runs after validation, so the answer is already known to be one of the four
    options; a permutation cannot break that. The Reviewer therefore judges the
    same order the child sees.
    """
    for mcq in output.mcqs:
        mcq.options = balanced_options(mcq.question, mcq.options)
    return output


class GeneratorAgent:
    """Input: GeneratorInput. Output: GeneratorOutput."""

    async def run(self, data: GeneratorInput, ctx: ExecutionContext) -> GeneratorOutput:
        system = GENERATOR_SYSTEM.format(band=grade_band_guidance(data.grade))

        if ctx.feedback:
            user = GENERATOR_REFINE_USER.format(
                grade=data.grade,
                topic=escape_topic(data.topic),
                feedback="\n".join(f"- {item}" for item in ctx.feedback),
            )
        else:
            user = GENERATOR_USER.format(grade=data.grade, topic=escape_topic(data.topic))

        output = await self._generate_with_repair(system, user, ctx)
        return _spread_answer_positions(output)

    async def _generate_with_repair(
        self, system: str, user: str, ctx: ExecutionContext
    ) -> GeneratorOutput:
        """Retry on ValidationError only.

        Shape is guaranteed by the API, but cross-field rules (answer must be one
        of the options, options must be distinct) are Python-level and can still
        fail. Those raise locally and are invisible to the transport retry layer,
        so they need their own bounded loop that feeds the error back to the model.
        """
        repair_feedback = ""
        max_attempts = settings.schema_repair_max_attempts

        for attempt in range(max_attempts + 1):
            try:
                output = await call_llm(
                    config=GENERATOR_CONFIG,
                    system=system,
                    user=user + repair_feedback,
                    output_format=GeneratorOutput,
                    deadline=ctx.deadline,
                    counters=ctx.counters,
                )
                ctx.schema_repair_attempts = attempt
                return output

            except (ValidationError, LLMStructuredOutputError) as exc:
                if attempt == max_attempts:
                    logger.warning("generator schema repair exhausted after %d attempts", attempt)
                    ctx.schema_repair_attempts = attempt
                    raise
                logger.info("generator output failed validation, repairing (%d)", attempt + 1)
                repair_feedback = (
                    f"\n\nYour previous response was rejected: {exc}. "
                    "Fix exactly that problem and resend the whole thing."
                )

        raise AssertionError("unreachable")
