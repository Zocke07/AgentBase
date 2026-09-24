# Knowledge and memory

[Guide contents](README.md)

## One vault per space

Open **Knowledge** in the left rail. Every note shown there is an ordinary
UTF-8 Markdown file in the selected space's folder. AgentBase does not import
the note into a proprietary format, so you can edit the same file in the
built-in source editor, Obsidian, VS Code or another text editor.

**Open in Obsidian** appears in the toolbar only when Obsidian is installed
where its installer puts it (`Applications` on macOS, its per-user program
folder on Windows). It asks the desktop shell to open the space folder through
Obsidian's URI handler; AgentBase validates the folder first and does not give
the webview a general URL-opening permission. If Obsidian lives somewhere else,
or the link does not open, use **Open folder** in Space settings to find the
folder and add it from Obsidian's own vault picker. The built-in editor works
either way.

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

`memory/` is written by AgentBase after runs and agent proposals; `captures/`
holds notes you save from a run's event log; `daily/` and `templates/` are
used by the **Daily note** and **From template** buttons. The rest is yours.

A folder is deleted from the tree: the **✕** that appears beside a folder's
name asks first, then removes the folder and everything in it, notes and
other files alike, after copying every file it held under
`.agentbase/backups/`. Links into the deleted folder become unresolved
links. The vault itself and hidden folders cannot be deleted this way.

## Data files

**Data files**, beside **Files** at the top of the browser, lists the
plain-text files in the space folder that are not notes: `.json`, `.jsonl`,
`.csv`, `.txt`, `.yaml`, `.yml`, `.toml`, `.ndjson` and `.tsv`. These are the
configuration and data the agents read with `read_file` and write with
`write_file`: the investment roster's `config/watchlist.json`, its
`raw/news-*.json`, a `portfolio/positions.csv`. Open one to edit it as plain
text and **Save file**; a `.json` file that does not parse is refused before
it is written, so an agent never reads a broken config. **New file** takes a
path inside the space; an empty list offers the roster's three config files
as templates. **Delete…** asks first and keeps a copy under
`.agentbase/backups/`. Hidden files, binaries and anything outside the
space folder stay out of reach. An agent may change these files too, through
the same `write_file` approval as any write.

## Links, properties and preview

Link notes with Obsidian wikilinks such as `[[research/sqlite]]`,
`[[research/sqlite#Concurrency|the concurrency section]]` or standard
Markdown links to `.md` files. Typing `[[` in the editor lists matching notes;
Enter completes the link. The **Links** pane beneath the note shows linked
mentions (backlinks) with `←`, outgoing links with `→`, and names that match
no note with `?`. Select a link to open the note; a link with a heading
scrolls to it. **Graph** draws the same links across the vault, or, with
**Around this note**, only the open note and its neighbours.

The preview reads the Obsidian dialect: `#tags` (click one to filter the
tree), `==highlights==`, `~~strikethrough~~`, callouts such as
`> [!tip] Title` (`[!warning]-` starts folded), task lists whose boxes you
can tick in the preview to change the source, nested lists, tables and fenced
code with its language. A single newline is a line break, as in Obsidian.

Start a note with YAML properties to make it easier to organize and retrieve:

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

Properties and tags appear under the note's path. **Split** shows Markdown
source and a safe preview together; **Write** and **Preview** use the full
area, and Ctrl/Cmd+E cycles between them. The formatting bar above the source
wraps the selection in bold, italic, highlight, code or a link, or turns the
selected lines into a heading, list, task, quote or callout. HTML inside a
note is not executed. Hidden folders, including Obsidian's `.obsidian`
configuration, are excluded and cannot be edited through the Knowledge screen.

**Save note** (Ctrl/Cmd+S) writes the file; **Unsaved** beside it says the
editor differs from the disk, and opening another note first asks whether to
discard the change. The status line counts words and shows when the file last
changed.

## Managing the vault

- **Files** shows the vault as folders that fold, with the open note marked.
  Typing in the filter box narrows the tree at once; Enter searches note text
  through retrieval instead. The search icon (or Ctrl/Cmd+O) opens a quick
  switcher: type part of a title or path, arrow to it and press Enter, or
  create a note with that name when none matches.
- **Filters.** The **Show notes** menu narrows the browser to pinned notes,
  orphans (notes nothing links to) or notes with unresolved links. The tag
  chips under it filter by tag; the vault header counts orphans and unresolved
  links so you can tidy them.
- **Pin note** marks a note as a favourite with `pinned: true`. Pinned notes
  are listed with a star and pass every retrieval filter, including the memory
  trust filter described below.
- **Move or rename** changes a note's path. Every wikilink and Markdown link in
  the vault that pointed at it is rewritten, and the files that changed are
  copied to `.agentbase/backups/` first.
- **Daily note** (the calendar icon) opens today's `daily/YYYY-MM-DD.md`,
  creating it from `templates/daily.md` when that exists. **Template** lists
  every note under `templates/`; a new note copies it with `{{date}}` and
  `{{title}}` filled in, then lets you choose its path before saving.
- **Import vault folder**, under **Filters and import**, copies the Markdown
  files of a folder you choose into this space, keeping their relative paths.
  Existing notes are skipped unless **replace conflicts with backup** is
  ticked, in which case the replaced files are backed up first. The practical limit is 10,000 notes per space; the
  header says when a vault exceeds it and some notes are not indexed.

## Local retrieval and citations

Knowledge search uses the same retrieval path as agents. Notes are split at
headings, and each chunk is ranked by a BM25 score, a deterministic local term
vector, and term, title and tag overlap. Nothing is sent to a separate
embedding or vector-database service. Because the live files are read when
the index is used, an external edit appears on the next search or run; only
the files that changed are parsed again.

Results carry stable citations such as `[[research/sqlite#Concurrency]]`, a
relevance score, the terms that matched and where they matched (title,
heading, tags or body), and an estimated token cost. The **folder** and
**#tag** fields narrow a search. Select a result to open its source and follow
links or backlinks for surrounding context.

## What a run receives

When a run starts, AgentBase retrieves up to six relevant chunks for the
goal. It retrieves again for each worker's specific handoff. Those excerpts
are sent to the selected model as cited, untrusted reference material. A cloud
model therefore receives relevant excerpts just as it receives the rest of
the run prompt; use a separate space for notes that must never reach that
model. Retrieval tells the model never to execute instructions found inside a
note, but reviewing imported content remains prudent because models can still
be influenced by malicious text.

**Preview context** on the Home page shows what the goal would retrieve before
the run starts: each citation with its excerpt rendered, its score, matched
terms and token cost, the total that will be kept, and the provider and model
those excerpts are sent to. Untick a result to keep it out of the run and its
worker handoffs; the exclusion is recorded with the run. Click a citation,
here or in a run's **Retrieved context**, to open the note in Knowledge.

In the run view, **Retrieved context** lists the excerpts the supervisor
actually received and the citations you excluded, folded from `run.started`,
so a replay shows the same evidence the live view did. Worker-specific excerpts
are visible in that worker's `llm.request` message. Agents whose allowlist
includes `search_knowledge` can refine a search while working; it is a
low-risk tool call and passes through the same approval gate as other reads.

## The memory inbox

After a successful run, AgentBase saves a note at `memory/runs/<run-id>.md`
with the goal, the supervisor's outcome, the citations that were retrieved for
the goal, structured properties and `agent-memory` tags. The unique run ID
prevents an automatic memory from overwriting an earlier note, and the
`run.completed` event records its path. Agents whose allowlist includes
`propose_memory` can also propose a memory of their own while working; it is
a medium-risk tool call that asks for approval and writes to `memory/inbox/`.

Every memory starts as **proposed**. Proposed memories are not retrieved:
they wait in the **Memory inbox** tab of the Knowledge browser, whose count
also shows beside **Knowledge** in the rail. The run that wrote a memory
shows its status under the supervisor's account, with **Approve** and **Open
in the inbox** there, so the decision can be made without leaving the run.
The inbox shows
where each one came from (a run, with an **Open run** link, or an agent),
when it was created, its confidence, its tags and the citations that support
it. From there you can:

- **Approve** a memory so later runs can retrieve it, or **Archive** one to
  keep it without retrieving it. Both are properties in the note's YAML.
- **Pin** a memory so it is retrieved whatever its status.
- **Edit** the note like any other Markdown file if its conclusion is wrong.
- **Merge** several memories: tick them, optionally give the result a title,
  and choose **Merge selected**. The merged note under `memory/merged/`
  carries every goal, outcome, tag and citation; the originals are archived
  with a `merged_into` property after being backed up.
- **Forget** a memory, which deletes its file after a confirmation.

Failed and cancelled runs do not produce a memory; their event logs remain
under **Runs**.

## Capturing notes from a run

In a run's event log, expand an agent message or the run's completion and
choose **Save as note**. The text is written to
`captures/<run-id>-<event>.md` in the run's space with the run, event and
agent recorded as properties. Captures are ordinary notes: they are retrieved
like any other note, and nothing automatic overwrites them.

## Evaluating retrieval

**Evaluate** in the Knowledge toolbar runs a small test set against the
vault. Enter one question per line followed by `=>` and the note paths you
expect, then choose **Run evaluation**. The result reports the mean
reciprocal rank and recall at the chosen limit, and lists what each question
retrieved, so a change to notes or ranking can be checked before relying on
it.
