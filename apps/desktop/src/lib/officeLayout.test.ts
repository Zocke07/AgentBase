import { describe, expect, it } from "vitest";

import {
  BOARD_CARD_HEIGHT,
  BOARD_LIFT,
  CARDS,
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
  PAPERS_DROP,
  project,
  RECEPTION_DROP,
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

  it("fits everything that stands in the room, with the board's card in view, never larger than life", () => {
    const viewport = { width: 500, height: 260 };
    const camera = fitCamera(layout, viewport);
    const { frame, corners } = layout;
    expect(camera.scale).toBeLessThanOrEqual(1);
    const standing = [layout.reception, layout.lead, ...layout.desks, layout.board, layout.clock, layout.meter, layout.library, corners[1], corners[2]];
    for (const point of standing) {
      const x = point.x * camera.scale + camera.x;
      const y = point.y * camera.scale + camera.y;
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(viewport.width);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(viewport.height);
    }
    expect(frame.width).toBeGreaterThan(0);
    // The board's card hangs above the wall and keeps its size: however tall
    // it is, its top stays in the view, and a taller card never gets a larger room.
    let previous = Infinity;
    // Up to a quarter of the view's height, which is all a card is given.
    for (const card of [0, BOARD_CARD_HEIGHT, 105, 160]) {
      const fitted = fitCamera(layout, { width: 1000, height: 640 }, { ...CARDS, board: card });
      expect(fitted.y + (layout.board.y - BOARD_LIFT) * fitted.scale - card, `card ${String(card)}`).toBeGreaterThanOrEqual(0);
      expect(fitted.scale).toBeLessThanOrEqual(previous);
      previous = fitted.scale;
    }
    expect(fitCamera(layout, { width: 4000, height: 3000 }).scale).toBe(1);
  });

  it("keeps the words in front of the room in view below it, up to a fifth of the view", () => {
    // The reception's card and the lead desk's plate keep their size, so they
    // stick out furthest when the room is small. 300 high is about the
    // shortest view the room fits at the minimum zoom; below that the room
    // itself runs off both edges.
    for (const viewport of [{ width: 555, height: 300 }, { width: 1000, height: 640 }]) {
      for (const [reception, lead] of [[CARDS.reception, 0], [CARDS.reception + 22, 0], [0, CARDS.lead], [0, 130]] as const) {
        const fitted = fitCamera(layout, viewport, { ...CARDS, reception, lead });
        const allowed = (height: number) => Math.max(0, height - viewport.height / 5) + 0.001;
        const receptionBottom = (layout.reception.y + RECEPTION_DROP) * fitted.scale + fitted.y + reception;
        const leadBottom = (layout.lead.y + PAPERS_DROP) * fitted.scale + fitted.y + lead;
        const label = `${String(viewport.height)} high, ${String(reception)} and ${String(lead)}`;
        expect(receptionBottom - viewport.height, label).toBeLessThanOrEqual(allowed(reception));
        expect(leadBottom - viewport.height, label).toBeLessThanOrEqual(allowed(lead));
      }
    }
  });

  it("frames less than the whole floor, and the same box however many seats of a row are taken", () => {
    const { frame, bounds } = layout;
    expect(frame.height).toBeLessThan(bounds.height);
    expect(frame.y).toBe(bounds.y);
    expect(frame.x).toBe(bounds.x);
    expect(frame.x + frame.width).toBe(bounds.x + bounds.width);
    expect(placeOffice(1).frame).toEqual(placeOffice(DESKS_PER_ROW).frame);
    expect(placeOffice(0).frame).toEqual(placeOffice(DESKS_PER_ROW).frame);
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

  it("keeps the room in view when the desk at work is near an edge", () => {
    const crowded = placeOffice(20);
    const { bounds } = crowded;
    const small = { width: 420, height: 240 };
    // Every seat, the reception's included: the view never runs past the
    // room's edge, and the followed desk is always inside it.
    for (const spot of [crowded.reception, crowded.lead, ...crowded.desks]) {
      const camera = followCamera(crowded, small, spot);
      expect(bounds.x * camera.scale + camera.x).toBeLessThanOrEqual(0.001);
      expect((bounds.x + bounds.width) * camera.scale + camera.x).toBeGreaterThanOrEqual(small.width - 0.001);
      expect(bounds.y * camera.scale + camera.y).toBeLessThanOrEqual(0.001);
      expect((bounds.y + bounds.height) * camera.scale + camera.y).toBeGreaterThanOrEqual(small.height - 0.001);
      const x = spot.x * camera.scale + camera.x;
      const y = spot.y * camera.scale + camera.y;
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(small.width);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(small.height);
    }
    // A room wider than it is tall for the window: the axis that fits is centred.
    const wide = { width: 4000, height: 240 };
    const centred = followCamera(crowded, wide, crowded.lead);
    expect((bounds.x + bounds.width / 2) * centred.scale + centred.x).toBeCloseTo(wide.width / 2);
  });

  it("leaves the followed desk's words in view, past the room's edge if it must, never losing the desk", () => {
    const crowded = placeOffice(20);
    const back = crowded.desks[19] ?? crowded.lead;
    const front = crowded.desks[3] ?? crowded.lead;
    for (const height of [240, 300, 420]) {
      const viewport = { width: 420, height };
      for (const words of [0, 120, 180, 400]) {
        // Over a desk at the back: the view comes down for its plate and bubble.
        const over = followCamera(crowded, viewport, back, CARDS, () => ({ above: words, below: 0 }));
        const y = back.y * over.scale + over.y;
        expect(y, `${String(height)} high, ${String(words)} px over`).toBeGreaterThanOrEqual(Math.min(words, height - 48) - 0.001);
        expect(y).toBeLessThanOrEqual(height);
        // Under a desk at the front: the view goes up for its papers.
        const under = followCamera(crowded, viewport, front, CARDS, () => ({ above: 0, below: words }));
        const z = front.y * under.scale + under.y;
        expect(z, `${String(height)} high, ${String(words)} px under`).toBeLessThanOrEqual(Math.max(height - Math.max(words, 48), 24) + 0.001);
        expect(z).toBeGreaterThanOrEqual(24 - 0.001);
      }
    }
    // No words: the camera is the one that keeps to the room's edges.
    const plain = followCamera(crowded, { width: 420, height: 240 }, back);
    expect(followCamera(crowded, { width: 420, height: 240 }, back, CARDS, () => ({ above: 0, below: 0 }))).toEqual(plain);
  });
});
