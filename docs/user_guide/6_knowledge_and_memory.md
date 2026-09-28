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

## Data files

**Data files** lists non-note plain-text space files: `.json`, `.jsonl`,
`.csv`, `.txt`, `.yaml`, `.yml`, `.toml`, `.ndjson`, and `.tsv`, including
`config/watchlist.json`, `raw/news-*.json`, and `portfolio/positions.csv`.
Edit as text and **Save file**; invalid `.json` is refused before write.
**New file** accepts a space-relative path; an empty list offers three roster
config templates. **Delete…** confirms and backs up to `.agentbase/backups/`.
Hidden files, binaries, and out-of-space paths remain inaccessible. Agents use
the same `write_file` approval to modify them.

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

Properties/tags appear below the path. **Split** pairs source with safe preview;
**Write** and **Preview** use the full area; Ctrl/Cmd+E cycles modes. The
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

## The memory inbox

Successful runs save `memory/runs/<run-id>.md` with goal, supervisor outcome,
goal citations, properties, and `agent-memory` tags. The unique ID prevents
overwrites; `run.completed` stores its path. Allowlisted `propose_memory` is a
medium-risk, approval-gated agent proposal written to `memory/inbox/`.

Memories start **proposed** and are not retrieved. They wait in Knowledge's
**Memory inbox**, whose count appears in the rail. A writing run shows status,
**Approve**, and **Open in the inbox** under the supervisor summary. The inbox
shows origin (including **Open run**), creation time, confidence, tags, and
citations. From it you can:

- **Approve** for later retrieval, or **Archive** to keep without retrieval;
  both are YAML properties.
- **Pin** a memory so it is retrieved whatever its status.
- **Edit** it like any Markdown note if its conclusion is wrong.
- **Merge** selected memories (optionally title it). The `memory/merged/` note
  retains every goal, outcome, tag, and citation; backed-up originals archive
  with `merged_into`.
- **Forget** a memory, which deletes its file after a confirmation.

Failed/cancelled runs produce no memory; their logs remain in **Runs**.

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
