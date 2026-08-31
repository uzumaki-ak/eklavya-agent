// Hand-drawn icon set from a school-desk world — a real yellow pencil, a teacher's
// red marking pen, a worn eraser. Deliberately not a generic icon-library set;
// these should read as "my classroom", not "an app".

const box = (size) => ({
  width: size,
  height: size,
  viewBox: "0 0 48 48",
  fill: "none",
  xmlns: "http://www.w3.org/2000/svg",
});

/** Yellow pencil writing a wavy line on ruled paper. */
export function PencilWriting({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      {/* ruled page */}
      <rect x="4" y="8" width="26" height="32" rx="3" fill="#fff" stroke="#2d2438" strokeWidth="2" />
      <path d="M9 18h14M9 24h14M9 30h9" stroke="#38b6ff" strokeWidth="1.5" strokeLinecap="round" />
      {/* pencil body, angled */}
      <g transform="rotate(38 34 22)">
        <rect x="30" y="6" width="8" height="22" fill="#ffc93c" stroke="#2d2438" strokeWidth="2" />
        <rect x="30" y="4" width="8" height="5" rx="1.5" fill="#ff6b9d" stroke="#2d2438" strokeWidth="2" />
        <path d="M30 28h8l-4 7z" fill="#f5d9a8" stroke="#2d2438" strokeWidth="2" strokeLinejoin="round" />
        <path d="M32.4 33.6h3.2l-1.6 2.8z" fill="#2d2438" />
      </g>
    </svg>
  );
}

/** Teacher's red pen putting a tick on a marked page. */
export function MarkingPen({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      <rect x="5" y="7" width="25" height="33" rx="3" fill="#fff" stroke="#2d2438" strokeWidth="2" />
      <path d="M10 16h13M10 22h13" stroke="#38b6ff" strokeWidth="1.5" strokeLinecap="round" />
      {/* big red tick over the work */}
      <path
        d="M10 28.5l5 5.5 10-12"
        stroke="#e5484d"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* red pen, nib toward the tick */}
      <g transform="rotate(40 36 20)">
        <rect x="32" y="7" width="7" height="20" rx="1" fill="#e5484d" stroke="#2d2438" strokeWidth="2" />
        <rect x="32" y="5" width="7" height="4" rx="1" fill="#2d2438" />
        <path d="M32 27h7l-3.5 6z" fill="#c1343a" stroke="#2d2438" strokeWidth="2" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

/** Eraser rubbing out a mistake, with crumbs. */
export function EraserFixing({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      <rect x="5" y="7" width="26" height="33" rx="3" fill="#fff" stroke="#2d2438" strokeWidth="2" />
      <path d="M10 16h15" stroke="#38b6ff" strokeWidth="1.5" strokeLinecap="round" />
      {/* half-erased line: solid, then faded */}
      <path d="M10 23h7" stroke="#6b5f7a" strokeWidth="2" strokeLinecap="round" />
      <path d="M18 23h6" stroke="#6b5f7a" strokeWidth="2" strokeLinecap="round" opacity="0.25" />
      {/* eraser block, tilted, mid-rub */}
      <g transform="rotate(-18 28 27)">
        <rect x="21" y="22" width="16" height="10" rx="2" fill="#ff6b9d" stroke="#2d2438" strokeWidth="2" />
        <rect x="21" y="22" width="16" height="4" rx="2" fill="#ffd6e4" stroke="#2d2438" strokeWidth="2" />
      </g>
      {/* crumbs */}
      <circle cx="15" cy="35" r="1.6" fill="#ff6b9d" />
      <circle cx="21" cy="37" r="1.2" fill="#ff6b9d" />
      <circle cx="27" cy="35.5" r="1" fill="#ff6b9d" />
    </svg>
  );
}

/** Gold star sticker — the reward a teacher sticks on finished work. */
export function StarSticker({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      <path
        d="M24 6l5.3 11.2 12.2 1.7-8.9 8.5 2.2 12.1L24 33.8 13.2 39.5l2.2-12.1-8.9-8.5 12.2-1.7z"
        fill="#ffc93c"
        stroke="#2d2438"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <circle cx="19" cy="21" r="1.6" fill="#2d2438" />
      <circle cx="29" cy="21" r="1.6" fill="#2d2438" />
      <path d="M20 26q4 3.5 8 0" stroke="#2d2438" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  );
}

/** Open exercise book — used as the section marker for a finished lesson. */
export function OpenBook({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      <path
        d="M24 13c-4-3-9-4-15-3v25c6-1 11 0 15 3 4-3 9-4 15-3V10c-6-1-11 0-15 3z"
        fill="#fff"
        stroke="#2d2438"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M24 13v25" stroke="#2d2438" strokeWidth="2.5" />
      <path d="M13 20h6M13 26h6M29 20h6M29 26h6" stroke="#38b6ff" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** Paper aeroplane — the "send it" action on the form button. */
export function PaperPlane({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      <path
        d="M42 6L6 21l13 5 5 13z"
        fill="#fff"
        stroke="#2d2438"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M42 6L19 26" stroke="#2d2438" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M19 26l5 13 4-9z" fill="#c9c2d6" stroke="#2d2438" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}

/** Folded paper note — the "did you know" fact marker. */
export function FoldedNote({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      <path
        d="M10 5h18l10 10v28H10z"
        fill="#fff"
        stroke="#2d2438"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M28 5v10h10" fill="#ffe9c2" stroke="#2d2438" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M16 24h16M16 30h16M16 36h10" stroke="#38b6ff" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** Paper luggage tag on a string — the label a finished piece of work gets filed under. */
export function LabelTag({ size = 32 }) {
  return (
    <svg {...box(size)} aria-hidden="true">
      {/* string, looped through the punched hole */}
      <path
        d="M6 9c5 1 8 3 10 6"
        stroke="#2d2438"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
      {/* the tag itself, corner cut off toward the hole */}
      <path
        d="M17 12l6-5 18 3a3 3 0 012.5 3.4l-2.6 17A3 3 0 0137.5 33L19 30a3 3 0 01-2.5-2.6L15 15a3 3 0 012-3z"
        fill="#ffd88a"
        stroke="#2d2438"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      {/* punched hole */}
      <circle cx="21" cy="14" r="2.2" fill="#fff" stroke="#2d2438" strokeWidth="2" />
      {/* two written lines, as if labelled by hand */}
      <path
        d="M23 22l14 2M22.5 27l9 1.4"
        stroke="#7c5cff"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
