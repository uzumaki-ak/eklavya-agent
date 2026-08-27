// Same-origin API calls — the frontend container proxies /api to the backend,
// so there is no build-time URL to bake in and no CORS to configure.

const SESSION_KEY = "eklavya-session-id";

function sessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

export async function startGeneration(grade, topic, signal, idempotencyKey) {
  const response = await fetch("/api/generate", {
    method: "POST",
    signal, // lets the caller abort if the user navigates away or resubmits
    headers: {
      "Content-Type": "application/json",
      "X-Session-Id": sessionId(),
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ grade, topic }),
  });

  if (response.status === 409) {
    throw new Error("That request was already sent with different details.");
  }
  if (response.status === 503) {
    throw new Error("We're a bit busy right now. Please try again in a moment.");
  }
  if (!response.ok) {
    throw new Error("Could not start. Please try again!");
  }
  return response.json();
}

// Streams stage-by-stage updates so the UI can animate the agent flow live.
export function streamJob(jobId, onUpdate, onError) {
  const source = new EventSource(`/api/jobs/${jobId}/stream`);

  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onUpdate(data);
      if (TERMINAL.has(data.status)) source.close();
    } catch {
      // Ignore a malformed frame; the next one usually arrives fine.
    }
  };

  source.onerror = () => {
    source.close();
    onError?.();
  };

  return () => source.close();
}

const TERMINAL = new Set([
  "completed_pass",
  "completed_fail",
  "generator_error",
  "reviewer_error",
  "moderation_blocked",
  "moderation_error",
]);
