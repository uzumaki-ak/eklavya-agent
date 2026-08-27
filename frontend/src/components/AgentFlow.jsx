// The three-stage stepper. This is what makes the agent pipeline visible:
// a kid can see the helper write, then check, then fix.

import { Fragment } from "react";
import { EraserFixing, MarkingPen, PencilWriting, StarSticker } from "./icons";

const STEPS = [
  { key: "generate", Icon: PencilWriting, label: "Writing" },
  { key: "review", Icon: MarkingPen, label: "Checking" },
  { key: "refine", Icon: EraserFixing, label: "Fixing" },
];

// Maps job state onto per-step status. "Fixing" only appears once the
// reviewer actually asks for a rewrite.
function stepStates(job) {
  if (!job) return { generate: "idle", review: "idle", refine: "idle" };

  const failed =
    job.status?.endsWith("_error") ||
    job.status === "moderation_blocked" ||
    job.status === "moderation_error";
  const hasDraft = Boolean(job.original_output);
  const hasReview = Boolean(job.initial_review);
  const wasRefined = Boolean(job.refined_output);
  const finished = job.status?.startsWith("completed");

  // On a terminal failure nothing is still in progress — a step is either
  // already done or it never happened. Leaving one "active" would animate forever.
  if (failed) {
    return {
      generate: hasDraft ? "done" : "idle",
      review: hasReview ? "done" : "idle",
      refine: wasRefined ? "done" : "idle",
    };
  }

  return {
    generate: hasDraft ? "done" : "active",
    review: hasReview ? "done" : hasDraft ? "active" : "idle",
    refine: wasRefined && finished ? "done"
      : wasRefined ? "active"
      : hasReview && job.initial_review.status === "fail" ? "active"
      : "idle",
  };
}

export default function AgentFlow({ job }) {
  const states = stepStates(job);
  const refineNeeded = job?.initial_review?.status === "fail" || Boolean(job?.refined_output);
  const visible = refineNeeded ? STEPS : STEPS.slice(0, 2);

  return (
    <div className="flow" role="status" aria-live="polite">
      {visible.map(({ key, Icon, label }, index) => (
        <Fragment key={key}>
          {index > 0 && (
            <div
              className={`step-connector ${
                states[visible[index - 1].key] === "done" ? "filled" : ""
              }`}
            />
          )}
          <div className={`step ${states[key]}`}>
            <div className="step-bubble">
              {states[key] === "done" ? <StarSticker size={30} /> : <Icon size={30} />}
            </div>
            <div className="step-label">{label}</div>
          </div>
        </Fragment>
      ))}
    </div>
  );
}
