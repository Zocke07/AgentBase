import { describe, expect, it } from "vitest";

import {
  centreCamera,
  DESKS_PER_ROW,
  deskSpot,
  fitCamera,
  FOLLOW_ZOOM,
  followCamera,
  labelDensity,
  MAX_ZOOM,
  MIN_ZOOM,
  placeOffice,
  project,
  ROOM_ACROSS,
  zoomBand,
  zoomCamera,
} from "./officeLayout";

describe("the office's floor", () => {
  it("never moves a placed desk when another arrives", () => {
    for (let count = 1; count <= 24; count += 1) {
      const before = placeOffice(count - 1);
      const after = placeOffice(count);
      expect(after.desks.slice(0, count - 1)).toEqual(before.desks);
      expect(after.reception).toEqual(before.reception);
      expect(after.lead).toEqual(before.lead);
    }
  });

  it("seats desks in rows of up to four, each in its own place", () => {
    const { desks } = placeOffice(12);
    const rows = new Map<number, number[]>();
    for (const desk of desks) rows.set(desk.depth, [...(rows.get(desk.depth) ?? []), desk.across]);
    expect(rows.size).toBe(3);
    for (const places of rows.values()) {
      expect(places).toHaveLength(DESKS_PER_ROW);
      expect(new Set(places).size).toBe(DESKS_PER_ROW);
    }
  });

  it("fills a row from the middle, so a small team sits together", () => {
    const [first, second] = placeOffice(2).desks;
    const middle = ROOM_ACROSS / 2;
    expect(Math.abs((first?.across ?? 0) - middle)).toBeLessThan(2);
    expect(Math.abs((second?.across ?? 0) - middle)).toBeLessThan(2);
    expect(deskSpot(0)).toEqual(first);
  });

  it("grows at the back: more rows, a deeper floor, the same front", () => {
    const small = placeOffice(4);
    const large = placeOffice(9);
    expect(large.rows).toBe(3);
    expect(large.depth).toBeGreaterThan(small.depth);
    expect(large.across).toBe(small.across);
    expect(large.corners[0]).toEqual(small.corners[0]);
    expect(large.corners[3]).toEqual(small.corners[3]);
  });

  it("keeps every desk on the floor, behind the lead desk and the reception", () => {
    for (const count of [0, 1, 5, 12, 20, 33]) {
      const layout = placeOffice(count);
      expect(layout.reception.depth).toBeLessThan(layout.lead.depth);
      expect(layout.reception.across).toBeLessThan(layout.lead.across);
      for (const desk of layout.desks) {
        expect(desk.across).toBeGreaterThan(0);
        expect(desk.across).toBeLessThan(layout.across);
        expect(desk.depth).toBeGreaterThan(layout.lead.depth);
        expect(desk.depth).toBeLessThan(layout.depth);
      }
    }
  });

  it("has room for one row before any desk exists", () => {
    expect(placeOffice(0)).toMatchObject({ rows: 1, desks: [] });
  });

  it("holds the whole room, walls and wall fittings included, inside its bounds", () => {
    for (const count of [0, 4, 12, 20]) {
      const layout = placeOffice(count);
      const { bounds } = layout;
      const inside = (point: { x: number; y: number }) =>
        point.x > bounds.x && point.x < bounds.x + bounds.width && point.y > bounds.y && point.y < bounds.y + bounds.height;
      for (const point of [...layout.corners, ...layout.desks, layout.lead, layout.reception, layout.board, layout.clock, layout.meter, layout.library]) {
        expect(inside(point)).toBe(true);
      }
    }
  });

  it("projects depth up the screen and across down it, as an isometric floor does", () => {
    expect(project(0, 0)).toEqual({ x: 0, y: 0 });
    expect(project(0, 1).y).toBeLessThan(0);
    expect(project(1, 0).y).toBeGreaterThan(0);
    expect(project(1, 0).x).toBe(project(0, 1).x);
    expect(project(1, 1, 10).y).toBe(-10);
  });

  it("shows less on each desk the further out the camera is", () => {
    expect(zoomBand(1)).toBe("near");
    expect(zoomBand(0.85)).toBe("near");
    expect(zoomBand(0.7)).toBe("mid");
    expect(zoomBand(0.4)).toBe("far");
  });

  it("shortens labels to names past twenty desks", () => {
    expect(labelDensity(6)).toBe("full");
    expect(labelDensity(20)).toBe("full");
    expect(labelDensity(21)).toBe("names");
  });
});

describe("the office's camera", () => {
  const layout = placeOffice(6);

  it("fits the whole room, centred, never larger than life", () => {
    const viewport = { width: 500, height: 260 };
    const camera = fitCamera(layout, viewport);
    const { bounds } = layout;
    expect(camera.scale).toBeLessThanOrEqual(1);
    expect(camera.x + bounds.x * camera.scale).toBeGreaterThanOrEqual(0);
    expect(camera.y + bounds.y * camera.scale).toBeGreaterThanOrEqual(0);
    expect(camera.x + (bounds.x + bounds.width) * camera.scale).toBeLessThanOrEqual(viewport.width + 0.001);
    expect(camera.y + (bounds.y + bounds.height) * camera.scale).toBeLessThanOrEqual(viewport.height + 0.001);
    expect(fitCamera(layout, { width: 4000, height: 3000 }).scale).toBe(1);
  });

  it("answers for a viewport it has not been given yet", () => {
    expect(fitCamera(layout, { width: 0, height: 0 }).scale).toBe(1);
  });

  it("centres a point at a zoom, within the zoom's limits", () => {
    const point = layout.desks[0] ?? { x: 0, y: 0 };
    const camera = centreCamera(point, { width: 800, height: 400 }, 1.5);
    expect(point.x * camera.scale + camera.x).toBeCloseTo(400);
    expect(point.y * camera.scale + camera.y).toBeCloseTo(200);
    expect(centreCamera(point, { width: 800, height: 400 }, 9).scale).toBe(MAX_ZOOM);
    expect(centreCamera(point, { width: 800, height: 400 }, 0.01).scale).toBe(MIN_ZOOM);
  });

  it("zooms about the pointer, which stays over the same part of the room", () => {
    const start = fitCamera(layout, { width: 800, height: 400 });
    const anchor = { x: 300, y: 150 };
    const room = { x: (anchor.x - start.x) / start.scale, y: (anchor.y - start.y) / start.scale };
    const zoomed = zoomCamera(start, 1.4, anchor);
    expect(room.x * zoomed.scale + zoomed.x).toBeCloseTo(anchor.x);
    expect(room.y * zoomed.scale + zoomed.y).toBeCloseTo(anchor.y);
  });

  it("follows by showing the whole room while it is readable, else the desk at work", () => {
    const roomy = { width: 1600, height: 1000 };
    const focus = layout.desks[2] ?? null;
    expect(followCamera(layout, roomy, focus)).toEqual(fitCamera(layout, roomy));

    const crowded = placeOffice(20);
    const small = { width: 420, height: 240 };
    const target = crowded.desks[17] ?? { x: 0, y: 0 };
    const camera = followCamera(crowded, small, target);
    expect(camera.scale).toBeCloseTo(FOLLOW_ZOOM);
    expect(target.x * camera.scale + camera.x).toBeCloseTo(small.width / 2);
    expect(followCamera(crowded, small, null)).toEqual(fitCamera(crowded, small));
  });
});
