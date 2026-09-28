# Integrations

[Guide contents](README.md) · [Next: Troubleshooting and reference](5_troubleshooting_and_reference.md)

## Discord

Discord starts tasks and displays updates for the desktop-visible run. Keep
AgentBase running. Only allowed accounts can start tasks; ordinary channel
conversation never enters agent context.

### Create and install the bot

1. Create an application in the
   [Discord Developer Portal](https://discord.com/developers/applications).
2. Open **Bot**, generate or reset and copy its token. Leave privileged gateway
   intents off; AgentBase does not request them.
3. Under **Installation**, configure **Guild Install** with `bot` and
   `applications.commands` scopes plus **Send Messages**. Use its install link,
   then ensure the bot can view and send in the target channel.

Discord's [bot setup guide](https://docs.discord.com/developers/quick-start/getting-started)
covers the portal flow.

### Save the token and allow accounts

1. In AgentBase, open **Settings → Keys**, click **Set…** beside
   `discord_bot_token`, paste the token and click **Save key**.
2. Click **Restart AgentBase** under the key list, or reopen the app, to send
   the new token to the sidecar.
3. Open **Settings → Chat channels** and tick **Enable discord**.
4. Under **Who may give the bots tasks**, enter the Discord **Account id**
   and a **Name** to identify that person in the log, then click **Add**.
5. Choose the destination space under **Where a chat command runs**, then
   click **Save settings**.

A Discord account ID is numeric, not a username. Enable **User Settings →
Advanced → Developer Mode**, then **Copy User ID** from your profile.
Alternatively, enable/save the bot, try a command, and read its **Refused**
account in AgentBase's chat status.

Status should become **running**; otherwise, read its adjacent error. Channel
settings apply when saved; changed tokens require restart. Removing and saving
an account blocks its future tasks. An empty allowlist permits nobody.

### Start a task

In a channel the bot can see, type `/agent`, then fill in its task argument,
for example:

```text
Summarise the files in this space's folder into one paragraph.
```

The bot posts then updates a status message. Open the configured space's
**Runs** to watch or replay it. Desktop space selection does not change chat
routing.

The adapter also accepts explicit bot mentions. Slash commands have live
Discord verification; mentions have automated coverage.

### Answer approvals from Discord

By default, **Who may answer an approval** is **Only this window**. Discord
shows the wait; answer in AgentBase's approval panel.

To allow Discord answers, choose **Also the chat user who started the run** and
**Save settings**. Pending requests receive **Allow / Deny** buttons usable
only by that run's originator. Requests answered elsewhere cannot be repeated.

Chat and desktop runs share tool permissions, folder checks, and approval
policies. Chat approval changes who can answer, not which calls auto-run.

## Telegram

Telegram is unsupported in 0.2.0; its adapter and settings were removed. The
app does not read existing credentials. Remove obsolete `telegram_bot_token`
from OS credential storage if desired; historical runs remain in their space.
