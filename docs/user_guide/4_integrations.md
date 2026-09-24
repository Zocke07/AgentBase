# Integrations

[Guide contents](README.md) · [Next: Troubleshooting and reference](5_troubleshooting_and_reference.md)

## Discord

Discord can start a task and display updates from the same run you watch on
the desktop. AgentBase must remain running on your computer. Only accounts
you explicitly allow can start tasks; ordinary channel conversation is not
fed into an agent's context.

### Create and install the bot

1. Create an application in the
   [Discord Developer Portal](https://discord.com/developers/applications).
2. Open its **Bot** page, generate or reset the token, and copy it. Leave
   the privileged gateway intents off; AgentBase does not request them.
3. Under **Installation**, configure **Guild Install** with the `bot` and
   `applications.commands` scopes and **Send Messages** permission. Use its
   install link to add the app to your server. Ensure it can view and send
   messages in the channel you will use.

These are Discord's server installation controls; its
[bot setup guide](https://docs.discord.com/developers/quick-start/getting-started)
covers the portal flow.

### Save the token and allow accounts

1. In AgentBase, open **Settings → Keys**, click **Set…** beside
   `discord_bot_token`, paste the token and click **Save key**.
2. Click **Restart AgentBase** under the key list, or quit and reopen the
   app, so the sidecar receives the new token.
3. Open **Settings → Chat channels** and tick **Enable discord**.
4. Under **Who may give the bots tasks**, enter the Discord **Account id**
   and a **Name** to identify that person in the log, then click **Add**.
5. Choose the destination space under **Where a chat command runs**, then
   click **Save settings**.

A Discord account ID is the long numeric ID, not a username. In Discord,
enable **User Settings → Advanced → Developer Mode**, then use **Copy User
ID** on your profile. Alternatively, enable and save the bot first, try a
command, and read the **Refused** account shown in AgentBase's chat status.

The status should become **running**. If it does not, the message beside it
explains the error. Channel settings take effect when saved; a changed token
requires the restart above. Removing an account and saving prevents future
tasks from that account. An empty allowlist permits nobody.

### Start a task

In a channel the bot can see, type `/agent`, then fill in its task argument,
for example:

```text
Summarise the files in this space's folder into one paragraph.
```

The bot posts a message and edits it as agents work. Open the configured
space's **Runs** section to watch the graph or replay the run. The desktop's
currently selected space does not change where chat commands are routed.

The adapter also recognizes explicit mentions of the bot. Slash commands
are the path verified against a real Discord server; mention handling has
automated coverage.

### Answer approvals from Discord

By default, **Who may answer an approval** is **Only this window**. Discord
shows that the run is waiting, and you answer in AgentBase's approval panel.

To answer from Discord too, choose **Also the chat user who started the
run** and click **Save settings**. For pending requests, the bot posts
**Allow / Deny** buttons that only that run's originator may use. A request
already answered elsewhere cannot be answered again.

The same tool permissions, space folder checks and approval policies apply
to chat and desktop runs. Enabling chat approval changes who may answer;
it does not automatically allow tool calls.

## Telegram

Telegram is not supported in 0.2.0. Its adapter and settings were removed.
Existing Telegram credentials are not read by the app; remove an old
`telegram_bot_token` entry from the OS credential store if you no longer need
it. Historical runs remain part of their space's history.
