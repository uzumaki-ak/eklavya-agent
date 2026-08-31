// Failure states, written for a child.
//
// A moderation block and a technical error are deliberately different messages:
// one means "let's pick a different topic", the other means "our fault, try again".
//
// Every state offers a way out. `canRetry` decides the *wording*, never whether
// there is a button: a blocked topic should not say "Try again", but leaving it
// with no action at all stranded the child on a dead end with nothing to click.

const MESSAGES = {
  moderation_blocked: {
    title: "Let's pick something else",
    body: "That topic isn't one we can help with. Try asking about something you're learning in class.",
    canRetry: false,
    action: "Pick another topic",
  },
  moderation_error: {
    title: "We couldn't check that safely",
    body: "Our safety checker isn't working right now, so we stopped. Please try again in a minute.",
    canRetry: true,
  },
  generator_error: {
    title: "Something went wrong",
    body: "Your helper got stuck writing that one. It's not your fault — please try again.",
    canRetry: true,
  },
  reviewer_error: {
    title: "We couldn't check the work",
    body: "The lesson was written, but we couldn't check it properly, so we didn't show it. Please try again.",
    canRetry: true,
  },
};

const CODE_MESSAGES = {
  provider_daily_quota_exhausted: {
    title: "Today's AI limit is reached",
    body: "This project's free daily allowance has been used. Try again after it resets or ask a grown-up to check the API plan.",
    canRetry: false,
  },
  provider_rate_limited: {
    title: "Too many lessons at once",
    body: "The helper needs a short break. Please try again in about a minute.",
    canRetry: true,
  },
  LLMCallTimeout: {
    title: "The helper took too long",
    body: "The AI service did not answer in time. Please try once more.",
    canRetry: true,
  },
  worker_restarted: {
    title: "The helper restarted",
    body: "That lesson was interrupted while the helper restarted. Please try again.",
    canRetry: true,
  },
};

const FALLBACK = {
  title: "Something went wrong",
  body: "Please try again in a moment.",
  canRetry: true,
};

function SadPage({ size = 44 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <path d="M10 5h18l10 10v28H10z" fill="#fff" stroke="#2d2438" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M28 5v10h10" fill="#ffeaea" stroke="#2d2438" strokeWidth="2.5" strokeLinejoin="round" />
      <circle cx="19" cy="27" r="1.8" fill="#2d2438" />
      <circle cx="29" cy="27" r="1.8" fill="#2d2438" />
      <path d="M19 36q5 -4 10 0" stroke="#2d2438" strokeWidth="2.2" strokeLinecap="round" fill="none" />
    </svg>
  );
}

export default function ErrorCard({ status, code, message, onRetry }) {
  const copy = message
    ? { title: "Something went wrong", body: message, canRetry: true }
    : CODE_MESSAGES[code] || MESSAGES[status] || FALLBACK;

  // Retrying the same blocked topic or an exhausted quota cannot succeed, so the
  // label sends the child back to the form instead of promising another attempt.
  const actionLabel = copy.action || (copy.canRetry ? "Try again" : "Start over");

  return (
    <section className="card error">
      <SadPage />
      <h2>{copy.title}</h2>
      <p>{copy.body}</p>

      <button className="btn-go" onClick={onRetry}>
        {actionLabel}
      </button>

      {/* Technical detail, small and out of the way — useful when debugging. */}
      {code && <p className="error-code">Reference: {code}</p>}
    </section>
  );
}
