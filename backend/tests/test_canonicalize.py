"""Cache-key canonicalization tests.

The point of these: "Types of Angles" and "types of angle" must land on the same
cache entry, or popular topics never actually get cached.
"""

import pytest

from app.services.canonicalize import canonicalize_topic


@pytest.mark.parametrize(
    "raw",
    [
        "Types of angles",
        "  Types of Angles  ",
        "TYPES OF ANGLES",
        "types-of-angles",
        "Types of angles!!!",
        "types  of   angles",
        "Types of angle",  # alias
        "Angle types",  # alias
    ],
)
def test_variants_collapse_to_one_key(raw):
    assert canonicalize_topic(raw) == "types of angles"


def test_distinct_topics_stay_distinct():
    # Canonicalization must not over-merge — these are different lessons.
    assert canonicalize_topic("Fractions") != canonicalize_topic("Decimals")


def test_unicode_is_normalized():
    # Full-width characters normalize to their ASCII equivalents under NFKC.
    assert canonicalize_topic("ｆｒａｃｔｉｏｎｓ") == "fractions"


def test_empty_input_yields_empty_string():
    assert canonicalize_topic("   !!!   ") == ""
