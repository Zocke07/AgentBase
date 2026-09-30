/** Compact version of the three-node mark used by the packaged app icon. */
export function BrandMark({ className }: { className: string }) {
  return (
    <svg
      className={`brand-mark ${className}`}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      data-testid="brand-mark"
    >
      <path className="brand-mark__links" d="M16 6 6.5 25h19z" />
      <circle className="brand-mark__node brand-mark__node--lead" cx="16" cy="6" r="4.8" />
      <circle className="brand-mark__node brand-mark__node--base" cx="6.5" cy="25" r="4.8" />
      <circle className="brand-mark__node brand-mark__node--base" cx="25.5" cy="25" r="4.8" />
    </svg>
  );
}
