# Troubleshooting and reference

[Guide contents](README.md)

## Startup and model setup

**The app stays on “Connecting to the sidecar” or says “Sidecar unreachable.”**
The local server could not start or another process is holding port 8787.
Quit other AgentSpace instances or development servers and reopen the app,
or use **Retry**. A message about a different sidecar means the app found a
server from another launch on that port and refused to attach to it. The
installed app uses the fixed address `127.0.0.1:8787`.

**macOS blocks the app.**
Follow the [macOS installation steps](1_getting_started.md#macos). The 0.2.0
archive is for Apple Silicon, and the build has no Developer ID signature or
notarization. The Gatekeeper exception and the later keychain access prompt
are separate steps.

**Home says there is no API key, or a run fails with “No API key.”**
In **Settings → Keys**, set the key for the selected provider, then quit and
reopen AgentSpace. A row saying **set: restart AgentSpace to apply** has not
been loaded into the running sidecar. On macOS, a denied keychain read also
leaves the key unavailable: relaunch and allow the named keychain item. Check
whether the space or an individual agent selects a different provider from
the app default.

**Check says Ready, but a real run fails.**
**Settings → Model → Check** checks the saved local configuration. It does
not authenticate with the provider or send a model request. Read the run's
error for an invalid key, unavailable model, provider limit or network
problem. Save changed settings before checking them.

**The model is unpriced.**
Choose a model offered by the relevant model dropdown. If the space or an
agent pins its own model, change it there as well. Local Ollama models are
priced at zero by the app.

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
the spending already recorded.

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
| App data folder | `%LOCALAPPDATA%\dev.agentspace.desktop` | `~/Library/Application Support/dev.agentspace.desktop` |
| Runs, events, agents, settings and spending | `agentspace.sqlite3` inside app data | `agentspace.sqlite3` inside app data |
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

Before manually backing up or removing data, quit AgentSpace. Copying the
whole app data folder preserves the database, any SQLite companion files
and space folders together. Keys are stored separately in the OS credential
store and are not included in that folder.

## Uninstall or start over

On Windows, uninstall AgentSpace through **Settings → Apps**. On macOS,
remove **AgentSpace.app** from wherever you installed it. Uninstalling leaves
the app data folder and stored credentials in place.

To erase runs, definitions, settings and space files, quit the app and delete
its app data folder listed above. Copy any files you want to retain first.
The next launch creates a fresh default space and its three built-in roles.

To remove a key while keeping the app, use **Settings → Keys → Clear** and
restart. After uninstalling, remove entries through Credential Manager or
Keychain Access instead. Current secret names are:

| Name | Purpose |
|---|---|
| `anthropic_api_key` | Anthropic API key. |
| `openai_api_key` | OpenAI API key. |
| `discord_bot_token` | Discord bot token. |

The service is `dev.agentspace.desktop`. Windows generic credential addresses
are `<name>.dev.agentspace.desktop`; macOS keychain items use that service
and the secret name as the account. Old Telegram credentials can also be
removed manually.

## Advanced local API reference

Normal setup and use are available in the app window. While it is running,
`http://127.0.0.1:8787/docs` exposes the local API reference for inspection or
advanced use. This browser page is not the app's **Settings** screen, and
cannot store secrets in the OS keychain.

| Endpoint | Use |
|---|---|
| `GET /settings` | Saved app defaults and names of loaded secrets. |
| `PATCH /settings` | Change app defaults; unknown fields are refused. |
| `GET /settings/providers` | Providers and the model names priced by this build. |
| `POST /settings/verify` | Check local provider configuration without calling a model. |
| `GET /budget` | Shared monthly spend and cap. |
| `GET /spaces` | Spaces and their folder paths. |
| `GET /agents` | Agent definitions; use `space_id` to select a roster. |
| `GET /runs` | Run history; use `space_id` to select a space. |
| `GET /channels` | Discord connection state, errors and refused accounts. |
| `GET /tools` | Registered tools and risk levels. |

The API represents money in integer millionths of a dollar:
`monthly_cap_micros: 20000000` means $20.00. The desktop settings screen
accepts dollars directly. The server binds only to this computer's loopback
address; Discord connects outward instead of exposing this server to chat.
