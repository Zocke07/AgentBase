# Knowledge and memory

[Guide contents](README.md)

## One vault per space

Open **Knowledge**. Every note is an ordinary UTF-8 Markdown file in the
selected space folder, editable in the built-in editor, Obsidian, VS Code, or
another text editor, never a proprietary import.

**Open in Obsidian** appears only for installer-default locations (`Applications`
on macOS; the per-user program folder on Windows). It asks the desktop shell to
open the validated space through Obsidian's URI handler; the webview has no
general URL-opening permission. Otherwise use **Space settings → Open folder**
and Obsidian's vault picker. The built-in editor always works.

Use folders to keep a larger vault scannable. A useful starting shape is:

```text
knowledge/
  projects/
  research/
  decisions/
  procedures/
templates/
daily/
captures/
memory/
  runs/
  inbox/
  merged/
```

AgentBase writes `memory/` after runs/proposals; `captures/` holds event-log
saves; **Daily note** uses `daily/`; **From template** uses `templates/`.

The folder-tree **✕** confirms, backs up every file under `.agentbase/backups/`,
then deletes the folder and all contents. Its links become unresolved. It
cannot delete the vault root or hidden folders.

The tree lists notes by file name, and under a note whose title differs it
shows the file name too: an agent's `decisions/2026-10-06.md` can be titled
**DECISION TABLE**, and the file name is the one its run reports. The
`memory` folder of run summaries starts folded, since **Saved context**
manages them; select it to unfold. The open note's folder always unfolds.

## User Summary and Technical Details

Knowledge opens on **User Summary**: what was written for you to read,
grouped and newest first.

- **Decisions**, **Portfolio reviews**, **Weekly reviews** and **Market
  alerts**: the pipeline's dated reports.
- **Forecast workbooks**: the monthly Excel workbook, named for its month,
  such as **Forecasts for October 2026**.
- **Charts and dashboards**, drawn when opened.
- **Daily notes** and other **Notes**: yours and the research notes agents
  write.

Each opens in **Preview**, a reading view, so looking at a file cannot change
it; **Write** or **Split** edits a note. **Find a result** narrows the list,
**New…** starts a note, chart, dashboard or diagram, and **All reports as one
page** opens the Journal.

**Technical Details** holds what the agents work from: the raw collected data
(`raw/`), the bull and bear theses, risk checks, the computed portfolio, the
forecast ledger, your settings and inputs (`config/`, `portfolio/positions.csv`),
run summaries and templates. Its tabs are **Recent**, **Notes** (the whole
vault, with search, tags, links, **Graph** and **Evaluate**), **Agent files**
and **Saved context**. A file appears in one section's list, never both; a
note or file a run links to opens in the section it belongs to.

## Journal

The Journal, under User Summary's **All reports as one page**, reads every
dated report in the space as one page, newest first:
each day's decision (`decisions/`), its portfolio review
(`portfolio/review-*`), the weekly review of the month's predictions
(`scores/review-*`), each market alert's explanation (`alerts/`), your daily
notes, and any other note with a date in its file name. A month's review heads
that month. The dates are listed down the
left, grouped by month; select one to jump to it. **Show** narrows the page to
one kind, such as decisions only. The page draws a week of dates at a time,
and **Show N older dates** adds the next. **Open note** opens a report in
Preview; **‹ All results** returns to the list. Run summaries and templates
never appear here.

The Journal only reads. Each report stays its own file, because an agent can
only rewrite a whole file and reads at most a file's first 20,000 characters:
a single log that grew every day would have to be copied out and back by a
model, would hide its newest entries from the next run, and could change a
past prediction before it is scored.

## Recent

Under Technical Details, **Recent** lists notes and agent files together, newest first, under Today,
Yesterday and Earlier, whoever wrote them. Select one to open it in **Notes** or
**Agent files**. Run summaries stay in **Saved context**. Each day shows its
reports and the inputs you keep; the working data the runs write for each
other (`raw/`, `theses/`, `risk/`, `scores/`, the computed portfolio and its
weights) folds into one **Show N working files** line. Every Knowledge list
rereads the space folder when you open the section, when a run finishes and
when you return to the window, so a run's outputs appear without a restart.

## Agent files

Under Technical Details, **Agent files** lists the raw data, settings and
records in plain text: `.json`, `.jsonl`, `.csv`, `.txt`, `.yaml`, `.yml`,
`.toml`, `.ndjson`, and `.tsv`, including `config/watchlist.json`,
`raw/news-*.json`, and `portfolio/positions.csv`. Workbooks, charts and
dashboards are listed in User Summary instead. A file opens in **Preview**: a
table where it has rows (CSV, TSV, JSON-lines, or a JSON list of records,
the first 200 rows), other JSON indented, anything else as written. **Text**
edits it and **Save file** writes it; invalid `.json` is refused before write.
**New file** accepts a space-relative path; an empty list offers three roster
config templates. **Delete…** confirms and backs up to `.agentbase/backups/`.
Hidden files, binaries, and out-of-space paths remain inaccessible. Agents use
the same `write_file` approval to modify them. A folder holding only the runs'
working data (`raw/`, `theses/`, `risk/`, `scores/`) starts folded; select its
name to unfold it. A search, or a file opened from a run, unfolds its folder.

A CSV, TSV, JSON or JSON-lines file also has **Chart**, which draws it; **Save
chart** keeps that chart as a file of its own, opened in User Summary. A saved
chart (`.viz.json`), dashboard (`.dashboard.json`) or Mermaid diagram (`.mmd`)
opens drawn, with **Text** for its source; one whose data file a run has not
written yet says **No data yet** rather than failing. User Summary's **New…**
starts a new chart, dashboard or diagram. [Charts and dashboards](7_visualizations.md)
covers them in full.

## Links, properties and preview

Link notes with `[[research/sqlite]]`,
`[[research/sqlite#Concurrency|the concurrency section]]`, or Markdown `.md`
links. Typing `[[` suggests matches; Enter completes. **Links** shows backlinks
(`←`), outgoing links (`→`), and unresolved names (`?`); select to open, and
heading links scroll. **Graph** shows all vault links or, with **Around this
note**, the open note and neighbors.

Preview supports Obsidian `#tags` (filterable), `==highlights==`,
`~~strikethrough~~`, callouts (`> [!tip] Title`; `[!warning]-` starts folded),
task boxes that update source, nested lists, tables, and language-tagged fenced
code. A single newline is a line break.

Start a note with YAML properties for organization and retrieval:

```md
---
type: decision
status: accepted
pinned: true
tags:
  - architecture
  - database
---
# Storage decision

Use SQLite in WAL mode. Related: [[research/sqlite]].
```

Properties/tags appear below the path. A note opens in **Preview**; **Write**
shows its source and **Split** pairs source with safe preview; Ctrl/Cmd+E
cycles modes. A new note starts in **Split**. The
formatting bar wraps selections in bold, italic, highlight, code, or links, or
turns lines into headings, lists, tasks, quotes, or callouts. Note HTML never
executes. Hidden folders, including `.obsidian`, are excluded and uneditable.

**Save note** (Ctrl/Cmd+S) writes the file. **Unsaved** means source differs
from disk; opening another note asks whether to discard it. The status line
shows word count and last change.

## Managing the vault

- **Files** folds folders and marks the open note. Its filter narrows the tree;
  Enter runs retrieval. The search icon/Ctrl/Cmd+O opens a quick switcher:
  choose a title/path or create it when none matches.
- **Filters.** **Show notes** selects pinned, orphaned, or unresolved-link
  notes; tag chips filter by tag. The header counts orphans/unresolved links.
- **Pin note** sets `pinned: true`, adds a star, and bypasses all retrieval
  filters, including memory trust.
- **Move or rename** changes a path, rewrites inbound wikilinks/Markdown links,
  and backs up changed files under `.agentbase/backups/` first.
- **Daily note** opens `daily/YYYY-MM-DD.md`, using `templates/daily.md` when
  present. **Template** lists `templates/` notes, fills `{{date}}` / `{{title}}`,
  then prompts for a save path.
- **Import vault folder** preserves chosen-folder Markdown relative paths.
  Existing notes skip unless **replace conflicts with backup** is selected,
  which backs them up. Limit: 10,000 notes per space; overage is reported and
  not fully indexed.
- **Delete note…** confirms and keeps a copy under `.agentbase/backups/`, as
  deleting a file or folder does.

### When something does not work

A file action that fails says why in words and changes nothing else:

- A new note or file is never saved over one that already has its name: the
  save stops, says the name is taken and keeps what you wrote.
- A file that cannot be opened offers **Try again** and cannot be saved, so
  nothing unread is ever written over.
- Something a run or another window already removed is treated as gone: the
  list refreshes, and deleting it again simply finishes.
- Leaving a note or data file with unsaved changes, by opening another one or
  switching section, asks first.
- When the disk refuses, for instance because a workbook is open in Excel on
  Windows, the message names the file and asks you to close it and try again.
  If AgentBase's engine is restarting, the message says so instead of a
  browser error.

## Local retrieval and citations

Knowledge and agents share retrieval. Notes split at headings; chunks rank by
BM25, deterministic local term vector, and term/title/tag overlap. No separate
embedding/vector service receives data. Searches/runs read live files, so the
next access sees external edits and reparses only changes.

Results include stable citations such as `[[research/sqlite#Concurrency]]`,
relevance, matches and locations (title, heading, tag, body), and estimated
tokens. **folder** / **#tag** narrow results; select one for source and context.

## What a run receives

At run start, AgentBase retrieves up to six goal chunks and retrieves again for
each worker handoff. It sends cited excerpts to the selected model as untrusted
reference material. Cloud models receive these excerpts with the prompt; use a
separate space for notes that must never reach them. Retrieval tells models not
to execute note instructions, but review imported content for prompt injection.

Home **Preview notes** shows **Notes it will read** before start: rendered
citation/excerpt, score, matches, tokens, kept total, and receiving model.
Untick to exclude it from the run and handoffs; the exclusion is recorded.
Select citations here or in **Retrieved context** to open the note.

Run **Retrieved context** folds `run.started` to show supervisor excerpts and
excluded citations, so replay and live use the same evidence. Worker excerpts
appear in their `llm.request`. Allowlisted `search_knowledge` is low-risk and
passes the standard read approval gate.

## Saved context

Successful runs can save `memory/runs/<run-id>.md` with the goal, supervisor
outcome, citations, properties, and `agent-memory` tags. The unique ID prevents
overwrites; `run.completed` stores its path. Allowlisted `propose_memory` is a
medium-risk agent proposal written under `memory/inbox/`. Failed or cancelled
runs produce no run summary; their logs remain in **Runs**.

Knowledge's **Saved context** tab keeps this feature in one place. Its
management selector has three modes:

- **Automatic**, the default: after each successful run, the space's default
  model audits bounded new and existing context. It can keep a durable item,
  archive a disposable one, or combine clearly overlapping items. Uncertainty,
  conflict, sensitive material, and consequential changes stay in **Needs
  attention** for you. It may return questionable existing context to your
  attention, but never archives previously available context on its own.
- **Review every item**: every generated summary and proposal waits for you
  before later runs can retrieve it.
- **Off**: new run summaries and agent proposals are not saved.

Automatic management uses an extra bounded model call, counts against the
run's time and cost limits, treats every memory as untrusted input, and accepts
only a validated set of keep, archive, review, or merge decisions. If that call
fails or returns an invalid answer, new context remains in **Needs attention**.
Every managed item records the model and reason. Changes and merges are backed
up so their provenance remains inspectable.

The filters separate **Needs attention**, **Available**, and **History**. Open
an item to see its source run, creation time, confidence, tags, citations, and
management record. You can still override the model:

- **Keep for future runs** or **Move to history** changes whether retrieval can
  use the item.
- **Always include** pins it regardless of relevance; **Use when relevant**
  removes that pin.
- **Edit** corrects its Markdown content.
- **Combine** selected items into one `memory/merged/` note and archives the
  backed-up originals with `merged_into`.
- **Forget** permanently deletes it after confirmation.

## Capturing notes from a run

In a run event log, expand an agent message or completion and choose **Save as
note**. It writes `captures/<run-id>-<event>.md` in the run's space with run,
event, and agent properties. Captures retrieve as ordinary notes and are never
automatically overwritten.

## Evaluating retrieval

**Evaluate** runs a small vault test set. Enter one question per line, `=>`,
and expected note paths, then **Run evaluation**. Results show mean reciprocal
rank, recall at the chosen limit, and each result, letting you validate notes
or ranking changes.
