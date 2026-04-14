# Install Into Codex for macOS

This repo now contains an installable Codex plugin bundle with:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/telegram/SKILL.md`

The cleanest local install path is to expose this repo under `~/plugins/codex-telegram-gateway` and point Codex at it with a home marketplace file.

## 1. Expose the repo as a local plugin

```bash
mkdir -p ~/plugins
ln -s /Users/kangmo/sacle/src/codex-telegram ~/plugins/codex-telegram-gateway
```

If the symlink already exists, replace it:

```bash
rm -f ~/plugins/codex-telegram-gateway
ln -s /Users/kangmo/sacle/src/codex-telegram ~/plugins/codex-telegram-gateway
```

## 2. Create the Codex home marketplace file

Create `~/.agents/plugins/marketplace.json` with:

```json
{
  "name": "kangmo-local",
  "interface": {
    "displayName": "Kangmo Local Plugins"
  },
  "plugins": [
    {
      "name": "codex-telegram-gateway",
      "source": {
        "source": "local",
        "path": "./plugins/codex-telegram-gateway"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

A ready-to-copy sample is in `install/home-marketplace.sample.json`.

## 3. Restart Codex for macOS

Quit and reopen the Codex app after writing the marketplace file.

## 4. Install the plugin in the app

Open the plugins UI in Codex, find `Telegram Gateway`, and install it from the local marketplace.

## 5. Ensure the local runtime is ready

From this repo:

```bash
uv venv --python /Users/kangmo/.local/bin/python3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

Ensure `.env` exists at repo root with:

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=...
TELEGRAM_DEFAULT_CHAT_ID=...
CODEX_TELEGRAM_STATE_DB=.codex-telegram/gateway.db
```

## 6. Reload Codex App

Quit and reopen Codex App after the plugin files and `.venv` are ready. The app should then load the plugin-local MCP server from `.mcp.json`.

## 7. Use it from Codex App

The preferred path is to use the plugin MCP tools from inside Codex App. They run in app context and therefore use loaded Codex App projects and threads rather than CLI history.

Relevant tools:

- `Gateway Doctor`
- `List Loaded Projects`
- `List Loaded Threads`
- `Link Current Thread`
- `Link Loaded Threads`
- `Create Thread`
- `Sync Gateway Once`

The CLI remains available for manual verification:

```bash
.venv/bin/python -m codex_telegram_gateway.cli --env-file .env doctor
.venv/bin/python -m codex_telegram_gateway.cli --env-file .env link-current-thread
.venv/bin/python -m codex_telegram_gateway.cli --env-file .env link-loaded-threads
```

## Current limitation

The MCP server is plugin-local and the Telegram bridge logic still lives in the repo-local Python code. Project creation in Codex App is still modeled as choosing or creating a folder path on disk; Codex App does not expose a separate persisted "project create" API here.
