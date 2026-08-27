"""Topic canonicalization for cache keys.

Mechanical normalization only (NFKC + casefold + punctuation strip) plus a small
curated alias map. Deliberately NOT fuzzy/semantic matching — a loose similarity
threshold is how one user's cached content ends up served to another.
"""

import re
import unicodedata

# Hand-curated equivalences only. Add entries as real duplicates show up in logs;
# never auto-populate this from similarity scores.
ALIASES = {
    "types of angle": "types of angles",
    "angle types": "types of angles",
    "kinds of angles": "types of angles",
    "type of angles": "types of angles",
    "multiplication table": "multiplication tables",
    "the water cycle": "water cycle",
    "parts of a plant": "parts of plants",
}

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def canonicalize_topic(topic: str) -> str:
    """'  Types of ANGLES!! ' -> 'types of angles'"""
    value = unicodedata.normalize("NFKC", topic).casefold()
    value = " ".join(_WORD_RE.findall(value))
    return ALIASES.get(value, value)
