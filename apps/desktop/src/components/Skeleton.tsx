/**
 * Preserve layout with gray loading shapes rather than a flashing "Loading".
 * Announce `label` once as a screen-reader status.
 */

export interface SkeletonProps {
  /** Screen-reader loading text, such as "Loading your runs". */
  label: string;
  /** Text-like bars beneath optional title. */
  lines?: number;
  title?: boolean;
  /** Card blocks rather than lines for card grids. */
  cards?: number;
}

/** Prose-like bar widths: long, long, shorter. */
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
