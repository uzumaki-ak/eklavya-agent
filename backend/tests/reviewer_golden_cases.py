"""The hand-labelled cases. See `reviewer_golden_set.py` for the method.

Four cases expect `pass` and eight expect `fail`. The imbalance is deliberate —
defects are more varied than correctness — which is exactly why the evaluator
reports balanced accuracy rather than raw agreement.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenCase:
    name: str
    grade: int
    topic: str
    content: dict
    expected_status: str  # "pass" | "fail"
    expected_on_topic: bool
    why: str


def _case(name, grade, topic, explanation, mcqs, expected, on_topic, why):
    """Compact constructor: (question, [options], answer) tuples become MCQ dicts."""
    return GoldenCase(
        name=name,
        grade=grade,
        topic=topic,
        content={
            "explanation": explanation,
            "mcqs": [{"question": q, "options": o, "answer": a} for q, o, a in mcqs],
        },
        expected_status=expected,
        expected_on_topic=on_topic,
        why=why,
    )


GOLDEN_SET: list[GoldenCase] = [
    _case(
        "good_on_topic", 4, "Types of angles",
        "An angle is the corner made when two lines meet. A right angle is exactly 90 degrees, "
        "like the corner of a book. An acute angle is smaller than a right angle. An obtuse "
        "angle is bigger than a right angle but smaller than a straight line.",
        [("How many degrees is a right angle?",
          ["45 degrees", "90 degrees", "180 degrees", "360 degrees"], "90 degrees")],
        "pass", True,
        "Correct, grade-appropriate, on topic, plausible distractors.",
    ),
    _case(
        "off_topic_but_coherent", 1, "quantum entanglement",
        "Water is all around us. Water can be ice. Ice is hard and cold. Water can also be "
        "liquid. Liquid water flows and pours.",
        [("What is ice?", ["A solid", "A liquid", "A gas", "A cloud"], "A solid")],
        "fail", False,
        "THE live failure. A good lesson on the wrong subject is still wrong.",
    ),
    _case(
        "factually_wrong", 5, "The solar system",
        "The Sun goes around the Earth once every year. There are eight planets and the Sun "
        "orbits all of them.",
        [("What goes around the Earth every year?",
          ["The Sun", "The Moon", "Mars", "Jupiter"], "The Sun")],
        "fail", True,
        "On topic but geocentric - conceptual correctness must catch this.",
    ),
    _case(
        "too_advanced_for_grade", 2, "Photosynthesis",
        "Photosynthesis is the biochemical process whereby chlorophyll within the chloroplast "
        "organelles catalyses the conversion of carbon dioxide and water into glucose, "
        "utilising photonic energy, with oxygen as a byproduct.",
        [("Which organelle contains chlorophyll?",
          ["Chloroplast", "Mitochondrion", "Ribosome", "Nucleus"], "Chloroplast")],
        "fail", True,
        "Correct and on topic, but unreadable for Grade 2.",
    ),
    _case(
        "question_not_taught", 4, "The water cycle",
        "Water goes up into the sky when the sun warms it. Then it comes back down as rain. "
        "This happens again and again.",
        [("At what temperature does water boil at sea level?",
          ["50 C", "75 C", "100 C", "150 C"], "100 C")],
        "fail", True,
        "Question tests something the explanation never taught.",
    ),
    _case(
        "elimination_only_distractors", 1, "Black holes",
        "A black hole is a place in space that pulls very hard. It pulls so hard that even "
        "light cannot get out.",
        [("What is a black hole?",
          ["A place in space that pulls very hard", "A warm cozy blanket",
           "A fast racing car", "A tall green tree"],
          "A place in space that pulls very hard")],
        "fail", True,
        "Live miss. Answerable by elimination - criterion 6 should fire.",
    ),
    _case(
        "near_duplicate_options", 4, "Types of angles",
        "An acute angle is smaller than a right angle.",
        [("What is an angle smaller than 90 degrees called?",
          ["An acute angle", "A tiny angle", "A small angle", "A big angle"], "An acute angle")],
        "fail", True,
        "Live miss. 'Tiny'/'small' are not terms and both mean acute.",
    ),
    _case(
        "hard_topic_simplified_well", 1, "Gravity",
        "Gravity is a pull. It pulls things down to the ground. When you drop a ball, gravity "
        "pulls it down. Gravity is why we do not float away.",
        [("What does gravity do to a ball you drop?",
          ["Pulls it down", "Pushes it up", "Makes it vanish", "Turns it blue"],
          "Pulls it down")],
        "pass", True,
        "Guards the other direction: a hard topic simplified well must PASS.",
    ),
    _case(
        "incorrect_answer_key", 3, "Multiplication tables",
        "Multiplication is repeated addition. 3 times 4 means 4 + 4 + 4.",
        [("What is 3 times 4?", ["10", "12", "14", "15"], "10")],
        "fail", True,
        "Structurally valid, but the recorded answer is factually wrong.",
    ),
    _case(
        "partially_off_topic", 5, "Food chains",
        "A food chain shows who eats whom. Grass is eaten by a rabbit. The rabbit is eaten by "
        "a fox. Also, the Earth orbits the Sun once a year, and the Moon orbits the Earth.",
        [("What eats the rabbit?", ["A fox", "The grass", "The Sun", "The Moon"], "A fox")],
        "fail", True,
        "Mostly on topic but padded with unrelated facts.",
    ),
    _case(
        "good_older_grade", 8, "Newton's first law",
        "Newton's first law says an object stays still, or keeps moving at the same speed in "
        "the same direction, unless a force acts on it. This resistance to a change in motion "
        "is called inertia. A book on a table stays put because gravity pulling it down is "
        "balanced by the table pushing it up.",
        [("Why does a book on a table stay still?",
          ["The forces on it are balanced", "It has no mass",
           "Gravity does not act on it", "Inertia pushes it upward"],
          "The forces on it are balanced")],
        "pass", True,
        "Second pass case at an older grade, with genuinely tempting distractors.",
    ),
    _case(
        "good_with_plausible_distractors", 3, "The water cycle",
        "The sun warms water in rivers and seas. The water turns into vapour and rises. This "
        "is evaporation. High up it cools and turns back into tiny drops, which make clouds. "
        "When the drops get heavy they fall as rain.",
        [("What is it called when water turns into vapour and rises?",
          ["Evaporation", "Condensation", "Precipitation", "Collection"], "Evaporation")],
        "pass", True,
        "Distractors are the real neighbouring terms - hardest kind to get right.",
    ),
]
