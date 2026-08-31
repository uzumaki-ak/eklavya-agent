"""Structured moderation evidence stored in each RunArtifact."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["clear", "blocked", "error"]
    policy_version: str | None = None
    stage: str | None = None
