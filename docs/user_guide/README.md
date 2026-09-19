# AgentSpace: User Guide

**Version covered: 0.4.0.** For installation from source and development, use the
[Developer Guide](../developer_guide/README.md).

AgentSpace runs a team of AI agents on your computer. You give a task to a
supervisor, which delegates to the agents you have enabled. The graph and event
log show their work as it happens and let you replay it afterwards.

A **space** groups a roster of agents, a folder for their files, and settings
for their runs. Its folder is also a Markdown knowledge vault shared by people
and agents. The left rail switches between **Home**, **Runs**, **Agents**,
**Knowledge**, **Usage** and **Space settings** for the selected space;
Ctrl/Cmd+1 to 7 jump between them in that order, and a badge on **Runs** or
**Knowledge** counts approvals or memories waiting for you. **Settings** at
the bottom controls defaults, model access, API keys, the shared budget,
Discord, appearance, and shows the version. A first launch opens a short tour
of these, which Settings can replay.

Orchestration, tool execution and the run database stay on your machine. Cloud
models receive the prompts and tool results used in a run. Network tools can
contact public sites, shell commands can use the network, and enabling Discord
sends run updates to Discord. Every file, shell and network tool passes the
approval gate; a fresh install asks before each call. You can allow selected
risk levels to proceed automatically.

## Contents

1. [Getting started](1_getting_started.md): Windows and macOS installation,
   model setup, keys, spaces and settings.
2. [Running tasks](2_running_tasks.md): start a run, read the graph and log,
   answer approvals, replay, cancel, delete, schedule runs, and follow cost,
   tokens and context in Usage.
3. [Agents](3_agents.md): the built-in roster, the starter roles, your own definitions, tool
   permissions, and moving or copying agents between spaces.
4. [Integrations](4_integrations.md): connect Discord, allow accounts and
   choose where chat tasks run.
5. [Troubleshooting and reference](5_troubleshooting_and_reference.md): common
   failures, data locations, upgrades, removal and the local API.
6. [Knowledge and memory](6_knowledge_and_memory.md): Markdown notes, links,
   properties, Obsidian, retrieval, citations and durable run memory.
