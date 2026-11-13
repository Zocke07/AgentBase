import type { ReactNode } from "react";

import { settleTime, SPRINGS, springValue, type Spring } from "../../lib/springs";

/**
 * Space, radii, elevation, the floating material and the springs (Phase 20,
 * brief 4.3 and 5.1), each drawn from its token. The spring curves are
 * plotted from `lib/springs.ts`, the function that generated the tokens.
 */

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="wb-group">
      <h3 className="wb-group__title">{title}</h3>
      <div className="wb-group__row">{children}</div>
    </section>
  );
}

const SPACES = ["1", "2", "3", "4", "5", "6", "8", "10", "12"] as const;
const RADII = ["chip", "control", "card", "panel", "tile", "capsule"] as const;
const ELEVATIONS = ["card", "raised", "floating", "modal"] as const;

/** A spring's travel over time, as an SVG path in a 200 by 80 box. */
function curve(spring: Spring): string {
  const end = settleTime(spring);
  const points = Array.from({ length: 81 }, (_, index) => {
    const x = (index / 80) * 200;
    // 1.1 at the top leaves room for the bouncy spring's overshoot.
    const y = 80 - (springValue(spring, (index / 80) * end) / 1.1) * 80;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `M${points.join(" L")}`;
}

export function ShapePage() {
  return (
    <div className="wb-controls">
      <Group title="Space: a 4 px grid">
        {SPACES.map((step) => (
          <span key={step} className="wb-space">
            <span className="wb-space__bar" style={{ width: `var(--space-${step})` }} />
            <span className="wb-space__name">--space-{step}</span>
          </span>
        ))}
      </Group>

      <Group title="Radii">
        {RADII.map((name) => (
          <span key={name} className="wb-tile" style={{ borderRadius: `var(--radius-${name})` }}>
            {name}
          </span>
        ))}
      </Group>

      <Group title="Elevation">
        {ELEVATIONS.map((name) => (
          <span key={name} className="wb-tile wb-tile--raised" style={{ boxShadow: `var(--elevation-${name})` }}>
            {name}
          </span>
        ))}
      </Group>

      <Group title="Planes and fills">
        {(["window", "sidebar", "content", "elevated"] as const).map((plane) => (
          <span key={plane} className="wb-plane" style={{ background: `var(--${plane})` }}>
            <span className="wb-plane__name">{plane}</span>
            {(["fill", "fill-hover", "fill-selected", "fill-strong"] as const).map((fill) => (
              <span key={fill} className="wb-plane__fill" style={{ background: `var(--${fill})` }}>
                {fill}
              </span>
            ))}
          </span>
        ))}
      </Group>

      <Group title="Material: the floating plane only">
        <div className="wb-material">
          <p className="wb-material__behind" aria-hidden="true">
            Morning collection finished. Daily decision is next. Weekly review runs on Saturday.
          </p>
          <div className="wb-material__panel popover">
            <p className="type-headline">On a material</p>
            <p className="type-control">Text keeps its contrast over whatever is behind.</p>
            <p className="type-caption wb-type__faint">The Transparency switch above makes it solid.</p>
          </div>
        </div>
      </Group>

      <Group title="Springs">
        {Object.entries(SPRINGS).map(([name, spring]) => (
          <figure key={name} className="wb-spring">
            <svg viewBox="0 0 200 80" className="wb-spring__plot" role="img" aria-label={`The ${name} spring's travel over time`}>
              <line x1="0" x2="200" y1={80 - 80 / 1.1} y2={80 - 80 / 1.1} className="wb-spring__target" />
              <path d={curve(spring)} className="wb-spring__curve" />
            </svg>
            <figcaption className="type-caption">
              --spring-{name} · {Math.round(settleTime(spring) * 100) * 10} ms
            </figcaption>
          </figure>
        ))}
      </Group>
    </div>
  );
}
