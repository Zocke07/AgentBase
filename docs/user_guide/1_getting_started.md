# Getting started

[Guide contents](README.md) · [Next: Running tasks](2_running_tasks.md)

## Install and open AgentBase

The 0.4.6 downloads are a Windows x64 installer and a macOS Apple Silicon disk
image. Python, Node and Rust are bundled or unnecessary for installed users.
Use the [0.4.6 release](https://github.com/Zocke07/AgentBase/releases/tag/v0.4.6)
or the matching artifact from a successful
[build run](https://github.com/Zocke07/AgentBase/actions/workflows/build.yml).
See the [release notes](../releases/0.4.6.md) for release status and limitations.

### Windows

1. Download `AgentBase_0.4.6_x64-setup.exe` for an x64 Windows PC.
2. Run the installer. The build is unsigned; if SmartScreen shows **Windows
   protected your PC**, choose **More info → Run anyway** to proceed with the
   downloaded build you trust. A new installer or your machine's security
   policy may produce another warning.
3. Installation is for your account and needs no administrator rights. The
   installer includes a WebView2 bootstrapper for machines missing that runtime.
4. Open **AgentBase** from the Start menu.

### macOS

1. Download `AgentBase_0.4.6_aarch64.dmg` for an Apple Silicon Mac. This
   image is not an Intel or universal build.
2. Open the disk image and drag **AgentBase** onto the **Applications** link
   in the window that appears, then eject the image. Installing it there is
   what makes Spotlight list the app; an app run straight from
   the image or from Downloads is started by macOS as a temporary copy each
   time, which can show up as several AgentBase entries in Finder searches.
   Releases before 0.3.2 shipped a zip; if you kept one of those apps in
   Downloads, delete it and use the one in Applications.
3. Open the app from **Applications**. It has no Developer ID signature or
   Apple notarization. If macOS blocks it as an unidentified developer,
   attempt to open it once, then go to **System Settings → Privacy & Security
   → Open Anyway** and confirm the exception. Only do this for the project
   download you intended to run.
   [Apple's instructions](https://support.apple.com/en-us/102445) explain the
   prompts and the exception.

If the installed app remains quarantined, an alternative in Terminal is:

```bash
xattr -dr com.apple.quarantine /Applications/AgentBase.app
```

Adjust the path if you installed it elsewhere. This removes the quarantine
attribute from this app and its contents; it does not add a trusted Developer
ID signature or notarization.

A separate **keychain access** prompt can appear after you have stored a key,
particularly after an upgrade. It names **AgentBase** and
`dev.agentbase.desktop` and may request your **login keychain password**.
Choose **Allow** for this access, or **Always Allow** for this build. It is
asking for the Mac's keychain password, not your model API key. Because these
builds have an ad-hoc code identity, another build may ask again. If you choose
**Deny**, the app starts without that key; quit and reopen it to retry.

## Find your way around

On launch, **Starting up…** means the app is starting its local engine.
After it connects, you land on **Home** in the default space. The
first launch opens a short tour that points at each part of the window and
ends on the demo run; **Skip the tour** or Esc closes it for good, and
**Settings → About AgentBase → Replay the tour** brings it back.

| Control | What it opens |
|---|---|
| Space name at the top of the left rail | Switch spaces, find archived spaces, or choose **New space…**. |
| **Home** | Enter a task, see runs under **Now** and **Recent runs**, and enable or disable agents. |
| **Runs** | Open a current run or replay a past one in this space. |
| **Agents** | Create and edit this space's agent definitions. |
| **Knowledge** | The space folder as a Markdown vault, and the memory inbox. |
| **Visualize** | Charts from data files, saved dashboards and Mermaid diagrams. |
| **Usage** | What this month's model calls cost and carried, by day, model, space and run. |
| **Space settings** | Name, description, folder, model, limits, approval answers and schedules for this space. |
| **Settings**, at the bottom | App defaults, keys, shared budget, Discord, theme and the About box. |
| **Hide the sidebar**, beneath Settings | Folds the rail to icons (Ctrl/Cmd+B does the same); the names stay in tooltips and the space's initial stands in for its name. |

In a window narrower than about 1,100 pixels the rail folds to icons by
itself, and **Show the sidebar** opens it over the page; Esc, a click
outside it, or choosing a section closes it again. Pressing Tab first
offers **Skip to content**, which jumps past the rail to the section.

The header shows the model the selected space uses (by the name its maker
gives it, such as **Claude Opus 5**; hover for the provider), this month's
spending against your monthly limit (hover for the exact figures), and any
approvals waiting across spaces. While setup is unfinished, **Finish setup**
in the header opens Settings. Switching spaces changes what you are viewing;
it does not stop runs already in progress.

A fresh install has no cloud key. **Home** says so in **One step before
your first run** and offers **Open settings**. **Try a demo run** in that
notice shows a scripted run without calling a model or using a key.

Settings is one long page. The row of buttons at its top (**Provider**,
**Keys**, **Budget**, **Limits**, **Chat**, **Appearance**, **About**) jumps
to each section, and **Save settings** stays at the bottom of the window
however far down you are. The first group, **Get started**, holds the two
things a new install needs: the provider and its key.

## Connect a model

### Anthropic or OpenAI with an API key

1. Obtain an API key from your provider's account dashboard.
2. In the AgentBase window, open **Settings → Keys**. Click **Set…** beside
   **Anthropic API key** (`anthropic_api_key`) or **OpenAI API key**
   (`openai_api_key`), paste the key, and click **Save key**.
3. Click **Restart AgentBase**, which appears under the key list once a key
   has been saved or cleared, or quit and reopen the app yourself. The key is
   stored in the OS credential store and read when the app starts, so a
   change takes effect only after a restart, and a restart stops any run in
   progress. **Save settings** is separate from **Save key**.
4. Under **Settings → Provider**, choose the provider, then click **Save
   settings**. The default is Anthropic. The model is not chosen here: each
   space names the model its runs use, under **Space settings → Model**, and
   a new space starts on the provider's default (`claude-opus-5` for
   Anthropic, `gpt-5.5` for OpenAI; an Ollama model is typed). An agent can
   pick its own model in its definition.
5. Click **Check** under **Provider**. A **Ready** result means the saved
   configuration can construct a provider. It does not contact the provider,
   authenticate the key remotely or spend money. Your first run checks the
   real connection.

A space's model dropdown lists the cloud models whose prices this build
knows. A model that is not in its price table is refused before a model call;
an Anthropic dated snapshot such as `claude-haiku-4-5-20251001` is priced as
its alias `claude-haiku-4-5`, so either id works in a space or agent. Keys
are shared by every space. AgentBase displays their names and whether they
are set, never their stored values.

Key entry works in the desktop app. A browser showing the development UI can
only display which keys the sidecar received at startup.

### OpenAI with a ChatGPT subscription

1. In **Settings → Provider**, choose **openai** and select **ChatGPT
   subscription** under **OpenAI access**; the model stays each space's own.
2. Click **Connect ChatGPT**. AgentBase opens an OpenAI sign-in page in your
   browser. Complete sign-in with the ChatGPT account whose monthly plan you
   want to use, then return to AgentBase.
3. Wait for the account status to show **connected**, then click **Save
   settings**. **Check** confirms that the saved mode has a connected account
   without calling a model.

API-key and ChatGPT access both remain the `openai` provider. They use the same
selected model id, AgentBase agent loop, tool catalogue, approvals, event log,
run limits and normalized token accounting. Switching the access radio is the
only AgentBase behavior change. OpenAI can expose different models and usage
allowances to a ChatGPT plan and an API account. AgentBase does not silently
replace an unavailable model; the run reports the provider error so you can
choose another model or return to API-key access.

The first **Sign in with ChatGPT** downloads the OpenAI Codex App Server
runtime (about 113 MB on macOS, 138 MB on Windows) from PyPI into AgentBase's
data folder. The download is refused unless its size and SHA-256 checksum match
the build AgentBase was released with, and it happens once; later launches
reuse it. Settings shows the progress, and API-key access never needs it. The
ChatGPT credential is then stored by that runtime in the OS credential store.
OAuth tokens are never returned to the AgentBase webview or written to its
database. The runtime is used only to obtain one model decision; AgentBase
still executes every tool through its own approval gate. OpenAI's
[authentication guide](https://learn.chatgpt.com/docs/auth) documents ChatGPT
subscription and API-key access as Codex's two sign-in methods, and its
[App Server guide](https://learn.chatgpt.com/docs/app-server) documents the
browser flow used here.

Direct Claude Free, Pro and Max subscription login is not offered. Anthropic's
[authentication terms](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
do not permit third-party products to offer Claude.ai login or route those
credentials, so the ordinary Anthropic provider continues to require
`anthropic_api_key`. Anthropic separately permits products to embed an
unmodified Claude Code binary under stated conditions; that is a Claude Code
product mode rather than an interchangeable credential transport for this
provider loop.

### Ollama

1. Install and start [Ollama](https://ollama.com), then pull a model. This
   project has completed real runs with `qwen3:4b`:

   ```text
   ollama pull qwen3:4b
   ```

2. In **Settings → Provider**, choose **ollama** and leave **Ollama address**
   at `http://127.0.0.1:11434` for the local daemon. Click **Save settings**.
3. In **Space settings → Model**, type `qwen3:4b` into **Model** and click
   **Save space**, then start a small task from **Home**.

Ollama needs no API key, and its calls add $0 to AgentBase's budget. After the
model is downloaded, local inference works offline. Model capability and
speed depend on the model and your hardware; a successful setup check does
not prove that the daemon is running or the model can finish a task.

## Create and configure spaces

Open the space switcher, select **New space…**, enter a name, and choose
whether to start with **the three starter roles**, **no agents**, or
**copies of the current space's agents**. Click **Create space**. Copies have
their own definitions; later edits to the originals do not update them.

In **Space settings**, change the name and description, then use **Open
folder** to open the space's files in Explorer or Finder. Put input files
there before asking an agent to read them. File tools are confined to this
folder; shell commands have broader access, as explained in
[Approvals](2_running_tasks.md#approvals).

A space names its own model under **Model**; it starts on the app-wide
provider's default, and you can change the model or choose another provider
for the space. Limits are entered under **Limits and approvals**; a blank
limit uses the app default. Click **Save space** to apply changes to future
runs.

There is one important difference between limits and approval policy:

- A space can raise or lower a run limit relative to the app default.
- A space's automatic approvals can only narrow what the app permits. Under
  **Calls that run without asking**, choose **Inherit the app-wide policy**
  or this space's own policy. An own policy with nothing ticked asks for
  every tool call, even if the app permits automatic calls.

Under **Archive or delete**, archiving keeps the history accessible through
**Archived** in the switcher and prevents new runs. **Unarchive** makes the
space active again. Deletion is available only when the space has no runs;
it removes the space and its agent definitions, but leaves its files on disk.
The default space cannot be archived or deleted.

## Change app settings

**Settings** groups defaults for every space above account and app controls.

| Section | Controls |
|---|---|
| **Model** | Provider, model, OpenAI API-key or ChatGPT access, and local Ollama address. |
| **Limits and approvals** | Default **Steps per agent** (20), **Agents per run** (5), **Seconds per run** (600), and calls that may run automatically. |
| **Keys** | Store or clear cloud API keys and the Discord bot token; restart to apply. |
| **Monthly budget** | **Monthly cap (USD)**, $20.00 by default, shared across spaces. Enter dollars directly. |
| **Chat channels** | Enable Discord, allow accounts, choose approval responders and the destination space. |
| **Appearance** | **Follow the system**, **Light**, or **Dark**; changes immediately. |
| **About AgentBase** | The version that is running, the data folder with **Open folder**, and **Replay the tour**. |

Click **Save settings** for changed settings. Model, limit and approval
changes affect future runs; an active run keeps its starting configuration.
Discord settings take effect when saved, but changing its stored token still
requires restarting the app. A space or agent with its own model setting
continues using that setting instead of the changed app default.
