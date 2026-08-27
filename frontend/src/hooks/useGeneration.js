// Owns the job lifecycle: start a run, then stream stage updates until it ends.
//
// Both the POST and the stream are cancellable. Without that, a component that
// unmounts (or a resubmit) mid-POST would still open an EventSource afterwards.

import { useCallback, useEffect, useRef, useState } from "react";
import { startGeneration, streamJob } from "../lib/api";

const TERMINAL = new Set([
  "completed_pass",
  "completed_fail",
  "generator_error",
  "reviewer_error",
  "moderation_blocked",
  "moderation_error",
]);

export function useGeneration() {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const closeStreamRef = useRef(null);
  const abortRef = useRef(null);
  const timeoutRef = useRef(null);
  const runIdRef = useRef(0); // guards against a stale request resolving last
  const retryKeyRef = useRef(null); // retry a failed POST without orphaning its durable row

  const teardown = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    closeStreamRef.current?.();
    closeStreamRef.current = null;
    clearTimeout(timeoutRef.current);
    timeoutRef.current = null;
  }, []);

  useEffect(() => teardown, [teardown]);

  const start = useCallback(
    async (grade, topic) => {
      teardown();
      const runId = ++runIdRef.current;

      setError(null);
      setJob(null);
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const prior = retryKeyRef.current;
      const idempotencyKey =
        prior?.grade === grade && prior?.topic === topic ? prior.key : crypto.randomUUID();
      retryKeyRef.current = { grade, topic, key: idempotencyKey };

      try {
        const { job_id: jobId } = await startGeneration(
          grade, topic, controller.signal, idempotencyKey,
        );
        if (runId !== runIdRef.current) return; // superseded while in flight
        retryKeyRef.current = null; // server acknowledged; future submissions are new intents

        closeStreamRef.current = streamJob(
          jobId,
          (update) => {
            if (runId !== runIdRef.current) return;
            setJob(update);
            if (TERMINAL.has(update.status)) {
              clearTimeout(timeoutRef.current);
              timeoutRef.current = null;
              setBusy(false);
            }
          },
          () => {
            if (runId !== runIdRef.current) return;
            setError("Lost connection. Please try again.");
            setBusy(false);
          },
        );

        // The server's whole-pipeline deadline is 120 seconds. This guard is
        // deliberately slightly higher and prevents an orphaned row or broken
        // stream from leaving a child on "Writing" forever.
        timeoutRef.current = setTimeout(() => {
          if (runId !== runIdRef.current) return;
          closeStreamRef.current?.();
          closeStreamRef.current = null;
          setJob(null);
          setError("The helper took too long. Please try again.");
          setBusy(false);
        }, 130_000);
      } catch (err) {
        if (err.name === "AbortError" || runId !== runIdRef.current) return;
        setError(err.message);
        setBusy(false);
      }
    },
    [teardown],
  );

  const reset = useCallback(() => {
    runIdRef.current += 1; // invalidate anything still in flight
    teardown();
    setJob(null);
    setError(null);
    setBusy(false);
  }, [teardown]);

  return { job, error, busy, start, reset };
}

/** Which loader copy to show, derived from how far the job has got. */
export function currentStage(job) {
  if (!job) return "generate";
  if (job.refined_output || job.initial_review?.status === "fail") return "refine";
  if (job.original_output) return "review";
  return "generate";
}
