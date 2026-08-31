"""Closed target vocabulary for the demo moderation policy.

The regex and its coverage test share this one source. Each pair is the common
singular and plural form; irregular forms stay explicit rather than inferred.
"""

import re

PROTECTED_TARGET_FORMS: tuple[tuple[str, str], ...] = (
    ("student", "students"),
    ("kid", "kids"),
    ("child", "children"),
    ("classmate", "classmates"),
    ("teacher", "teachers"),
    ("person", "people"),
    ("bully", "bullies"),
    ("friend", "friends"),
    ("sibling", "siblings"),
    ("neighbour", "neighbours"),
    ("neighbor", "neighbors"),
    ("brother", "brothers"),
    ("sister", "sisters"),
    ("cousin", "cousins"),
    ("baby", "babies"),
    ("toddler", "toddlers"),
    ("infant", "infants"),
    ("human", "humans"),
    ("mum", "mums"),
    ("mom", "moms"),
    ("mother", "mothers"),
    ("dad", "dads"),
    ("father", "fathers"),
    ("aunt", "aunts"),
    ("uncle", "uncles"),
    ("grandma", "grandmas"),
    ("grandpa", "grandpas"),
    ("grandmother", "grandmothers"),
    ("grandfather", "grandfathers"),
    ("grandparent", "grandparents"),
    ("boy", "boys"),
    ("girl", "girls"),
    ("man", "men"),
    ("woman", "women"),
    ("animal", "animals"),
    ("pet", "pets"),
    ("dog", "dogs"),
    ("cat", "cats"),
)

_TARGETS = {form for pair in PROTECTED_TARGET_FORMS for form in pair}
PROTECTED_TARGET_PATTERN = "(?:" + "|".join(
    re.escape(target) for target in sorted(_TARGETS, key=lambda value: (-len(value), value))
) + ")"
