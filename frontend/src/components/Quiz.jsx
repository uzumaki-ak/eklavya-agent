// Interactive MCQs. Answering is per-question and non-punishing:
// a wrong pick reveals the right one rather than just saying "no".

import { useState } from "react";
import { StarSticker } from "./icons";

const CONFETTI = Array.from({ length: 18 }, (_, index) => {
  const angle = (index / 18) * Math.PI * 2;
  const distance = 58 + (index % 4) * 14;
  const colors = ["#7c5cff", "#2ec27e", "#ff9f1c", "#ff6b9d", "#38b6ff"];

  return {
    "--confetti-x": `${Math.round(Math.cos(angle) * distance)}px`,
    "--confetti-rise": `${Math.round(Math.sin(angle) * distance - 42)}px`,
    "--confetti-fall": `${72 + (index % 5) * 10}px`,
    "--confetti-spin": `${180 + index * 29}deg`,
    "--confetti-delay": `${(index % 4) * 0.025}s`,
    "--confetti-color": colors[index % colors.length],
  };
});

function ConfettiBurst() {
  return (
    <span className="confetti-burst" aria-hidden="true">
      {CONFETTI.map((style, index) => (
        <i key={index} className="confetti-piece" style={style} />
      ))}
    </span>
  );
}

function TickMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 13l5 5 11-13" stroke="#2ec27e" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CrossMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="#e5484d" strokeWidth="3.5" strokeLinecap="round" />
    </svg>
  );
}

function Question({ mcq, index, disabled }) {
  const [picked, setPicked] = useState(null);
  const answered = picked !== null;
  const correct = picked === mcq.answer;

  const optionClass = (option) => {
    if (!answered) return "option";
    if (option === mcq.answer) return "option correct";
    if (option === picked) return "option wrong";
    return "option";
  };

  return (
    <div className="mcq">
      {correct && <ConfettiBurst />}
      <div className="mcq-question">
        {index + 1}. {mcq.question}
      </div>

      <div className="options">
        {mcq.options.map((option) => (
          <button
            key={option}
            className={optionClass(option)}
            onClick={() => setPicked(option)}
            disabled={answered || disabled}
          >
            <span>{option}</span>
            {answered && option === mcq.answer && <TickMark />}
            {answered && option === picked && option !== mcq.answer && <CrossMark />}
          </button>
        ))}
      </div>

      {answered && (
        <p className="mcq-result">
          {correct ? <StarSticker size={22} /> : null}
          {correct ? "Nice one!" : "Not quite — the green one is right."}
        </p>
      )}
    </div>
  );
}

export default function Quiz({ mcqs = [], disabled = false }) {
  if (!mcqs.length) return null;
  return (
    <div className="quiz">
      <h3 className="quiz-heading">
        {disabled ? "Questions from this draft" : "Try the quiz"}
      </h3>
      <div className="quiz-grid">
        {mcqs.map((mcq, index) => (
          <Question key={mcq.question} mcq={mcq} index={index} disabled={disabled} />
        ))}
      </div>
    </div>
  );
}
