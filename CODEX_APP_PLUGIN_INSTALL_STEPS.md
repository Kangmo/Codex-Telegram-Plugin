# Codex App Plugin Install Steps Run

This file records the exact steps I ran to install the local `codex-telegram-gateway` plugin into Codex App on macOS.

## 1. Prepare local plugin paths

I created the standard local plugin directories:

```bash
mkdir -p ~/plugins ~/.agents/plugins
```

## 2. Expose this repo as a local plugin

I linked the repo into the local Codex plugin directory:

```bash
ln -sfn /Users/kangmo/sacle/src/codex-telegram ~/plugins/codex-telegram-gateway
```

Result:

- local plugin path: `/Users/kangmo/plugins/codex-telegram-gateway`
- target repo: `/Users/kangmo/sacle/src/codex-telegram`

## 3. Create the home marketplace entry

I created the local marketplace file:

- path: `/Users/kangmo/.agents/plugins/marketplace.json`

with this plugin entry:

- marketplace name: `kangmo-local`
- plugin name: `codex-telegram-gateway`
- source path: `./plugins/codex-telegram-gateway`
- installation policy: `INSTALLED_BY_DEFAULT`
- authentication policy: `ON_INSTALL`

## 4. Enable the plugin in Codex config

I added this block to:

- `/Users/kangmo/.codex/config.toml`

```toml
[plugins."codex-telegram-gateway@kangmo-local"]
enabled = true
```

The existing GitHub plugin setting was left intact.

## 5. Restart Codex App

I restarted the running Codex App with:

```bash
osascript -e 'tell application "Codex" to quit'
open -a Codex
```

## 6. Verify Codex App sees the plugin marketplace entry

I queried `codex app-server` and confirmed `plugin/list` returned:

- plugin id: `codex-telegram-gateway@kangmo-local`
- source path: `/Users/kangmo/plugins/codex-telegram-gateway`
- `enabled: true`
- `installed: false` at that point

## 7. Install the plugin through the Codex App plugin API

I completed installation with `plugin/install` via `codex app-server` using:

- marketplace path: `/Users/kangmo/.agents/plugins/marketplace.json`
- plugin name: `codex-telegram-gateway`

The install response returned:

- `authPolicy: ON_INSTALL`
- `appsNeedingAuth: []`

## 8. Verify final installed state

I re-read the plugin with `plugin/read` and confirmed:

- plugin id: `codex-telegram-gateway@kangmo-local`
- `installed: true`
- `enabled: true`
- bundled skill enabled: `codex-telegram-gateway:telegram`
- bundled MCP server present: `codex-telegram-gateway`

## Current local files involved

- plugin manifest: `/Users/kangmo/sacle/src/codex-telegram/.codex-plugin/plugin.json`
- plugin MCP config: `/Users/kangmo/sacle/src/codex-telegram/.mcp.json`
- home marketplace: `/Users/kangmo/.agents/plugins/marketplace.json`
- Codex config: `/Users/kangmo/.codex/config.toml`

## Notes

- UI scripting from this shell was not available because macOS Accessibility permission for `osascript` is denied.
- The actual install completion was done through the Codex App plugin API, not by clicking the UI.
