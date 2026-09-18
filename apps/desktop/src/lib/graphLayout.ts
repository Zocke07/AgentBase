/**
 * A force-directed layout for the vault graph, deterministic so the same
 * notes land in the same places on every open: nodes start on a circle in a
 * fixed order and the simulation runs a fixed number of steps with no
 * randomness. Fruchterman and Reingold's springs and charges, with a little
 * gravity so disconnected notes do not drift off. Quadratic in the node
 * count, so the step count falls as the vault grows and a very large graph
 * keeps the circle.
 */

export interface Point {
  readonly x: number;
  readonly y: number;
}

/** The distance two linked notes settle at, in canvas pixels. */
const SPRING = 150;

function stepsFor(count: number): number {
  if (count <= 80) return 260;
  if (count <= 250) return 110;
  if (count <= 600) return 40;
  return 0;
}

export function forceLayout(ids: readonly string[], edges: readonly (readonly [string, string])[]): Map<string, Point> {
  const count = ids.length;
  const index = new Map(ids.map((id, position) => [id, position] as const));
  const radius = Math.max(SPRING, (SPRING * Math.sqrt(count)) / 1.6);
  const xs = ids.map((_id, position) => Math.cos((position / Math.max(count, 1)) * Math.PI * 2) * radius);
  const ys = ids.map((_id, position) => Math.sin((position / Math.max(count, 1)) * Math.PI * 2) * radius);
  const links = edges
    .map(([source, target]) => [index.get(source), index.get(target)] as const)
    .filter((pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined && pair[0] !== pair[1]);

  const steps = stepsFor(count);
  const dx = new Array<number>(count).fill(0);
  const dy = new Array<number>(count).fill(0);
  for (let step = 0; step < steps; step += 1) {
    const temperature = SPRING * 0.9 * (1 - step / steps) + 2;
    dx.fill(0);
    dy.fill(0);
    for (let a = 0; a < count; a += 1) {
      for (let b = a + 1; b < count; b += 1) {
        const ddx = (xs[a] ?? 0) - (xs[b] ?? 0);
        const ddy = (ys[a] ?? 0) - (ys[b] ?? 0);
        const distance = Math.max(Math.hypot(ddx, ddy), 0.01);
        const force = (SPRING * SPRING) / distance;
        dx[a] = (dx[a] ?? 0) + (ddx / distance) * force;
        dy[a] = (dy[a] ?? 0) + (ddy / distance) * force;
        dx[b] = (dx[b] ?? 0) - (ddx / distance) * force;
        dy[b] = (dy[b] ?? 0) - (ddy / distance) * force;
      }
    }
    for (const [source, target] of links) {
      const ddx = (xs[source] ?? 0) - (xs[target] ?? 0);
      const ddy = (ys[source] ?? 0) - (ys[target] ?? 0);
      const distance = Math.max(Math.hypot(ddx, ddy), 0.01);
      const force = (distance * distance) / SPRING;
      dx[source] = (dx[source] ?? 0) - (ddx / distance) * force;
      dy[source] = (dy[source] ?? 0) - (ddy / distance) * force;
      dx[target] = (dx[target] ?? 0) + (ddx / distance) * force;
      dy[target] = (dy[target] ?? 0) + (ddy / distance) * force;
    }
    for (let a = 0; a < count; a += 1) {
      const gx = (dx[a] ?? 0) - (xs[a] ?? 0) * 0.04;
      const gy = (dy[a] ?? 0) - (ys[a] ?? 0) * 0.04;
      const magnitude = Math.max(Math.hypot(gx, gy), 0.01);
      const move = Math.min(magnitude, temperature);
      xs[a] = (xs[a] ?? 0) + (gx / magnitude) * move;
      ys[a] = (ys[a] ?? 0) + (gy / magnitude) * move;
    }
  }

  const placed = new Map<string, Point>();
  ids.forEach((id, position) => {
    placed.set(id, { x: Math.round(xs[position] ?? 0), y: Math.round(ys[position] ?? 0) });
  });
  return placed;
}
