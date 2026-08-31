// The Reviewer agent's verdict. Always shown, pass or fail — the transparency
// of the check is the point, so a "fail" is framed as the helper catching
// something, not as the child having done anything wrong.
//
// Part 2 made the review quantitative: four 1-5 scores, and feedback anchored to
// the field it is about. Both are shown. The scores are what the pass/fail
// decision is actually computed from, so hiding them would leave the verdict
// looking like an opinion when it is arithmetic.

import { MarkingPen, StarSticker } from "./icons";

const SUMMARY = {
  firstPass: "Everything looked right for your grade, so this is ready to read.",
  firstFail: "The checker spotted some problems, so the lesson gets rewritten.",
  finalPass: "The rewrite fixed the problems, so this is ready to read.",
  finalFail:
    "The rewrite is still not quite right, so this one isn't approved. Try asking again.",
};

// Child-facing names for the scored dimensions, in the order they are judged.
const DIMENSIONS = [
  ["age_appropriateness", "Right for your grade"],
  ["correctness", "Facts are right"],
  ["clarity", "Easy to follow"],
  ["coverage", "Answers what you asked"],
];

// Where in the lesson a piece of feedback points, in words rather than a path.
function plainField(path) {
  if (path.startsWith("teacher_notes")) return "Notes for the grown-up";
  if (path.startsWith("explanation")) return "The explanation";
  const question = path.match(/^mcqs\[(\d+)\]/);
  return question ? `Question ${Number(question[1]) + 1}` : path;
}

function ScoreRow({ scores }) {
  if (!scores) return null;
  return (
    <ul className="score-row">
      {DIMENSIONS.map(([key, label]) => (
        <li key={key} className="score">
          <span className="score-label">{label}</span>
          <span className="score-value" aria-label={`${scores[key]} out of 5`}>
            {scores[key]}/5
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function ReviewCard({ review, isFinal = false }) {
  if (!review) return null;

  const passed = review.pass === true;
  const items = (review.feedback || []).filter((item) => item?.issue?.trim());

  const summary = isFinal
    ? passed
      ? SUMMARY.finalPass
      : SUMMARY.finalFail
    : passed
      ? SUMMARY.firstPass
      : SUMMARY.firstFail;

  return (
    <section className={`card ${passed ? "review-pass" : "review-fail"}`}>
      <span className={`card-tag ${passed ? "tag-pass" : "tag-fail"}`}>
        {passed ? <StarSticker size={18} /> : <MarkingPen size={18} />}
        {passed ? "Checked and approved" : "Found things to fix"}
      </span>

      <h2>{isFinal ? "Final check" : "The checker's report"}</h2>

      <p className="review-summary">{summary}</p>

      <ScoreRow scores={review.scores} />

      {items.length > 0 && (
        <ul className="feedback-list">
          {items.map((item) => (
            <li key={`${item.field}:${item.issue}`}>
              <span className="feedback-field">{plainField(item.field)}</span>
              {item.issue}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
