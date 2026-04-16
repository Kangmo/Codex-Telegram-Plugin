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
- FP-08 `/unbind`
- FP-09 `/restore`
- FP-10 `/upgrade`
- FP-11 `/send`
- FP-12 `/toolbar`
- FP-13 `/verbose`
- FP-14 `/screenshot`
- FP-15 `/panes` compatibility
- FP-17 Command/menu sync
- FP-18 Full sessions dashboard
- FP-19 Interactive prompt bridge
- FP-20 Dedicated status bubble
- FP-21 Tool batching, failure probing, and completion summaries
- FP-22 Live view
- FP-23 Remote control actions
- FP-24 General file intake and unsupported-content UX
- FP-25 Outbound media and file delivery
- FP-26 Voice transcription flow
- FP-27 Inline query support
- FP-28 Inter-agent messaging/mailbox

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

### FP-08 verification
- Added `/gateway unbind` as a real detach flow rather than overloading `closed` or `deleted` binding status.
- Added persistence helpers to delete primary bindings, mirror bindings, pending inbound queue items for a thread, and topic history rows.
- Unbind now clears pending turn state, outbound message mappings, topic-scoped history/resume views, topic recall history, and pending mirror-creation jobs for the detached thread.
- Unbind leaves the Codex thread alive, strips topic-status prefixes, and returns the topic to unbound project-picker mode on the next inbound message.
- Mirror topics explicitly reject `/gateway unbind`; when a primary topic is unbound, its mirrors are detached too because the current sync loop is primary-binding anchored.

## Installer and Operations CLI Notes

### Additional sources reviewed
- `https://github.com/alexei-led/ccgram`
  - `/tmp/ccgram-review/src/ccgram/cli.py`
  - `/tmp/ccgram-review/README.md`
  - `/tmp/ccgram-review/docs/guides.md`
- `https://developers.openai.com/codex/plugins/build`
  - local plugin install section
  - marketplace metadata section

### Key findings for this workstream
- `ccgram` exposes a practical operator-facing surface:
  - top-level CLI with `run`, `status`, `doctor`, and upgrade guidance
  - docs for direct runtime control and service-style operation
- The Codex plugin docs explicitly support local plugin registration through:
  - `~/.agents/plugins/marketplace.json`
  - `source.path` values relative to the marketplace root and starting with `./`
- Codex caches installed local plugins under `~/.codex/plugins/cache/...`, so local-source updates still require a Codex restart to refresh the installed copy.
- This repo currently lacks:
  - a user-friendly install command
  - a reconfigure command
  - a background daemon manager
  - macOS service registration helpers
  - a top-level `README.md`

### Chosen direction
- Install source checkout: `~/.codex-telegram-plugin`
- Runtime home: `~/.codex-telegram`
- Managed env file: `~/.codex-telegram/.env`
- Personal marketplace path: `~/.agents/plugins/marketplace.json`
- One-line installer:
  - shell script clones or refreshes the checkout
  - creates a venv
  - installs the package
  - runs the interactive CLI install flow
- Update strategy:
  - discover `origin`
  - clone fresh into a temp directory
  - sync files into the install root
  - preserve runtime state and config outside the checkout

### CI-01 landed decisions
- Added `runtime_paths.py` as the managed path layer so later install/service/update commands do not each re-derive paths differently.
- Marketplace source paths are rendered relative to `HOME` with a `./` prefix when possible, matching Codex local marketplace expectations.
- Absolute marketplace source paths remain supported for non-home install roots to avoid breaking custom installations.
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_daemon.py -q` -> `70 passed`
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_gateway_flow.py -q` -> `3 passed`
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_state.py -q` -> `14 passed`
- Full suite verification: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `139 passed`
- Feature-specific changed-statement coverage for source diff is 58/67 = 86.6%.

### FP-09 verification
- Added an adapted recovery layer for Codex App bindings instead of tmux sessions:
  - `/gateway restore`
  - auto-prompt on inbound messages to closed primary topics
  - `Continue Here`
  - `Recreate Topic`
  - `Resume Other Thread`
  - `Cancel`
- Added persisted `RestoreViewState` rows in SQLite so restore menus survive restart and stale callbacks are rejected safely.
- Recovery cleanup is now tied into bind, rebind, unbind, and new-thread flows so old recovery widgets are removed when the topic becomes healthy.
- Two proofread fixes landed during implementation:
  - `Continue Here` now restores the canonical Telegram topic title immediately instead of waiting for a later sync
  - repeated messages on a closed topic reuse the existing restore message instead of sending duplicate menus
- One red-phase test bug was fixed before sign-off: batched callback updates were being processed in a single poll under the wrong state, so those tests were rewritten to isolate each callback branch under the intended binding state.
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_recovery.py tests/unit/test_daemon.py tests/unit/test_state.py tests/e2e/test_gateway_flow.py -q` -> `103 passed`
- Full suite verification: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `155 passed`
- Feature-specific changed-statement coverage for tracked source diff is 119/129 = 92.2%.

### FP-11 verification
- Added a dedicated send-browser stack:
  - `send_security.py` for project-root containment, browse pagination, search, and preview metadata
  - `send_command.py` for Telegram browser/preview rendering
  - `send_callbacks.py` for callback parsing
- Added persisted `SendViewState` rows in SQLite and wired them through the gateway state/port interfaces.
- Added `/gateway send` with:
  - root browse
  - exact file preview
  - exact directory open
  - search fallback
  - inline callbacks for page, enter, preview, back, root, cancel, send document, and send photo
- Added multipart Telegram upload helpers for outbound local file delivery.
- Proofread fixes:
  - reject negative callback indexes
  - reject directory-preview callbacks
  - clear send-browser state during rebind and unbind flows
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_send_command.py tests/unit/test_send_security.py tests/unit/test_daemon.py tests/unit/test_state.py tests/unit/test_telegram_api.py tests/e2e/test_gateway_flow.py` -> `163 passed`
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `216 passed`
- Feature-specific changed-statement coverage for tracked source diff is `197/223 = 88.3%`.

### FP-13 verification
- Branch and merge:
  - feature branch `feature/fp-13-verbose-and-notification-modes`
  - feature commit `e793d11`
  - merge commit on `main` `d0479a8`
- Added a dedicated `notification_modes.py` helper for normalization, callback parsing, picker rendering, and mode gating.
- Added `/gateway verbose` plus inline mode switching for `all`, `important`, `errors_only`, and `muted`.
- Routed supplemental topic notifications through one gate so typing and failure/interruption notices follow the configured per-topic mode.
- Kept assistant reply delivery outside the mute gate because Telegram is the primary conversation surface in this gateway.
- Proofread decisions:
  - normalize legacy `assistant_plus_alerts` to `all`
  - normalize legacy `assistant_only` to `important`
  - allow mirror topics to change their own notification mode because it is topic-local state
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_notification_modes.py tests/unit/test_daemon.py tests/unit/test_sessions_dashboard.py tests/e2e/test_gateway_flow.py` -> `154 passed`
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `244 passed`
- Feature-specific changed-statement coverage for tracked source diff is `40/48 = 83.3%`.

### FP-17 verification
- Added a dedicated `commands_catalog.py` module for Telegram menu generation, sanitization, known-description mapping, and hash-based registration.
- The Telegram menu is now built from three real sources only:
  - `/gateway`
  - configured pass-through commands from `CODEX_TELEGRAM_MENU_PASSTHROUGH_COMMANDS`
  - slash commands actually observed in bound topics and persisted in SQLite
- Menu registration is chat-scoped to the configured Telegram group and uses a persisted hash so unchanged catalogs do not trigger repeated `setMyCommands` calls on restart.
- Added persisted state for observed pass-through commands and registered menu hashes.
- `/gateway help` now prints the live Telegram menu catalog in addition to gateway subcommands.
- Proofread changes:
  - removed the stale static `BOT_COMMANDS` constant so menu registration has one source of truth
  - kept command-menu refresh best-effort so registration failures do not block the actual message pass-through flow
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_config.py tests/unit/test_commands_catalog.py tests/unit/test_state.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -q` -> `111 passed`
- Full suite verification: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `161 passed`
- Feature-specific changed-statement coverage for tracked source diff is 95/108 = 88.0%.

### FP-18 verification
- Replaced the lightweight bindings dashboard with a paginated sessions dashboard backed by a dedicated `sessions_dashboard.py` renderer/parser module.
- The dashboard now shows topic title, project, current thread title, ids, status, notification mode, recovery warnings, mirror details, and pending mirror topic-creation jobs.
- Added per-session actions for refresh, new thread, unbind with confirmation, restore, screenshot compatibility, and page navigation.
- Direct dashboard actions intentionally route by persisted topic identity (`chat_id + message_thread_id`) rather than mutable topic titles.
- Proofread cleanup removed obsolete pre-FP-18 session-dashboard constants/helpers and simplified unreachable callback branches already ruled out by the parser.
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_sessions_dashboard.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -k "sessions_dashboard or bindings_shows_dashboard or lists_mirrors_and_pending_jobs or status_icons_and_warnings"` -> `16 passed`
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `175 passed`
- Feature-specific coverage for tracked FP-18 source ranges:
  - `daemon.py` FP-18 ranges: `133/146 = 91.1%`
  - `sessions_dashboard.py`: `77/84 = 91.7%`

### FP-19 verification
- Added a dedicated `interactive_bridge.py` module that normalizes supported Codex App server-request prompts, renders Telegram widgets, parses callbacks, and assembles multi-question answer payloads.
- Supported prompt families are currently:
  - `item/commandExecution/requestApproval`
  - `item/fileChange/requestApproval`
  - `item/tool/requestUserInput`
- Added persisted `InteractivePromptViewState` rows in SQLite so pending prompt widgets can be edited, cleared, and rejected safely by topic after normal sync and cleanup flows.
- The gateway now surfaces interactive prompt widgets in Telegram, routes valid button and text answers back to the live app-server session, and expires old prompt widgets after restart instead of pretending stale server requests remain answerable.
- Proofread fixes landed before sign-off:
  - plain Telegram text can no longer accidentally answer approval prompts or option-only questions
  - text-only tool questions now reject image replies explicitly
  - prompt cleanup now clears stale reply markup when the prompt or topic state is torn down
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `261 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/codex_api.py`: `34/36 = 94.4%`
  - `src/codex_telegram_gateway/daemon.py`: `92/122 = 75.4%`
  - `src/codex_telegram_gateway/models.py`: `8/8 = 100.0%`
  - `src/codex_telegram_gateway/ports.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `TOTAL`: `146/178 = 82.0%`

### FP-20 verification
- Added a dedicated `status_bubble.py` renderer plus persistent `StatusBubbleViewState` rows so each active topic can keep one editable operator bubble.
- The status bubble is separate from assistant reply blocks and shows project, thread title, normalized topic state, queued inbound count, and the latest assistant-summary line.
- The bubble reuses the existing `gw:resp:*` callbacks, and its control row stays visible during running and approval states instead of disappearing until idle.
- Proofread fixes landed before sign-off:
  - fixed stale active-target handling after missing-topic rename failures
  - unbind now clears bubble view state and render cache
  - fallback bubble recreation now rechecks missing-topic send failures instead of assuming only the edit can fail
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_status_bubble.py tests/unit/test_state.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `163 passed`
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `266 passed`
- Feature-specific changed-statement coverage for tracked executable source diff:
  - `src/codex_telegram_gateway/daemon.py`: `56/70 = 80.0%`
  - `src/codex_telegram_gateway/models.py`: `6/6 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `src/codex_telegram_gateway/status_bubble.py`: `0/0 = 100.0%`
  - `TOTAL`: `74/88 = 84.1%`

### FP-21 verification
- Added `response_builder.py` so Codex App `commandExecution` items are normalized into stable `tool_batch` and `completion_summary` outbound events rather than leaking raw command spam into Telegram.
- `CodexAppServerClient.list_events()` now delegates to that builder, and the daemon now renders `tool_batch` plus `completion_summary` events with the existing message edit-in-place flow.
- Recreated topics now replay the latest visible event instead of only the latest assistant event, which covers tool-batch and completion-summary output too.
- Proofread fixes landed before sign-off:
  - failure probing now prefers concrete lines such as `AssertionError: boom` over vague `tests failed` summaries
  - turns with an early assistant note and a final command batch still emit a terminal summary
  - explicit completion-summary events suppress the old generic terminal failure alert for the same turn
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_response_builder.py tests/unit/test_codex_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `164 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `274 passed`
- Feature-specific changed-executable coverage:
  - `src/codex_telegram_gateway/response_builder.py`: `117/138 = 84.8%`
  - `src/codex_telegram_gateway/codex_api.py` changed executable lines: `2/2 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `14/14 = 100.0%`
  - `src/codex_telegram_gateway/service.py` changed executable lines: `5/5 = 100.0%`
  - `TOTAL`: `138/159 = 86.8%`

### FP-24 verification
- Branch and merge:
  - feature branch `feature/fp-24-general-file-intake-and-unsupported-content-ux`
  - feature commit `9bf226f`
  - merge commit on `main` `e69c4c8`
- Added `media_ingest.py` so inbound documents, PDFs, audio, and video files share one prompt/unsupported-notice normalization layer.
- `TelegramBotClient.get_updates()` now keeps direct image delivery unchanged while downloading non-image files into `.ccgram-uploads` and converting them into explicit saved-path prompts for Codex App threads.
- Unsupported Telegram payloads now normalize into explicit `unsupported_message` updates and the daemon replies in-topic instead of silently discarding them.
- Implementation decisions locked during FP-24:
  - non-image attachments are adapted through text prompts because Codex App currently ingests local images directly but does not expose native local document/audio/video inputs through this gateway
  - attachment metadata stays out of SQLite for this feature; the saved-path prompt is the durable queue payload
  - downloads remain gateway-local under `.ccgram-uploads` rather than per-project storage
- Proofread changes before sign-off:
  - preserved the existing photo/image-document flow unchanged
  - blocked unauthorized unsupported-media notices from being echoed back into Telegram
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_media_ingest.py tests/unit/test_telegram_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `176 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `288 passed`
- Feature-specific changed-executable coverage:
  - `src/codex_telegram_gateway/media_ingest.py`: `25/25 = 100.0%`
  - `src/codex_telegram_gateway/telegram_api.py` changed executable lines: `68/68 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `7/7 = 100.0%`
  - `TOTAL`: `100/100 = 100.0%`

### FP-25 verification
- Branch and merge:
  - feature branch `feature/fp-25-outbound-media-and-file-delivery`
  - feature commit `cfee857`
  - merge commit on `main` `851f48a`
- Reviewed `ccgram`’s outbound upload references in `handlers/send_command.py::_upload_file()` and `handlers/screenshot_callbacks.py` before coding the parity path.
- Added `artifact_detector.py` so Codex outbound text that explicitly mentions generated files expands into stable `artifact_photo` and `artifact_document` events.
- `CodexAppServerClient.list_events()` now appends artifact events after the normal assistant/tool/completion event, and the daemon sends those files through the existing Telegram multipart helpers.
- Implementation decisions locked during FP-25:
  - outbound file parity is adapted through safe path detection because Codex App `thread/read` does not currently expose first-class generated-file attachment objects
  - the artifact allowlist is intentionally limited to the bound project root and gateway-local `.ccgram-uploads`
  - captions remain short and path-based because the adjacent text event already carries the conversational summary
- Proofread fixes before sign-off:
  - `.ccgram-uploads/...` token cleanup now preserves the leading dot instead of stripping the path
  - missing-file artifact events stay retryable because they are not marked seen
  - missing-topic artifact send failures delete the binding, while unrelated upload errors still surface normally
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_artifact_detector.py tests/unit/test_codex_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `172 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `296 passed`
- Feature-specific changed-executable coverage:
  - `src/codex_telegram_gateway/artifact_detector.py`: `96/101 = 95.0%`
  - `src/codex_telegram_gateway/codex_api.py` changed executable lines: `7/7 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `25/25 = 100.0%`
  - `src/codex_telegram_gateway/models.py` changed executable lines: `1/1 = 100.0%`
  - `TOTAL`: `129/134 = 96.3%`

### FP-26 verification
- Branch and merge:
  - feature branch `feature/fp-26-voice-transcription-flow`
  - feature commit `040e4c0`
  - merge commit on `main` `9dc93ae`
- Reviewed `ccgram` voice flow in `handlers/voice_handler.py`, `handlers/voice_callbacks.py`, and the `whisper/` provider layer before implementation.
- Added `voice_ingest.py` with a pluggable transcription interface, OpenAI-compatible multipart uploads, and the confirm/discard widget helpers.
- `TelegramBotClient.get_updates()` now downloads voice notes into `.ccgram-uploads` and emits dedicated `voice_message` updates.
- `GatewayDaemon` now transcribes voice notes, persists `VoicePromptViewState`, and routes confirmed transcripts either into the bound Codex queue or back through the existing project picker for unbound topics.
- Implementation decisions locked during FP-26:
  - transcripts require explicit user confirmation before submission
  - provider support is intentionally limited to config-backed OpenAI-compatible endpoints for now
  - unbound-topic voice flow reuses the existing topic binding UX instead of inventing a second project-selection path
- Proofread fixes before sign-off:
  - voice prompt state is now cleared during resume/rebind, bind-to-project, new-thread creation, unbind, and missing-topic cleanup so stale transcript callbacks cannot route into the wrong thread
  - voice download routing now runs before the generic unsupported-media path
  - multipart request headers are written directly onto the `urllib` request object to keep the upload contract stable
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_voice_ingest.py tests/unit/test_config.py tests/unit/test_state.py tests/unit/test_telegram_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `210 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `306 passed`
- Feature-specific module coverage:
  - `src/codex_telegram_gateway/voice_ingest.py`: `64/72 = 88.9%`
  - `src/codex_telegram_gateway/config.py`: `95/103 = 92.2%`
  - `src/codex_telegram_gateway/state.py`: `366/379 = 96.6%`
  - `src/codex_telegram_gateway/models.py`: `158/158 = 100.0%`
  - targeted changed-module set total: `2658/3199 = 83.1%`

### FP-27 verification
- Branch and merge:
  - feature branch `feature/fp-27-inline-query-support`
  - feature commit `bd51493`
  - merge commit on `main` `b9f368f`
- Reviewed `ccgram` inline-query handling in `bot.py::inline_query_handler()` and `handlers/command_history.py` before implementation.
- Added `inline_query.py` for safe result building, and extended the Telegram transport with inline-query normalization plus `answerInlineQuery`.
- `GatewayDaemon` now answers authorized inline queries with personal, zero-cache results built from:
  - the raw query text
  - gateway commands
  - remembered pass-through Codex commands
- Implementation decisions locked during FP-27:
  - parity is adapted to safe text insertion rather than project/binding search because inline query is stateless and best aligned with `ccgram`’s text-echo usage
  - existing callback UIs remain the place for project selection, recovery, and other topic-scoped actions
- Proofread fixes before sign-off:
  - duplicate command suggestions are suppressed when the query already equals a command
  - slash-only queries now surface suggestions instead of being treated as blank
  - malformed inline-query updates and unauthorized users are filtered before answer generation
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_inline_query.py tests/unit/test_telegram_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `192 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `316 passed`
- Feature-specific changed-code coverage:
  - `src/codex_telegram_gateway/inline_query.py`: `30/30 = 100.0%`
  - `src/codex_telegram_gateway/telegram_api.py` changed executable lines: `13/13 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `12/12 = 100.0%`
  - `TOTAL`: `55/55 = 100.0%`

### FP-16 verification
- Branch and merge:
  - feature branch `feature/fp-16-top-level-recall-flow`
  - feature commit `f6b579a`
  - merge commit on `main` `2884792`
- Reviewed `ccgram` recall handling in `handlers/command_history.py` and its unit tests before implementation.
- Added `recall_command.py` for shared history-label rendering plus top-level recall prompt generation.
- `/gateway recall` now exposes recent topic history beyond the two shortcut buttons already present in the response/status widgets.
- Implementation decisions locked during FP-16:
  - text-only history entries use inline query so the user can edit before resending
  - image-bearing history entries keep using the existing callback replay path so local image attachments are preserved
  - no new persisted view state is introduced because topic history already exists and the prompt itself is stateless
- Proofread fixes before sign-off:
  - image-count suffixes now survive label truncation
  - inline-query command ordering was adjusted so pass-through commands remain visible after adding `/gateway recall`
  - help output now includes the recall command
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_recall_command.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -k "recall"` -> `7 passed, 163 deselected`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `323 passed`
- Feature-specific changed-code coverage:
  - `src/codex_telegram_gateway/recall_command.py`: `33/36 = 91.7%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `21/24 = 87.5%`
  - `TOTAL`: `54/60 = 90.0%`

### FP-12 verification
- Branch and merge:
  - feature branch `feature/fp-12-toolbar-configurable-action-bar`
  - feature commit `a6b22ee`
  - merge commit on `main` `47fd034`
- Re-reviewed `ccgram` toolbar sources before implementation:
  - `/tmp/ccgram/src/ccgram/toolbar_config.py`
  - `/tmp/ccgram/src/ccgram/handlers/toolbar_callbacks.py`
  - `/tmp/ccgram/tests/ccgram/handlers/test_toolbar.py`
- Added `toolbar.py` as a pure configuration/rendering module with:
  - TOML-backed action and layout loading
  - built-in default toolbar actions
  - project and topic override resolution
  - callback parsing and inline keyboard rendering
- Added persisted `ToolbarViewState` so `/gateway toolbar` refreshes the existing toolbar message in place and survives daemon restart.
- `GatewayDaemon` now supports:
  - `/gateway toolbar`
  - toolbar callbacks for gateway commands
  - toolbar callbacks that enqueue bound-thread text
  - toolbar callbacks that explicitly steer an active Codex turn
  - toolbar refresh and dismiss actions
- Implementation decisions locked during FP-12:
  - toolbar config path defaults to `.codex-telegram/toolbar.toml` and is overrideable via `CODEX_TELEGRAM_TOOLBAR_CONFIG`
  - topic override precedence is higher than project override precedence
  - toolbar actions reuse existing gateway code paths instead of inventing a second command executor
  - malformed toolbar config is treated as a real configuration error rather than silently downgraded behavior
- Proofread fixes before sign-off:
  - corrected the toolbar status callback test to assert against raw sent messages instead of the helper that intentionally filters `Topic status` text
  - verified the feature under `.venv/bin/pytest` after the shell initially picked Anaconda Python 3.9 instead of the repo’s required Python 3.11
- Focused verification:
  - `.venv/bin/pytest tests/unit/test_toolbar.py tests/unit/test_config.py tests/unit/test_state.py tests/unit/test_daemon.py -k 'toolbar or toolbar_config_path'` -> `12 passed`
  - `.venv/bin/pytest tests/e2e/test_gateway_flow.py -k toolbar_override_persists_across_restart` -> `1 passed`
- Full-suite verification:
  - `.venv/bin/pytest` -> `336 passed`
- Feature-specific module coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway.toolbar --cov-report=term-missing tests/unit/test_toolbar.py tests/unit/test_daemon.py::test_poll_telegram_once_gateway_toolbar_sends_and_refreshes_persisted_view tests/unit/test_daemon.py::test_poll_telegram_once_toolbar_status_callback_routes_to_gateway_command tests/unit/test_daemon.py::test_poll_telegram_once_toolbar_thread_text_callback_enqueues_bound_inbound tests/unit/test_daemon.py::test_poll_telegram_once_toolbar_steer_callback_steers_active_turn tests/unit/test_daemon.py::test_poll_telegram_once_toolbar_dismiss_callback_clears_persisted_view tests/e2e/test_gateway_flow.py::test_gateway_flow_toolbar_override_persists_across_restart` -> `src/codex_telegram_gateway/toolbar.py 88%`

### FP-14 verification
- Branch and merge:
  - feature branch `feature/fp-14-screenshot`
  - feature commit `aecb122`
  - merge commit on `main` `de40180`
- Re-reviewed `ccgram` screenshot sources before implementation:
  - `/tmp/ccgram/src/ccgram/handlers/screenshot_callbacks.py`
  - `/tmp/ccgram/src/ccgram/handlers/toolbar_callbacks.py`
- Added `screenshot_capture.py` with:
  - a `ScreenshotProvider` interface for daemon injection
  - a native `MacOSWindowScreenshotProvider`
  - AppleScript window-geometry lookup plus `screencapture` PNG capture
- `GatewayDaemon` now supports:
  - `/gateway screenshot`
  - the existing sessions dashboard 📸 callback
  - photo/document delivery based on captured file size
- Implementation decisions locked during FP-14:
  - whole-window capture is the supported parity adaptation because Codex App has no pane model
  - screenshot delivery returns to the topic where the command or dashboard action was invoked
  - automated tests use fake providers and do not depend on live macOS capture permissions
- Proofread fixes before sign-off:
  - fixed an undefined `message_thread_id` local in the sessions screenshot callback path that otherwise caused the poller to swallow the exception silently
- Focused verification:
  - `.venv/bin/pytest tests/unit/test_screenshot_capture.py tests/unit/test_daemon.py -k screenshot tests/e2e/test_gateway_flow.py::test_gateway_flow_gateway_screenshot_sends_photo` -> `5 passed`
- Full-suite verification:
  - `.venv/bin/pytest` -> `340 passed`
- Feature-specific module coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway.screenshot_capture --cov-report=term-missing tests/unit/test_screenshot_capture.py tests/unit/test_daemon.py::test_poll_telegram_once_gateway_screenshot_sends_photo tests/unit/test_daemon.py::test_poll_telegram_once_sessions_dashboard_screenshot_sends_photo tests/e2e/test_gateway_flow.py::test_gateway_flow_gateway_screenshot_sends_photo` -> `src/codex_telegram_gateway/screenshot_capture.py 81%`

### FP-22 verification
- Branch and merge:
  - feature branch `feature/fp-22-live-view`
  - feature commit `b31a0b8`
  - merge commit on `main` `11f9a7d`
- Re-reviewed `ccgram` live-view sources before implementation:
  - `/tmp/ccgram/src/ccgram/handlers/live_view.py`
  - `/tmp/ccgram/tests/ccgram/handlers/test_live_view.py`
  - `/tmp/ccgram/src/ccgram/handlers/screenshot_callbacks.py`
- Added `live_view.py` with:
  - persisted `LiveViewState`
  - inline callback parsing
  - active/inactive live-view keyboards
  - stable caption rendering and capture hashing
- `GatewayDaemon` now supports:
  - `/gateway live`
  - a `📺` action in the sessions dashboard
  - start/refresh/stop callbacks on the live-view message itself
  - restart-stable live-view ticking during the poll loop
- Implementation decisions locked during FP-22:
  - live view is an auto-refreshing whole-window Codex App screenshot, not a tmux pane stream
  - the poll loop owns live-view ticking so the first `/gateway live` send and the first periodic refresh stay separate
  - live views persist in SQLite by topic so a daemon restart resumes editing the same Telegram message
  - stop and timeout keep the existing Telegram message and switch its controls to a `Start live` button instead of deleting the operator surface
- Proofread fixes before sign-off:
  - moved live-view ticking from the end of `poll_telegram_once()` to the start so zero-interval tests and production callbacks do not immediately double-refresh a just-started session
  - updated all sessions-dashboard expectations after adding the new `📺` action, rather than weakening the dashboard assertions
- Focused verification:
  - `.venv/bin/pytest tests/unit/test_config.py tests/unit/test_sessions_dashboard.py tests/unit/test_state.py tests/unit/test_telegram_api.py tests/unit/test_live_view.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py::test_gateway_flow_live_view_persists_and_edits_same_message -q` -> `227 passed`
- Full-suite verification:
  - `.venv/bin/pytest -q` -> `367 passed`
- Feature-specific changed-executable coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway --cov-report=json:coverage-fp22.json -q` plus diff-based changed-line audit -> `155/168 = 92.3%`

### FP-23 verification
- Branch and merge:
  - feature branch `feature/fp-23-remote-control-actions`
  - feature commit `97657cf`
  - merge commit on `main` `2dc886d`
- Re-reviewed `ccgram` remote-control sources before implementation:
  - `/tmp/ccgram-review/src/ccgram/handlers/status_bubble.py`
  - `/tmp/ccgram-review/src/ccgram/handlers/callback_data.py`
  - `/tmp/ccgram-review/src/ccgram/handlers/screenshot_callbacks.py`
  - `/tmp/ccgram-review/README.md`
- Added `remote_actions.py` for status-bubble button rendering and callback parsing.
- `GatewayDaemon` now exposes:
  - `⏹ Stop` and `▶ Continue` on running status bubbles
  - approval-choice buttons for active command/file approval prompts
  - `↻ Retry Last` after failed/interrupted turns when topic history exists
  - `gw:remote:*` callback handling with explicit stale/unbound/closed-topic toasts
- Implementation decisions locked during FP-23:
  - adapt `ccgram` remote control to app-native Codex actions only; do not emulate tmux keys or remote-control sessions
  - use app-server `turn/interrupt` for stop
  - implement retry by replaying persisted topic history instead of `thread/rollback`
  - keep generic tool-request-user-input flows on the existing interactive prompt message UI
- Proofread fixes before sign-off:
  - confirmed remote callbacks are routed before generic response callbacks
  - checked stop handling across primary and mirror targets
  - added branch-coverage tests for stale, invalid, and closed-topic remote callbacks instead of softening the behavior
- Focused verification:
  - `.venv/bin/pytest tests/unit/test_remote_actions.py tests/unit/test_codex_api.py::test_interrupt_turn_uses_turn_interrupt_rpc -q` -> `5 passed`
  - `.venv/bin/pytest tests/unit/test_status_bubble.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py::test_status_bubble_stop_interrupts_active_turn_and_exposes_retry -q` -> `178 passed`
- Full-suite verification:
  - `.venv/bin/pytest -q` -> `385 passed`
- Feature-specific changed-executable coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway --cov-report=json:coverage-fp23.json -q` plus diff-based changed-line audit including new source files -> `188/199 = 94.5%`

### FP-10 verification
- Branch and merge:
  - feature branch `feature/fp-10-upgrade`
  - feature commit `409f524`
  - merge commit on `main` `1bedb38`
- Re-reviewed `ccgram` upgrade source before implementation:
  - `/tmp/ccgram-review/src/ccgram/handlers/upgrade.py`
- Added `upgrade_diagnostics.py` for:
  - plugin root discovery
  - plugin version/manifest discovery
  - repo/user marketplace install discovery
  - operator-facing upgrade instructions rendering
- `GatewayDaemon` now handles `/gateway upgrade` directly and returns a diagnostics report instead of mutating the plugin installation.
- Implementation decisions locked during FP-10:
  - keep the feature diagnostics-only; do not run `git pull`, reinstall, or self-restart from Telegram
  - restrict marketplace lookup to the documented repo-local and user-local plugin marketplace manifests
  - render both raw and resolved marketplace source paths when available
- Proofread fixes before sign-off:
  - updated the gateway help snapshot after adding the new subcommand
  - added an explicit failure-path test so missing-manifest discovery errors become visible Telegram output
- Focused verification:
  - `.venv/bin/pytest tests/unit/test_upgrade_diagnostics.py tests/unit/test_daemon.py::test_poll_telegram_once_handles_commands_without_queueing_to_codex tests/unit/test_daemon.py::test_poll_telegram_once_gateway_upgrade_sends_rendered_diagnostics tests/unit/test_daemon.py::test_poll_telegram_once_gateway_upgrade_reports_discovery_failure tests/e2e/test_gateway_flow.py::test_gateway_flow_upgrade_command_reports_version_and_marketplace_source -q` -> `6 passed`
- Full-suite verification:
  - `.venv/bin/pytest -q` -> `391 passed`
- Feature-specific changed-executable coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway --cov-report=json:coverage-fp10.json -q` plus diff-based changed-line audit including new source files -> `79/85 = 92.9%`

### FP-15 verification
- Branch and merge:
  - feature branch `feature/fp-15-panes-compatibility`
  - feature commit `503d092`
  - merge commit on `main` `a4c90fa`
- Re-reviewed `ccgram` pane handling before implementation:
  - `/tmp/ccgram-review/src/ccgram/handlers/screenshot_callbacks.py`
  - `/tmp/ccgram-review/src/ccgram/cc_commands.py`
  - `/tmp/ccgram-review/src/ccgram/bot.py`
- Added `panes_compat.py` for:
  - same-project loaded-thread filtering
  - explicit Codex-App compatibility message rendering
- `GatewayDaemon` now handles `/gateway panes` directly and returns a project-thread summary instead of falling back to help.
- Implementation decisions locked during FP-15:
  - keep `/panes` compatibility-only; do not emulate tmux panes in Codex App mode
  - keep the command read-only so it is safe for primary and mirror bindings
  - direct operators to `/gateway threads`, `/gateway screenshot`, and `/gateway live` for the app-native equivalents
- Proofread fixes before sign-off:
  - updated the gateway help snapshot after adding the new subcommand
  - corrected a daemon test fixture that expected a third same-project thread it had not actually created
  - added explicit edge-case tests for missing project roots and empty project-thread sets
- Focused verification:
  - `.venv/bin/pytest -q tests/unit/test_panes_compat.py tests/unit/test_daemon.py::test_poll_telegram_once_handles_commands_without_queueing_to_codex tests/unit/test_daemon.py::test_poll_telegram_once_gateway_panes_reports_project_threads tests/e2e/test_gateway_flow.py::test_gateway_flow_gateway_panes_reports_project_threads` -> `7 passed`
- Full-suite verification:
  - `.venv/bin/pytest -q` -> `397 passed`
- Feature-specific changed-executable coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway.daemon --cov=codex_telegram_gateway.panes_compat --cov-report=json:/tmp/fp15_cov.json tests/unit/test_panes_compat.py tests/unit/test_daemon.py::test_poll_telegram_once_handles_commands_without_queueing_to_codex tests/unit/test_daemon.py::test_poll_telegram_once_gateway_panes_reports_project_threads tests/e2e/test_gateway_flow.py::test_gateway_flow_gateway_panes_reports_project_threads`
  - diff-based changed-line audit for FP-15 source work -> `32/34 = 94.1%`

### FP-28 verification
- Branch and merge:
  - feature branch `feature/fp-28-inter-agent-messaging-mailbox`
  - feature commit `89d473e`
  - merge commit on `main` `c65b9a4`
- Re-reviewed `ccgram` mailbox sources before implementation:
  - `/tmp/ccgram-review/src/ccgram/msg_cmd.py`
  - `/tmp/ccgram-review/src/ccgram/mailbox.py`
  - `/tmp/ccgram-review/src/ccgram/handlers/msg_broker.py`
  - `/tmp/ccgram-review/README.md`
- Added `mailbox_commands.py` for:
  - `/gateway msg ...` parsing
  - mailbox help rendering
  - peer-list rendering
  - delivery and notification text rendering
- Added persisted SQLite mailbox state for:
  - message creation
  - inbox listing
  - pending delivery queue listing
  - delivered/read status updates
- `GatewayDaemon` now handles `/gateway msg peers|send|inbox|read|reply|broadcast` and drains one pending mailbox message per `deliver_inbound_once()` cycle into an idle recipient Codex thread.
- Implementation decisions locked during FP-28:
  - adapt `ccgram` mailbox identities from tmux-window ids to `codex_thread_id`
  - scope peer messaging to active bound threads so Telegram notifications have a stable destination
  - use SQLite instead of file mailboxes because the gateway already coordinates through SQLite
  - treat self-send blocking and pending-turn recipient skipping as the adapted loop-safety mechanisms for Codex App mode
- Proofread fixes before sign-off:
  - added the `/gateway msg` help snapshot update after introducing the new command family
  - added operator-error tests for missing args, self-send, unknown recipients, empty inbox, and no-peer broadcast
  - added delivery-skip tests for pending-turn, missing-binding, closed-binding, and busy-recipient cases
- Focused verification:
  - `.venv/bin/pytest -q tests/unit/test_mailbox_commands.py tests/unit/test_state.py::test_sqlite_state_persists_mailbox_messages_and_status_updates tests/unit/test_daemon.py::test_poll_telegram_once_handles_commands_without_queueing_to_codex tests/unit/test_daemon.py::test_poll_telegram_once_gateway_msg_send_and_deliver_mailbox_message tests/unit/test_daemon.py::test_poll_telegram_once_gateway_msg_inbox_read_reply_and_broadcast tests/unit/test_daemon.py::test_poll_telegram_once_gateway_msg_help_and_error_paths tests/unit/test_daemon.py::test_poll_telegram_once_gateway_msg_broadcast_without_peers_and_reply_target_not_bound tests/unit/test_daemon.py::test_deliver_inbound_once_skips_unavailable_mailbox_recipients_until_idle_bound_peer tests/e2e/test_gateway_flow.py::test_gateway_flow_gateway_msg_send_delivers_to_idle_peer_thread` -> `15 passed`
  - `.venv/bin/pytest --cov=codex_telegram_gateway.daemon --cov=codex_telegram_gateway.state --cov=codex_telegram_gateway.mailbox_commands --cov=codex_telegram_gateway.models --cov-report=json:/tmp/fp28_cov.json tests/unit/test_daemon.py tests/unit/test_state.py tests/unit/test_mailbox_commands.py tests/e2e/test_gateway_flow.py` -> `244 passed`
- Full-suite verification:
  - `.venv/bin/pytest -q` -> `411 passed`
- Feature-specific changed-executable coverage:
  - diff-based changed-line audit for FP-28 source work -> `220/227 = 96.9%`

### FP-29 verification
- Branch and merge:
  - feature branch `feature/fp-29-shell-nl-to-command-mode`
  - feature commit `eb85f32`
  - merge commit on `main` `8711c72`
- Re-reviewed `ccgram` shell sources before implementation:
  - `/tmp/ccgram-review/src/ccgram/providers/shell.py`
  - `/tmp/ccgram-review/src/ccgram/handlers/shell_commands.py`
  - `/tmp/ccgram-review/src/ccgram/handlers/shell_capture.py`
- Red-phase sequence:
  - added end-to-end shell contracts first for raw `!command` execution and NL suggestion approval
  - added interface-only `shell_mode.py` with protocols, dataclasses, parse/render surface, and runner/suggester builders
  - added unit tests over the interface surface with dummy suggester/runner doubles
  - confirmed the expected failures:
    - shell helper tests failed with `NotImplementedError`
    - gateway e2e tests failed because `GatewayDaemon` did not yet accept `shell_runner` or `shell_suggester`
- Implementation decisions locked during FP-29:
  - adapt `ccgram` shell mode into an explicit `/gateway shell ...` command family instead of a separate provider mode
  - keep raw execution and NL suggestion as two explicit paths:
    - `/gateway shell !<command>` executes immediately in the bound project directory
    - `/gateway shell <request>` generates a suggested command and requires Telegram approval
  - persist pending shell suggestions per topic in SQLite so Run/Cancel callbacks survive daemon restarts
  - scope shell control to primary bindings only because project control actions stay out of mirror topics
  - use an OpenAI-compatible chat-completions provider only when configured; otherwise NL suggestion is disabled and raw execution remains explicit
- Proofread fixes before sign-off:
  - added mirror-topic gating after the first implementation draft so shell control follows the project-control rule
  - found and fixed a real recovery bug where deleted suggestion messages could cause shell updates to disappear into the polling exception path
  - added tests for stale callbacks, suggester failure, deleted-widget recovery, and deleted-result-message recovery instead of leaving those paths soft-fail
- Focused verification:
  - `.venv/bin/pytest tests/unit/test_shell_mode.py tests/unit/test_daemon.py -k 'shell or handles_commands_without_queueing_to_codex' tests/unit/test_state.py -k shell tests/unit/test_config.py -k shell tests/e2e/test_gateway_flow.py -k shell` -> `17 passed`
  - `.venv/bin/pytest tests/unit/test_daemon.py -k 'gateway_shell or shell_cancel or shell_callback_rejects_stale or handles_commands_without_queueing_to_codex'` -> `9 passed`
  - `.venv/bin/pytest tests/unit/test_daemon.py -k 'previous_message_is_gone or original_widget_is_gone or gateway_shell or shell_cancel or shell_callback_rejects_stale or handles_commands_without_queueing_to_codex'` -> `11 passed`
- Full-suite verification:
  - `.venv/bin/pytest -q` on the feature branch -> `433 passed`
  - `.venv/bin/pytest -q` on `main` after merge -> `433 passed`
- Feature-specific changed-executable coverage:
  - `.venv/bin/pytest --cov=codex_telegram_gateway --cov-report=json:coverage-fp29.json -q` plus diff-based changed-line audit against `main` -> `234/273 = 85.7%`
  - changed executable lines by file:
    - `src/codex_telegram_gateway/config.py` -> `10/10 = 100.0%`
    - `src/codex_telegram_gateway/daemon.py` -> `89/108 = 82.4%`
    - `src/codex_telegram_gateway/shell_mode.py` -> `118/138 = 85.5%`
    - `src/codex_telegram_gateway/state.py` -> `16/16 = 100.0%`
