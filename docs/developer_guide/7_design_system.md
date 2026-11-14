# Design system

How the interface is built, so a change looks like the rest of it and stays
accessible. The project skill `.claude/skills/agentbase-ui/` is the short form
of this chapter for a coding session; the rules below are also held by tests.

## Colour: roles, never values

Every colour is a token in `apps/desktop/src/styles/tokens.css`, defined three
times: light, dark by the system, and dark by the viewer's choice. No other
stylesheet names a colour or uses `color-mix()`; `src/design/rules.test.ts`
fails if one does, and checks that each token is in all three blocks.

| Need | Token |
|---|---|
| Behind everything; navigation columns; cards and panels; menus and sheets | `--window`, `--sidebar`, `--content`, `--elevated` |
| Button and field fills | `--control`, `--control-hover`, `--control-pressed` |
| A quiet inset; a hovered row; a selected row; tracks and tags | `--fill`, `--fill-hover`, `--fill-selected`, `--fill-strong` |
| Hairlines; control outlines | `--separator` with `var(--hairline)`; `--border-strong` |
| Text | `--text`, `--muted`, `--faint` |
| The accent as a mark; as text; as a tint; as an edge | `--accent`, `--accent-strong`, `--accent-soft`, `--accent-line` |
| The keyboard's focus ring | `--focus-ring` |
| Status and risk | `--good`, `--bad`, `--warn`, `--info`, each with `-soft` and `-line`; `--on-*` for text on a solid fill |
| Floating layers | `--material` with `--material-filter` |
| Chart series | `--viz-1` to `--viz-6`, in that order |
| The office | `--office-*` |

- `--faint` is the lightest text allowed, and only on a plane, a control,
  `--fill` or `--fill-hover`. Accent-coloured text is `--accent-strong`.
- Colour means status, risk or the next action, never decoration, and no state
  rests on colour alone: a word or a glyph goes with it.
- Every text and ground pairing is listed in `CONTRAST_PAIRS`
  (`src/design/tokens.ts`) and held to 4.5:1 in both themes; marks (the accent
  as an icon, the focus ring) to 3:1. A new pairing is added there.
- The chart series were chosen with the `dataviz` skill's validator: their
  order is what keeps neighbouring series apart for colour-blind readers,
  and every one meets 3:1 on `--content` in both themes (held in
  `CONTRAST_PAIRS`). Assign them in order, never cycled: `Chart.tsx` draws
  six series at most and folds a pie's smaller slices into Other. Re-run
  the validator before changing one.

## Type, space, shape and depth

- Sizes are tokens: 26, 22 and 17 px titles, 15 px body and headline, 14 px
  controls, 13 px captions. Nothing is smaller than 13 px (a rule test reads
  every `font-size`). Titles of 20 px and over use `--font-display`;
  `--font-mono` is for IDs, payloads and code. Numbers that change or line up
  are tabular (`num`).
- Space is `--space-1` to `--space-12` on a 4 px grid. Radii are
  `--radius-chip` 4, `--radius-control` 6, `--radius-card` 10, `--radius-panel`
  14, `--radius-tile` 20 and `--radius-capsule`. Depth is `--elevation-card`,
  `-raised`, `-floating`, `-modal`.

## Parts to reuse

- **Icons**: `<Icon name size filled label />` (`components/icons/`), Lucide's
  shapes vendored with their licence. A test fails on an icon nobody uses.
- **Primitives** (`components/ui/`): `Popover`, `Menu` and `MenuButton`,
  `useContextMenu`, `Sheet`, `Inspector` and `InspectorGroup`, `IconButton`,
  `Switch`, `Segmented`, `Status`. They own focus, Escape, outside presses and
  ARIA. A floating layer renders into `document.body` and registers in
  `ui/layers.ts`, which gives Escape to the topmost layer and closes a layer
  whose section is hidden under it: every section stays mounted.
- **The shell**: `App.tsx`, `Rail`, `Toolbar` (props only), `CommandPalette`
  (rows in `lib/palette.ts`). Every shortcut is in `lib/shortcuts.ts`; match a
  key with `matchesKeys` and `shouldIgnoreKey`, show one with `withShortcut`.
  A section change goes through `App.tsx`'s `setSection` or `goTo`, which
  cross-fades through a view transition (`lib/viewTransition.ts`).
- **Empty states and vignettes**: `EmptyState` and `EmptyVignette`
  (`components/EmptyState.tsx`) draw a desk at rest, the library or the
  calendar from the office's own parts; `components/office/vignette.ts` holds
  where such a desk stands.
- **A context menu** offers only actions its thing already has elsewhere.
- **A switch** is for something that takes effect at once. A setting saved
  with a form's Save button is a checkbox, as in a native app.

## Native details

Controls keep the arrow pointer; only a link shows the hand (the rule "the
pointer" lists the link rules). Chrome's words are not selectable and its
pictures cannot be dragged; content (notes, summaries, the log) can be
selected. The window does not rubber-band. The focus ring is 3 px of
`--focus-ring` on `:focus-visible`, following the element's corners. Disabled
controls drop to 40%. A loading list shows a `Skeleton`, not "Loading". The
webview's own context menu opens only in fields and over selected text
(`lib/nativeMenu.ts`). On macOS inside the app the title bar is an overlay
(`data-titlebar="overlay"`), and the rail's selection greys while another
window is in front (`data-window-active`).

## Motion

Animate `transform` and `opacity`. Controls and menus use `--spring-snappy`,
panels and sheets `--spring-smooth`, arrivals `--spring-bouncy`
(generated by `lib/springs.ts`); fades use `--dur-*` with `--ease-out`.
Nothing lifts toward the pointer; a press scales to 0.97. The event log, the
approval panel and the run summary never animate their arrival, because a
replay must look like the live run. The office may, under decision D1
([The office](8_the_office.md)). Reduced motion shrinks every duration to
1 ms (`styles/accessibility.css`), and a hidden window pauses every animation
(`lib/visibility.ts`).

## Seeing and testing it

| Command | What it does |
|---|---|
| `just workbench` | every page from fixtures, no sidecar (`src/workbench/pages.tsx`) |
| `just test-visual` | each page in Chromium and WebKit: a screenshot comparison and axe |
| `just test-visual --update` | rewrite the baselines after an intended change |
| `just ui-shots <label>` | the real app from scratch data, both themes, three sizes; fails on sideways overflow and on a control Tab cannot reach |
| `just ui-shots <label> --forced-colors` | the same under forced colours (or `--reduced-motion`) |

The user guide's pictures (`docs/user_guide/images/`) are `just ui-shots`
captures at 1,100 by 800 in light: capture, look at each, and copy over the
file of the same subject. Never use Space settings, which shows the scratch
folder's full path, and never a capture from real data.

A changed visual baseline is looked at before it is committed, and a test
changed for a markup change is listed in `docs/verification.md`. Fixtures and
screenshots come from made-up content and scratch data only.
