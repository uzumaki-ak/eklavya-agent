// Renders one GeneratorOutput: the explanation plus a quiz.
// Also exposes the raw JSON, since the agent contract is part of what's shown.
//
// A draft the Reviewer rejected is collapsed and its quiz disabled — it stays
// visible (the assessment wants the flow shown) but a child should not be able
// to practise on content that failed the check.

import { useEffect, useState } from "react";
import Quiz from "./Quiz";
import { EraserFixing, PencilWriting } from "./icons";

const VARIANTS = {
  draft: {
    Icon: PencilWriting,
    tagClass: "tag-draft",
    label: "First try",
    // A rejected first draft is followed by a rewrite.
    rejectedNote: "The checker found problems with this one, so it was rewritten below.",
    expandLabel: "Show what the first try said",
  },
  final: {
    Icon: EraserFixing,
    tagClass: "tag-final",
    label: "Improved version",
    // Refinement is capped at two passes, so once this card is showing a
    // rejected rewrite there is nothing further coming. Promising another
    // rewrite here would be a lie.
    rejectedNote: "The checker still found problems, so this one is not approved.",
    expandLabel: "Show what the rewrite said",
  },
};

// Written for the adult, so it stays folded away by default rather than
// competing with the lesson for a child's attention.
function TeacherNotes({ notes }) {
  if (!notes) return null;
  return (
    <details className="teacher-notes">
      <summary>For the grown-up</summary>
      <p className="objective">{notes.learning_objective}</p>
      {notes.common_misconceptions?.length > 0 && (
        <>
          <p className="misconception-heading">Things children often get wrong</p>
          <ul>
            {notes.common_misconceptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}


export default function ContentCard({ content, variant = "draft", title, superseded = false }) {
  const [showRaw, setShowRaw] = useState(false);
  const [expanded, setExpanded] = useState(!superseded);

  // The draft normally mounts before its asynchronous review arrives. Collapse
  // it when that later review rejects it; useState's initializer runs only once.
  useEffect(() => {
    if (superseded) setExpanded(false);
  }, [superseded]);

  if (!content) return null;

  const { Icon, tagClass, label, rejectedNote, expandLabel } = VARIANTS[variant];

  return (
    <section className={`card ${variant} ${superseded ? "superseded" : ""}`}>
      <span className={`card-tag ${tagClass}`}>
        <Icon size={18} />
        {label}
      </span>

      {superseded && <p className="superseded-note">{rejectedNote}</p>}

      {title && <h2>{title}</h2>}

      {superseded && !expanded ? null : (
        <>
          <p className="explanation">{content.explanation?.text}</p>
          <Quiz mcqs={content.mcqs} disabled={superseded} />
          <TeacherNotes notes={content.teacher_notes} />
        </>
      )}

      <div className="card-actions">
        {superseded && !expanded && (
          <button className="raw-toggle" onClick={() => setExpanded(true)}>
            {expandLabel}
          </button>
        )}
        <button className="raw-toggle" onClick={() => setShowRaw((open) => !open)}>
          {showRaw ? "Hide" : "Show"} the raw data
        </button>
      </div>
      {showRaw && <pre className="raw-json">{JSON.stringify(content, null, 2)}</pre>}
    </section>
  );
}
