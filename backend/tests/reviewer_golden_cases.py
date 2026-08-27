"""The hand-labelled cases. See `reviewer_golden_set.py` for the method."""

from tests.reviewer_golden_set import GoldenCase

GOLDEN_SET: list[GoldenCase] = [
    GoldenCase(
        name="good_on_topic",
        grade=4,
        topic="Types of angles",
        content={
            "explanation": "An angle is the corner made when two lines meet. A right angle is exactly 90 degrees, like the corner of a book. An acute angle is smaller than a right angle. An obtuse angle is bigger than a right angle but smaller than a straight line.",
            "mcqs": [
                {
                    "question": "How many degrees is a right angle?",
                    "options": ["45 degrees", "90 degrees", "180 degrees", "360 degrees"],
                    "answer": "90 degrees",
                }
            ],
        },
        expected_status="pass",
        expected_on_topic=True,
        why="Correct, grade-appropriate, on topic, plausible distractors.",
    ),
    GoldenCase(
        name="off_topic_but_coherent",
        grade=1,
        topic="quantum entanglement",
        content={
            "explanation": "Water is all around us. Water can be ice. Ice is hard and cold. Water can also be liquid. Liquid water flows and pours.",
            "mcqs": [
                {
                    "question": "What is ice?",
                    "options": ["A solid", "A liquid", "A gas", "A cloud"],
                    "answer": "A solid",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=False,
        why="THE live failure. A good lesson on the wrong subject is still wrong.",
    ),
    GoldenCase(
        name="factually_wrong",
        grade=5,
        topic="The solar system",
        content={
            "explanation": "The Sun goes around the Earth once every year. There are eight planets and the Sun orbits all of them.",
            "mcqs": [
                {
                    "question": "What goes around the Earth every year?",
                    "options": ["The Sun", "The Moon", "Mars", "Jupiter"],
                    "answer": "The Sun",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="On topic but geocentric — conceptual correctness must catch this.",
    ),
    GoldenCase(
        name="too_advanced_for_grade",
        grade=2,
        topic="Photosynthesis",
        content={
            "explanation": "Photosynthesis is the biochemical process whereby chlorophyll within the chloroplast organelles catalyses the conversion of carbon dioxide and water into glucose, utilising photonic energy, with oxygen as a byproduct.",
            "mcqs": [
                {
                    "question": "Which organelle contains chlorophyll?",
                    "options": ["Chloroplast", "Mitochondrion", "Ribosome", "Nucleus"],
                    "answer": "Chloroplast",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="Correct and on topic, but unreadable for Grade 2.",
    ),
    GoldenCase(
        name="question_not_taught",
        grade=4,
        topic="The water cycle",
        content={
            "explanation": "Water goes up into the sky when the sun warms it. Then it comes back down as rain. This happens again and again.",
            "mcqs": [
                {
                    "question": "At what temperature does water boil at sea level?",
                    "options": ["50 C", "75 C", "100 C", "150 C"],
                    "answer": "100 C",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="Question tests something the explanation never taught.",
    ),
    GoldenCase(
        name="elimination_only_distractors",
        grade=1,
        topic="Black holes",
        content={
            "explanation": "A black hole is a place in space that pulls very hard. It pulls so hard that even light cannot get out.",
            "mcqs": [
                {
                    "question": "What is a black hole?",
                    "options": [
                        "A place in space that pulls very hard",
                        "A warm cozy blanket",
                        "A fast racing car",
                        "A tall green tree",
                    ],
                    "answer": "A place in space that pulls very hard",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="Live miss. Answerable by elimination — criterion 6 should fire.",
    ),
    GoldenCase(
        name="near_duplicate_options",
        grade=4,
        topic="Types of angles",
        content={
            "explanation": "An acute angle is smaller than a right angle.",
            "mcqs": [
                {
                    "question": "What is an angle smaller than 90 degrees called?",
                    "options": ["An acute angle", "A tiny angle", "A small angle", "A big angle"],
                    "answer": "An acute angle",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="Live miss. 'Tiny'/'small' are not terms and both mean acute.",
    ),
    GoldenCase(
        name="hard_topic_simplified_well",
        grade=1,
        topic="Gravity",
        content={
            "explanation": "Gravity is a pull. It pulls things down to the ground. When you drop a ball, gravity pulls it down. Gravity is why we do not float away.",
            "mcqs": [
                {
                    "question": "What does gravity do to a ball you drop?",
                    "options": [
                        "Pulls it down",
                        "Pushes it up",
                        "Makes it vanish",
                        "Turns it blue",
                    ],
                    "answer": "Pulls it down",
                }
            ],
        },
        expected_status="pass",
        expected_on_topic=True,
        why="Guards the other direction: a hard topic simplified well must PASS.",
    ),
    GoldenCase(
        name="answer_not_among_options",
        grade=3,
        topic="Multiplication tables",
        content={
            "explanation": "Multiplication is repeated addition. 3 times 4 means 4 + 4 + 4.",
            "mcqs": [
                {
                    "question": "What is 3 times 4?",
                    "options": ["7", "10", "14", "15"],
                    "answer": "12",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="Structurally impossible answer. Schema catches it first, but the Reviewer should too if it ever reaches here.",
    ),
    GoldenCase(
        name="partially_off_topic",
        grade=5,
        topic="Food chains",
        content={
            "explanation": "A food chain shows who eats whom. Grass is eaten by a rabbit. The rabbit is eaten by a fox. Also, the Earth orbits the Sun once a year, and the Moon orbits the Earth.",
            "mcqs": [
                {
                    "question": "What eats the rabbit?",
                    "options": ["A fox", "The grass", "The Sun", "The Moon"],
                    "answer": "A fox",
                }
            ],
        },
        expected_status="fail",
        expected_on_topic=True,
        why="Mostly on topic but padded with unrelated facts — 'stay on topic'.",
    ),
]
