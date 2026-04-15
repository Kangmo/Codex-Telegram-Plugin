# Notes: Codex Telegram Gateway Plugin

## Sources

### Official Codex plugin docs
- URL: https://developers.openai.com/codex/plugins
- URL: https://developers.openai.com/codex/plugins/build
- Key points:
  - Codex plugins bundle reusable `skills/`, app integrations via `.app.json`, and MCP servers via `.mcp.json`.
  - `.codex-plugin/plugin.json` is the required manifest entry point.
  - Only `plugin.json` belongs inside `.codex-plugin/`; `skills/`, `.mcp.json`, `.app.json`, and `assets/` stay at plugin root.
  - Local install/testing uses `.agents/plugins/marketplace.json` at repo scope or `~/.agents/plugins/marketplace.json` at personal scope.
  - Bundled MCP servers may require extra setup or authentication after plugin install.

### OpenAI plugin examples
- URL: https://github.com/openai/plugins
- URL: https://github.com/openai/plugins/tree/main/plugins/slack
- Key points:
  - Slack plugin is app-backed: `.codex-plugin/plugin.json` + `.app.json` + `skills/`.
  - Slack skills are split into a router skill and specialized skills with explicit guardrails.
  - Manifest shape includes `interface.displayName`, descriptions, capabilities, branding, and default prompts.
  - MCP-backed examples such as `build-web-apps`, `vercel`, and `build-ios-apps` show `.mcp.json` usage for both HTTP and stdio-backed servers.

### ccgram Telegram gateway reference
- URL: https://github.com/alexei-led/ccgram
- Key files reviewed:
  - `/tmp/ccgram/README.md`
  - `/tmp/ccgram/.claude/rules/topic-architecture.md`
  - `/tmp/ccgram/src/ccgram/thread_router.py`
  - `/tmp/ccgram/src/ccgram/topic_state_registry.py`
  - `/tmp/ccgram/src/ccgram/config.py`
  - `/tmp/ccgram/src/ccgram/handlers/topic_orchestration.py`
  - `/tmp/ccgram/src/ccgram/telegram_sender.py`
  - `/tmp/ccgram/tests/ccgram/test_thread_router.py`
  - `/tmp/ccgram/tests/ccgram/test_new_window_sync.py`
  - `/tmp/ccgram/tests/ccgram/test_group_filter.py`
- Key points:
  - ccgram is intentionally topic-only: one Telegram forum topic maps to one underlying runtime target.
  - It persists both forward and reverse bindings plus chat/topic metadata.
  - It uses an allowlist of numeric Telegram user IDs and an optional group filter.
  - Topic creation handles Telegram flood-control backoff and multi-group fanout.
  - Message splitting, resilient polling, cleanup registries, and state persistence are treated as first-class concerns.

### Local Codex runtime inspection
- Commands reviewed:
  - `codex --version`
  - `codex resume --help`
  - `codex app-server --help`
  - `codex app-server generate-json-schema --out /tmp/codex-app-schema`
  - `env | rg '^CODEX'`
- Key points:
  - This runtime exports `CODEX_THREAD_ID` in the shell environment.
  - `codex app-server` exposes thread and turn operations including `thread/read`, `thread/list`, `thread/set-name`, `turn/start`, and `turn/steer`.
  - App-server schemas expose thread history, thread status, and rich thread item types suitable for outbound sync.
  - The app-server surface is marked experimental, so any design depending on it needs a fallback path.

## Synthesized Findings

### Packaging
- Telegram should be implemented as an MCP-backed plugin, not an app-backed plugin, because Telegram is not an existing Codex app connector like Slack.
- The plugin should still copy Slack's manifest and skill-guardrail style: one router skill, explicit supported/unsupported actions, concise manifest metadata, and clear default prompts.

### Thread and topic identity
- `ccgram`'s strongest reusable idea is a strict 1:1 binding model with persisted forward and reverse indices.
- In this environment, `CODEX_THREAD_ID` gives a viable automatic binding key for "current Codex thread".
- Because `CODEX_THREAD_ID` is not surfaced in the public plugin docs, the design should include a fallback explicit binding key.

### Codex integration strategy
- A true two-way gateway is feasible if a local service can call Codex's app-server thread APIs:
  - read thread history for Codex -> Telegram mirroring
  - enqueue Telegram messages into the linked thread with `turn/start` when idle
- Using app-server notifications is possible later, but polling `thread/read` is simpler and lower-risk for v1.

### Telegram integration strategy
- Long polling should be the default because webhook deployment adds avoidable infrastructure requirements for a local developer workstation.
- Topic routing must key by both `chat_id` and `message_thread_id`; topic IDs alone are not globally unique.
- Required Telegram setup for v1 is broader than just bot token + allowed user ID:
  - forum-enabled group chat
  - bot admin rights needed to create topics if auto-create is supported
  - either a default group chat ID or a bind-to-existing-topic workflow

### State and reliability
- A background daemon is needed for continuous sync; an MCP server alone is not enough if Telegram messages should be processed while the user is away from the current tool call.
- SQLite is a better fit than ad hoc JSON for concurrent daemon + MCP access, dedupe, cursors, and crash recovery.
- The implementation should persist:
  - thread/topic bindings
  - Telegram update offsets
  - outbound Codex event cursors
  - inbound queued Telegram messages
  - daemon lease / heartbeat metadata

### Security and constraints
- Secrets belong in env vars or a user config file outside the plugin manifest.
- Only configured numeric user IDs should be able to inject Telegram messages into Codex.
- The gateway must defend against:
  - unauthorized chats or users
  - duplicate delivery after restart
  - Telegram 429 backoff
  - Codex thread active-state conflicts
  - noisy loopbacks and oversized Telegram messages

### Main design risk
- The official plugin docs cover plugin packaging, not thread-bridge internals. The critical runtime bridge pieces (`CODEX_THREAD_ID`, app-server thread APIs) are validated locally but not clearly documented in the reviewed public plugin docs.
- The plan should therefore include a supported fallback mode:
  - manual bind/unbind
  - explicit `sync now`
  - queue inbound Telegram messages until the local bridge can resume delivery

## ccgram Feature Sweep Notes

### Source files reviewed
- `/tmp/ccgram/CLAUDE.md`
- `/tmp/ccgram/src/ccgram/bot.py`
- `/tmp/ccgram/src/ccgram/cc_commands.py`
- `/tmp/ccgram/src/ccgram/handlers/sync_command.py`

### Relevant transferable behaviors
- Bot-native Telegram commands are first-class and registered into Telegram’s command menu.
- `/new` exists as the “start a fresh session” command, with `/start` kept as a compatibility alias.
- `/commands` exists as a user-facing command discovery surface.
- `/sync` is a user-triggered reconciliation tool, not only a background task.
- Topic titles are actively synchronized to runtime state.
- `edit_message_text` is preferred for in-place UI updates and growing status/output blocks.

### Behaviors already present in this repo
- Topic title updates from Codex thread title changes.
- Typing heartbeat while a turn is active or blocked on approval.
- In-place growth of a single outbound Codex message block in Telegram.
- Project picker and directory browser for unbound topics.

### Behaviors selected for this port
- Telegram bot command menu registration.
- Topic commands: `/new`, `/start`, `/project`, `/status`, `/sessions`, `/sync`, `/commands`, `/help`.
- `/new` semantics adapted to this architecture:
  - if topic is bound, create a new Codex thread in the same project and rebind the topic
  - if topic is unbound, show the existing project picker
- `/sync` semantics adapted to this architecture:
  - audit Codex App loaded threads against persisted bindings and Telegram topic reachability
  - offer an inline fix action for unbound loaded threads and deleted Telegram topics
- automatic adoption of newly loaded Codex App threads during the normal sync loop
- lightweight `/sessions` dashboard for current bindings with refresh

### Behaviors intentionally not ported in this pass
- tmux window/session dashboards
- pane screenshots / live view
- provider-specific toolbars
- transcript history browsers
- provider command discovery beyond the gateway’s own commands
- tmux/provider-specific orphan adoption, kill flows, and recovery callbacks

## ccgram Parity Plan Notes

### Deliverable
- `ccgram_feature_parity_plan.md`

### Planning focus
- Convert the missing-feature inventory from the line-by-line `ccgram` review into a structured implementation roadmap.
- Keep the plan explicit about what is:
  - directly portable
  - adapted to Codex App
  - compatibility-only
  - intentionally deferred

### Highest-priority parity targets
- Topic lifecycle ingestion and recovery
- `/history`, `/resume`, `/unbind`, `/restore`, `/send`, `/verbose`
- Richer sessions dashboard and status bubble
- Interactive prompt bridge if Codex app-server supports it
- Generalized media intake and outbound artifact delivery

### Explicitly deferred or compatibility-only
- `/panes` as compatibility messaging only
- inter-agent mailbox
- shell/NL-to-command provider mode

## Parity Implementation Progress

### Completed features
- FP-01 Topic close/reopen lifecycle
- FP-02 Bidirectional topic rename sync
- FP-03 Topic emoji/status state
- FP-04 Lifecycle sweeps, topic probing, autoclose, unbound TTL, pruning
- FP-05 Multi-chat fanout and Telegram flood-control backoff
- FP-06 `/history`
- FP-07 `/resume`

### FP-02 verification
- Added inbound `forum_topic_edited` normalization in the Telegram client.
- Added reverse rename handling from Telegram topic title to Codex thread title when the canonical project prefix is preserved.
- Restores canonical topic names when the rename is malformed or attempts to change the project segment.
- Coverage for FP-02-specific lines is 46/46 = 100.0%.

### FP-03 verification
- Added lightweight topic-status prefixes for non-idle states: running, waiting approval, failed, and closed.
- Idle topics intentionally remain unprefixed to avoid constant rename churn across loaded Codex App threads.
- Added status-prefix stripping so Telegram-side topic renames continue to update the correct Codex thread title.
- Added per-chat suppression after topic-edit permission failures so status-only prefix updates stop retrying noisily.
- Coverage for tracked FP-03 changed source lines is 77/81 = 95.1%; the new `topic_status.py` helper module is 21/21 = 100.0%.

### FP-04 verification
- Added persisted `TopicLifecycle` state plus unbound-topic activity timestamps in SQLite.
- Added periodic lifecycle sweeps for topic probing, completed-topic autoclose, unbound-topic TTL cleanup, and orphan history pruning.
- Hooked lifecycle sweeps into CLI and MCP sync loops so the background runtime performs the same hygiene automatically.
- Fixed two lifecycle edge cases during proof review:
  - missing-topic probes now delete lifecycle rows as well as marking the binding deleted
  - reopen/new-inbound flows now truly clear `completed_at` instead of accidentally preserving it
- Feature-specific changed-statement coverage versus `main` is 152/169 = 89.9%.

### FP-05 verification
- Added optional `TELEGRAM_MIRROR_CHAT_IDS` support and a deduped `telegram_target_chat_ids` config view.
- Added persisted mirror bindings plus mirror-specific seen-event, outbound-message, and topic-creation-queue state.
- Added mirror topic creation in the daemon with persisted retry scheduling when Telegram returns `RetryAfter`.
- Added mirror-aware outbound sync and inbound routing so mirrored topics can feed the same Codex thread.
- Hardened the design during proof review by blocking project/thread rebinding controls inside mirror topics; mirror topics remain conversation surfaces only.
- Feature-specific changed-statement coverage versus `main` is 225/261 = 86.2%.

### FP-06 verification
- Added a dedicated `history_command.py` renderer with older/newer pagination and restart-stable callback parsing.
- Added `CodexBridge.list_history_entries()` plus Codex App normalization for `userMessage`, final `agentMessage`, and `commandExecution` thread items.
- Added persisted `HistoryViewState` in SQLite so `/gateway history` callbacks reject stale messages and continue to work after daemon restart.
- Fixed two issues during red-phase review:
  - command-result summaries now prefer concrete error lines over vague `failed` lines
  - every paginated history page now repeats the thread header instead of losing context after page 1
- Full suite verification: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `123 passed`
- Feature-specific changed-statement coverage versus `main` is 142/166 = 85.5%.

### FP-07 verification
- Added Codex-App-native resumable thread discovery from `~/.codex/state_5.sqlite`, filtered by project root and excluding the currently bound thread.
- Added `/gateway resume` plus a persisted Telegram picker with paging and restart-safe callback handling.
- Added `GatewayService.rebind_topic_to_thread()` so resume reuses the existing topic, renames it to the resumed thread title, and marks the resumed thread’s historical assistant events as seen.
- Fixed one real implementation gap during testing: rebinding to a `notLoaded` thread now explicitly calls `thread/resume`, so outbound sync can continue on the resumed thread.
- Full suite verification: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `135 passed`
- Feature-specific changed-statement coverage versus `main` is 115/139 = 82.7%.
