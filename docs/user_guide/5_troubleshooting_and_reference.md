# Troubleshooting and reference

[Guide contents](README.md)

## Startup and model setup

**The app stays on “Starting the engine” or says it “could not start its engine.”**
The local server failed to start or another process holds 8787. **Waiting for
an earlier AgentBase to finish closing** means something else answers on that
port; it is usually a copy of AgentBase that is still quitting. Quit other
AgentBase instances/development servers and reopen or select **Try again**.
A first start after installing or updating can take a minute or two.
**Technical details** shows the attempted address and error. A different-sidecar
message means another launch occupies the port and this app refused to attach.
Installed apps always use `127.0.0.1:8787`.

**macOS blocks the app.**
Follow [macOS installation](1_getting_started.md#macos). The app is ad-hoc
signed, without trusted Developer ID signing or notarization. Gatekeeper and
the later keychain prompt are separate. Replace an "app is damaged" 0.2.0
download with the current disk image.

**Spotlight does not find AgentBase, or Finder shows several copies.**
It is running from Downloads or the disk image. macOS launches quarantined apps
outside Applications from a temporary copy, registering each independently.
Drag **AgentBase** to the disk image's **Applications** link, delete Downloads
copies, and launch it from Applications.

**Home says there is no API key, or a run fails with “No API key.”**
Set the selected provider's key in **Settings → Keys**, then use **Restart
AgentBase** or reopen the app. **set: restart AgentBase to apply** means the
running sidecar lacks it. On macOS, relaunch and allow a denied named keychain
item. Also check space and agent provider overrides.

**ChatGPT subscription says disconnected or connecting.**
Under **Settings → Provider**, select **openai** and **ChatGPT subscription**,
then **Connect ChatGPT**. Complete browser sign-in and return. If it does not
open, retry and allow the browser; **Cancel** a stuck attempt or **Sign out**
and reconnect. A working OS credential store is required; plaintext fallback is
deliberately refused.

**ChatGPT is connected, but the selected OpenAI model fails.**
ChatGPT and API accounts can have different model entitlements/allowances.
AgentBase sends the same selected ID in both modes and never substitutes one.
Choose a plan-available model, wait for allowance reset, or switch **OpenAI
access** to **API key**.

**Check says Ready, but a real run fails.**
**Settings → Provider → Check** only checks saved local configuration; it does
not authenticate or call a model. Read the run error for invalid keys,
unavailable models, provider limits, or networking. Save changes before checks.

**The model is unpriced.**
Choose a model from the relevant dropdown, including space/agent overrides.
Anthropic dated snapshots such as `claude-haiku-4-5-20251001` use alias
`claude-haiku-4-5`; all other IDs must exactly match pricing. Ollama costs zero
in the app.

**Ollama is slow or does not finish.**
Confirm its daemon runs and `ollama list` contains the selected model.
`qwen3:4b` completed project runs; other models may need different hardware or
fail to coordinate workers. Raise space time/step limits only when reached,
and check agent step ceilings. Higher limits cannot make a model choose to
finish.

## Runs, approvals and spaces

**A completed run did not produce its claimed file.**
The supervisor summary is only its account. Check log `write_file` entries and
results, then **Space settings → Open folder**. Coordination calls also count,
so a summary or nonzero total does not prove a file was written.

**A run lists missed lookups or calls sent again.**
An agent looked for a file or folder that was not there, or sent a request
to read without saying which file. Nothing was changed, the agent was told,
and it can look again; a missed lookup does not stop a chain. A call sent
again is a request the app could not run as written, such as one whose
details came out garbled, that the agent then sent again and the app ran.
The first try ran nothing, so it does not stop a chain either. Open the list
to see each one. A failed write, fetch, calculation or model call is listed
as an error instead, and is worth reviewing before you trust the outcome, as
is a request that could not be run and was never sent again: what it would
have done may not have happened.

**I denied a request and another question appeared.**
Exact same-run tool/argument repeats are automatically denied. Different
arguments can ask again. Inspect and deny the new call, or **Cancel run**.

**The approval panel has no Allow or Deny buttons.**
You may be replaying an earlier point or viewing a finished run. **Jump to end**
to answer current requests. Requests pending at app close expire on next start.

**The budget cap is reached.**
Raise **Settings → Monthly budget → Monthly cap (USD)** or wait for the next
UTC month. The cap spans spaces and deletion preserves spending. ChatGPT
subscription calls use API-equivalent price for this local cap, not an API bill.

**A run or agent disappeared after switching spaces.**
Runs and rosters belong to the selected space. Switch back or inspect
**Archived**. Moved agents belong to their destination; copied agents are
independent definitions.

**A space cannot be deleted.**
The default space is protected. Other spaces need no runs; archive to retain
history while blocking new runs, or delete finished runs first. Deletion removes
definitions but preserves the folder and files.

## Discord

**The bot does not respond.**
Check **Settings → Chat channels** for **running**, connection errors, and
refused accounts. Set a missing token in **Keys** and restart. Confirm server/
channel access. If `/agent` is absent, review
[Discord setup](4_integrations.md#create-and-install-the-bot) scopes.

**The bot says my account is not allowed.**
Add your numeric ID under **Who may give the bots tasks**, **Add**, then
**Save settings**. A display name is not an account ID.

**A chat run is in the wrong space.**
Choose and save **Where a chat command runs** under **Settings → Chat channels**.
It routes future commands only.

## Data and upgrades

| Data | Windows | macOS |
|---|---|---|
| App data folder | `%LOCALAPPDATA%\dev.agentbase.desktop` | `~/Library/Application Support/dev.agentbase.desktop` |
| Runs, events, agents, settings and spending | `agentbase.sqlite3` inside app data | `agentbase.sqlite3` inside app data |
| A space's files | `spaces\<space-id>` inside app data | `spaces/<space-id>` inside app data |
| Keys and bot token | Windows Credential Manager | macOS Keychain |

Use **Space settings → Open folder** for the exact space folder. Its stable ID
means renaming does not move or lose files. Upgrades from before spaces place
legacy runs/agents in the default space and adopt legacy `workspace` as its
folder.

Each run's event log is its persistent work record. The UI has no separate app
log; for startup/developer diagnostics, see the
[debugging guide](../developer_guide/3_debugging.md).

Quit AgentBase before manually backing up or removing data. Copy the whole app
data folder to preserve database, SQLite companion files, and spaces together.
Keys live separately in OS credential storage.

## Uninstall or start over

On Windows, uninstall through **Settings → Apps**; on macOS, remove
**AgentBase.app**. Both leave app data and stored credentials.

To erase runs, definitions, settings, and space files, quit and delete the
listed app-data folder after copying what you need. Next launch creates a
fresh default space and built-in roster.

To remove a key while keeping the app, use **Settings → Keys → Clear** and
restart. After uninstalling, use Credential Manager or Keychain Access.
Current secret names:

| Name | Purpose |
|---|---|
| `anthropic_api_key` | Anthropic API key. |
| `openai_api_key` | OpenAI API key. |
| `discord_bot_token` | Discord bot token. |

The service is `dev.agentbase.desktop`. Windows credential addresses are
`<name>.dev.agentbase.desktop`; macOS items use that service and secret name as
the account. You can also remove old Telegram credentials.

## Advanced local API reference

Use the app window for normal setup. While it runs,
`http://127.0.0.1:8787/docs` exposes its local API for inspection/advanced use.
This is not **Settings** and cannot store OS-keychain secrets.

| Endpoint | Use |
|---|---|
| `GET /settings` | App defaults, loaded-secret names, sidecar version/data folder. |
| `PATCH /settings` | Change defaults; rejects unknown fields. |
| `GET /settings/providers` | Providers and models priced in this build. |
| `POST /settings/verify` | Check local provider configuration without a model call. |
| `GET /auth/chatgpt` | Safe ChatGPT connection state; never OAuth tokens. |
| `POST /auth/chatgpt/runtime` | Fetch pinned Codex App Server runtime; status reports progress. |
| `POST /auth/chatgpt/login` | Start browser sign-in. |
| `POST /auth/chatgpt/login/cancel` | Cancel active sign-in. |
| `POST /auth/chatgpt/logout` | Delete ChatGPT session from credential storage. |
| `GET /budget` | Shared monthly spend and cap. |
| `GET /usage` | Ledger calls by model, space, day, and run; `period` is `YYYY-MM`, `space_id` narrows. |
| `GET`, `POST /schedules` | List by `space_id` or create an app-open scheduled space goal, optionally with `max_run_seconds`. |
| `PATCH`, `DELETE /schedules/{id}` | Change, switch off or remove a schedule. |
| `POST /schedules/{id}/run` | Start now without changing next run time. |
| `POST /schedules/preview` | Describe cadence and next three times before save. |
| `GET /spaces` | Spaces and their folder paths. |
| `GET /spaces/{id}/knowledge` | Markdown notes, vault statistics, and incremental-index result. |
| `GET`, `PUT`, `DELETE /spaces/{id}/knowledge/note` | Read, save or delete a Markdown note. |
| `POST /spaces/{id}/knowledge/move` | Move/rename a note, rewrite links, and back up. |
| `DELETE /spaces/{id}/knowledge/folder` | Backed-up folder deletion; never vault root/hidden folder. |
| `GET /spaces/{id}/knowledge/files`; `GET`, `PUT`, `DELETE .../knowledge/file` | List, read, JSON-checked write, or backed-up deletion of plain-text data files. |
| `PATCH /spaces/{id}/knowledge/pin` | Pin or unpin any note. |
| `POST /spaces/{id}/knowledge/import` | Import Markdown, skipping or backing up conflicts. |
| `POST /spaces/{id}/knowledge/search` | Local cited retrieval with optional folder/tag/type/date/status filters. |
| `GET /spaces/{id}/knowledge/memories` | Inbox of run/agent memories with status, citations, provenance. |
| `PATCH /spaces/{id}/knowledge/memory` | Approve, archive or pin a memory. |
| `POST /spaces/{id}/knowledge/memories/merge` | Merge memories, archive originals. |
| `POST /spaces/{id}/knowledge/evaluate` | Score retrieval against expected note paths. |
| `GET /spaces/{id}/knowledge/graph` | Resolved note-link nodes/edges. |
| `GET /agents` | Agent definitions; select roster with `space_id`. |
| `GET /runs` | Run history; narrow with `space_id` or `origin` (`ui`, `schedule`, `discord`). |
| `GET /channels` | Discord state, errors, and refused accounts. |
| `GET /tools` | Registered tools and risk levels. |

The API uses integer dollar-millionths: `monthly_cap_micros: 20000000` is
$20.00. Desktop settings accept dollars. The server binds only to loopback;
Discord connects outward rather than exposing it to chat.
