"""Pipeline-specific exceptions.

These distinguish failure *classes* that must be handled differently:
a per-call timeout is retryable, a pipeline deadline is terminal.
"""


class LLMCallTimeout(Exception):
    """One LLM call exceeded its per-call watchdog. Retryable."""


class LLMStructuredOutputError(ValueError):
    """The provider returned no schema-validated payload."""


class PipelineDeadlineExceeded(Exception):
    """The whole job ran out of its time budget. Terminal — never retried."""


class ModerationBlocked(Exception):
    """Content was flagged by moderation. Terminal, never shown to the user."""


class ModerationUnavailable(Exception):
    """The moderation check itself failed. Fails closed, but distinct from a block."""


class LeaseLost(Exception):
    """Another worker reclaimed this job. Abort immediately without writing."""


class FlightLeadershipLost(Exception):
    """Another run took over this content flight; stop generating this duplicate."""
