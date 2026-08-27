// App shell. The stage cards render in pipeline order so the agent flow reads
// top to bottom: draft, then the check, then the rewrite if one happened.

import AgentFlow from "./components/AgentFlow";
import ContentCard from "./components/ContentCard";
import ErrorCard from "./components/ErrorCard";
import FunFactLoader from "./components/FunFactLoader";
import Mascot from "./components/Mascot";
import ReviewCard from "./components/ReviewCard";
import TopicForm from "./components/TopicForm";
import { currentStage, useGeneration } from "./hooks/useGeneration";

const FAILED = new Set([
  "generator_error",
  "reviewer_error",
  "moderation_blocked",
  "moderation_error",
]);

export default function App() {
  const { job, error, busy, start, reset } = useGeneration();

  const failed = job && FAILED.has(job.status);
  const finished = job?.status?.startsWith("completed");
  const showLoader = busy && !failed;

  return (
    <div className={`app ${job ? "has-job" : ""}`}>
      <header className={`header ${job ? "header-compact" : ""}`}>
        <Mascot mood={finished ? "happy" : "writing"} size={job ? 64 : 88} />
        <h1>Eklavya</h1>
        <p>Ask about anything. Your helper writes it, then checks its own work.</p>
      </header>

      {!job && <TopicForm onSubmit={start} busy={busy} />}

      {error && <ErrorCard message={error} onRetry={reset} />}

      {job && (
        <>
          <AgentFlow job={job} />

          {job.cache_hit && (
            <p className="cache-note">Someone already asked this — here it is straight away.</p>
          )}

          {/* Stage 1 — the Generator's draft. Collapsed and non-interactive
              once the Reviewer has rejected it. */}
          <ContentCard
            content={job.original_output}
            variant="draft"
            title={job.topic}
            superseded={job.initial_review?.status === "fail"}
          />

          {/* Stage 2 — the Reviewer's verdict, shown pass or fail */}
          <ReviewCard review={job.initial_review} />

          {/* Stage 3 — the single refinement pass, only if the reviewer failed it.
              A rewrite that fails its own check stays visible (the brief requires
              showing it) but is marked unapproved with the quiz disabled, so a
              child cannot practise on content the checker just rejected. */}
          <ContentCard
            content={job.refined_output}
            variant="final"
            title={job.topic}
            superseded={job.final_review?.status === "fail"}
          />
          <ReviewCard review={job.final_review} isFinal />

          {showLoader && <FunFactLoader stage={currentStage(job)} />}

          {failed && <ErrorCard code={job.error_code} status={job.status} onRetry={reset} />}

          {finished && (
            <button className="btn-go" onClick={reset}>
              Learn something else
            </button>
          )}
        </>
      )}
    </div>
  );
}
