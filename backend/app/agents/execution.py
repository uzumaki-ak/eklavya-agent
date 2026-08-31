"""Shared execution context and the bounded schema-repair pass.

All four agents need the same loop: call the model, validate, and on a validation
failure hand the error back once and try again. Keeping one implementation means
the retry budget is provably identical across agents rather than four times
nearly-identical.

Two failure classes are deliberately kept apart here:
  - *schema* failures (this loop) — the model produced the wrong content, so the
    fix is to tell it what was wrong and ask again.
  - *transport* failures (Tenacity, inside `call_llm`) — the call never landed, so
    the fix is to repeat it unchanged.
Merging them would let a network blip consume the model's one chance to correct
itself.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from app.agents.client import call_llm
from app.agents.providers import LLMRoleConfig
from app.core.config import settings
from app.core.exceptions import ContentContractError, LLMStructuredOutputError

logger = logging.getLogger(__name__)

# What a repair loop treats as "the model got it wrong", as opposed to "the call
# failed". ContentContractError is included so request-relative rules get the
# same one retry as schema rules.
REPAIRABLE = (ValidationError, LLMStructuredOutputError, ContentContractError)


@dataclass
class ExecutionContext:
    """Runtime concerns, deliberately separate from an agent's I/O contract.

    Counter keys: "schema_repair_attempts" and "transport_attempts". They are
    summed into the run state by the pipeline nodes and end up in the artifact's
    provenance, which is how "this run needed three retries" becomes auditable
    rather than merely logged.
    """

    deadline: float
    counters: dict[str, int] = field(default_factory=dict)

    @property
    def schema_repair_attempts(self) -> int:
        return self.counters.get("schema_repair_attempts", 0)

    @property
    def transport_attempts(self) -> int:
        return self.counters.get("transport_attempts", 0)


async def call_with_repair(
    *,
    role: str,
    config: LLMRoleConfig,
    system: str,
    user: str,
    output_format: type[BaseModel],
    ctx: ExecutionContext,
    validate: Callable[[BaseModel], None] | None = None,
    repair_hint: str = "",
) -> BaseModel:
    """One structured call plus a bounded repair pass.

    `validate` runs extra checks that need context the schema cannot see; raising
    ContentContractError from it spends a repair attempt exactly as a schema
    failure would.
    """
    max_repairs = settings.schema_repair_max_attempts
    repair_feedback = ""

    for attempt in range(max_repairs + 1):
        try:
            output = await call_llm(
                config=config,
                system=system,
                user=user + repair_feedback,
                output_format=output_format,
                deadline=ctx.deadline,
                counters=ctx.counters,
            )
            if validate is not None:
                validate(output)
            ctx.counters["schema_repair_attempts"] = (
                ctx.counters.get("schema_repair_attempts", 0) + attempt
            )
            return output

        except REPAIRABLE as exc:
            if attempt == max_repairs:
                ctx.counters["schema_repair_attempts"] = (
                    ctx.counters.get("schema_repair_attempts", 0) + attempt
                )
                logger.warning(
                    "%s schema repair exhausted after %d repair(s): %s", role, attempt, exc
                )
                raise
            logger.info("%s output failed validation, repairing (%d)", role, attempt + 1)
            repair_feedback = (
                f"\n\nYour previous response was rejected: {exc}\n"
                f"Fix exactly that problem and resend the whole object.{repair_hint}"
            )

    raise AssertionError("unreachable")  # pragma: no cover - the loop always exits
