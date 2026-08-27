// Shown while the agents work. Rotating facts give kids something to read
// instead of a spinner, which makes the wait feel shorter.

import { useEffect, useState } from "react";
import { randomFact } from "../lib/facts";
import Mascot from "./Mascot";
import { FoldedNote } from "./icons";

const ROTATE_MS = 7000;

const STAGE_COPY = {
  generate: { mood: "writing", text: "Your helper is writing your lesson…" },
  review: { mood: "checking", text: "Now it's double-checking the work…" },
  refine: { mood: "polishing", text: "Fixing a few things to make it better…" },
};

export default function FunFactLoader({ stage = "generate" }) {
  const [fact, setFact] = useState(() => randomFact());
  const { mood, text } = STAGE_COPY[stage] ?? STAGE_COPY.generate;

  useEffect(() => {
    const timer = setInterval(() => setFact((prev) => randomFact(prev)), ROTATE_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="loading">
      <Mascot mood={mood} size={104} />
      <h3>{text}</h3>

      <div className="fact-box">
        <div className="fact-header">
          <FoldedNote size={22} />
          <span className="fact-label">Did you know?</span>
        </div>
        <div className="fact-text">{fact}</div>
      </div>
    </div>
  );
}
