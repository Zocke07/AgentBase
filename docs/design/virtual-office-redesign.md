# Design brief: the virtual office and the interface redesign

*Proposed 2026-11-12 at the maintainer's request and confirmed the same day:
the maintainer accepted section 2's recommended defaults, D1 to D9, and
BUILD_SPEC Phase 20 records them with the acceptance list from section 10.
This file stays as the detailed specification until the phase is complete.
Then its lasting parts move into the developer guide (design system, the
office) and the user guide, and this file is removed, as the Phase 17 roster
design was. Stages 20.1 and 20.2 are built, and the foundations of 20.3 to
20.5 are laid: **section 13 says where the phase stands and where to pick
up.** The appendix holds what 20.1 found, and `docs/verification.md` what
each session ran.*

Readers: the agent building Phase 20 (read this after CLAUDE.md and
BUILD_SPEC), and the maintainer reviewing it.

---

## 1. What changes, and what does not

The request: a polished, fluid, premium interface inspired by Apple's design
principles, fully compatible with Windows and macOS; agent collaboration shown
as a virtual office, where each agent is a character working at its own desk,
instead of a node graph; and a better developer experience, preserving the
existing functionality and architecture wherever possible.

Three outcomes:

1. **An interface that feels native on both platforms.** On macOS it reads
   like a well-made Mac app, on Windows like a well-made Windows 11 app: system
   type, quiet chrome, exact alignment, soft depth, short spring motion and
   complete keyboard control. Windows stays the primary target (§1 constraint
   7), so every surface is judged in WebView2 first.
2. **The office.** A run is shown as a small office. Each agent sits at its
   own desk; delegation, model calls, tool use, waiting for approval, failures
   and results happen visibly in the room. Everything in the room is a
   projection of the event log at the cursor, so live and replay stay
   identical.
3. **A UI loop that needs nobody's screen.** A workbench renders every
   component and every office state from fixture logs; screenshot tests run in
   Chromium and WebKit; design rules (token parity, contrast, no stray
   colours) are tests.

Unchanged, by constraint or by choice:

- §1's hard constraints: no new service, language or network surface.
- The backend and the event contract (§4, 26 types). The office needs no new
  event type. If it seems to, stop and ask; the contract rule (Python types,
  generated TypeScript and reducer in one commit) still applies.
- The meaning of everything `state/reducer.ts` computes. It may gain derived
  fields the office needs, test-first in `reducer.test.ts`.
- Replay identity (§5 Phase 7, `replayIdentity.test.tsx`): the run
  projection, the office included, renders identical DOM live and in replay
  at the same cursor.
- Questions are answered only in the docked approval panel, with Deny focused
  (Phase 11). The office mirrors a waiting question; it never offers a second
  place to answer it.
- The CSP in `tauri.conf.json` (no remote fonts or images, no `blob:`, no
  `wasm-unsafe-eval`) and the webview's capability list, except the one
  addition recorded in D5.
- Knowledge's file-safety rules, `lib/errors.ts`, the Markdown renderer's
  no-HTML rule, the default-space-only surfaces, WCAG AA text contrast in both
  themes, the 800 by 600 minimum window, the drawer below 1,100 px, copy
  written for someone who is not a developer (§0), and no em dashes.

---

## 2. Decisions to confirm before coding

Each has a recommended default. **Confirmed 2026-11-12: the maintainer
accepted all nine as recommended**, and BUILD_SPEC Phase 20 records them.

**D1. The motion rule is amended for the office.** Today nothing animates a
value that comes from the log (the header of `index.css`, and the developer
guide's "Motion, contrast and accessibility in the window"), because a
transition keyed on arrival time would make a replayed event look different
from a live one. Proposed text:

> The office may animate log-driven content when (a) the motion depicts one
> cursor step and is produced by CSS from the new step's DOM (classes, data
> attributes and custom properties), so a step animates the same way whether
> it came from the live stream or from replay playback; (b) the DOM at rest
> for any cursor is a pure function of the event prefix; and (c) a looping
> animation runs only while the fold shows an operation open (a model call
> without its response, a tool call without its result, a question without
> its answer) and ends when it closes. The event log, the approval panel and
> the run summary keep the old rule. Under reduced motion every change is
> immediate.

Phase 7's guarantee holds: the identity test compares DOM, and CSS motion
leaves the DOM alone. Whether a cursor move animates (a short step forward)
or settles at once (a jump, a step back, opening a run) is transport, like
the scrubber, and lives on a wrapper outside the compared subtree.

**D2. The office is DOM and inline SVG, animated by CSS.** No canvas or WebGL
renderer, and no JavaScript animation library inside the run projection:

- A canvas has no DOM, so the identity test would pass without checking
  anything.
- Buttons, names and states stay real elements for the keyboard and screen
  readers.
- The existing tokens theme it in light, dark and forced colours.
- Rive and dotLottie runtimes need WebAssembly, which the CSP refuses, and
  their binary files cannot be reviewed in a diff.
- A JavaScript animation library writes inline styles into the compared DOM,
  as the developer guide already notes.
- A run has a handful of agents (5 by default, `DEFAULT_MAX_AGENTS_PER_RUN`),
  well within what the DOM draws smoothly, and an always-running GPU scene
  would cost battery during long unattended chains.

**D3. Agents are abstract characters, not people.** A small rounded desk
companion whose face is a display showing its state: dots while it asks its
model, a tool's glyph while the tool runs, a raised card while it waits, a
tick when it is done. Identity comes from silhouette (head shape, antenna,
ear pods, visor), chosen by a stable hash of the agent's name, and from the
name plate, never from colour: colour already means status and risk here
(Phase 11: no decorative colour). Rejected: human avatars (they imply gender
and ethnicity, and are hard to draw well in code). Kept as a fallback at
small sizes: a monogram tile.

**D4. One accent: the brand orange.** `--accent` stays the single accent,
retuned only if the new neutrals need it, with white text on it at 4.5:1 or
better. Alternative: a blue accent like macOS's default.

**D5. Window chrome: an overlay title bar on macOS, the native one on
Windows, and an opaque window.**

- macOS: a `tauri.macos.conf.json`, merged over `tauri.conf.json` on macOS
  only, sets `titleBarStyle: "Overlay"` and `hiddenTitle: true`, with
  `trafficLightPosition` placing the window controls inside the toolbar row.
  The toolbar's empty space carries `data-tauri-drag-region`, which needs
  the `core:window:allow-start-dragging` permission: add it to
  `capabilities/default.json` and extend that file's description with the
  reason, as it does for every permission it grants.
- Windows: keep the native title bar for Snap Layouts, accessibility and
  reliability. It follows the system theme; making it follow the in-app theme
  override needs `core:window:allow-set-theme` and is optional.
- No native window materials (macOS vibrancy, Windows Mica) in this phase.
  They need a transparent window (and `macOSPrivateApi` on macOS); text over
  a wallpaper-dependent material cannot be held to AA; the
  `prefers-reduced-transparency` query is not reliably available in WebKit;
  and Acrylic lags while resizing on some Windows builds. Translucent
  materials appear only on floating layers inside the window. A
  setting-guarded native material can be proposed after stage 20.6 if the
  maintainer wants it.

**D6. Dependencies.**

- Runtime: none added. Icons are vendored: the Lucide icons in use (ISC
  licence) are copied as path data into one module with the licence notice,
  replacing today's hand-drawn inline SVGs.
- Development only: `@vitest/browser-playwright` and `playwright` (screenshot
  tests in Chromium and WebKit, and the screenshot script) and `axe-core`
  (accessibility checks in browser tests). No Storybook (a second build
  pipeline; the workbench uses Vite directly), no CSS framework, no animation
  library.

**D7. Type keeps Phase 11's prose size.** Prose stays 15 px at 1.5 line
height. Controls and dense rows use 14 px and captions 13 px, the smallest
text. Titles are 26, 22 and 17 px. Numbers are tabular.

**D8. The diagram stays until the office has parity.** The run view offers
**Office** and **Diagram** (today's React Flow canvas). After stage 20.5's
acceptance the maintainer decides whether to retire the diagram and drop
`@xyflow/react`.

**D9. Two kinds of office.** The run office projects the log alone, so it is
replay-safe. Home's office and the Agents floor plan project API state
(roster, runs) and are not under replay identity. They open no event stream
of their own.

---

## 3. Principles

Take Apple's principles (clear hierarchy, deference to content, restrained
depth, fluid and interruptible motion), not a literal copy of Liquid Glass:
its refraction needs backdrop SVG filters that WebKit lacks, costs GPU time
and weakens contrast. Each principle below says what it means here.

1. **The work is the content.** Chrome recedes: neutral surfaces, hairline
   separators, no decorative colour. The office, the notes and the results are
   what people look at.
2. **Every colour, glyph and movement means something.** Status, risk, the
   accent and the event families keep their meanings (the header of
   `index.css`). The room itself is neutral; colour in it marks state.
3. **Depth with restraint.** Four planes: window, sidebar, content and
   floating (menus, popovers, sheets, the palette). Soft layered shadows;
   translucent material only on the floating plane.
4. **Motion explains a change.** Short springs, interruptible, from where
   something came to where it went. Nothing loops unless something is in
   progress.
5. **The keyboard reaches everything.** Every action has a keyboard path, and
   frequent ones have shortcuts, shown in tooltips and in the command palette.
6. **The office is honest.** It shows no activity the log does not show. What
   a model said looks like a claim; what a tool did looks like evidence
   (CLAUDE.md: model summaries are claims, executed tool calls are evidence).
7. **At home on each platform.** The same layout and features everywhere,
   with each platform's window controls, font, shortcut glyphs and
   scrollbars.

---

## 4. Visual language

Values here are starting points for design judgment unless a line says
must. Set the direction with the `frontend-design` skill and hold every text
colour to the contrast test (9.4).

### 4.1 Tokens

The token rules stay, and become tests:

- Every colour is a token, defined three times: light on `:root`, dark under
  `@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])`,
  and again under `:root[data-theme="dark"]`.
- Nothing outside the token file names a raw colour.
- Text tokens meet 4.5:1 on every surface they sit on, in both themes;
  `--faint` stays the lightest text allowed.

Components use semantic roles, never ramp values:

| Role | Use |
|---|---|
| `--window`, `--sidebar`, `--content`, `--elevated` | the four planes |
| `--control`, `--control-hover`, `--control-pressed` | button and field fills |
| `--fill-hover`, `--fill-selected` | row, rail and list states |
| `--separator`, `--border-strong` | hairlines and outlines |
| `--text`, `--muted`, `--faint` | text levels (names kept) |
| `--accent`, `--accent-strong`, `--accent-soft`, `--on-accent` | the one accent (kept) |
| `--good`, `--bad`, `--warn`, `--info`, each with `-soft` | status and risk (meanings kept) |
| `--material-*` | floating-layer material, with an opaque fallback |
| `--office-*` | the room: floor, walls, desk faces, furniture, shadow |

Dark mode moves toward Apple's neutral greys rather than today's blue-black,
roughly 1C1C1E for the window, 232325 for content and 2C2C2E for raised
surfaces, with a 1 px lit top edge (white at about 6%) on raised surfaces, as
macOS dark mode has. Status hues may move toward the system greens, reds,
yellows and blues, keeping AA as text and each gaining a glyph.

### 4.2 Type

- Stack: `-apple-system, BlinkMacSystemFont, "Segoe UI Variable Text",
  "Segoe UI", system-ui, sans-serif`. On macOS that is SF Pro from the system;
  on Windows 11, Segoe UI Variable with its optical sizes, named explicitly;
  on Windows 10, Segoe UI. Titles of 20 px and over use
  `"Segoe UI Variable Display"` before `"Segoe UI"`.
- Never bundle SF Pro or SF Symbols: Apple licenses them for Apple platforms,
  and this app ships on Windows. Reaching the Mac's own system font through
  `-apple-system` is fine.
- Mono: `ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas,
  monospace`, only for IDs, payloads and code (Phase 11).

| Style | Size / line height | Weight | Use |
|---|---|---|---|
| Large title | 26 / 32 | 700 | section titles |
| Title 1 | 22 / 28 | 700 | page and sheet titles |
| Title 2 | 17 / 24 | 600 | card and group headings, the toolbar title |
| Headline | 15 / 22 | 600 | emphasis in lists |
| Body | 15 / 1.5 | 400 | prose (Phase 11) |
| Control | 14 / 20 | 400 to 500 | buttons, fields, rail, rows |
| Caption | 13 / 18 | 400 | metadata and chips; the smallest text |

- `font-variant-numeric: tabular-nums` for money, counts, times and the
  scrubber's counter.
- `text-wrap: balance` on headings and `pretty` on prose, where the engine has
  them.
- No uppercase micro-labels (Phase 11).

### 4.3 Space, shape and depth

- A 4 px grid: 4, 8, 12, 16, 20, 24, 32, 40, 48.
- Radii: 4 (chips), 6 (controls), 10 (cards), 14 (panels, popovers, sheets),
  20 (the office floor and large tiles), and capsules. Nested corners are
  concentric: the inner radius is the outer radius minus the padding between
  them. Do not use `corner-shape` until both engines have it; only Chromium
  does today, so Windows would get squircles and macOS would not.
- Elevation: flat; card (hairline and a faint shadow); raised (hover and
  selection); floating (menus, popovers, the palette); modal (sheets).
  Shadows have two or three layers: a wide soft ambient and a short key.
- Hairlines are 1 px at 1x and 0.5 px from 2x (`@media (resolution >=
  2dppx)`), so Windows at 100% scaling never loses a separator.
- Materials, floating plane only: a token surface at no less than about 80%
  opacity, with `backdrop-filter: blur(24px) saturate(160%)` and its
  `-webkit-` twin. They fall back to opaque under forced colours, where
  `backdrop-filter` is missing, and when **Reduce transparency**, a new
  Settings switch, is on. The switch starts from `prefers-reduced-transparency`
  where the engine reports it, and is kept the way the theme is
  (`lib/theme.ts`: browser storage under an `agentbase.` key, applied as a
  data attribute on `<html>`), so the backend does not change.

### 4.4 Icons

- One `Icon` component and one style: 1.5 px strokes on a 20 px grid, round
  caps and joins, `currentColor`, at 16, 20 and 24 px. A filled variant marks
  the selected rail row, as macOS sidebars do.
- Vendor the Lucide icons in use into `components/icons/` with the ISC
  notice, and replace the inline SVGs in `Rail`, `RunGraph`, `SpaceSwitcher`
  and `KnowledgeView`. `BrandMark` stays.
- SF Symbols serve only as a reference for which metaphor to use.

### 4.5 Platform adaptations

Detect the platform once, in `lib/platform.ts` (tested), and set
`data-platform="mac"` or `"windows"` on `<html>`. Nothing else reads the user
agent. Today the only platform handling is the `metaKey || ctrlKey` checks in
`App.tsx` and `KnowledgeView.tsx`.

| | macOS (WKWebView) | Windows (WebView2) |
|---|---|---|
| Title bar | overlay, controls inside the toolbar row | native, system theme |
| Font | SF Pro (system) | Segoe UI Variable, else Segoe UI |
| Shortcut glyphs | ⌘ ⌥ ⇧ ⌃ | Ctrl, Alt, Shift |
| Settings shortcut | ⌘, | Ctrl+, |
| Scrollbars | the system's overlay scrollbars | thin and themed (`scrollbar-width`, `scrollbar-color`) |
| Reduce transparency | the Settings switch | the switch, defaulting from the media query |
| High contrast | `prefers-contrast: more` | the existing `forced-colors` block |
| The webview's context menu | suppressed outside editable text | the same |

---

## 5. Motion

### 5.1 Curves and durations

- Springs are CSS `linear()` easings, generated from a damped spring by a
  small tested function (`lib/springs.ts`) and committed as tokens:
  - `--spring-snappy`, about 0.3 s with no overshoot: controls and menus;
  - `--spring-smooth`, about 0.45 s with no overshoot: panels, sheets and the
    camera;
  - `--spring-bouncy`, about 0.5 s with 3 to 5% overshoot: arrivals in the
    office, a folder landing, a badge.

  Keep a `cubic-bezier` fallback under `@supports not
  (transition-timing-function: linear(0, 1))`.
- Keep the three durations (120, 200 and 320 ms) for fades. An exit runs at
  about 70% of its entrance.

### 5.2 Rules

- Animate `transform` and `opacity` only, and a material's blur as it opens.
  Never width, height, top or left.
- Hover feedback within 120 ms; a press scales to 0.97, as today.
- Cards and primary buttons stop lifting toward the pointer (today they move
  1 to 2 px on hover); a fill or elevation change is enough. Mac controls do
  not jump.
- Prefer transitions on custom properties to keyframes for anything that can
  change mid-flight, so a new state retargets smoothly.
- A still frame shows every fact: no motion carries information that the
  frame at rest does not.
- Reduced motion keeps today's single block at the end of the styles, which
  shrinks every duration to 1 ms so that `animationend` still fires and
  `state/usePresence.ts` still works.
- While the window is hidden (`visibilitychange`), a class on `<html>` pauses
  every animation. A long unattended chain must not spend GPU on an unseen
  window.

### 5.3 Moving between places

- Use same-document View Transitions (`document.startViewTransition`) for
  switching sections and opening a run, where the engine has them and motion
  is allowed. Elsewhere keep today's `view-in`.
- Sections stay mounted behind `hidden`; give `view-transition-name` only to
  the leaving and arriving views.
- Never leave a transform on `.app__view`: a leftover transform becomes the
  containing block of the full-screen canvas, which is why `view-in` uses
  `backwards`.

---

## 6. The shell and its interactions

### 6.1 Window and toolbar

- A 52 px toolbar row spans the content area: the section's title at the left
  (Title 2); the section's actions and the global items (model chip, spend,
  waiting questions) at the right, as 28 px toolbar buttons. On macOS the
  traffic lights sit at its left end, above the rail.
- Drag regions cover the toolbar's empty space only; everything inside it
  stays clickable.
- On macOS, when the window is not key, the rail's selection and the
  toolbar's icons dim, as in Mac apps: `focus` and `blur` on `window` set
  `data-window-active` on `<html>`.

### 6.2 Rail

- Keep its order, its folding (Ctrl/Cmd+B) and the drawer below 1,100 px.
- Rows 30 px tall with a 6 px radius, 18 px icons and 14 px labels.
  Selection is a filled pill (`--accent-soft` under `--accent-strong` text, a
  neutral fill while the window is inactive), replacing the bar that grows
  from the edge. The pill may slide between rows with a view transition.
- The space switcher at the top is a toolbar-style button with the space's
  name and a chevron that opens the existing menu as a popover.

### 6.3 Inspector

One `Inspector` pane on the right, shared by Runs (the agent detail), Agents
(the editor) and Knowledge (properties and links): a title row, collapsible
groups, the existing `Splitter`, and a remembered width (`useStoredSize`).
Below 1,100 px it opens as a sheet.

### 6.4 Command palette

Cmd+K or Ctrl+K opens a palette that finds sections, actions (Run once, New
space, Switch space, Fold the rail, Theme), spaces, recent runs by title or
goal, agents and notes, reusing `lib/fuzzy.ts` and the QuickSwitcher's
ranking. Results are grouped; Enter acts; Esc closes it and returns focus.
Default-space-only actions (Edit portfolio, Market watch) appear only in the
default space.

### 6.5 Keyboard

- Keep Ctrl/Cmd+1 to 8 for sections and Ctrl/Cmd+B for the rail. Add
  Ctrl/Cmd+K for the palette and Ctrl/Cmd+, for Settings.
- In the office: arrow keys move between desks, Enter opens the inspector,
  Esc closes it, F toggles follow, 0 fits, + and - zoom.
- In the timeline: Space plays and pauses, Left and Right step, and Shift
  with Left or Right jumps to the previous or next notable event.
- Each shortcut shows in its tooltip and palette row with the platform's
  glyphs.
- Document-level handlers ignore keys from editable fields and from inside
  `[hidden]`, because every section stays mounted.

### 6.6 Menus, popovers, sheets, context menus and banners

- One `Popover` primitive (anchored; flips at the window's edges; focus moves
  in and returns; Esc closes) and one `Menu` built on it (roving focus,
  type-ahead, disabled rows announced).
- One `Sheet` for modal dialogs: focus trapped, background dimmed, a spring
  in, Esc closes unless a destructive change is pending.
- Context menus on run cards, files and notes, agents and desks, opened by
  right-click, Shift+F10 or the Menu key. Suppress the webview's own context
  menu except in editable text, where Cut, Copy and Paste help.
- Confirmations appear as a small banner near the bottom of the window.
  Errors keep their `lib/errors.ts` sentences, inline at the field or as a
  banner, never as a toast that loses which field was wrong (Phase 7).

### 6.7 Details that make it feel native

- Buttons and controls keep the arrow cursor; the hand is for links. Today
  58 declarations set `cursor: pointer`.
- Chrome text (rail, toolbar, buttons, the office) is not selectable; content
  (notes, summaries, the log, payloads) is.
- Focus rings appear on `:focus-visible` only, follow the element's radius,
  and use the accent at about 50%, 3 px wide.
- Disabled controls drop to about 40% opacity, never to colour alone.
- Icons and images in the chrome cannot be dragged out
  (`-webkit-user-drag: none`). The window does not rubber-band
  (`overscroll-behavior: none` on the root); inner scroll areas keep native
  scrolling.
- Tooltips wait about 600 ms, then show the name and the shortcut.
- Skeletons replace "Loading"; anything slower than a second also says what
  it waits for.
- An empty state is a small office vignette, one sentence and one action.

---

## 7. The virtual office

### 7.1 The idea

The run view becomes a small office seen from above at a gentle isometric
angle. The supervisor's desk stands at the head of the room and each worker
has a desk of its own. The person sits at the reception at the front, where
the goal arrives and questions wait. Delegation is a folder carried from one
desk to another; a model call is a thought bubble; a tool call is the tool's
object at work on the desk; a result lands in the desk's tray; the outcome
goes up on the board. Nothing in the room moves unless the log at the cursor
says so.

Art direction, as a starting point: a calm architectural miniature. Matte
surfaces in two or three tones per object (top, left and right faces from one
token), soft contact shadows, rounded edges, generous empty floor; no
textures, and no outlines except under forced colours.

### 7.2 Architecture

```
events ─reduce─▶ RunView                     state/reducer.ts
                    │
           officeOf(view) ─▶ OfficeModel     state/office.ts: pure, no clock
                    │
     placeOffice(model, size) ─▶ Layout      lib/officeLayout.ts: arithmetic
                    │
     <OfficeScene>   SVG room and furniture, HTML layer for text and buttons
                    │
     styles/office.css   poses, objects, folders and transitions, keyed on
                         data attributes and custom properties
```

- The projection and the layout are pure functions with unit tests, as
  `state/graph.ts` and `lib/graphLayout.ts` are. Nothing in the office reads
  a clock, a random source, the network or the roster API, and nothing keeps
  run state in component state.
- Text, buttons and badges live in an HTML layer over the SVG, placed by the
  same projection, so text stays sharp at any zoom and every interactive
  object is a real element. The SVG is `aria-hidden`.
- Static furniture is one memoized SVG; desks are memoized per agent, so an
  `llm.token` re-renders only the streaming desk (`withAgent` keeps the other
  agents' objects).
- Transport stays outside the compared subtree, as the scrubber does: the
  camera, the motion mode, hover and timeline playback. Exclude that wrapper
  in `replayIdentity.test.tsx` explicitly, with a comment saying why.
- If the office needs a per-agent fact the fold lacks, such as the seq of an
  agent's latest event, add it to the reducer as a derived field, test-first.
  Never scan the raw event prefix during render.
- Tool presentation (label, family, icon, whether it fetches) moves into one
  `lib/tools.ts`, used by `state/describe.ts`, `state/files.ts`,
  `RunGraph.tsx`, `Schedules.tsx` and the office, with a test that every
  built-in tool has an entry. Today those four files each name tools on their
  own.

### 7.3 The room

- Zones, front to back: the reception ("You": waiting questions, and where
  the goal came from); the lead desk (the supervisor); worker desks in rows of
  up to four; the library on the side wall (retrieved knowledge); the back
  wall with the board (goal, outcome, memory note), the clock and the meter.
- Desks are placed in the order agents first appear, then ghosts (handoff
  targets never spawned, as `graph.ts` draws them). A placed desk never moves
  when another appears; the room grows at the back.
- Sizes are declared, never measured, so live and replay lay out the same:
  the lesson of React Flow's `measured`.
- The default camera fits the room. Design for two to six desks; stay legible
  at twelve; past twenty, labels shorten to names.

### 7.4 Characters

- Drawn in SVG from a few shared parts: a rounded body, a head whose face is
  a dark display, simple arms. They stay seated: folders travel and people do
  not walk, which matches sequential delegation and keeps motion honest.
- Silhouette variants chosen by a stable hash of the agent's name. The name
  plate is always visible, and the model is a chip on the desk from
  `modelLabel` ("Claude Haiku 4.5", "GPT-5.6 Sol").
- One pose per reducer activity:

| Activity | Set by | Pose and face |
|---|---|---|
| `spawned` | `agent.spawned` | sits down, lamp on; a dot |
| `calling` | `llm.request`, until its response | thought bubble with the tail of `streamedText`; moving dots |
| `thinking` | `agent.thinking`, and after a response, result, denial or error | chin in hand; still dots |
| `executing` | `tool.called`, until its result | hands on the tool's object; its glyph |
| `waiting` | an `approval.requested` that is not automatic | raises a card edged in the risk colour; "?" |
| `completed` | `agent.completed` | leans back, lamp dims; a tick, or a knot when `finishedReason` is `stuck` |

- An unresolved `lastError` shows "!" and marks the desk. An error that
  `changedNothing` (a missed lookup, or a refused call sent again) shows a
  neutral note instead, with no alarm colour, as the run summary does.
- A ghost is an empty chair at a dashed desk, with its name plate.

### 7.5 From the log to the room

| In the log | In the office |
|---|---|
| `run.started` | lights on; the goal card on the board; the reception shows the origin (you, a schedule, an automation, a market alert, Discord); the library hands the lead desk one book per retrieved excerpt; the clock shows the time limit |
| `agent.spawned` | a desk lights and its character sits down |
| `llm.request`, `llm.token`, `llm.response` | the bubble opens, its text grows (the last 80 or so characters), it closes and the desk's meter adds the call's cost |
| `llm.error` | a mark on the desk; a retry shows as a new bubble |
| `agent.thinking` | still dots |
| `tool.requested` | a request slip with the tool's glyph |
| `approval.requested` | the raised card; the reception's bell counts it; the docked panel is where it is answered |
| an automatic answer (`approval.requested` with `automatic`) | the slip is stamped "Allowed by policy", naming the rule (level or tool) and the host, or "Allowed for this run" when an earlier yes covers it (`precedent`), as the log says |
| `approval.resolved`, `tool.approved` | the card is stamped Allowed or Denied |
| `tool.denied` | a Denied stamp; a sandbox refusal shows a barrier and "Outside this space's folder" |
| `tool.called` | the tool's object works (7.6) |
| `tool.result` | a sheet drops into the tray; files in `written` (trusted from the deterministic tools only, as today) become documents that open in Knowledge |
| `tool.error` | a mark, or a neutral note when it changed nothing |
| `agent.handoff` | a folder labelled with the task travels from the delegating desk to the delegate's |
| `agent.message` | a speech bubble, styled as a claim |
| `agent.completed` | the completed pose; a folder returns to the lead desk |
| `budget.warning`, `budget.exceeded` | the meter turns amber, then red |
| `run.completed` | the board shows the summary as a claim and pins the memory note when there is one |
| `run.failed`, `run.cancelled`, `run.paused` | the board says so in words; a failing desk is marked; the room dims for cancelled and paused |
| `channel.inbound`, `channel.outbound` | a slip at the reception's mail slot |
| an unrecognised type | a neutral note on the board naming it (the reducer keeps `unrecognised`) |

### 7.6 Tool families

| Family | Tools | Object on the desk |
|---|---|---|
| delegation | `spawn_agent` and the other control calls | none: the folder (7.5) |
| reading | `read_file`, `list_dir` | an open drawer and a sheet being read |
| writing | `write_file` | a sheet being written; the document lands in the tray |
| knowledge | `search_knowledge`, `propose_memory` | a book from the library; a note for the board |
| network | `http_get`, `read_feed` | a globe, labelled with the host |
| market data | `read_prices`, `read_market`, `read_company_reports` | a small ticker screen, labelled with the host |
| computation | `compute_portfolio`, `check_limits`, `score_predictions`, `track_forecasts` | a calculator and a ledger |
| shell | `run_shell` | a terminal with a high-risk edge |
| unknown | anything else | a plain box with the tool's name |

### 7.7 Claims and evidence

- Evidence (executed calls, results, written files, ledger costs, stamps) is
  drawn as objects: documents with icons, stamps, numbers in tabular type.
  Each opens its log row, its result or its file.
- Claims (streamed model text, `agent.message`, the run's summary) are bubbles
  and the board's summary card, in the claim style the run summary already
  uses (`.claim__*`), and labelled as what the agent said. A claim never gets
  a tick or a stamp.

### 7.8 Motion that follows the fold

- A transient object exists for a span of events, never a span of time. A
  folder is in flight from its `agent.handoff` until the delegate's next
  event, then lies on the delegate's desk until the delegate completes; a
  stamp stays on its slip until the call's result. In replay at a cursor
  inside the span the same element exists, so the DOM matches, and its CSS
  entrance plays on mount in both modes.
- The stage wrapper carries `data-motion="step"` when the cursor moved
  forward by a few events, and `"settle"` otherwise, which turns transitions
  off for that commit. A burst of `llm.token` events counts as one step.
- No `setTimeout` removes a visual. No `Date.now()`, `performance.now()` or
  `Math.random()` runs in the projection, and no `requestAnimationFrame` loop
  drives it. A test stubs them to throw while the office renders.
- The clock shows the time from `startedTs` to `latestTs`, the log's own
  timestamps, against `max_run_seconds`. It does not tick between events.

### 7.9 Camera, selection and inspection

- Fit and follow derive from the model. Fit shows the whole room; follow, on
  by default while live, centres the desk with the latest event. The camera
  eases with `--spring-smooth`.
- The wheel and trackpad pinch zoom (Chromium reports a pinch as Ctrl+wheel;
  check what WebKit sends and handle both), dragging pans, double-click
  zooms to a desk. Any of these turns follow off; a Follow button turns it
  back on.
- Click or Enter selects a desk through the existing `selectedAgent` and
  opens `AgentDetail` in the inspector. Hover shows the role, model,
  `activityLabel` sentence and tool counts.

### 7.10 The timeline

The scrubber keeps its labels, values and test ids, and gains:

- play and pause at 1x, 2x, 4x and 8x, stepping the cursor one event at a
  time, so that replay shows the same motion as live;
- step, and jump to the previous or next notable event;
- markers on the track for handoffs, questions, denials, errors, written files
  and the end, with `sentenceFor` on hover;
- a Live pill, beside the existing way back to the latest event.

Playback timing is transport and may use timers.

### 7.11 Accessibility

- The scene is a labelled region described by the Now line. Each desk is a
  button whose name reads, for example, "researcher, Finds sources. Reading a
  feed. 3 tool calls."
- Tab enters on the selected or active desk; arrow keys move in reading
  order; Home and End go to the ends.
- One polite live region announces agent completions, the run's end and
  budget warnings, without repeats. Questions are already announced by the
  approval panel (`aria-live="assertive"`); do not announce them twice.
- Reduced motion: nothing travels, folders appear where they land, and loops
  become still glyphs.
- Forced colours: outlines in system colours, and every state keeps its word
  and glyph.
- Text at the default zoom is 13 px or more. Zoomed out, labels shorten to
  names, with the full text in the accessible name and the tooltip.
- The log and the diagram remain as non-spatial equivalents.

### 7.12 Performance

- 60 frames a second with twelve desks while one streams, on an
  integrated-GPU Windows laptop in WebView2, and in a Chromium trace at 4x
  CPU slowdown.
- An `llm.token` commit under 4 ms; a jump settles in one frame; nothing
  animates while the window is hidden or the office is off screen.
- SVG `<symbol>` and `<use>` for repeated parts, `contain: layout paint` on
  desks, and drawn shadows rather than `filter: drop-shadow` on many
  elements.
- Record the measurements in `docs/verification.md`.

### 7.13 The office beyond the run

- **Home**: Home polls the runs list and opens no event stream, so its office
  works at run level. While runs are going, the Now area lights one desk per
  run, with its title, status and any waiting question; it shows agent-level
  detail only for a run the run store already follows. Otherwise it shows the
  room at rest, with the next automation's time on the wall calendar.
- **Agents**: the roster as a floor plan of desk cards (character, name,
  role, model chip, tools with risk dots, an enabled switch). A disabled
  agent's chair is pushed in. A card opens the editor in the inspector.
- **Start screen**: the three stages (engine, settings, spaces) light three
  parts of the room, still naming each stage in words.
- **Tour**: one new step introduces the office; the rest still points at
  real UI.
- **Empty states**: Runs shows the room at rest with Run once, Knowledge the
  library, Automations the calendar.

---

## 8. Each section

Behaviour stays; presentation changes.

- **Home**: Run once as a large, calm field; Now; recent runs as cards with
  a status glyph, title, time, duration and cost. The pipeline offer and My
  portfolio appear only in the default space.
- **Automations**: the day's runs and next times as a strip; chains as
  connected cards; Market watch last, in the default space only.
- **Runs**: a dense list (status glyph, title, origin icon, start, cost) and
  the run view: title and status, Office or Diagram, the timeline, the docked
  questions, the log and the inspector.
- **Agents**: the floor plan (7.13). Validation errors stay inline on their
  fields (Phase 7).
- **Knowledge**: the vault layout and both sections stay; reading width about
  70 characters; Space on a selected file opens its Preview in a sheet.
- **Usage**: restyled with the `dataviz` skill over the `--viz-*` tokens;
  figures stay ledger-only (Phase 13).
- **Settings and Space settings**: grouped lists in the manner of System
  Settings (rounded groups, labels on the left, controls on the right, notes
  under the groups, switches for on and off), with Inherit first where it
  applies.
- **The approval panel**: the risk edge, the sentence question, the folded
  history and the focused Deny stay; it takes the new buttons and type.
- **The header's chips**: the model and the spend become toolbar items; the
  spend breakdown opens as a popover.

---

## 9. Developer experience

### 9.1 The workbench

- `apps/desktop/workbench.html` with `src/workbench/main.tsx`, added to
  Vite's inputs for the dev server only, and absent from `dist`. A test or a
  `just verify-build` step proves it is absent.
- Pages: tokens (with live contrast ratios), type, icons, every primitive in
  every state, the shell at 800, 1,100 and 1,440 px, and the office for every
  scenario, with a cursor slider, playback and speed, and switches for theme,
  reduced motion and platform.
- `just workbench` starts it. Nothing in it calls the sidecar.

### 9.2 Fixtures

Scenario builders on `LogBuilder` (`src/test/log.ts`, fixed timestamps): a
morning collection with four collectors and policy answers naming hosts; a
question waiting on `run_shell`; a sandbox denial; a missed lookup; a stuck
worker; a budget warning; a failed run and a cancelled one; a Discord origin;
a ghost handoff; twelve desks and twenty. They feed the workbench, the
identity test and the screenshot tests.

Never commit or screenshot a real log from `.dev/data` or from an installed
app's data: the default space holds the end user's portfolio. Where a real
run's shape matters, write a scenario that mirrors it.

### 9.3 Splitting the stylesheet

`index.css` (8,763 lines) splits into files under `src/styles/` along its own
section comments, imported from `index.css` in the original order. That
commit moves text only, with no rule changed, proven by identical screenshots
before and after. Cascade layers and per-component CSS imports do not come in
the same step: both change precedence. *(Done in stage 20.1: 42 files, the
built stylesheet byte-identical and 66 screenshots identical. Import order
is the cascade, so a new file goes where its rules must sit, and tests read
the stylesheet through `test/stylesheet.ts`.)*

### 9.4 Design rules as tests

In the house style, "two lists that must agree get a test":

- every colour token is defined in all three theme blocks;
- no raw colour literal outside the token file;
- listed text and surface pairs meet 4.5:1 (3:1 for large text and icons) in
  both themes;
- every built-in tool has a `lib/tools.ts` entry with a family;
- every reducer activity and every tool family has a pose or an object;
- the office renders identically live and in replay at several cursors of
  every scenario;
- the office reads no clock.

### 9.5 Screenshots and accessibility in a browser

- Vitest browser mode with the Playwright provider and `toMatchScreenshot`,
  in a config of its own (`vitest.browser.config.ts`), runs the workbench
  scenarios in Chromium, which is close to WebView2, and in WebKit, which is
  close to WKWebView.
- Baselines are per platform, because fonts differ.
- `axe-core` fails a test on serious or critical findings.
- `just test-visual` runs these. They join `just ci` once both platforms have
  baselines.

### 9.6 Screenshots of the real app

`just ui-shots` turns the browser recipe of earlier sessions into a script:

- a scratch sidecar, with `AGENTBASE_DATA_DIR` in a scratch folder and
  `AGENTBASE_PORT=8790`, because the installed app may hold 8787;
- Vite;
- Playwright, which seeds notes, skips the tour (`PATCH /settings
  {"onboarding_completed": true}`), starts `POST /debug/fake_run` and captures
  every section in both themes at 800 by 600, 1,100 by 800 and 1,440 by 900
  into `.dev/shots/<label>/`.

A sidecar port override in `lib/sidecar.ts`, honoured only under
`import.meta.env.DEV` and only for `127.0.0.1`, is simpler than rewriting
requests. Recipes must also work under PowerShell 5.1.

### 9.7 Inspecting the real webview

- Debug builds (`just dev-app`) have DevTools on both platforms (right-click,
  Inspect); on macOS, Safari's Develop menu also lists the app's webview.
- The terminal session on the maintainer's Mac can neither see nor click the
  Tauri window. Window-level checks (title bar, traffic lights, drag regions,
  native menus) are the maintainer's, or are verified by log and process.

### 9.8 Claude Code around the project

- After stage 20.2, create a project skill, `.claude/skills/agentbase-ui/`,
  with the `skill-creator` skill: the token roles, primitives, motion rule,
  office mapping, accessibility checklist and the commands in 9.1 to 9.6,
  pointing here and to BUILD_SPEC for detail. Keep it short so it loads
  cheaply.
- A `PostToolUse` hook, set up with the `update-config` skill, lints an
  edited `.ts` or `.tsx` file and looks for em dashes in any edited file, so
  mistakes show at once rather than at `just ci`. It runs under Node on both
  platforms and adds no shell script. *(Both exist since stage 20.2:
  `.claude/skills/agentbase-ui/`, and `.claude/settings.json` with
  `.claude/hooks/check-edit.mjs`.)*
- Browser MCP servers, where installed (Playwright MCP; Chrome DevTools MCP
  for performance traces), can drive the dev server headless. They do not
  replace the committed tests.

---

## 10. Stages

BUILD_SPEC §6 asks for one phase per session. Phase 20 has six stages, and
each stage is one session that ends with a report. Commit each logical unit.
The order of the stages is fixed; within a stage, use judgment.

**20.1 Baseline, workbench and rules.** No visible change.

- Inventory the components, the stylesheet's sections, the inline SVGs, the
  `cursor: pointer` rules, the key handlers and the tests that pin markup.
- Capture baseline screenshots of every section with `just ui-shots`.
- Add the browser test setup, the workbench, the scenarios, the design-rule
  tests and the recipes `just workbench`, `just test-visual` and
  `just ui-shots`.
- Split the stylesheet as a pure move, proven by identical screenshots.
- Record Phase 20 in BUILD_SPEC with the confirmed decisions, and add a
  current-state line to CLAUDE.md.
- Accept when `just ci` passes, the visual tests pass in Chromium and WebKit,
  the screenshots before and after the split are identical, and BUILD_SPEC
  holds Phase 20.

**20.2 Tokens, type, icons and primitives.**

- The token roles, type scale, spacing, radii, elevation, materials, springs,
  `lib/platform.ts`, the icon module and the primitives. Existing components
  move onto them one section at a time.
- Create the project skill (9.8).
- Accept when the contrast and parity tests pass in both themes, every
  pre-existing test passes (each one changed for an intended markup change is
  listed in the report), and forced colours and reduced motion have been
  checked in screenshots.
- *(Built 2026-11-13. Left for the stages that draw them: the `--office-*`
  tokens (20.4), glyphs beside the status words (20.4, with the office's
  states), and moving every section's own spacing onto the 4 px grid (20.3
  and 20.6, as each section is redrawn). `--fill`, `--fill-strong`,
  `-line`, `-tint` and `--on-*` tokens were added to the role table's set;
  the token file's header is the current list.)*

**20.3 The shell.**

- The toolbar and the macOS title bar (`tauri.macos.conf.json`, drag regions,
  the permission recorded in D5), the rail, the inspector, the command
  palette, the keyboard map, context menus, the details in 6.7, view
  transitions and the inactive-window state.
- Accept when every section works by keyboard alone, shortcuts show the
  platform's glyphs, nothing clips at 800 by 600 or scrolls sideways below
  1,100 px, the `security-review` skill has read the configuration and
  capability changes, and the maintainer has seen the title bar on macOS and
  on Windows.

**20.4 The office, at rest.**

- `lib/tools.ts`, `state/office.ts`, `lib/officeLayout.ts`,
  `components/office/` and `styles/office.css`: characters and objects,
  Office and Diagram in the run view, the inspector link, claims and evidence,
  reduced motion and forced colours, and the identity, coverage and no-clock
  tests.
- Settle the character style first: draw two or three directions in the
  workbench for the maintainer to choose from.
- Accept when every scenario renders in both themes with every activity,
  tool family, question state and error kind distinct in words and glyphs;
  identity holds at several cursors of every scenario; desks are reachable by
  keyboard; and axe reports nothing serious.

**20.5 The office in motion.**

- Transitions that follow the fold, the motion mode, folders, stamps and
  arrivals, loops for open operations only, the timeline, the camera and the
  performance measurements. Update the header of the styles and the developer
  guide's motion section to the rule in D1.
- Accept when replay playback shows the same motion as live and the settled
  frames match, nothing animates while the window is hidden, and the budgets
  in 7.12 are met and recorded.

**20.6 The office everywhere, every section, both platforms.**

- Home's office, the Agents floor plan, the start screen, the tour step, the
  empty states, Settings, Usage, Knowledge's reading view and the approval
  panel.
- Installed builds checked on Windows and on macOS.
- The developer guide gains "Design system" and "The office"; the user
  guide's words and pictures follow; release notes are drafted.
- This brief's lasting parts move into those guides, and the file is
  removed.
- Accept when Phase 20's acceptance list passes and the maintainer has
  watched a real-model run live in the office and replayed it.

**Phase 20 acceptance, for BUILD_SPEC**

1. Any run, including one recorded before this phase, renders the same office
   live and in replay at the same cursor.
2. Every event type has a visible, worded consequence in the office or in the
   log, and nothing in the office lacks a source in the log.
3. Every existing feature works, and every pre-existing test passes or was
   changed only for a listed, intended markup change.
4. Text meets AA in both themes; every section and the office work by
   keyboard alone; reduced motion and forced colours show a complete, still
   office.
5. Nothing clips at 800 by 600, and nothing scrolls sideways below 1,100 px.
6. Installed on Windows and on macOS, the app shows each platform's title
   bar, font and shortcut glyphs, and the maintainer has looked at both.
7. The performance budgets are met and recorded.
8. The screenshot tests pass in Chromium and WebKit, and the workbench is
   not in `dist`.
9. §1's constraints, the CSP, the webview permissions (apart from the
   recorded drag permission), the event contract, the gate, the sandbox and
   the budget ledger are unchanged.

---

## 11. Working rules for every Phase 20 session

**What the session owns.** The presentation layer: components, styles,
layout, motion, icons, the workbench, the fixtures and the frontend's UI
tests. Restructure it where that makes it clearer; later stages build on it.
Behaviour is not the session's to change: every existing feature works as it
did, and the backend, the event contract, the reducer's meanings and
CLAUDE.md's boundaries hold. Review the diff, not only the summary, for
behaviour changes.

**Approved without asking.** The maintainer approves these by starting a
session with the Phase 20 prompt:

- work on the branch `phase-20-redesign`, committing each logical unit;
- the development dependencies in D6;
- any `just` recipe; a scratch sidecar and Vite on the ports in 9.6; headless
  Chromium and WebKit; stopping the servers the session started; retrying a
  flaky test or a command that timed out;
- reading `.dev/data`, read-only, to learn the shape of a run;
- editing BUILD_SPEC, CLAUDE.md, the guides, `docs/verification.md` and this
  brief as the stages require;
- from stage 20.3, `tauri.macos.conf.json` and the permission in D5.

**Ask first:**

- any change to §1, the event contract, the CSP, or the webview capabilities
  beyond D5;
- anything that changes how an existing feature behaves;
- a runtime dependency, or a development dependency not in D6;
- what to do about changes in the working tree the session did not make:
  another session may be working there, so stage only your own files.

**Never:** push, tag or release; stop the installed app; copy, screenshot or
publish anything from `.dev/data` or an installed app's data.

**Finishing work.** Finish the stage. Diagnose ordinary obstacles (an error,
a timeout, a flaky test, an empty result, a failing tool) and work through
them. Leave deliberate blockers alone (a §1 constraint, a decision this brief
reserves for the maintainer, files another session is changing), say what
was found, and carry on with the work that does not depend on them. The end
of a stage is a deliberate stop.

**Skills, where they help:**

| Skill | When |
|---|---|
| `frontend-design` | setting the visual direction: tokens, the shell, the office's art |
| `ui-ux-pro-max` | checking a decision against its UX guidelines and stack notes |
| `vercel-composition-patterns` | the primitives' APIs (Popover, Menu, Sheet, Inspector) |
| `vercel-react-best-practices` | render cost, above all the office while tokens stream |
| `web-design-guidelines` | auditing each stage's result before the report |
| `dataviz` | Usage and the charts in Knowledge |
| `humanizer` | interface copy and documentation |
| `run` | launching the dev server or the app to see a change |
| `code-review` | at high effort, on the stage's diff, before the report |
| `security-review` | whenever the Tauri configuration, capabilities or CSP change |
| `skill-creator`, `update-config` | the project skill and the hook (9.8) |
| `brainstorming` | only where this brief leaves a question open, such as the character style |

**Ending a session.**

- `just ci`, then `just test-visual`: green, or the failure reported with its
  output.
- Screenshots before and after for what changed, from scratch data and
  fixtures only. A private Artifact page of them makes a convenient review.
- `docs/verification.md` records what ran, with results, and what did not;
  the CLAUDE.md current-state entry is updated.
- Commits per logical unit, nothing pushed.
- A report for a reader who saw none of the work: what was built, what ran
  and what it showed, what was not verified and why, where the screenshots
  are, and any decision needed before the next stage.

---

## 12. Traps this codebase has already hit

- Sections stay mounted behind `hidden`. Click-by-text in a browser script
  must skip `[hidden]` ancestors, and document-level key handlers must check
  `root.closest("[hidden]")`. The UA's `[hidden]` loses to any author
  `display`, so the stylesheet restates it.
- React Flow nodes must declare their size (`measured`), or every new layout
  remounts every edge: the canvas flicker fixed in 0.4.8.
- `.app__view`'s entrance uses `backwards`, never `both` (5.3).
- The BEM roots `.switcher` and `.editor` are taken (space switcher, agent
  editor).
- user-event reads `[[` as one literal bracket: type `[[[[`.
- The hygiene test also walks untracked files, and one em dash anywhere fails
  it.
- `replayIdentity` can flake under load: stop scratch servers when done.
- The installed app may hold port 8787: use 8790 for scratch work, and never
  stop the installed app.
- `requestAnimationFrame` does not fire in a background headless tab: bring
  the page to the front first.
- Pipeline surfaces appear only in the default space.
- Errors reach people through `lib/errors.ts`, never as "HTTP 500" or
  "Failed to fetch".

---

## 13. Where the phase stands, and where to pick up (2026-11-13)

Read this before starting a Phase 20 session. It replaces guessing from the
commit log.

**A change of order, at the maintainer's direction (2026-11-13).** Section
10 has one stage per session, in order. After stage 20.2 the maintainer
asked for the load-bearing foundations of every remaining stage to be laid
first, so that whoever continues, a person or another model, builds on
settled ground. So the pure cores of stages 20.3 to 20.5 exist ahead of
their stages. Each stage's acceptance in section 10 is unchanged and still
has to be met in order; what changed is that part of each stage's work is
already done.

### What is built

| Stage | Built | Not built |
|---|---|---|
| 20.1 | all of it | |
| 20.2 | all of it; accepted | |
| 20.3 the shell | the keyboard map with platform glyphs (`lib/shortcuts.ts`), used by the rail's and Knowledge's tooltips; `Popover`, `Menu`, `Sheet` and the layer registry from 20.2 | everything a person sees: toolbar, macOS title bar, rail restyle, inspector, command palette, context menus, section 6.7's details, view transitions, the inactive-window state |
| 20.4 the office, at rest | `lib/tools.ts`, the reducer's four positions, `state/office.ts`, `lib/officeLayout.ts`, `lib/character.ts`, `components/office/`, `styles/office.css`, the `--office-*` tokens, Office and Diagram in the run view, office pages in the workbench, the identity, coverage and no-clock tests | the character style chosen by the maintainer; the run view's layout around the office; polish (below) |
| 20.5 the office in motion | `state/timeline.ts`: markers, next and previous notable event, step or settle, playback pacing | all motion; the timeline's controls; camera easing; performance measurements |
| 20.6 everywhere | nothing | all of it |

### The office: how it is put together

```
events ─reduce─▶ RunView                         state/reducer.ts
                    │   latestSeq, lastMessageSeq, completedSeq, modelCallSeq
           officeOf(view) ─▶ OfficeModel          state/office.ts
                    │   lead, desks[], folders[], reception, board,
                    │   library, clock, meter, focus, announcement
     placeOffice(deskCount) ─▶ OfficeLayout       lib/officeLayout.ts
                    │   spots, corners, wall fittings, bounds; cameras
     <OfficeScene>                                components/office/
        ├─ <Room>   one SVG, aria-hidden: floor, walls, desks, characters
        └─ layer    real elements: desk buttons, slips, bubbles, board
     styles/office.css
```

- **Spans, not timers.** A folder is `arriving` until its receiver's next
  event, `open` while the receiver works, `returning` until the sender's
  next event, then `returned`. A slip belongs to its agent's current step:
  it is listed from `tool.requested` until the agent's next `llm.request`.
  A speech bubble stays until its speaker's next event. All read from the
  reducer's positions; nothing scans the log during render.
- **Two kinds of handoff.** The supervisor starts a worker
  (`agent.spawned`) and then hands it its work (`agent.handoff` from
  `supervisor`): that is a `delegated` folder, with the four phases. A
  worker's own `handoff` call is a request: it emits `agent.handoff`, tells
  the supervisor, and completes with reason `handoff`. That is a
  `requested` folder, drawn only while nobody of the named name exists (an
  empty chair), and never counted as work that came back.
- **A finish is not always a success.** Only reasons `finished`, `handoff`
  or none get a tick. `max_steps`, `stuck` and anything else are a stop,
  with their own words and no tick.
- **Pairing a call's events.** The orchestrator handles a model's calls one
  after another, so everything that happened to a call lies between its
  request and the same agent's next request. `slipsFor` relies on that.
- **Claims and evidence.** `Bubble` and `Board.claim` are claims. Slips,
  stamps, result counts, documents and costs are evidence. A claim never
  gets a stamp; a test holds that.
- **Transport.** The camera is three custom properties and two data
  attributes on `.office__stage[data-transport="camera"]`; the view buttons
  are `[data-transport="controls"]`. `replayIdentity.test.tsx` strips
  exactly those and compares everything else.
- **Labels keep their size.** The SVG is scaled by the camera; the layer of
  words is only moved, and each label multiplies its own point by
  `--office-zoom`. How much a desk shows depends on the zoom band
  (`near`, `mid`, `far`), set as `data-zoom` and applied in CSS, so the DOM
  the identity test compares does not depend on the camera.
- **Accessible names open with the visible words**, in their order (WCAG
  2.5.3): axe fails the page otherwise.
- **`channel.outbound` stays out of the fold.** A reducer test says a
  delivery must not change the run, so the office shows only where a run
  came from; the log shows deliveries. Acceptance item 2 allows "in the
  office or in the log".

### To finish stage 20.4

1. **The maintainer chooses the character style.** Section 10 asks for two
   or three directions drawn in the workbench. One is built (`Room.tsx`,
   `Character`: a rounded body, a head whose face is a dark display,
   antennae, ear pods and a visor by hash of the name). Draw the
   alternatives as a workbench page and ask.
2. **Give the office room.** The run view's grid gives the canvas what is
   left between the summary and the log: about 180 px at 1,100 by 720, a
   strip of a room that needs 400. Decide, with screenshots: fold the
   summary into the board when the office shows, start the log folded, or
   give the canvas a larger default share. Then `followCamera`'s constants
   (`READABLE_ZOOM`, `FOLLOW_ZOOM`) want retuning.
3. **Make Office the default** once 1 and 2 are settled: `RunPanel.tsx`,
   `useStoredFlag("runs.office")`, one word. It is Diagram today so that
   nothing unfinished is the first thing a person sees.
4. **Crowded rooms.** At twelve desks and more, slips and bubbles of
   neighbours can overlap at `near` zoom. Stack or cap them, and check the
   twelve and twenty desk pages.
5. **Per-desk memo of the word layer.** `Room`'s desks are memoized
   (`sameDeskArt`); `DeskButton` is not, and `officeOf` makes new desk
   objects on every event. Before the 4 ms token budget of 7.12 is
   measured, memoize `DeskButton` on the fields it shows, or cache desks by
   agent object in `officeOf` (`withAgent` keeps the other agents' objects).
   The review of 2026-11-14 measured nothing but named the costs: `officeOf`
   runs on every event, re-running `writtenFiles` (a `JSON.parse` of every
   reporting tool's result) and the quadratic `foldersOf`; and `reduce`
   copies the agents map a second time per event to stamp `latestSeq`,
   which `withAgent` could do in its one copy.
6. **What the table in 7.5 still lacks:** documents landing in a desk's
   tray (the board lists the run's files; a desk shows only a count), the
   library handing books to the lead desk (the shelf is drawn and counted),
   the wall calendar. Status glyphs beside status words elsewhere in the
   app (4.1) were also left for this stage.
7. **Acceptance checks not yet run:** forced colours and reduced motion
   screenshots of the office (`just ui-shots` cannot reach the office until
   it is the default or the script clicks the switch); Windows.

### To do stage 20.3

In this order, because each needs the one before:

1. Lift the header out of `App.tsx` into a `Toolbar` component, so the
   workbench can draw the shell with no sidecar (the appendix notes why).
2. Bind the map's two unbound shortcuts, `palette` and `settings`, and
   route `App.tsx`'s and `KnowledgeView.tsx`'s handlers through
   `matchesKeys` and `shouldIgnoreKey`.
3. The command palette on `Sheet` (placement `top`), ranking with
   `lib/fuzzy.ts` as `QuickSwitcher` does; default-space-only actions only
   in the default space.
4. The rail (6.2), the inspector (6.3, and the `Splitter` value noted in
   the appendix), context menus on `Menu` (6.6), section 6.7's details
   (59 `cursor: pointer` declarations, selection, focus rings), view
   transitions (5.3), the inactive-window state (6.1).
5. `tauri.macos.conf.json`, the drag region and
   `core:window:allow-start-dragging` (D5), then the `security-review`
   skill on the configuration. This needs a build to check
   (`just check-tauri` needs a frozen sidecar) and the maintainer's eyes on
   both title bars; it was deliberately not attempted without either.

### To do stage 20.5

1. A motion wrapper outside the compared subtree carrying
   `data-motion="step"` or `"settle"` from `motionMode(events, from, to)`.
2. CSS entrances and transitions in `styles/office.css`, keyed on the
   attributes already in the DOM: `data-activity`, `data-face`,
   `data-state` on slips, the folder phase classes, `office-face__dots
   --asking` for the one loop an open model call allows. Springs are
   tokens.
3. The scrubber's new controls from `state/timeline.ts`, keeping its
   labels, values and test ids. Add the icons then (a test fails an icon
   nothing uses).
4. Camera easing with `--spring-smooth`; pause on `visibilitychange`.
5. Measure 7.12 and record it. Update the header of `index.css` and the
   developer guide's motion section to the rule in D1.

### Decisions waiting for the maintainer

- The character style (20.4, item 1).
- How the run view makes room for the office (20.4, item 2).
- Whether the edit hook's three seconds per TypeScript edit are welcome
  (`.claude/settings.json`; remove the entry to turn it off).
- After 20.5, D8: whether to retire the diagram and drop `@xyflow/react`.

---

## Appendix: what stage 20.1 found (2026-11-12)

The inventory section 10 asks for, as numbers and places, with what later
stages should know. `docs/verification.md` has what ran.

**Components.** `src/components` holds 45 components and 35 test files. The
largest are `KnowledgeView.tsx` (2,042 lines), `SettingsView.tsx` (1,451),
`SpaceSettingsView.tsx` (879), `FilesPanel.tsx` (812) and `Schedules.tsx`
(797). The shell's header (model chip, spend, setup chip) is inline in
`App.tsx`, not a component, so the workbench cannot draw the shell without
a sidecar until stage 20.3 separates it.

**Stylesheet.** 42 files under `src/styles`, 8,736 lines, in the order
`index.css` imports them. The largest are `knowledge.css` (1,695 lines),
`file-views.css` (616), `graph.css` (607) and `markdown.css` (482). The
reduced-motion and forced-colours blocks are in `accessibility.css`, which
is not last: six files follow it, from `responsive.css` on, and its
`!important` durations still win. `PortfolioEditor.css` is the one
stylesheet a component imports itself.

**Inline SVGs** to replace with the icon module (4.4): `Rail.tsx` 9,
`RunGraph.tsx` 8, `KnowledgeView.tsx` 3, `SpaceSwitcher.tsx` 1. `Chart.tsx`
draws its charts in SVG (3) and `BrandMark.tsx` is the mark (1); both stay.

**`cursor: pointer`** (6.7): 59 declarations in 25 files, 22 of them in
`knowledge.css`, 4 each in `markdown.css` and `space-switcher.css`, 3 in
`run-panel.css`.

**Key handlers.** Six listen on the document or window:

| Where | Keys | Skips `[hidden]`? |
|---|---|---|
| `App.tsx` | Ctrl/Cmd+1 to 8, Ctrl/Cmd+B, Esc (drawer) | not needed: the shell is never hidden |
| `KnowledgeView.tsx` | Ctrl/Cmd+S, E and O | yes |
| `Tour.tsx` | Left, Right, Esc | its targets, yes |
| `RunPanel.tsx` | Esc (expanded canvas), on `window` | no: bound only while expanded |
| `BudgetMeter.tsx`, `SpaceSwitcher.tsx` | Esc, while their popover is open | no: bound only while open |

Element-level `onKeyDown` handlers are in `HomeView`, `KnowledgeView`,
`NoteEditor`, `QuickSwitcher`, `SettingsView` and `Splitter`. Platform
handling is only the `metaKey || ctrlKey` checks in `App.tsx` and
`KnowledgeView.tsx`.

**Tests that pin markup** (class names, `innerHTML` or selectors), and so
will need a listed change when their component's markup changes: `App`,
`ApprovalPanel`, `BrandMark`, `BudgetMeter`, `Chart`, `EventLog`, `HomeView`,
`Journal`, `KnowledgeView`, `Markdown`, `MarketAlerts`, `MermaidDiagram`,
`ModelOptions`, `RecentFiles`, `RunCard`, `RunGraph`, `RunPanel`,
`RunSummary`, `SettingsView`, `StartupScreen`, `UsageView`,
`replayIdentity` and `state/graph`. `BrandMark.test.tsx` also reads the
brand tokens' values from the stylesheet.

**Tokens today.** 34 colour tokens, each in all three theme blocks, and the
two dark blocks agree. Outside the token file there are 12 raw colour
literals in 7 files and 30 `color-mix()` colours in 10 files; the rule test
holds both counts per file so they can only fall.

**Contrast today.** `--text` and `--muted` pass on all four surfaces in both
themes. Sixteen listed pairs fall short of 4.5:1 and are named in
`design/tokens.ts` (`KNOWN_SHORTFALLS`) for stage 20.2 to fix:

- `--faint` on `--surface-2` and `--surface-3`, in both themes (4.35 and
  4.00 in light, 4.37 and 3.84 in dark);
- in light, `--accent` on `--surface-2` and `--surface-3`; `--bad` on
  `--surface-2`; and every status colour on `--surface-3`;
- in light, each status colour on its own soft fill over `--bg`, and `--bad`
  on `--bad-soft` over `--surface` (4.49).

The header of `index.css` says text meets AA "on every surface"; that holds
for `--bg` and `--surface`, not the two deeper surfaces.

**Axe today.** Three serious findings in the existing interface, listed in
`workbench/pages.visual.tsx` (`KNOWN_FINDINGS`) for stage 20.2: the dark
theme's Allow button (dark text on the green fill), the error count badge in
a failed run's summary in light, and the space switcher, whose accessible
name "Space: Main" does not contain its visible text.

**Smaller things seen.**

- React warns that `Markdown.tsx` spreads a props object containing `key`
  into its headings. It is a console warning in development, not a visible
  fault.
- A `Splitter`'s `aria-valuenow` is its fallback on a first render and the
  measured size on later ones, because it measures through a ref. It sits
  inside the run projection, so a tree rendered once and a tree re-rendered
  differ there; the identity test renders both sides fresh and does not see
  it. The shared `Inspector` (6.3) is the place to settle it.
- In a real browser two captures of the same page could differ by one
  colour level on antialiased edges when one landed inside a 1 ms
  animation. `ui-shots` and the visual tests therefore end every animation
  and transition at once before capturing (`test/still.ts`). One capture in
  eight still showed 8 pixels of noise on a native select's corners, which
  `ui-shots --compare` now measures. Stage 20.5's motion needs its own way
  to capture a step.
- Type-aware lint over the frontend peaked at 1.92 GB before this stage,
  under Node's default 2 GB heap; the lint scripts now allow 4 GB.
- `run.paused` is in the event contract and the reducer, and nothing in the
  sidecar emits it, so no scenario has one.
