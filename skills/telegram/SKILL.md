---
name: telegram
description: Use the Telegram gateway plugin from inside Codex App to inspect loaded projects and threads, bind Telegram topics, and run sync passes.
---

# Telegram Gateway

Use this skill when the user wants to operate the Telegram gateway from Codex App on macOS.

## Preconditions

- The plugin root is this repository.
- `.env` exists at the repo root and contains the Telegram bot token, allowed Telegram user IDs, and the target chat ID.
- `.venv` exists at the repo root and has this package installed editable.
- The plugin is installed into Codex App so its MCP server runs in app context.

## Preferred tools

Prefer the plugin MCP tools first. They run in Codex App context and therefore see loaded projects and loaded threads from the app rather than CLI session history.

Relevant tools:

- `Gateway Doctor`
- `List Loaded Projects`
- `List Loaded Threads`
- `List Gateway Bindings`
- `Link Current Thread`
- `Link Loaded Threads`
- `Create Thread`
- `Sync Gateway Once`

## CLI fallback

Run all commands from the repo root.

### Check connectivity

```bash
.venv/bin/python -m codex_telegram_gateway.cli --env-file .env doctor
```

### Link the current loaded Codex App thread

```bash
.venv/bin/python -m codex_telegram_gateway.cli --env-file .env link-current-thread
```

### Link all currently loaded Codex App threads

```bash
.venv/bin/python -m codex_telegram_gateway.cli --env-file .env link-loaded-threads
```

## Notes

- If Telegram returns `group chat was upgraded to a supergroup chat`, update `TELEGRAM_DEFAULT_CHAT_ID` to the returned `migrate_to_chat_id`.
- If Telegram returns `Too Many Requests`, wait for the reported `retry_after` seconds before retrying.
- Do not use the removed history-based `link-workspace-threads` or `link-all-threads` flow. This gateway is app-only now.
