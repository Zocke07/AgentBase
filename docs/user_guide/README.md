# AgentSpace: User Guide

**Version covered: 0.2.1.** For installation from source and development, use the
[Developer Guide](../developer_guide/README.md).

AgentSpace runs a team of AI agents on your computer. You give a task to a
supervisor, which delegates to the agents you have enabled. The graph and event
log show their work as it happens and let you replay it afterwards.

A **space** groups a roster of agents, a folder for their files, and settings
for their runs. The left rail switches between **Home**, **Runs**, **Agents**
and **Space settings** for the selected space. **Settings** at the bottom
controls defaults, API keys, the shared budget, Discord and appearance.

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
   answer approvals, replay, cancel, delete and manage the budget.
3. [Agents](3_agents.md): the built-in roles, your own definitions, tool
   permissions, and moving or copying agents between spaces.
4. [Integrations](4_integrations.md): connect Discord, allow accounts and
   choose where chat tasks run.
5. [Troubleshooting and reference](5_troubleshooting_and_reference.md): common
   failures, data locations, upgrades, removal and the local API.
