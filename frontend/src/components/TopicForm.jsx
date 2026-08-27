// Grade picker + topic input. Grades are chips rather than a dropdown —
// easier to tap, and shows the whole range at once.

import { useState } from "react";
import { PaperPlane } from "./icons";

// Full 1-12 range, matching what the backend schema accepts.
const GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

// Per-grade starter topics, so a kid who doesn't know what to type isn't stuck.
const SUGGESTIONS = {
  1: ["Shapes around us", "Counting to 20", "Day and night"],
  2: ["Adding numbers", "Parts of plants", "Our five senses"],
  3: ["Multiplication tables", "The water cycle", "Living and non-living"],
  4: ["Types of angles", "Fractions", "The solar system"],
  5: ["Decimals", "Food chains", "States of matter"],
  6: ["Integers", "Photosynthesis", "Simple machines"],
  7: ["Algebra basics", "The human heart", "Acids and bases"],
  8: ["Linear equations", "Newton's laws", "Cell structure"],
  9: ["Quadratic equations", "Periodic table", "Tissues"],
  10: ["Trigonometry", "Chemical reactions", "Light and reflection"],
  11: ["Limits and derivatives", "Thermodynamics", "Cell cycle"],
  12: ["Integration", "Electromagnetism", "Genetics"],
};

export default function TopicForm({ onSubmit, busy }) {
  const [grade, setGrade] = useState(4);
  const [topic, setTopic] = useState("");

  const canSubmit = topic.trim().length > 0 && !busy;

  const handleSubmit = (event) => {
    event.preventDefault();
    if (canSubmit) onSubmit(grade, topic.trim());
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <div className="field">
        <label id="grade-label">What class are you in?</label>
        <div className="grade-picker" role="group" aria-labelledby="grade-label">
          {GRADES.map((value) => (
            <button
              key={value}
              type="button"
              className="grade-chip"
              aria-pressed={grade === value}
              onClick={() => setGrade(value)}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label htmlFor="topic">What do you want to learn about?</label>
        <input
          id="topic"
          className="topic-input"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="Try 'types of angles'"
          maxLength={200}
          autoComplete="off"
        />

        <div className="suggestions">
          {(SUGGESTIONS[grade] || []).map((item) => (
            <button
              key={item}
              type="button"
              className="suggestion"
              onClick={() => setTopic(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <button className="btn-go" type="submit" disabled={!canSubmit}>
        <PaperPlane size={26} />
        {busy ? "Working…" : "Teach me!"}
      </button>
    </form>
  );
}
