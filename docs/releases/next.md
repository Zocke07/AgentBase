# AgentBase (next release): draft

*Draft notes for the redesign (Phase 20). Rename this file to the version's
number (`0.x.y.md`) when the release is tagged, and add the other changes
made since 0.4.8, which `docs/verification.md` lists. Not yet checked on an
installed build on either platform.*

AgentBase has a new look, made to feel at home on macOS and Windows, and a
run is now drawn as an office where you can watch your agents work.

## What changed

- **A run is an office.** Each agent has a desk: the supervisor in front, a
  desk for each worker behind. Work handed on travels as a folder, every
  tool call appears as a slip on the desk and gets a stamp when it is done
  or refused, and each figure's pose says what its agent is doing: asking
  its model, thinking, using a tool, or waiting for you. What an agent says
  is shown as what it said; what its tools did is shown as what happened.
  Click a desk for everything that agent said and did. The cards-and-arrows
  diagram is gone.
- **Play a run back.** The timeline under the office plays a finished run at
  1x to 8x, steps one event at a time, and jumps between the moments that
  mattered: work handed on, questions, refusals, errors, files written.
- **Find anything.** Press Ctrl+K (Command+K on a Mac) or the magnifying
  glass to find a section, an action, a space, a run, an agent or a note.
  Ctrl+comma (Command+comma) opens Settings.
- **Right-click menus** on runs, agents, notes and folders, and the office's
  desks, with what each already offers. Shift+F10 or the Menu key opens the
  same menu from the keyboard.
- **Agents as desks.** The Agents section shows each agent as a desk card
  with its role, model, tools by risk and an Available switch; a desk opens
  its editor at the side.
- **Home shows what is going.** A desk lights over each run in progress and
  raises a card when it waits for you; when nothing runs, Home says when the
  space next runs on its own.
- **Knowledge.** A note's tags, properties and links sit beside it. Space on
  a note in the Notes list shows a preview without leaving the note you are
  on.
- **Usage.** Daily spend is easier to read, with the busiest day labelled,
  a tooltip on each day and the figures as a table, and each model shows its
  share of the cost.
- **Throughout.** A toolbar with each section's name, a sidebar with a
  clearer selection, settings laid out as rows, empty sections that say what
  to do next, a calmer start screen, sections that fade into one another,
  and a clearer keyboard focus ring.
- **macOS.** The window's buttons sit in the toolbar row, and dragging the
  toolbar's empty space moves the window. Windows keeps its own title bar.

## Things to know

- Nothing about how runs work, what they cost or what agents may do has
  changed: this release changes how AgentBase looks and how you move
  around it.
- Chart colours in Knowledge changed to a set chosen to stay distinct for
  colour-blind readers.
- If motion is reduced in your system settings, the office stays still and
  shows the same information.
