// The Reviewer agent's verdict. Always shown, pass or fail — the transparency
// of the check is the point, so a "fail" is framed as the helper catching
// something, not as the child having done anything wrong.

import { MarkingPen, StarSticker } from "./icons";

export default function ReviewCard({ review, isFinal = false }) {
  if (!review) return null;

  const passed = review.status === "pass";
  const items = (review.feedback || []).filter((item) => item.trim());

  return (
    <section className={`card ${passed ? "review-pass" : "review-fail"}`}>
      <span className={`card-tag ${passed ? "tag-pass" : "tag-fail"}`}>
        {passed ? <StarSticker size={18} /> : <MarkingPen size={18} />}
        {passed ? "Checked and approved" : "Found things to fix"}
      </span>

      <h2>{isFinal ? "Second check" : "The checker's report"}</h2>

      <p className="review-summary">
        {passed
          ? "Everything looked right for your grade, so this is ready to read."
          : "The checker spotted some problems, so the lesson gets rewritten."}
      </p>

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
