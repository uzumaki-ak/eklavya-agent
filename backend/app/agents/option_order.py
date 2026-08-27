"""Deterministic MCQ option ordering.

The model writes the correct answer first and then pads with distractors, so
generated quizzes were answerable by always tapping the top box: across a live
sample of nine questions the answer sat at index 0 six times and index 1 three
times, never lower. Asking a model to randomise the position in the prompt is
advisory and unreliable, so the order is fixed in code instead.

The permutation is a pure function of the question and its option set. That keeps
it stable across regenerations and cache reuse, and idempotent - sorting before
shuffling means re-applying it cannot move anything a second time.
"""

import hashlib
import random

_SEED_BYTES = 8


def _seed(question: str, ordered: list[str]) -> int:
    material = "|".join([question, *ordered]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:_SEED_BYTES], "big")


def balanced_options(question: str, options: list[str]) -> list[str]:
    """Same options, in a stable order that does not favour any position."""
    ordered = sorted(options)
    random.Random(_seed(question, ordered)).shuffle(ordered)
    return ordered
