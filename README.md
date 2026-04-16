# Codex Telegram Gateway

Control the macOS Codex App from Telegram by mapping Codex App threads to Telegram forum topics.

This project is a local plugin plus a local gateway daemon:

- Codex App provides the thread and project surface.
- Telegram provides the remote chat UI.
- This gateway binds each Codex App thread to one Telegram topic and keeps messages flowing in both directions.

## Why This Exists

Codex App is strongest on the desktop, but remote monitoring and steering are awkward when you step away from your Mac. Telegram topics solve the remote-control side well, but only if the bridge understands Codex App projects, Codex App threads, and Codex plugin installation.

This repository packages that bridge so you can:

- see Codex App projects and threads in Telegram topics
- send thread messages from Telegram and receive Codex replies back in the same topic
- configure and operate the gateway with a normal CLI
- run the gateway directly or as a macOS `launchd` service
- install the plugin into Codex App through a local marketplace entry instead of manual JSON editing

## How It Works

The system has three parts:

1. The plugin bundle, which Codex App loads from a local marketplace entry.
2. The local gateway runtime, which polls Telegram and talks to Codex App.
3. The operator CLI, which installs, configures, updates, starts, stops, and services the runtime.

Default managed paths:

- Install root: `~/.codex-telegram-plugin`
- Runtime home: `~/.codex-telegram`
- Managed env file: `~/.codex-telegram/.env`
- Personal plugin marketplace: `~/.agents/plugins/marketplace.json`
- macOS launch agent: `~/Library/LaunchAgents/com.kangmo.codex-telegram-gateway.plist`

## Quick Start

Run the one-line installer:

```sh
curl -fsSL https://raw.githubusercontent.com/Kangmo/Codex-Telegram-Plugin/main/install/install.sh | sh
```

The installer will:

1. Clone or refresh the managed checkout in `~/.codex-telegram-plugin`
2. Create `~/.codex-telegram-plugin/.venv`
3. Install the package into that venv
4. Prompt for:
   - Telegram bot token
   - numeric user ID
   - group chat ID
5. Register the plugin in your personal Codex plugin marketplace

After that:

1. Restart Codex App.
2. Open `Plugins` in Codex App.
3. Look for the local marketplace named `Codex Local Plugins`.
4. Install or enable `codex-telegram-gateway`.
5. Start the gateway runtime:

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway start
```

Or install it as a service:

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway service install
```

## Telegram Setup

### 1. Create the Bot

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Run `/newbot`.
3. Choose a bot name and username.
4. Copy the bot token.

### 2. Configure BotFather Settings

In BotFather, configure the bot so the gateway can work in forum topics:

1. Enable group usage for the bot.
2. Turn `Privacy Mode` off so the bot can see topic messages in the group.
3. Make sure `Topics` support is enabled when BotFather offers that setting.

### 3. Create the Telegram Group

1. Create a normal Telegram group.
2. Convert or configure it as a topic-enabled group.
3. Enable `Topics` in the group settings.
4. Add your bot to that group.
5. Promote the bot to admin if you want it to create or rename topics automatically.

Recommended admin permissions:

- manage topics
- delete messages
- pin messages

### 4. Find Your Numeric IDs

You need:

- the bot token
- your numeric user ID
- the group chat ID

Ways to get them:

- numeric user ID:
  - ask [@userinfobot](https://t.me/userinfobot), or
  - use another ID bot that reports your numeric user ID
- group chat ID:
  - ask a bot such as [@RawDataBot](https://t.me/RawDataBot), or
  - use a Telegram ID bot inside the group and copy the group chat ID

The installer asks for all three values directly.

## Codex App Setup

The installer already registers this plugin in your personal marketplace. Codex App still needs to load it.

### 1. Restart Codex App

Restart after the installer or after `codex-telegram-gateway update`.

### 2. Open Plugins

In Codex App:

1. Open `Plugins`.
2. Find the marketplace named `Codex Local Plugins`.
3. Install or enable `codex-telegram-gateway`.

If the plugin does not appear:

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway plugin status
```

If needed, re-register it:

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway plugin install
```

Then restart Codex App again.

## CLI Reference

The installed operator CLI is:

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway
```

### Configuration

Interactive first-time setup:

```sh
codex-telegram-gateway install
```

Reconfigure later:

```sh
codex-telegram-gateway configure
codex-telegram-gateway configure --group-chat-id -1001234567890
```

### Plugin Marketplace

Register the plugin entry:

```sh
codex-telegram-gateway plugin install
```

Check marketplace status:

```sh
codex-telegram-gateway plugin status
```

### Local Runtime

Start the local daemon:

```sh
codex-telegram-gateway start
```

Stop it:

```sh
codex-telegram-gateway stop
```

Restart it:

```sh
codex-telegram-gateway restart
```

Show runtime and install summary:

```sh
codex-telegram-gateway status
```

Show recent logs:

```sh
codex-telegram-gateway logs
```

### macOS Service

Install and bootstrap the `launchd` service:

```sh
codex-telegram-gateway service install
```

Stop the service:

```sh
codex-telegram-gateway service stop
```

Start it again:

```sh
codex-telegram-gateway service start
```

Restart it:

```sh
codex-telegram-gateway service restart
```

Check service status:

```sh
codex-telegram-gateway service status
```

Remove the service:

```sh
codex-telegram-gateway service uninstall
```

### Updating

Refresh the managed checkout from its git `origin`:

```sh
codex-telegram-gateway update
```

This command will:

1. Read the installed checkout's git `origin`
2. Clone a fresh copy
3. Sync it into the managed install root
4. Preserve `.git` and `.venv`
5. Re-run `pip install -e`
6. Refresh the local plugin marketplace entry

After `codex-telegram-gateway update`, restart Codex App so the plugin cache reloads the new version.

## Typical Operator Flows

### One-Time Install

```sh
curl -fsSL https://raw.githubusercontent.com/Kangmo/Codex-Telegram-Plugin/main/install/install.sh | sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway service install
```

Then restart Codex App and enable the plugin from `Plugins`.

### Reconfigure Telegram Credentials

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway configure
```

### Direct Runtime Without launchd

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway start
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway status
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway logs
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway stop
```

### launchd Runtime

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway service install
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway service status
```

### Upgrade

```sh
~/.codex-telegram-plugin/.venv/bin/codex-telegram-gateway update
```

Then:

1. Restart Codex App
2. Reopen `Plugins`
3. Confirm the plugin is still enabled

## Runtime Data

Managed files are split intentionally:

- source checkout:
  - `~/.codex-telegram-plugin`
- runtime state:
  - `~/.codex-telegram/.env`
  - `~/.codex-telegram/gateway.db`
  - `~/.codex-telegram/toolbar.toml`
  - `~/.codex-telegram/logs/gateway.log`
  - `~/.codex-telegram/run/gateway.pid`

This keeps updates from overwriting your runtime configuration and local state.

## Troubleshooting

### Plugin Does Not Show Up in Codex App

1. Run:

```sh
codex-telegram-gateway plugin status
```

2. Confirm the marketplace entry exists under `Codex Local Plugins`
3. Restart Codex App
4. Open `Plugins` again

### Runtime Does Not Start

1. Run:

```sh
codex-telegram-gateway status
codex-telegram-gateway logs
```

2. Confirm `~/.codex-telegram/.env` exists
3. Confirm the bot token, numeric user ID, and group chat ID are correct

### Service Looks Installed But Not Running

1. Run:

```sh
codex-telegram-gateway service status
codex-telegram-gateway logs
```

2. If needed:

```sh
codex-telegram-gateway service restart
```

### Update Completed But Codex App Still Shows Old Behavior

Run:

```sh
codex-telegram-gateway update
```

Then fully restart Codex App. Local plugins are cached by Codex App, so the app restart matters.
