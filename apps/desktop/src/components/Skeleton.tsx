/**
 * Grey shapes in place of content that is on its way, so the page keeps its
 * layout while it loads instead of flashing the word "Loading". Announced to
 * screen readers once, as a status, with the words given in `label`.
 */

export interface SkeletonProps {
  /** What is loading, read out to screen readers: "Loading your runs". */
  label: string;
  /** Text-like bars under an optional title bar. */
  lines?: number;
  title?: boolean;
  /** Card-shaped blocks instead of lines, for a grid of cards. */
  cards?: number;
}

/** Bar widths that read as prose rather than a table: long, long, shorter. */
const WIDTHS = ["100%", "92%", "70%", "84%", "60%"];

export function Skeleton({ label, lines = 3, title = false, cards = 0 }: SkeletonProps) {
  if (cards > 0) {
    return (
      <div className="skeleton skeleton--cards" role="status" aria-label={label} data-testid="skeleton">
        {Array.from({ length: cards }, (_, index) => (
          <div key={index} className="skeleton__card" aria-hidden="true">
            <span className="skeleton__bar skeleton__bar--title" />
            <span className="skeleton__bar" style={{ width: "90%" }} />
            <span className="skeleton__bar" style={{ width: "55%" }} />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="skeleton" role="status" aria-label={label} data-testid="skeleton">
      {title && <span className="skeleton__bar skeleton__bar--title" aria-hidden="true" />}
      {Array.from({ length: lines }, (_, index) => (
        <span
          key={index}
          className="skeleton__bar"
          style={{ width: WIDTHS[index % WIDTHS.length] }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}
