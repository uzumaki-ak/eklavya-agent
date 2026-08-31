"""Tagger output — classification of approved content only.

Every field is a closed enumeration except `topic`, which is a normalised label
for the thing actually taught. Closed sets are the point: tags exist to be
filtered and grouped, and a free-text `difficulty` that returns "Medium-Hard"
once in fifty runs quietly breaks every query built on it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Subject = Literal[
    "Mathematics",
    "Science",
    "English",
    "Social Studies",
    "History",
    "Geography",
    "Computer Science",
    "Art",
    "Music",
    "Physical Education",
    "General Knowledge",
]

Difficulty = Literal["Easy", "Medium", "Hard"]

ContentType = Literal["Explanation", "Quiz"]

# Bloom's revised taxonomy, lowest to highest.
BloomsLevel = Literal[
    "Remembering",
    "Understanding",
    "Applying",
    "Analyzing",
    "Evaluating",
    "Creating",
]


class ContentTags(BaseModel):
    """Spec output: subject, topic, grade, difficulty, content_type, blooms_level."""

    model_config = ConfigDict(extra="forbid")

    subject: Subject
    topic: str = Field(min_length=1, max_length=200)
    grade: int = Field(ge=1, le=12)
    difficulty: Difficulty
    content_type: list[ContentType] = Field(min_length=1, max_length=2)
    blooms_level: BloomsLevel

    @field_validator("topic")
    @classmethod
    def topic_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic must not be blank")
        return value

    @field_validator("content_type")
    @classmethod
    def content_types_are_distinct(cls, values: list[ContentType]) -> list[ContentType]:
        if len(set(values)) != len(values):
            raise ValueError("content_type must not repeat a value")
        return values
