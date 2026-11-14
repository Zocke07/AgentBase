# AgentBase: User Guide

**Version covered: 0.4.8.** For installation from source and development, use the
[Developer Guide](../developer_guide/README.md).

AgentBase runs a team of AI agents on your computer that work on their own. A
space's automations run goals at set times or one after another while the app
is open; a task you want done once goes to a supervisor, which delegates it to
enabled agents. The office, the diagram and the event log show every step,
live or replayed.

A **space** groups agents, a folder for their files, and run settings. Its
folder is also a Markdown knowledge vault shared by people and agents. The
left rail shows **Home**, **Automations**, **Runs**, **Agents**, **Knowledge**,
**Usage**, and **Space settings** for the selected space; Ctrl/Cmd+1 to 8 jump
to those sections and Settings in order. Badges on **Runs** or **Knowledge** show waiting
approvals or memories. **Settings** at the bottom controls
defaults, model access, API keys, the shared budget, Discord, appearance, and
the version. The first launch opens a short tour that you can replay from
Settings.

Orchestration, tool execution, and the run database stay on your machine. Cloud
models receive the prompts and tool results used in a run. Network tools can
contact public sites, shell commands can use the network, and Discord can send
run updates. Every file, shell, and network tool passes the approval gate. On a
fresh install the gate answers reads, writes inside the space and fetches from
listed sites itself and records why; a shell command always asks, and so does
anything else the policy does not answer. An upgraded install keeps asking
before each call until you choose **Autonomous**.

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
6. [Knowledge and memory](6_knowledge_and_memory.md): the Journal of dated
   reports, Markdown notes, links, properties, Obsidian, retrieval, citations
   and durable run memory.
7. [Charts and dashboards](7_visualizations.md): data files drawn as charts in
   Knowledge, agent-written chart files, dashboards, Mermaid and exports.
