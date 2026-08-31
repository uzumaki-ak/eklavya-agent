// The three-stage stepper. This is what makes the agent pipeline visible:
// a kid can see the helper write, then check, then fix.

import { Fragment } from "react";
import { EraserFixing, LabelTag, MarkingPen, PencilWriting, StarSticker } from "./icons";

const STEPS = [
  { key: "generate", Icon: PencilWriting, label: "Writing" },
  { key: "review", Icon: MarkingPen, label: "Checking" },
  { key: "refine", Icon: EraserFixing, label: "Fixing" },
  { key: "tag", Icon: LabelTag, label: "Filing" },
];

// Maps job state onto per-step status. "Fixing" only appears once the
// reviewer actually asks for a rewrite.
function stepStates(job) {
  if (!job) return { generate: "idle", review: "idle", refine: "idle", tag: "idle" };

  const failed =
    job.status?.endsWith("_error") ||
    job.status === "moderation_blocked" ||
    job.status === "moderation_error";
  const hasDraft = Boolean(job.original_output);
  const hasReview = Boolean(job.initial_review);
  const wasRefined = Boolean(job.refined_output);
  const wasTagged = Boolean(job.tags);
  const finished = job.status?.startsWith("completed");
  // Only approved content is classified. A rejected run marks Filing as
  // skipped explicitly so the final grey step cannot look like a stalled job.
  const approved = job.status === "completed_pass";

  // On a terminal failure nothing is still in progress — a step is either
  // already done or it never happened. Leaving one "active" would animate forever.
  if (failed) {
    return {
      generate: hasDraft ? "done" : "idle",
      review: hasReview ? "done" : "idle",
      refine: wasRefined ? "done" : "idle",
      tag: wasTagged ? "done" : "idle",
    };
  }

  return {
    generate: hasDraft ? "done" : "active",
    review: hasReview ? "done" : hasDraft ? "active" : "idle",
    refine: wasRefined && finished ? "done"
      : wasRefined ? "active"
      : hasReview && job.initial_review.pass === false ? "active"
      : "idle",
    tag: wasTagged ? "done" : approved ? "active" : finished ? "skipped" : "idle",
  };
}

export default function AgentFlow({ job }) {
  const states = stepStates(job);
  const refineNeeded = job?.initial_review?.pass === false || Boolean(job?.refined_output);
  // "Fixing" only appears once a review actually asks for a rewrite.
  const visible = refineNeeded ? STEPS : STEPS.filter((step) => step.key !== "refine");

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
            <div className="step-label">
              {key === "tag" && states[key] === "skipped"
                ? "Filing skipped — lesson not approved"
                : label}
            </div>
          </div>
        </Fragment>
      ))}
    </div>
  );
}
