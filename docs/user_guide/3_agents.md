# Agents

[Guide contents](README.md) · [Next: Integrations](4_integrations.md)

## The roster belongs to a space

Choose a space, then open **Agents** in the left rail. Its enabled definitions
are the workers the supervisor can delegate to. The supervisor itself is
part of the orchestrator and is not a row you edit here.

A fresh install starts with three built-ins in the default space:

| Agent | Role | Allowed tools |
|---|---|---|
| `researcher` | Gather facts and report them plainly. | `read_file`, `list_dir` |
| `writer` | Turn findings into clear prose. | `read_file`, `write_file` |
| `reviewer` | Check work against the requested task. | `read_file`, `list_dir` |

These original built-ins can be edited, disabled and moved, but cannot be
deleted. A new space seeded from the built-in roles receives editable,
deletable copies. An empty space can add them with **Start from the built-in
roles** on Home, or you can define your own agents.

## Create or edit an agent

Click **New agent**, or select an existing agent in the list. Fill in its
fields and save the definition.

| Field | Meaning |
|---|---|
| **Name** | Unique within this space. Use lowercase letters, digits, `-` or `_`, starting with a letter, up to 40 characters. |
| **Role** | A one-line description the supervisor uses when choosing a worker. |
| **System prompt** | Instructions for the worker's task and behavior. The app supplies the coordination instructions. |
| **Provider / Model** | Inherit the current space's defaults, or choose a model for this agent. |
| **Max steps** | A saved ceiling on this agent's turns. Blank selects the lower of 20 and the current app-wide step limit; it is not a value that grows automatically when settings change. |
| **Tools this agent may call** | The tools the agent is permitted to request. An agent with no file, shell or network tools can still reason and report back. |
| **Calls this agent may make without asking** | Optional restriction on automatic approvals. Nothing ticked inherits the space policy; selected levels are intersected with that policy. |
| **Available to the supervisor** | Disable to keep the definition but remove it from future runs' rosters. |

Errors appear beside the relevant field. An explicit **Max steps** must fit
within the app-wide limit when saved; at run time it is also clamped to the
space's effective step limit. Changing only a space's limit does not raise
an agent's saved ceiling.

Allowing a tool lets an agent request it; the approval gate still decides
whether the call may execute. An agent cannot add tools to its own allowlist.
See [Approvals](2_running_tasks.md#approvals) for each tool's effects.

An active run keeps the roster and definitions it started with. Editing,
disabling, moving or deleting a definition changes future runs, while old
runs retain the definitions recorded in their event logs.

## Move, copy or delete

With an existing agent open, **Move to** transfers its definition to another
active space. **Copy to** creates an independent definition there. Choose the
destination in the dropdown to perform the action. A copy receives a unique
name if that name is already used in the destination and is deletable even
when its source is a built-in.

Use the list's **Delete** control and confirmation to remove a definition.
Attempting to delete an original built-in reports that it is protected;
disable it instead if you do not want the supervisor using it.

## Custom tools

The app lets you combine the five registered tools into an agent's allowlist.
It has no UI for installing or writing another tool. Adding a tool requires
a code change; see the
[developer checklist](../developer_guide/5_checklists.md).
