# Knowledge and memory

[Guide contents](README.md)

## One vault per space

Open **Knowledge** in the left rail. Every note shown there is an ordinary
UTF-8 Markdown file in the selected space's folder. AgentSpace does not import
the note into a proprietary format, so you can edit the same file in the
built-in source editor, Obsidian, VS Code or another text editor.

**Open in Obsidian** asks the desktop shell to open the space folder through
Obsidian's URI handler. If Obsidian is not installed, the operating system may
report that no application handles the link; the built-in editor still works.
AgentSpace validates the folder before opening it and does not give the webview
a general URL-opening permission.

Use folders to keep a larger vault scannable. A useful starting shape is:

```text
knowledge/
  projects/
  research/
  decisions/
  procedures/
memory/
  runs/
```

The `memory/runs/` folder is created automatically after successful runs.

## Links, properties and preview

Link notes with Obsidian wikilinks such as `[[research/sqlite]]` or standard
Markdown links to `.md` files. The note metadata strip shows resolved outgoing
links with `→` and backlinks with `←`. Select either to open the related note.
**Graph** shows the same resolved links across the vault.

Start a note with YAML properties to make it easier to organize and retrieve:

```md
---
type: decision
status: accepted
tags:
  - architecture
  - database
---
# Storage decision

Use SQLite in WAL mode. Related: [[research/sqlite]].
```

Properties and tags appear above the editor. **Split** shows Markdown source
and a safe preview together; **Write** and **Preview** use the full area. HTML
inside a note is not executed. Hidden folders, including Obsidian's
`.obsidian` configuration, are excluded and cannot be edited through the
Knowledge screen.

## Local retrieval and citations

Knowledge search uses the same retrieval path as agents. It splits notes at
headings, calculates deterministic local term vectors, and combines vector
similarity with term, title and tag relevance. Nothing is sent to a separate
embedding or vector-database service. Because the live files are read when the
index is used, an external edit appears on the next search or run.

Results carry stable citations such as
`[[research/sqlite#Concurrency]]`. Search for a subject, select a result to
open its source, and follow links or backlinks for surrounding context.

When a run starts, AgentSpace retrieves up to six relevant chunks for the
goal. It retrieves again for each worker's specific handoff. Those excerpts
are sent to the selected model as cited, untrusted reference material. A cloud
model therefore receives relevant excerpts just as it receives the rest of
the run prompt; use a separate space for notes that must never reach that
model. Retrieval tells the model never to execute instructions found inside a
note, but reviewing imported content remains prudent because models can still
be influenced by malicious text.

The supervisor's initial citations and excerpts are recorded in
`run.started`. Worker-specific excerpts are visible in that worker's
`llm.request` message, so replay preserves the evidence the model received.
Agents whose allowlist includes `search_knowledge` can refine a search while
working. It is a low-risk tool call and passes through the same approval gate
as other reads.

## Durable agent memory

After a successful run, AgentSpace saves a compact note at
`memory/runs/<run-id>.md`. It contains the goal, the supervisor's outcome,
structured properties and `agent-memory` tags. The unique run ID prevents an
automatic memory from overwriting an earlier note. The `run.completed` event
records its path.

Later runs search these files alongside your notes, which provides durable,
per-space memory without hiding conversation state in a vendor database. Edit
or delete a memory like any other note if its conclusion is wrong. Failed and
cancelled runs do not produce an outcome memory; their event logs remain under
**Runs**.
