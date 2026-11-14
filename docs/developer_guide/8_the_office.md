# The office

A run is drawn as an office: a room with a desk for the supervisor in front
and a desk for each worker behind, where folders travel when work is handed
on, slips and stamps show each tool call, and a figure's pose says what its
agent is doing. This chapter says how it is put together and the rules that
keep it honest. BUILD_SPEC Phase 20 holds the decisions (D1 to D9).

## How it is put together

```
events ─reduce─▶ RunView                         state/reducer.ts
                    │   latestSeq, lastMessageSeq, completedSeq, modelCallSeq
           officeOf(view) ─▶ OfficeModel          state/office.ts
                    │   lead, desks[], folders[], reception, board,
                    │   library, clock, meter, focus, announcement
     placeOffice(deskCount) ─▶ OfficeLayout       lib/officeLayout.ts
                    │   spots, corners, wall fittings, frame; cameras
     <OfficeScene>                                components/office/
        ├─ <Room>   one SVG, aria-hidden: floor, walls, desks, figures
        └─ layer    real elements: desk buttons, slips, bubbles, board
     styles/office.css
```

`lib/tools.ts` is the one table of tools (each with its family and the words a
slip shows), held to the backend's names by a test. `lib/character.ts` gives
each agent a silhouette from a hash of its name, so it looks the same in every
run on every machine; colour is never identity, because colour already means
status and risk.

## The rules

- **A projection of the fold and nothing else.** `state/office.ts` and
  `lib/officeLayout.ts` read no clock, random source, network or roster and
  keep no state. Live and replay at the same cursor render the same DOM;
  `replayIdentity.test.tsx` holds every scenario to it at about two dozen
  positions and after each notable event, and a test stubs the clocks to
  throw while the office renders.
- **Spans, not timers.** Anything that comes and goes lasts for a span of
  events read from the reducer's positions. A folder is `arriving` until its
  receiver's next event, `open` while the receiver works, `returning` until
  the sender's next event, then `returned`. A slip belongs to its agent's
  current step, from `tool.requested` to the agent's next `llm.request`. A
  speech bubble stays until its speaker's next event. Nothing scans the log
  during render, and no timer removes anything.
- **Claims and evidence.** What a model said (a bubble, the board's summary)
  is drawn as a claim, in italics and labelled as said, and never gets a
  stamp. What a tool did (slips, stamps, result counts, documents, costs) is
  evidence. A test holds that a claim is never stamped.
- **A finish is not always a success.** Only reasons `finished`, `handoff`
  or none get a tick; `max_steps`, `stuck` and the rest are a stop with their
  own words.
- **A question is mirrored, never answered, in the office.** The docked
  approval panel answers it.
- **Every state has a word and a glyph** (`office/glyphs.ts`), so nothing
  rests on colour, under forced colours included; a desk button's accessible
  name opens with the words on its plate (WCAG 2.5.3).
- **Transport is marked.** The camera is custom properties on
  `.office__stage[data-transport="camera"]`; the view buttons are
  `[data-transport="controls"]`. The identity test strips exactly those.

## Words keep their size

The SVG is scaled by the camera; the layer of words is only moved, and each
label multiplies its own point by `--office-zoom`. How much a desk shows
depends on the zoom band (`near`, `mid`, `far` on `data-zoom`) and on whether
it is `quiet` (ready or done with nothing to say), applied in CSS, so the DOM
does not depend on the camera. A quiet desk shows its name alone and opens on
hover, focus or selection.

The camera frames `OfficeLayout.frame` (the furniture and its labels), not the
whole floor. Words that hang outside it (the board's card, the reception's
card, the lead's plate) are reserved by height estimates in
`office/estimates.ts`, never measured, because a measured card changes with
the band the camera picks; those numbers follow `styles/office.css`, so change
a label's lines or padding in both. The lead desk's plate and papers hang in
front of it, where only floor lies, because desks of neighbouring rows share
screen columns. A room needs about half its width in height, which is why the
run view folds the summary and the log beside it.

## Motion (decision D1)

The office animates one cursor step at a time, by CSS on the DOM that step
produced: a desk arriving, a folder travelling, a stamp landing, a pose
changing. `state/useMotionMode.ts` decides whether a cursor move is a step or
a jump to settle; that is transport, on the stage as `data-motion`, and every
entrance and transition scales its duration by `--office-step` (0 when
settling). Never switch an animation's name on or off by mode, which restarts
it on everything. A loop runs only while the fold shows an operation open.
The timeline (`components/Scrubber.tsx`) plays a run one event at a time, so a
replay shows the same motion as the live run. A pose is four arm angles and a
lean, set as custom properties on `.office-character--{activity}`; the
drawing never changes shape, so a pose change is a transition. A lit lamp
means a desk at work. Reduced motion shows the same still office; a hidden
window pauses every animation.

## The office beyond the run (decision D9)

The run's office projects the log alone, so it is replay-safe. The other
offices project API state and are not under replay identity, and open no
event stream of their own: `state/floorPlan.ts` draws the Agents section's
desk cards (`restingDesk`), Home's desk over each going run (`runDesk`, at the
run's level only: status and a waiting question) and the next automation on
the wall calendar (`nextAutomation`). Every desk drawn outside a run starts
from `restDesk`, at rest with its lamp out; `components/office/vignette.ts`
says where it stands. The start screen's desk and the empty states are drawn
from the same parts.

## Adding to it

- A new fact in the room goes into `OfficeModel`, with a test over the
  scenarios in `office.test.ts`. A component never reads the event list or a
  clock.
- Something that comes and goes reads its span from the reducer's positions;
  add a position, test-first, if one is missing.
- A new backend tool needs an entry in `lib/tools.ts`, or its test fails.
- A new label needs a line in the CSS that rations words by `data-face` and
  `data-zoom`, and, if it hangs outside the frame, an estimate.
- Look at the result on the workbench (`just workbench`): the Office pages
  draw every scenario, **Characters** every pose, **Agents floor plan**,
  **Home's office** and **Empty states** the offices beyond the run.

## Performance

The budgets are 60 frames a second with twelve desks while one streams, an
`llm.token` commit under 4 ms, and a jump settling in one frame; nothing
animates while the window is hidden. They were measured on a production build
of the workbench in Chromium and are recorded in `docs/verification.md`;
WebView2 on Windows is not yet measured. Repeated parts are drawn once, desks
are memoized as data (`lib/equal.ts`), and shadows are drawn rather than
filtered.
