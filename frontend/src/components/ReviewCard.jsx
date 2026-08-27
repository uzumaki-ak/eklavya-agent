// The Reviewer agent's verdict. Always shown, pass or fail — the transparency
// of the check is the point, so a "fail" is framed as the helper catching
// something, not as the child having done anything wrong.
//
// The copy differs between the first and second check: after the first, a
// rewrite really does follow, but the refinement pass is capped at one, so a
// failed second check is the end of the road. Saying "the lesson gets
// rewritten" there would promise something that never arrives.

import { MarkingPen, StarSticker } from "./icons";

const SUMMARY = {
  firstPass: "Everything looked right for your grade, so this is ready to read.",
  firstFail: "The checker spotted some problems, so the lesson gets rewritten.",
  finalPass: "The rewrite fixed the problems, so this is ready to read.",
  finalFail:
    "The rewrite is still not quite right, so this one isn't approved. Try asking again.",
};

export default function ReviewCard({ review, isFinal = false }) {
  if (!review) return null;

  const passed = review.status === "pass";
  const items = (review.feedback || []).filter((item) => item.trim());

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

      <h2>{isFinal ? "Second check" : "The checker's report"}</h2>

      <p className="review-summary">{summary}</p>

      {items.length > 0 && (
        <ul className="feedback-list">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
