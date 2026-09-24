# Troubleshooting and reference

[Guide contents](README.md)

## Startup and model setup

**The app stays on “Connecting to the sidecar” or says “Sidecar unreachable.”**
The local server could not start or another process is holding port 8787.
Quit other AgentBase instances or development servers and reopen the app,
or use **Retry**. A message about a different sidecar means the app found a
server from another launch on that port and refused to attach to it. The
installed app uses the fixed address `127.0.0.1:8787`.

**macOS blocks the app.**
Follow the [macOS installation steps](1_getting_started.md#macos). The app is
ad-hoc signed but does not have a trusted Developer ID signature or Apple
notarization. The Gatekeeper exception and the later keychain access prompt
are separate. If an earlier 0.2.0 download reports that the app is damaged,
download the current disk image again.

**Spotlight does not find AgentBase, or Finder shows several copies.**
The app is running from Downloads or straight from the disk image. macOS
starts a quarantined app outside Applications from a temporary copy on every
launch, and each copy is registered separately. Drag **AgentBase** from the
disk image onto its **Applications** link, delete any copy left in Downloads,
and open the one in Applications.

**Home says there is no API key, or a run fails with “No API key.”**
In **Settings → Keys**, set the key for the selected provider, then click
**Restart AgentBase** under the key list, or quit and reopen the app. A row
saying **set: restart AgentBase to apply** has not
been loaded into the running sidecar. On macOS, a denied keychain read also
leaves the key unavailable: relaunch and allow the named keychain item. Check
whether the space or an individual agent selects a different provider from
the app default.

**ChatGPT subscription says disconnected or connecting.**
In **Settings → Provider**, select **openai** and **ChatGPT subscription**, then
click **Connect ChatGPT**. Complete the OpenAI page in the browser and return
to the app. If the page did not open, retry and allow the browser window. Use
**Cancel** to discard a stuck attempt, or **Sign out** and connect again. The
OS must provide a working credential store; AgentBase deliberately refuses
plaintext fallback storage.

**ChatGPT is connected, but the selected OpenAI model fails.**
ChatGPT plans and API accounts can offer different model entitlements and
usage allowances. AgentBase sends the same selected model id in both modes
and never substitutes a different one. Choose a model available to the plan,
wait for its usage allowance to reset, or switch **OpenAI access** back to
**API key**.

**Check says Ready, but a real run fails.**
**Settings → Provider → Check** checks the saved local configuration. It does
not authenticate with the provider or send a model request. Read the run's
error for an invalid key, unavailable model, provider limit or network
problem. Save changed settings before checking them.

**The model is unpriced.**
Choose a model offered by the relevant model dropdown. If the space or an
agent pins its own model, change it there as well. An Anthropic dated snapshot
such as `claude-haiku-4-5-20251001` is priced as its alias
`claude-haiku-4-5`; other ids must match the table exactly. Local Ollama
models are priced at zero by the app.

**Ollama is slow or does not finish.**
Confirm the daemon is running and `ollama list` contains the exact model you
selected. The project has completed runs with `qwen3:4b`; other models may
need different hardware or may fail to coordinate workers. Increase the
space's time or step limit if the run actually hits that limit, and check
agents' own step ceilings. A model that never decides to finish can still
exhaust higher limits.

## Runs, approvals and spaces

**A completed run did not produce its claimed file.**
The supervisor's summary is its account of the work. Check `write_file`
entries and their results in the log, then use **Space settings → Open
folder**. Coordination calls count toward the tool-call total too. A summary
or a nonzero count alone does not prove that a file was written.

**I denied a request and another question appeared.**
An exact repeat of the tool and arguments in the same run is automatically
denied. Different arguments can raise another question, even when the task
sounds similar. Inspect the details, deny the new call, or use **Cancel run**
if you want the task to stop.

**The approval panel has no Allow or Deny buttons.**
You may be viewing an earlier replay position or a finished run. Use **Jump
to end** to answer a current request. Requests left pending when the app
closed are expired on its next start.

**The budget cap is reached.**
Raise **Settings → Monthly budget → Monthly cap (USD)** or wait for the next
UTC calendar month. The cap spans all spaces, and deleting runs preserves
the spending already recorded. ChatGPT subscription calls use the selected
model's API-equivalent price for this local safety cap; the recorded amount is
not an API bill.

**A run or agent disappeared after switching spaces.**
Runs and rosters are shown for the selected space. Switch back, or inspect
**Archived** in the space switcher. A moved agent belongs to its destination
space; a copied agent is an independent definition there.

**A space cannot be deleted.**
The default space is protected. Other spaces must have no runs before they
can be deleted. Archive a space to keep its history while preventing new
runs, or delete its finished runs from **Runs** first. Space deletion removes
its definitions but preserves its folder and files.

## Discord

**The bot does not respond.**
Check **Settings → Chat channels** for **running**, any connection error,
and refused accounts. Store a missing token under **Keys** and restart.
Confirm the bot is installed in the server and can access the channel. If
`/agent` is absent, review the server installation scopes in the
[Discord setup](4_integrations.md#create-and-install-the-bot).

**The bot says my account is not allowed.**
Add your numeric account ID under **Who may give the bots tasks**, click
**Add**, then **Save settings**. A display name alone is not the account ID.

**A chat run is in the wrong space.**
Choose **Where a chat command runs** under **Settings → Chat channels** and
save. This selects the destination for future commands; it does not move
existing runs.

## Data and upgrades

| Data | Windows | macOS |
|---|---|---|
| App data folder | `%LOCALAPPDATA%\dev.agentbase.desktop` | `~/Library/Application Support/dev.agentbase.desktop` |
| Runs, events, agents, settings and spending | `agentbase.sqlite3` inside app data | `agentbase.sqlite3` inside app data |
| A space's files | `spaces\<space-id>` inside app data | `spaces/<space-id>` inside app data |
| Keys and bot token | Windows Credential Manager | macOS Keychain |

Use **Space settings → Open folder** for the exact folder of a space. The
folder follows its stable ID, so renaming a space does not rename or lose its
files. Upgrading an installation from before spaces existed puts its old runs
and agents in the default space and adopts the old `workspace` folder as
that space's folder.

The event log in each run is the persistent record of its work. This version
does not provide a separate application log file in the UI. For startup
output and developer diagnostics, see the
[debugging guide](../developer_guide/3_debugging.md).

Before manually backing up or removing data, quit AgentBase. Copying the
whole app data folder preserves the database, any SQLite companion files
and space folders together. Keys are stored separately in the OS credential
store and are not included in that folder.

## Uninstall or start over

On Windows, uninstall AgentBase through **Settings → Apps**. On macOS,
remove **AgentBase.app** from wherever you installed it. Uninstalling leaves
the app data folder and stored credentials in place.

To erase runs, definitions, settings and space files, quit the app and delete
its app data folder listed above. Copy any files you want to retain first.
The next launch creates a fresh default space and its built-in roster.

To remove a key while keeping the app, use **Settings → Keys → Clear** and
restart. After uninstalling, remove entries through Credential Manager or
Keychain Access instead. Current secret names are:

| Name | Purpose |
|---|---|
| `anthropic_api_key` | Anthropic API key. |
| `openai_api_key` | OpenAI API key. |
| `discord_bot_token` | Discord bot token. |

The service is `dev.agentbase.desktop`. Windows generic credential addresses
are `<name>.dev.agentbase.desktop`; macOS keychain items use that service
and the secret name as the account. Old Telegram credentials can also be
removed manually.

## Advanced local API reference

Normal setup and use are available in the app window. While it is running,
`http://127.0.0.1:8787/docs` exposes the local API reference for inspection or
advanced use. This browser page is not the app's **Settings** screen, and
cannot store secrets in the OS keychain.

| Endpoint | Use |
|---|---|
| `GET /settings` | Saved app defaults, names of loaded secrets, the sidecar's version and data folder. |
| `PATCH /settings` | Change app defaults; unknown fields are refused. |
| `GET /settings/providers` | Providers and the model names priced by this build. |
| `POST /settings/verify` | Check local provider configuration without calling a model. |
| `GET /auth/chatgpt` | Safe ChatGPT connection status; never an OAuth token. |
| `POST /auth/chatgpt/runtime` | Fetch the pinned Codex App Server runtime once; the status reports its progress. |
| `POST /auth/chatgpt/login` | Start ChatGPT browser sign-in. |
| `POST /auth/chatgpt/login/cancel` | Cancel the active sign-in attempt. |
| `POST /auth/chatgpt/logout` | Remove the ChatGPT session from the credential store. |
| `GET /budget` | Shared monthly spend and cap. |
| `GET /usage` | A month of model calls from the ledger, by model, space, day and run; `period` is `YYYY-MM`, `space_id` narrows. |
| `GET`, `POST /schedules` | List (by `space_id`) or create a schedule: a goal a space runs at set times while the app is open, optionally with its own `max_run_seconds`. |
| `PATCH`, `DELETE /schedules/{id}` | Change, switch off or remove a schedule. |
| `POST /schedules/{id}/run` | Start the schedule's run now, leaving its next time as it was. |
| `POST /schedules/preview` | A cadence in words and its next three times, before saving. |
| `GET /spaces` | Spaces and their folder paths. |
| `GET /spaces/{id}/knowledge` | Markdown notes, vault statistics and what the incremental index did. |
| `GET`, `PUT`, `DELETE /spaces/{id}/knowledge/note` | Read, save or delete a Markdown note. |
| `POST /spaces/{id}/knowledge/move` | Move or rename a note, rewriting links, with a backup. |
| `DELETE /spaces/{id}/knowledge/folder` | Delete a folder and everything in it, with a backup; never the vault root or a hidden folder. |
| `GET /spaces/{id}/knowledge/files`; `GET`, `PUT`, `DELETE .../knowledge/file` | The plain-text data files beside the notes: list, read, write (JSON checked) or delete one, with a backup. |
| `PATCH /spaces/{id}/knowledge/pin` | Pin or unpin any note. |
| `POST /spaces/{id}/knowledge/import` | Import Markdown files into the space, skipping or backing up conflicts. |
| `POST /spaces/{id}/knowledge/search` | Local cited retrieval with optional folder, tag, type, date and status filters. |
| `GET /spaces/{id}/knowledge/memories` | The memory inbox: run and agent memories with status, citations and provenance. |
| `PATCH /spaces/{id}/knowledge/memory` | Approve, archive or pin a memory. |
| `POST /spaces/{id}/knowledge/memories/merge` | Merge memories into one note and archive the originals. |
| `POST /spaces/{id}/knowledge/evaluate` | Score retrieval against expected note paths. |
| `GET /spaces/{id}/knowledge/graph` | Resolved note-link nodes and edges. |
| `GET /agents` | Agent definitions; use `space_id` to select a roster. |
| `GET /runs` | Run history; use `space_id` to select a space and `origin` (`ui`, `schedule`, `discord`) to keep runs started one way. |
| `GET /channels` | Discord connection state, errors and refused accounts. |
| `GET /tools` | Registered tools and risk levels. |

The API represents money in integer millionths of a dollar:
`monthly_cap_micros: 20000000` means $20.00. The desktop settings screen
accepts dollars directly. The server binds only to this computer's loopback
address; Discord connects outward instead of exposing this server to chat.
