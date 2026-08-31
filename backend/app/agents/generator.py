"""Generator Agent — drafts a lesson for a (grade, topic) pair.

Responsibility: produce grade-appropriate, factually correct draft content.
Structured input: GeneratorInput. Structured output: GeneratorOutput.

The public contract is exactly the spec's. Execution concerns (deadline, retry
counters) travel in a separate ExecutionContext so they never pollute the
declared agent interface.

Scope note: this agent writes from a topic. Revising an existing draft against
reviewer feedback is a different job with different instructions, and belongs to
`app.agents.refiner`.
"""

import logging

from app.agents.client import GENERATOR_CONFIG
from app.agents.contract import check_generated_matches_request
from app.agents.execution import ExecutionContext, call_with_repair
from app.agents.option_order import balanced_output
from app.agents.prompts import (
    GENERATOR_SYSTEM,
    GENERATOR_USER,
    escape_topic,
    grade_band_guidance,
)
from app.schemas.content import GeneratorInput, GeneratorOutput

logger = logging.getLogger(__name__)

# Appended to a repair request. The index is the field models get wrong most
# often, and reminding them of the rule costs nothing on the retry path.
_REPAIR_HINT = (
    " Remember that correct_index is 0-based and must point at the one correct "
    "option, and that explanation.grade must equal the requested grade."
)


class GeneratorAgent:
    """Input: GeneratorInput. Output: GeneratorOutput."""

    async def run(self, data: GeneratorInput, ctx: ExecutionContext) -> GeneratorOutput:
        system = GENERATOR_SYSTEM.format(band=grade_band_guidance(data.grade))
        user = GENERATOR_USER.format(grade=data.grade, topic=escape_topic(data.topic))

        output = await call_with_repair(
            role="generator",
            config=GENERATOR_CONFIG,
            system=system,
            user=user,
            output_format=GeneratorOutput,
            ctx=ctx,
            validate=lambda draft: check_generated_matches_request(draft, data),
            repair_hint=_REPAIR_HINT,
        )

        # After validation, so the index is already known to be in range; the
        # rebalancing re-derives it rather than carrying it across.
        return balanced_output(output)
