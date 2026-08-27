// Inline SVG mascot — a friendly owl that changes expression per pipeline stage.
// Inline (not an image file) so it inherits theme colours and animates cheaply.

const EYES = {
  writing: { lid: 0.35, sparkle: false },
  checking: { lid: 0.1, sparkle: false }, // wide-eyed, inspecting
  polishing: { lid: 0.3, sparkle: true },
  happy: { lid: 0.5, sparkle: true },
};

export default function Mascot({ mood = "writing", size = 96 }) {
  const { lid, sparkle } = EYES[mood] ?? EYES.writing;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      role="img"
      aria-label="Your learning helper"
      className={`mascot mascot-${mood}`}
    >
      {/* body */}
      <ellipse cx="50" cy="58" rx="32" ry="34" fill="var(--purple)" />
      <ellipse cx="50" cy="64" rx="23" ry="25" fill="var(--purple-soft)" />

      {/* ear tufts */}
      <path d="M22 32 L30 14 L40 28 Z" fill="var(--purple)" />
      <path d="M78 32 L70 14 L60 28 Z" fill="var(--purple)" />

      {/* eyes */}
      <circle cx="39" cy="46" r="12" fill="#fff" />
      <circle cx="61" cy="46" r="12" fill="#fff" />
      <circle cx="39" cy="46" r="6" fill="var(--ink)" />
      <circle cx="61" cy="46" r="6" fill="var(--ink)" />
      <circle cx="41" cy="44" r="2" fill="#fff" />
      <circle cx="63" cy="44" r="2" fill="#fff" />

      {/* eyelids — drive the expression */}
      <rect x="27" y="34" width="24" height={24 * lid} rx="4" fill="var(--purple)" />
      <rect x="49" y="34" width="24" height={24 * lid} rx="4" fill="var(--purple)" />

      {/* beak */}
      <path d="M50 54 L45 62 L55 62 Z" fill="var(--amber)" />

      {sparkle && (
        <g className="mascot-sparkle" fill="var(--amber)">
          <path d="M84 24 l2.2 5.4 5.4 2.2 -5.4 2.2 -2.2 5.4 -2.2 -5.4 -5.4 -2.2 5.4 -2.2 Z" />
          <path d="M16 52 l1.5 3.6 3.6 1.5 -3.6 1.5 -1.5 3.6 -1.5 -3.6 -3.6 -1.5 3.6 -1.5 Z" />
        </g>
      )}
    </svg>
  );
}
