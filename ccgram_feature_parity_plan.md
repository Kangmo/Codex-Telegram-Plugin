# ccgram Feature Parity Plan

## Objective

Close the feature gap between this Codex App Telegram gateway and `ccgram` as far as the Codex App architecture allows.

This document turns the line-by-line gap review into an implementation roadmap. For each missing or partial-parity feature, it defines:

- the parity target
- the adapted design for Codex App
- the implementation steps
- the automated test strategy

## Scope Rules

- Keep `codex_thread_id <-> (chat_id, message_thread_id)` as the routing key.
- Do not regress existing working flows: app-backed thread discovery, topic binding, queued `Steer`, streaming edits, image intake, and typing signals.
- Prefer app-native Codex integrations over tmux-style emulation.
- When a `ccgram` feature is tmux-only, implement either:
  - a Codex-App-native equivalent, or
  - a compatibility command that explains why the feature is unsupported.

## Workstreams

1. Topic lifecycle and sync parity
2. Commands and dashboard parity
3. Runtime interaction parity
4. Media and content parity
5. Advanced provider and messaging parity

## Feature Inventory

| ID | Feature | Priority | App Fit | Notes |
|---|---|---|---|---|
| FP-01 | Topic close/reopen lifecycle | P0 | Native | Missing |
| FP-02 | Bidirectional topic rename sync | P0 | Adapted | Missing inbound rename handling |
| FP-03 | Topic emoji/status state | P1 | Adapted | Missing |
| FP-04 | Lifecycle sweeps: probe/autoclose/unbound TTL/prune | P0 | Native | Partial today |
| FP-05 | Multi-chat fanout and Telegram flood-control backoff | P1 | Native | Missing |
| FP-06 | `/history` | P0 | Native | Missing |
| FP-07 | `/resume` | P0 | Adapted | Missing |
| FP-08 | `/unbind` | P0 | Native | Missing |
| FP-09 | `/restore` and richer recovery flows | P0 | Adapted | Partial today |
| FP-10 | `/upgrade` | P2 | Adapted | Not critical |
| FP-11 | `/send` file browser/upload | P0 | Native | Implemented |
| FP-12 | `/toolbar` configurable action bar | P1 | Adapted | Missing |
| FP-13 | `/verbose` and notification modes | P0 | Native | Implemented |
| FP-14 | `/screenshot` | P1 | Adapted | Missing |
| FP-15 | `/panes` compatibility | P2 | Compatibility only | Codex App has no pane model |
| FP-16 | `/recall` top-level recall flow | P1 | Native | Implemented |
| FP-17 | Command discovery and Telegram menu sync | P0 | Adapted | Partial today |
| FP-18 | Full sessions dashboard | P0 | Native | Partial today |
| FP-19 | Generic interactive prompt bridge | P0 | Depends on app-server support | Implemented |
| FP-20 | Dedicated status bubble | P0 | Native | Implemented |
| FP-21 | Tool batching, failure probing, completion summaries | P0 | Native | Implemented |
| FP-22 | Live view | P1 | Adapted | Missing |
| FP-23 | Remote control actions | P1 | Depends on app-server support | Missing |
| FP-24 | General file intake and unsupported-content UX | P0 | Native | Implemented |
| FP-25 | Outbound media/file delivery | P0 | Native | Implemented |
| FP-26 | Voice transcription flow | P1 | Native | Implemented |
| FP-27 | Inline query support | P2 | Native | Implemented |
| FP-28 | Inter-agent messaging/mailbox | P3 | Separate subsystem | Not recommended for near-term parity |
| FP-29 | Shell/NL-to-command mode | P3 | Separate subsystem | Not recommended for this plugin |

## Feature Execution Tracker

Update these checkboxes as each feature lands.

### FP-01: Topic Close/Reopen Lifecycle
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-02: Bidirectional Topic Rename Sync
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-03: Topic Emoji/Status State
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-04: Lifecycle Sweeps, Topic Probing, Autoclose, Unbound TTL, Pruning
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-05: Multi-Chat Fanout and Telegram Flood-Control Backoff
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-06: `/history`
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-07: `/resume`
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-08: `/unbind`
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-09: `/restore` and Rich Recovery Flows
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-10: `/upgrade`
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-11: `/send` File Browser and Upload
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-12: `/toolbar` Configurable Action Bar
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-13: `/verbose` and Notification Modes
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-14: `/screenshot`
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-15: `/panes` Compatibility
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-16: `/recall`
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-17: Command Discovery and Telegram Menu Sync
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-18: Full Sessions Dashboard
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-19: Generic Interactive Prompt Bridge
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-20: Dedicated Status Bubble
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-21: Tool Batching, Failure Probing, Completion Summaries
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-22: Live View
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-23: Remote Control Actions
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-24: General File Intake and Unsupported-Content UX
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-25: Outbound Media and File Delivery
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-26: Voice Transcription Flow
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-27: Inline Query Support
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### FP-28: Inter-Agent Messaging/Mailbox
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-29: Shell/NL-to-Command Mode
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

## Documentation Discipline

This file is the tracker of record for the full parity program. For every feature branch before merge to `main`, update this document with:

- implementation decisions and any design changes from the original plan
- automated test scope, commands run, and changed-line coverage result
- line-by-line code review notes, including defects found and fixed during proof reading
- branch name, commit SHA, and merge commit SHA once the feature is complete

Do not treat the checkbox tracker as sufficient by itself. A feature is not considered done until the three checkboxes are complete and its implementation/test/code-review notes are written here.

## Project-Wide Decisions Collected From Chat

These decisions are already fixed unless a later feature explicitly supersedes them.

- The gateway is for the macOS Codex App, not Codex CLI history. Thread/project discovery must come from Codex App runtime or Codex App local store, never from CLI session history.
- Routing key is `codex_thread_id <-> (chat_id, message_thread_id)`. Topic titles are metadata only and may change at any time.
- Bindings must persist on disk in SQLite. Topic title drift must never affect delivery routing.
- New Telegram topic titles are canonicalized as `(<project name>) <thread title>`.
- If a Telegram topic is created manually and receives its first message unbound, the bot must reply with a project selection flow like `ccgram`.
- New-project selection from Telegram must support choosing an existing loaded Codex App project or browsing folders starting at the macOS user home directory. Absolute-path free-text entry is intentionally not the UX.
- Choosing a folder from Telegram creates or exposes that project in Codex App, creates a new thread titled `untitled`, binds the topic, and renames the topic to `(<project>) untitled`.
- When Codex later renames that thread from `untitled` to a real title, Telegram topic rename sync must follow automatically.
- The plugin must be installable into Codex App and must use an MCP/plugin path that runs inside Codex App context.
- On plugin startup, loaded Codex App projects/threads should sync automatically into Telegram topics.
- Typing indicators should appear as soon as a Telegram message starts processing and continue while Codex is still answering or waiting for approval.
- Outbound assistant text should edit the same Telegram message while the same Codex message block is growing; a new Telegram message is only sent when Codex starts a new assistant block.
- If a user sends a message while Codex is still answering, the gateway queues it, echoes that it was queued, and offers a real `Steer` control that maps to Codex App `turn/steer`.
- Telegram images must be ingested and delivered to Codex as real local image inputs, not reduced to a path string only.
- Telegram bot API cannot force chat read receipts, so `vv`/read state is not a supported feature.
- Mirror topics are conversation surfaces only. Project/thread management actions stay in the primary topic unless a later feature explicitly broadens that rule.
- Slash commands are passed through to Codex as plain thread input unless they use the reserved `/gateway ...` namespace.
- The gateway should adopt `ccgram` behavior where it fits the Codex App architecture, but tmux-only behaviors must be adapted or explicitly unsupported rather than emulated poorly.

## Completed Feature Journal

This section summarizes the work already completed before the remaining backlog items.

### FP-01 to FP-05 Summary

Implementation decisions:

- Topic lifecycle state uses persisted `binding_status` and topic-lifecycle timestamps instead of in-memory flags.
- Inbound Telegram topic close/reopen/edit service events are normalized in the polling layer.
- Topic rename sync is guarded so only safe thread-title changes flow back into Codex App; malformed project-prefix edits are corrected back to the canonical format.
- Topic emoji/status behavior is adapted to title-prefix status markers with chat-level suppression after Telegram permission failures.
- Lifecycle sweeps cover topic probing, autoclose, unbound-topic TTL expiry, and pruning of stale topic-scoped state.
- Multi-chat support is implemented as one primary binding plus zero or more mirror bindings with persisted topic-creation jobs and retry-after handling.

Test and verification notes:

- FP-02 changed-line coverage: `46/46 = 100.0%`
- FP-03 changed-line coverage: `77/81 = 95.1%`
- FP-04 changed-line coverage: `152/169 = 89.9%`
- FP-05 changed-line coverage: `225/261 = 86.2%`

Code review notes:

- Fixed lifecycle cleanup so missing-topic probes remove topic-lifecycle rows, not only binding state.
- Fixed reopen/new-inbound handling so `completed_at` is actually cleared when activity resumes.
- Hardened mirror controls so mirror topics cannot run project/thread management actions intended for the primary topic.

### FP-06: `/history`

Branch and merge:

- Feature branch: `feature/fp-06-history`
- Feature commit: `6517676`
- Merge commit on `main`: `2eaef9e`

Implementation decisions:

- History is rendered from Codex App `thread/read` items, not from terminal transcript bytes.
- A dedicated `history_command.py` module owns pagination and rendering.
- History-view callback context is persisted in SQLite so paging survives daemon restarts.

Test and verification notes:

- Full-suite verification at completion: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `123 passed`
- Changed-line coverage: `142/166 = 85.5%`

Code review notes:

- Fixed history summarization to prefer concrete command failure lines over vague `failed` text.
- Fixed pagination rendering so later pages repeat the thread header instead of losing context.
- Corrected one test bug where a fake command output used literal `\\n` instead of a real newline.

### FP-07: `/resume`

Branch and merge:

- Feature branch: `feature/fp-07-resume`
- Feature commit: `a88a96f`
- Merge commit on `main`: `fa28a34`

Implementation decisions:

- Resume discovery is project-scoped and uses Codex App local store data, not Telegram topic history or CLI session history.
- The existing Telegram topic is rebound to the chosen older thread instead of creating a new topic.
- Historical assistant events for the resumed thread are marked seen immediately to avoid replaying old content.
- If the chosen thread is `notLoaded`, the gateway explicitly resumes it through Codex App before rebinding.

Test and verification notes:

- Full-suite verification at completion: `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `135 passed`
- Changed-line coverage: `115/139 = 82.7%`

Code review notes:

- Fixed a real gap where rebinding to a non-loaded thread updated the DB but did not actually load the thread into Codex App.
- Improved stale-picker behavior so empty resume pages clear the existing picker instead of leaving a dangling control message.

### FP-08: `/unbind`

Branch and status:

- Feature branch: `feature/fp-08-unbind`
- Feature commit: `f7a8d9e`
- Merge commit on `main`: `4ded88a`

Implementation decisions:

- `/gateway unbind` is implemented as a real detach, not as a fake `closed` or `deleted` lifecycle status.
- Because the current sync loop is anchored on a primary binding, unbinding a primary topic also detaches any mirror topics for the same Codex thread instead of leaving unsupported mirror-only routing behind.
- Unbind keeps the Codex thread alive in Codex App, but clears Telegram-side transient state for that thread:
  - queued inbound items
  - pending turn state
  - outbound message mappings
  - topic-scoped history/resume views
  - topic recall history
  - pending mirror topic-creation jobs
- After unbind, the topic becomes an unbound topic again, with fresh topic-project metadata and unbound-topic activity timestamps so the normal project-picker flow can resume on the next inbound message.
- Unbind strips status-prefix metadata from the topic name before leaving the topic idle.
- Mirror topics reject `/gateway unbind` just like other project/thread control commands.

Test and verification notes:

- Red-phase tests were added first:
  - unit tests for `/gateway unbind` cleanup behavior and mirror-control rejection
  - end-to-end test proving that unbind returns the topic to the project-picker flow on the next message
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_daemon.py -q` -> `70 passed`
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_gateway_flow.py -q` -> `3 passed`
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_state.py -q` -> `14 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `139 passed`
- Changed-line coverage for source diff:
  - `src/codex_telegram_gateway/daemon.py`: `46/55 = 83.6%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `TOTAL`: `58/67 = 86.6%`

Code review notes:

- The main design risk identified during review was that removing only the primary binding would stop `sync_codex_once()` from servicing mirror topics, because the current outbound loop iterates primary bindings first. That is why FP-08 detaches mirrors together with the primary topic.
- The proofread pass also confirmed that seen-event state should stay intact during unbind so rebinding the same Codex thread later does not replay old assistant history into a fresh topic unexpectedly.

### FP-09: `/restore` and Rich Recovery Flows

Branch and merge:

- Feature branch: `feature/fp-09-restore-and-richer-recovery-flows`
- Feature commit: `67f4ec5`
- Merge commit on `main`: `a3b4dc3`

Implementation decisions:

- Recovery is adapted to Codex App bindings rather than tmux sessions. The supported recovery states are:
  - `closed` topic bound to the same Codex thread
  - `deleted` or unreachable Telegram topic for the same Codex thread
- Recovery UI is driven by a dedicated `recovery.py` module plus persisted `RestoreViewState` rows in SQLite, so restore menus survive daemon restarts and reject stale callbacks safely.
- `/gateway restore` is the explicit operator entry point, and the daemon also auto-offers the restore menu when a user sends a message into a closed primary topic.
- `Continue Here` restores the existing topic in place for closed bindings, immediately normalizes the Telegram topic title back to the canonical `(<project>) <thread>` form, and clears the closed-status override without waiting for a later sync pass.
- `Recreate Topic` is reserved for deleted bindings and reuses the existing `GatewayService.recreate_topic()` path so the same Codex thread is preserved and only the Telegram topic identity changes.
- `Resume Other Thread` deliberately reuses the FP-07 `/resume` picker instead of creating a parallel thread-selection flow.
- Repeated inbound messages on a closed topic reuse the existing restore prompt message by editing it in place instead of spamming multiple recovery menus.
- Deleted topics still cannot click `/gateway restore` themselves because Telegram no longer has a reachable topic surface there; that recovery case remains accessible through the existing `/gateway sync` repair flow. FP-09 adds richer guided recovery where Telegram still has a callable topic context.
- Cleanup paths for bind, rebind, unbind, and new-thread creation all clear persisted restore-view state so recovery widgets cannot survive after the topic is healthy again.

Test and verification notes:

- Red-phase tests were added first for:
  - explicit `/gateway restore` on closed and healthy topics
  - automatic restore prompt on inbound messages to closed topics
  - callback flows for continue, recreate, resume, cancel, stale menus, issue drift, wrong-action rejection, and healthy-after-click behavior
  - SQLite persistence of restore-view state across restart
  - end-to-end restart survival for restore-continue followed by normal routing
  - direct `recovery.py` rendering coverage for both closed and deleted prompts
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_recovery.py tests/unit/test_daemon.py tests/unit/test_state.py tests/e2e/test_gateway_flow.py -q` -> `103 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `155 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/daemon.py`: `100/110 = 90.9%`
  - `src/codex_telegram_gateway/models.py`: `7/7 = 100.0%`
  - `src/codex_telegram_gateway/ports.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `src/codex_telegram_gateway/recovery.py` statement coverage: `20/20 = 100.0%`
  - `TOTAL`: `119/129 = 92.2%`

Code review notes:

- The first version of the new tests was wrong in two places: it queued multiple callback updates before changing state, which meant one `poll_telegram_once()` processed the whole batch under the old state. Those tests were fixed before sign-off so each callback branch is asserted under the intended binding state.
- The proofread pass identified a UX issue where `Continue Here` would restore routing but leave the topic name drifted until a later sync. That was fixed by renaming the topic immediately inside the restore callback.
- The proofread pass also identified menu spam risk on repeated messages to a closed topic. `_offer_restore_prompt()` now reuses the existing restore-menu message id when present.

### FP-11: `/send` File Browser and Upload

Branch and status:

- Feature branch: `feature/fp-11-send-file-browser-and-upload`
- Feature commit: `8a08655`
- Merge commit on `main`: `dea79a2`

Implementation decisions:

- `/gateway send` is implemented as a project-root-scoped Telegram file browser rather than an arbitrary-path sender.
- The feature is split into three dedicated modules:
  - `send_security.py` for path containment, browse pagination, search, and preview metadata
  - `send_command.py` for browser/preview rendering
  - `send_callbacks.py` for compact callback parsing
- Send-browser state is persisted in SQLite as `SendViewState`, keyed by `chat_id + message_thread_id`, so callback navigation is restart-safe and one active browser exists per topic.
- Query resolution order is:
  - exact safe relative path
  - exact safe directory open
  - exact safe file preview
  - search fallback for other text
- Mirror topics reject `/gateway send` because file-management controls stay in the primary topic.
- Telegram outbound file delivery uses dedicated multipart helpers:
  - `send_document_file`
  - `send_photo_file`

Test and verification notes:

- Red-phase tests were added first for:
  - path traversal and symlink escape rejection
  - browse pagination and search behavior
  - preview rendering and callback parsing
  - SQLite persistence of send-browser state
  - daemon command/callback flows for root browse, directory open, preview, document send, photo send, stale widgets, and mirror/unbound rejection
  - Telegram multipart upload success and error handling
  - end-to-end file send from a bound project into Telegram
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_send_command.py tests/unit/test_send_security.py tests/unit/test_daemon.py tests/unit/test_state.py tests/unit/test_telegram_api.py tests/e2e/test_gateway_flow.py` -> `163 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `216 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/daemon.py`: `153/156 = 98.1%`
  - `src/codex_telegram_gateway/models.py`: `11/11 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `src/codex_telegram_gateway/telegram_api.py`: `21/44 = 47.7%`
  - `src/codex_telegram_gateway/send_callbacks.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/send_command.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/send_security.py`: `0/0 = 100.0%`
  - `TOTAL`: `197/223 = 88.3%`
- Whole-module regression coverage from the focused FP-11 suite:
  - `send_callbacks.py`: `20/20 = 100.0%`
  - `send_command.py`: `31/31 = 100.0%`
  - `send_security.py`: `85/92 = 92.4%`
  - `daemon.py`: `1411/1720 = 82.0%`
  - `state.py`: `330/343 = 96.2%`
  - `models.py`: `134/134 = 100.0%`

Code review notes:

- The proofread pass found a real crafted-callback bug: negative indexes were accepted by the parser and could select the last list entry via Python negative indexing. The parser now rejects negative indexes.
- The proofread pass found a second crafted-callback bug: preview callbacks could target directories and crash preview generation. The daemon now rejects directory-preview callbacks cleanly.
- The proofread pass also found stale-state leakage around rebinding/unbind flows. Send-browser state is now cleared when a topic is rebound to a new thread or unbound from its thread.

### FP-13: `/verbose` and Notification Modes

Branch and merge:

- Feature branch: `feature/fp-13-verbose-and-notification-modes`
- Feature commit: `e793d11`
- Merge commit on `main`: `d0479a8`

Implementation decisions:

- FP-13 uses a dedicated `notification_modes.py` module so normalization, callback parsing, picker rendering, and gating rules stay out of the already-large daemon command handler.
- Notification modes are persisted per topic and normalized on read, so older rows storing `assistant_plus_alerts` or `assistant_only` transparently map to the new canonical values:
  - `all`
  - `important`
  - `errors_only`
  - `muted`
- This port intentionally gates only supplemental Telegram chatter:
  - typing indicators
  - failure/interruption notices
  - dashboard/status labels
- Assistant replies are never muted. Unlike `ccgram`, Telegram is the primary conversation surface in this gateway, so suppressing actual assistant output would make the topic unusable.
- Mirror topics can change their own notification mode because the setting is topic-local and does not alter project or thread ownership.

Test and verification notes:

- Red-phase tests were added first for:
  - mode normalization and legacy alias handling
  - verbose picker rendering and callback parsing
  - `/gateway verbose` command flow for bound and unbound topics
  - callback-driven mode updates and dismiss behavior
  - typing suppression and error-notification retention under muted/error-only modes
  - restart-stable persistence of mode changes in end-to-end flow
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_notification_modes.py tests/unit/test_daemon.py tests/unit/test_sessions_dashboard.py tests/e2e/test_gateway_flow.py` -> `154 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `244 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/daemon.py`: `40/48 = 83.3%`
  - `src/codex_telegram_gateway/notification_modes.py`: `0/0 = 100.0%`
  - `TOTAL`: `40/48 = 83.3%`

Code review notes:

- The proofread pass confirmed the key adaptation from `ccgram`: notification modes mute supplemental chatter only, never assistant reply content.
- The review also caught the need to normalize legacy persisted names up front so dashboards, status output, and callback updates do not keep surfacing stale labels.
- Remaining uncovered branches are low-signal stale/error paths in callback and send-failure handling; the changed-line coverage threshold still cleared 80%.

### FP-17: Command Discovery and Telegram Menu Sync

Branch and merge:

- Feature branch: `feature/fp-17-command-discovery-and-telegram-menu-sync`
- Feature commit: `65c2221`
- Merge commit on `main`: `176d9c6`

Implementation decisions:

- The Codex App bridge still does not expose a reliable slash-command discovery API, so FP-17 does not fake provider discovery. Instead, the Telegram menu is generated from:
  - the always-present `/gateway` namespace
  - explicitly configured pass-through commands from `CODEX_TELEGRAM_MENU_PASSTHROUGH_COMMANDS`
  - slash commands actually observed in bound topics and persisted in SQLite
- Menu registration is chat-scoped to the configured Telegram group rather than global, which matches the single-forum deployment model of this gateway and avoids polluting other chats if the bot is reused elsewhere.
- A dedicated `commands_catalog.py` module now owns:
  - menu generation
  - command-name sanitization to Telegram-safe names
  - stable description mapping for known Codex commands
  - registration hash calculation
- Menu hashes are persisted in SQLite, so plugin restart does not resend identical `setMyCommands` payloads and trigger unnecessary Telegram writes.
- Observed pass-through commands are learned only from non-`/gateway` slash commands in already bound topics. Unbound topics and gateway namespace commands do not affect the menu.
- `/gateway help` now shows both the gateway subcommands and the current top-level Telegram menu catalog so the visible bot menu and the documented menu stay in sync.

Test and verification notes:

- Red-phase tests were added first for:
  - config parsing of `CODEX_TELEGRAM_MENU_PASSTHROUGH_COMMANDS`
  - command-catalog generation from configured and observed pass-through commands
  - hash-based menu registration that skips redundant updates
  - SQLite persistence of observed pass-through commands and registered menu hashes
  - daemon learning of a new pass-through command from a bound-topic slash command and immediate menu refresh
  - end-to-end restart behavior proving observed menu commands persist across SQLite restart while unchanged catalogs do not re-register
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_config.py tests/unit/test_commands_catalog.py tests/unit/test_state.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -q` -> `111 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `161 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/cli.py`: `3/5 = 60.0%`
  - `src/codex_telegram_gateway/config.py`: `13/13 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py`: `23/27 = 85.2%`
  - `src/codex_telegram_gateway/mcp_server.py`: `3/5 = 60.0%`
  - `src/codex_telegram_gateway/ports.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `16/16 = 100.0%`
  - `src/codex_telegram_gateway/telegram_api.py`: `1/5 = 20.0%`
  - `src/codex_telegram_gateway/commands_catalog.py`: `36/37 = 97.3%`
  - `TOTAL`: `95/108 = 88.0%`

Code review notes:

- The main design decision was to stay explicit about the discovery limit: the menu is dynamic, but it is dynamic from real gateway capabilities, configuration, and observed usage, not from an invented Codex provider API that does not exist.
- The proofread pass removed the stale static `BOT_COMMANDS` constant so there is only one source of truth for Telegram menu registration.
- The proofread pass also kept registration failures non-fatal for chat flow: pass-through command learning should never block the actual inbound message from reaching Codex just because Telegram command registration failed.

### FP-18: Full Sessions Dashboard

Branch and merge:

- Feature branch: `feature/fp-18-full-sessions-dashboard`
- Feature commit: `10f8f79`
- Merge commit on `main`: `9909e0c`

### FP-19: Generic Interactive Prompt Bridge

Branch and merge:

- Feature branch: `feature/fp-19-generic-interactive-prompt-bridge`
- Feature commit: `c69624b`
- Merge commit on `main`: `18e7272`

Implementation decisions:

- Interactive prompt parity is adapted to Codex App server-request semantics, not tmux session prompts. The supported prompt families are:
  - command approval
  - file-change approval
  - tool `requestUserInput`
- A dedicated `interactive_bridge.py` module owns prompt normalization, Telegram rendering, callback parsing, and multi-question answer assembly so daemon logic stays bounded.
- Pending prompt discovery is pulled from the live app-server stdio stream. `codex_api.py` captures supported JSON-RPC server requests, keeps them in-memory, and writes response payloads back on the same session when Telegram answers.
- Prompt view metadata is persisted in SQLite as `InteractivePromptViewState`, keyed by `chat_id + message_thread_id`, so the gateway can edit or clear the visible Telegram prompt message safely across normal polling and cleanup flows.
- Because app-server prompt requests are tied to the current live stdio session, restart persistence is intentionally limited to visible widget cleanup and stale-callback rejection. After a daemon restart, the old prompt is surfaced as expired with explicit guidance to continue from Codex App instead of trying to answer an already-broken server request.
- Text answers are accepted only for tool questions that actually request free text. Approval prompts and option-only tool questions require button clicks.

Test and verification notes:

- Red-phase tests were added first for:
  - prompt normalization for supported app-server methods
  - callback parsing for choice and `Other` flows
  - JSON-RPC prompt capture and response submission in `codex_api.py`
  - daemon rendering of approval widgets, in-place prompt progression, cleanup, stale-callback rejection, and free-text answer routing
  - end-to-end restart expiry behavior for a pending prompt widget
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_interactive_bridge.py tests/unit/test_codex_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -k "interactive or prompt"` -> `17 passed, 139 deselected`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `261 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/codex_api.py`: `34/36 = 94.4%`
  - `src/codex_telegram_gateway/daemon.py`: `92/122 = 75.4%`
  - `src/codex_telegram_gateway/models.py`: `8/8 = 100.0%`
  - `src/codex_telegram_gateway/ports.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `TOTAL`: `146/178 = 82.0%`

Code review notes:

- The main design constraint identified during proofread was session lifetime: a Telegram callback cannot safely answer a stale app-server request after restart. The implementation now marks those widgets expired instead of guessing.
- The proofread pass caught a routing bug where plain Telegram text could accidentally satisfy approval or option-only prompts. Those branches now reject plain text and direct the user to the Telegram buttons.
- The proofread pass also caught an input-type gap for text-only questions with image attachments. Those replies are now rejected cleanly with explicit guidance instead of being dropped silently.

### FP-20: Dedicated Status Bubble

Branch and merge:

- Feature branch: `feature/fp-20-dedicated-status-bubble`
- Feature commit: `ff1c6b8`
- Merge commit on `main`: `698ef7e`

Implementation decisions:

- FP-20 adds a dedicated `status_bubble.py` renderer and persistent `StatusBubbleViewState` rows in SQLite so every active topic can keep a single editable status-control message.
- The bubble is separate from assistant reply blocks and renders a normalized topic snapshot with:
  - project name
  - thread title
  - high-level state
  - queued inbound count
  - latest assistant-summary line
- The bubble reuses the existing `gw:resp:*` callbacks instead of inventing a second callback namespace. This keeps `New`, `Project`, `Status`, `Sync`, and recall behavior aligned with the existing reply-widget controls.
- Unlike the reply widget, the bubble keeps its main control row visible during active and approval states so the operator surface does not disappear while Codex is busy.
- Bubble rendering is cached per topic in-memory and persisted by `(chat_id, message_thread_id)` in SQLite. When Telegram says the tracked bubble message is gone, the daemon sends a new bubble and updates the persisted message id.
- Protocol-only changes in `ports.py` were kept as interface declarations only; the actual behavioral work lives in `daemon.py`, `state.py`, and `status_bubble.py`.

Test and verification notes:

- Red-phase tests were added first for:
  - status-bubble rendering
  - SQLite persistence of bubble view state
  - daemon create/update behavior
  - callback reuse from the bubble surface
  - end-to-end bubble recreation after local Telegram deletion
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_status_bubble.py tests/unit/test_state.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `163 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `266 passed`
- Feature-specific changed-statement coverage for tracked executable source diff:
  - `src/codex_telegram_gateway/daemon.py`: `56/70 = 80.0%`
  - `src/codex_telegram_gateway/models.py`: `6/6 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `src/codex_telegram_gateway/status_bubble.py`: `0/0 = 100.0%`
  - `TOTAL`: `74/88 = 84.1%`

Code review notes:

- The proofread pass found a stale-target bug in `sync_codex_once()`: a topic rename failure could mark a binding deleted but still leave the pre-rename binding object in `active_targets`, which then allowed bubble sync to run on a dead topic. `active_targets` is now populated only after rename reconciliation.
- The proofread pass also found a cleanup gap where `_unbind_topic()` left status-bubble view state behind. The unbind flow now drops bubble persistence and render cache along with the other topic-scoped UI state.
- A final robustness pass tightened the recreate path so a fallback `send_message()` failure after an edit failure still reuses the missing-topic detection path instead of silently leaving stale bubble state behind.

## Shared Architecture Changes

These apply across many features and should be built first.

### Shared design

- Extend `models.py` and `state.py` with:
  - `binding_status`
  - `topic_closed_at`
  - `topic_deleted_at`
  - `topic_status_message_id`
  - `topic_notification_mode`
  - `topic_toolbar_config`
  - `last_topic_title_source`
  - `last_recovery_action`
  - `last_summary_message_id`
- Extend `telegram_api.py` with:
  - topic close/reopen support
  - topic edit support for name and icon state
  - file send helpers
  - media edit helpers
  - command registration scopes
- Extend `codex_api.py` with:
  - thread rename
  - thread resume discovery
  - capability reporting
  - optional approval/interaction hooks if app-server supports them
- Split `daemon.py` into smaller modules once the feature count grows:
  - `topic_lifecycle.py`
  - `command_handlers.py`
  - `response_builder.py`
  - `interactive_bridge.py`
  - `media_bridge.py`

### Shared implementation plan

1. Add schema migrations in `state.py` for all new persisted fields.
2. Move large callback handling out of `daemon.py` into dedicated modules.
3. Introduce a normalized `TelegramUpdateEnvelope` model for text, media, callback, and topic service events.
4. Introduce a `TopicRuntimeState` snapshot object built from DB + live bridge state.
5. Add a `GatewayFeatureFlags` config section so risky features can ship dark.

### Shared test automation plan

- Unit tests:
  - migrations on an old DB
  - update normalization
  - state machine transitions
- Integration tests:
  - fake Telegram client + fake Codex bridge + SQLite state
  - callback flows across restart boundaries
- E2E tests:
  - long-lived daemon loop with fake clock
  - restart/recovery replay tests

## Topic Lifecycle and Sync Parity

### FP-01: Topic Close/Reopen Lifecycle

**Parity target**

Mirror `ccgram`’s handling of topic closure so a Telegram topic closing does not silently corrupt bindings.

**Dev design**

- Detect Telegram service updates for:
  - topic closed
  - topic reopened
  - topic deleted/unreachable
- Preserve the `codex_thread_id` binding when a topic is closed.
- Mark the binding as `closed` instead of deleting it.
- Suspend outbound sends for closed topics.
- Allow explicit recovery through `/restore` or auto-reopen policy when configured.

**Implementation plan**

1. Extend inbound polling to normalize topic lifecycle service messages.
2. Add `binding_status` enum: `active`, `closed`, `deleted`, `orphaned`.
3. On close event:
   - persist closed status
   - stop outbound message sends
   - clear typing heartbeat
4. On reopen event:
   - restore active status
   - trigger immediate sync
5. On send failure that implies deletion/not found:
   - mark binding `deleted`
   - queue recovery recommendation

**Test automation plan**

- Unit:
  - close event moves binding to `closed`
  - reopen event restores `active`
  - sends are skipped while closed
- Integration:
  - simulate close during active turn and verify no outbound send occurs
  - reopen and confirm buffered summary is sent once
- E2E:
  - topic closes mid-session, daemon restarts, `/restore` recreates or reopens correctly

### FP-02: Bidirectional Topic Rename Sync

**Parity target**

Like `ccgram`, topic title edits from Telegram should influence the backing runtime where safe.

**Dev design**

- Continue using topic title format `(<project>) <thread title>`.
- When Telegram renames a topic:
  - parse the project prefix and thread title suffix
  - if only thread title changed, call Codex thread rename
  - if project prefix changed, treat as metadata drift and restore canonical prefix unless explicit project rebinding is underway
- Add loop protection so a Codex-initiated rename does not trigger a second reverse rename.

**Implementation plan**

1. Add inbound handler for `forum_topic_edited`.
2. Add `last_topic_title_source` and `last_topic_title_hash` to state.
3. Implement rename parser:
   - canonical project prefix
   - freeform thread title suffix
4. Call `thread/set-name` through `codex_api.py` for valid user-driven thread title changes.
5. If title is malformed, restore the canonical topic name on next sync.

**Test automation plan**

- Unit:
  - parse valid and invalid renamed titles
  - ignore no-op rename loops
- Integration:
  - rename topic in Telegram and assert Codex thread title changes
  - rename Codex thread and assert Telegram updates once
- E2E:
  - rename from both sides in quick succession and verify the last writer wins cleanly

### FP-03: Topic Emoji/Status State

**Parity target**

Expose a lightweight runtime state in the topic itself, similar to `ccgram`’s lifecycle signaling.

**Dev design**

- Use Telegram topic edit capabilities to set icon emoji where permissions allow.
- Map gateway states to topic status:
  - idle
  - running
  - waiting approval
  - failed
  - closed
- If topic icon editing is unavailable, degrade to title-prefix-free operation and rely on the status bubble.

**Implementation plan**

1. Add a status-to-emoji mapping table in a new `topic_status.py`.
2. Cache chat-level permission failures to avoid repeated Telegram errors.
3. Update topic emoji only on state transition, not on every poll.
4. Add config to disable emoji sync per chat or globally.

**Test automation plan**

- Unit:
  - state transition to emoji mapping
  - suppression after permission error
- Integration:
  - fake Telegram edit failures are cached
  - successful state changes emit one topic edit
- E2E:
  - run idle -> running -> approval -> ready transitions and verify emoji change history

### FP-04: Lifecycle Sweeps, Topic Probing, Autoclose, Unbound TTL, Pruning

**Parity target**

Match `ccgram`’s periodic hygiene so stale bindings and dead topics do not accumulate.

**Dev design**

- Add one lifecycle sweep loop with independent intervals for:
  - topic reachability probe
  - unbound-topic TTL
  - idle-completed autoclose
  - stale DB row pruning
- Keep these sweeps idempotent and cheap.

**Implementation plan**

1. Add a `topic_lifecycle.py` module.
2. Persist timestamps:
   - `bound_at`
   - `last_seen_at`
   - `last_outbound_at`
   - `completed_at`
3. Probe topic existence by lightweight Telegram API call.
4. Close or archive stale topics only when configured.
5. Prune:
   - old history rows
   - stale callback state
   - orphaned topic picker state

**Test automation plan**

- Unit:
  - TTL threshold decisions with frozen time
  - prune helpers preserve live rows
- Integration:
  - dead topic is marked deleted and offered for recovery
  - unbound topic expires according to config
- E2E:
  - daemon running under fake clock performs sweeps at expected intervals

### FP-05: Multi-Chat Fanout and Telegram Flood-Control Backoff

**Parity target**

Support optional mirroring into more than one Telegram group and handle `RetryAfter` safely.

**Dev design**

- Generalize one binding into one primary topic plus zero or more mirrored topics.
- Add a creation work queue with per-chat rate limiting and persisted retry deadlines.
- Treat fanout as opt-in; keep single-chat as default.

**Implementation plan**

1. Create `topic_mirrors` table keyed by `codex_thread_id`.
2. Add `topic_creation_queue` table with `retry_after_at`.
3. Wrap create/edit operations in backoff-aware workers.
4. Update command surface to list per-chat mirrors.

**Test automation plan**

- Unit:
  - retry scheduling after `RetryAfter`
  - dedupe queued creates
- Integration:
  - one thread fans out to two chats without duplicate creation
- E2E:
  - flood-control simulation confirms retries resume automatically

## Commands and Dashboard Parity

### FP-06: `/history`

**Parity target**

Expose thread history paging directly in Telegram.

**Dev design**

- Build history from `thread/read` items rather than terminal transcript bytes.
- Render paginated summaries with callback buttons for next/prev.
- Include text, user messages, assistant summaries, and notable tool results.

**Implementation plan**

1. Add `history_command.py` and callback handlers.
2. Add rendering helpers that compress long items safely.
3. Persist current history page per topic callback context.
4. Hide or summarize binary-only items.

**Test automation plan**

- Unit:
  - page slicing
  - item summarization
- Integration:
  - `/history` on a thread with many items paginates correctly
- E2E:
  - callback paging survives a daemon restart

### FP-07: `/resume`

**Parity target**

Offer a Telegram-side picker for resumable Codex App threads in the current project.

**Dev design**

- Use Codex App store data to find recent or unloaded threads by project root.
- Group results by project, newest first.
- Rebind current topic to selected thread without creating a new topic.

**Implementation plan**

1. Extend `codex_api.py` with resumable-thread discovery.
2. Add `/resume` command and callback picker.
3. Validate project compatibility before rebinding.
4. On selection:
   - update binding
   - rename topic
   - mark existing history as seen

**Test automation plan**

- Unit:
  - thread listing and sorting
  - rebind validation
- Integration:
  - `/resume` switches a topic to an older thread and does not replay old messages
- E2E:
  - resume after restart into a non-loaded thread and verify outbound sync resumes

### FP-08: `/unbind`

**Parity target**

Allow explicit topic unbinding without deleting the Codex thread.

**Dev design**

- Unbind should:
  - remove active routing
  - preserve topic history for audit
  - preserve Codex thread existence
- The topic becomes eligible for project/thread rebinding via first-message or `/project`.

**Implementation plan**

1. Add `/unbind` command with confirmation callback.
2. Persist an audit row describing previous binding.
3. Clear active pending turns and status bubble state for the topic.
4. Show project picker on the next inbound message.

**Test automation plan**

- Unit:
  - unbind clears routing but keeps thread id in audit trail
- Integration:
  - after unbind, inbound message does not route until rebind
- E2E:
  - unbind during active session, then bind to a different thread cleanly

### FP-09: `/restore` and Rich Recovery Flows

**Parity target**

Go beyond deleted-topic recreation and offer guided recovery choices.

**Dev design**

- Recovery modes:
  - recreate topic and keep same thread
  - continue on current topic if only status drift exists
  - bind topic to another resumable thread in the same project
- Recovery should be offered through `/restore` and automatic inline prompts on detected failures.

**Implementation plan**

1. Create `recovery.py` and callback flows.
2. Add recovery state capture:
   - deleted topic
   - closed topic
   - missing thread
   - malformed binding
3. Reuse `/resume` picker where thread selection is needed.
4. Add clear operator messaging on what was repaired.

**Test automation plan**

- Unit:
  - recovery option generation by failure type
- Integration:
  - deleted topic is recreated and rebound without duplicate thread creation
- E2E:
  - simulate several failure modes and verify the right recovery keyboard is shown

### FP-10: `/upgrade`

**Parity target**

Provide a safe plugin-upgrade operator path, adapted from `ccgram`’s self-update command.

**Dev design**

- Because this is a Codex plugin, do not auto-run arbitrary `git pull`.
- `/upgrade` should:
  - show installed version
  - show marketplace source path
  - optionally stage a local reinstall script or print exact operator steps
- Keep this as diagnostics, not autonomous mutation, unless explicitly enabled.

**Implementation plan**

1. Add version and install-source discovery.
2. Add `/upgrade` command that renders current version and upgrade instructions.
3. Optionally add a guarded `--apply-local` mode for developer installs only.

**Test automation plan**

- Unit:
  - version/source discovery
- Integration:
  - `/upgrade` renders the correct local source paths
- E2E:
  - developer-mode local reinstall flow in a temp plugin cache

### FP-11: `/send` File Browser and Upload

**Parity target**

Match `ccgram`’s secure Telegram-side file browser for sending local files into the chat.

**Dev design**

- Reuse the project-root security model.
- Browsing starts at the bound project root, not arbitrary absolute paths.
- Support:
  - paginated browse
  - text search
  - file preview metadata
  - send as document or photo where appropriate

**Implementation plan**

1. Add `send_command.py`, `send_callbacks.py`, and `send_security.py`.
2. Reuse topic project/browser state already stored in SQLite.
3. Add text query parsing:
   - exact path relative to project root
   - glob
   - substring search
4. Add document/photo sending helpers in `telegram_api.py`.

**Test automation plan**

- Unit:
  - path containment checks
  - paging and search results
- Integration:
  - browsing and file selection send the correct file type
- E2E:
  - upload a project image and a text file from the browser into Telegram

### FP-11 verification
- Added a dedicated send-browser stack:
  - `send_security.py` for project-root containment checks, browse pagination, query search, and file preview metadata
  - `send_command.py` for Telegram inline-keyboard rendering
  - `send_callbacks.py` for compact callback parsing
- Added persisted `SendViewState` plus new `GatewayState`/`TelegramClient` interfaces so one active browser can be tracked safely per topic.
- Added outbound Telegram upload helpers in `telegram_api.py`:
  - `send_document_file`
  - `send_photo_file`
  - multipart form-data encoding for local file delivery
- Added `/gateway send` handling in the daemon with these flows:
  - bound primary topic only
  - root project browse
  - exact file preview
  - exact directory open
  - text-search fallback when the query is not a safe in-root path
  - inline callbacks for page, enter, preview, back, root, cancel, send document, and send photo
- Design decisions locked during implementation:
  - browser scope is strictly the bound project root; absolute-path browsing is intentionally unsupported
  - routing uses persisted `chat_id + message_thread_id + message_id` browser state and never relies on mutable topic titles or browser text
  - query resolution order is exact safe path first, then directory/file direct open, then search fallback
  - mirror topics remain conversation surfaces only, so `/gateway send` is blocked there like the other topic-management controls
- Proofread fixes landed before sign-off:
  - crafted negative callback indexes are rejected instead of using Python negative indexing into the listing
  - crafted preview callbacks that target a directory are rejected cleanly instead of crashing preview generation
  - send-browser state is cleared when rebinding a topic to a new thread and when unbinding a topic so stale inline keyboards cannot cross bindings
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_send_command.py tests/unit/test_send_security.py tests/unit/test_daemon.py tests/unit/test_state.py tests/unit/test_telegram_api.py tests/e2e/test_gateway_flow.py` -> `163 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `216 passed`
- Coverage verification:
  - feature-specific changed executable statements versus `main`: `197/223 = 88.3%`
  - `send_callbacks.py`: `20/20 = 100.0%`
  - `send_command.py`: `31/31 = 100.0%`
  - `send_security.py`: `85/92 = 92.4%`
  - `daemon.py` full-file regression coverage after the new tests: `1411/1720 = 82.0%`
  - `state.py` full-file regression coverage after the new tests: `330/343 = 96.2%`
  - `models.py` full-file regression coverage after the new tests: `134/134 = 100.0%`
- Feature branch: `feature/fp-11-send-file-browser-and-upload`
- Feature commit: `8a08655`
- Merge commit on `main`: `dea79a2`

### FP-12: `/toolbar` Configurable Action Bar

**Parity target**

Expose a compact keyboard of high-frequency actions similar to `ccgram`’s provider toolbar.

**Dev design**

- Toolbar config should be declarative and local, for example TOML or JSON.
- Buttons may map to:
  - gateway actions
  - pass-through slash commands
  - steer templates
- Toolbar must be per-topic or per-project overridable.

**Implementation plan**

1. Add `toolbar.py` and a small config loader.
2. Define button kinds:
   - `gateway_command`
   - `thread_text`
   - `steer_template`
3. Add `/toolbar` command and callback dispatch.
4. Persist the last rendered toolbar per topic for quick refresh.

**Test automation plan**

- Unit:
  - toolbar config parsing
  - callback encoding/decoding
- Integration:
  - toolbar actions route to the correct gateway or Codex flow
- E2E:
  - topic-specific toolbar override is rendered and remains stable across restart

### FP-13: `/verbose` and Notification Modes

**Parity target**

Give operators control over noise level like `ccgram`’s verbose/muted modes.

**Dev design**

- Per-topic notification modes:
  - `all`
  - `important`
  - `errors_only`
  - `muted`
- Gate:
  - typing indicator
  - tool-call updates
  - status bubble chatter
  - completion summaries

**Implementation plan**

1. Add `topic_notification_mode` to state.
2. Add `/verbose` command plus inline picker.
3. Thread all outbound-notification paths through one `should_emit()` helper.
4. Keep user/auth/system errors visible even when muted.

**Test automation plan**

- Unit:
  - mode gating matrix
- Integration:
  - same turn under each mode emits expected subset of messages
- E2E:
  - switch modes live and verify new behavior without restart

### FP-13 verification

- Added a dedicated `notification_modes.py` module for mode normalization, inline-picker rendering, callback parsing, and the notification gating matrix.
- Added `/gateway verbose` plus inline callbacks so each topic can switch between `all`, `important`, `errors_only`, and `muted` without restart.
- The gateway now routes supplemental Telegram chatter through a single notification gate:
  - typing indicators
  - failure/interruption notices
  - session/status dashboard labels
- Assistant replies are intentionally never muted in this port. Unlike `ccgram`, Telegram is the primary conversation surface here, so notification modes only suppress supplemental chatter rather than the actual response stream.
- Proofread findings and fixes:
  - normalized legacy persisted values so `assistant_plus_alerts` reads back as `all`
  - normalized legacy `assistant_only` to `important`
  - ensured mirror topics can still use `/gateway verbose` because the mode is topic-local, not a project-management action
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_notification_modes.py tests/unit/test_daemon.py tests/unit/test_sessions_dashboard.py tests/e2e/test_gateway_flow.py` -> `154 passed`
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `244 passed`
- Feature-specific changed-statement coverage for tracked source diff is `40/48 = 83.3%`.

### FP-14: `/screenshot`

**Parity target**

Provide a Telegram-triggered visual snapshot of the current Codex App thread.

**Dev design**

- macOS-only adapter using `screencapture`, AppleScript, or Codex App window capture.
- Scope should be explicit:
  - whole Codex window
  - frontmost thread region if detectable
- Avoid blocking the main poller while taking screenshots.

**Implementation plan**

1. Define `ScreenshotProvider` interface.
2. Add macOS implementation in `screenshot_capture.py`.
3. Add `/screenshot` command.
4. Send captured image as photo or document depending on size.

**Test automation plan**

- Unit:
  - command flow using fake screenshot provider
- Integration:
  - screenshot send path with fake image bytes
- E2E:
  - manual macOS test in CI notes; automated test only validates adapter contract

### FP-15: `/panes` Compatibility

**Parity target**

Provide a compatibility answer for a tmux-only command.

**Dev design**

- Codex App has no pane model.
- Implement `/panes` as a compatibility command that shows:
  - loaded threads in the current project
  - current bound thread
  - explanation that pane-level controls are unsupported in app mode

**Implementation plan**

1. Add `/panes` alias to a compatibility handler.
2. Reuse loaded-thread discovery and bindings view.
3. Keep wording explicit so users do not expect tmux-like controls.

**Test automation plan**

- Unit:
  - compatibility message rendering
- Integration:
  - `/panes` in a bound topic shows loaded threads instead of erroring

### FP-16: `/recall`

**Parity target**

Expose explicit command-driven recall of recent topic messages, not only reply-widget shortcuts.

**Dev design**

- Reuse persisted `topic_history`.
- Adapt recall by payload type:
  - text-only entries use Telegram inline query so the user can edit before sending, matching the most useful `ccgram` behavior
  - entries with local image attachments reuse the existing replay callback so attachments are preserved
- Keep the top-level recall prompt stateless:
  - no extra view-state table
  - close action only clears reply markup

**Implementation plan**

1. Add `recall_command.py` for shared history-label rendering plus top-level recall prompt rendering.
2. Add `/gateway recall` command.
3. Reuse existing `gw:resp:recall:*` callback handling for image-bearing history entries.
4. Reuse inline query support for text-only entries so they stay editable before resend.

**Test automation plan**

- Unit:
  - history label generation and truncation
  - text-only versus image-bearing button rendering
  - empty-history and dismiss-callback handling
- Integration:
  - `/gateway recall` renders persisted topic history correctly
- E2E:
  - top-level recall command renders mixed text/image history into Telegram

### FP-16 verification

- Branch and merge:
  - feature branch `feature/fp-16-top-level-recall-flow`
- Reviewed `ccgram` recall references before implementation:
  - `src/ccgram/handlers/command_history.py`
  - `src/ccgram/tests/handlers/test_command_history.py`
- Added `recall_command.py` so the top-level recall flow has one shared rendering layer for:
  - truncated history labels
  - inline-query buttons for text-only history
  - callback replay buttons for image-bearing history
  - dismiss callback parsing
- `GatewayDaemon` now exposes `/gateway recall` and renders the most recent topic history into a dedicated Telegram message instead of limiting recall to the two shortcut buttons on reply/status widgets.
- Implementation decisions locked during FP-16:
  - text-only recall uses inline query because it matches `ccgram` and lets operators edit before resending
  - image-bearing recall intentionally stays on the existing callback replay path so local image attachments are preserved
  - the feature stays stateless because topic history is already persisted and the top-level recall prompt does not need its own long-lived topic binding
- Proofread fixes before sign-off:
  - label truncation now preserves the image-count suffix instead of truncating it away
  - adding `/gateway recall` to the gateway command set required reordering inline-query suggestions so pass-through commands like `/status` remain visible within the capped result set
  - help output and command discovery text were updated to include the new recall command
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_recall_command.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -k "recall"` -> `7 passed, 163 deselected`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `323 passed`
- Feature-specific changed-code coverage:
  - `src/codex_telegram_gateway/recall_command.py`: `33/36 = 91.7%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `21/24 = 87.5%`
  - `TOTAL`: `54/60 = 90.0%`

### FP-17: Command Discovery and Telegram Menu Sync

**Parity target**

Move beyond a static menu and align Telegram commands with actual supported features.

**Dev design**

- Maintain one generated command catalog from feature flags and bridge capabilities.
- Allow chat-scoped and global registration.
- Include compatibility aliases where needed.
- For Codex pass-through commands, optionally expose a configured catalog of known slash commands.

**Implementation plan**

1. Create `commands_catalog.py`.
2. Build menu from:
   - enabled gateway features
   - platform capabilities
   - operator config
3. Re-register commands on startup and after config changes.
4. Record last registered hash to avoid repeated Bot API writes.

**Test automation plan**

- Unit:
  - command catalog under different feature flags
- Integration:
  - set-my-commands called only when catalog changes
- E2E:
  - plugin restart updates Telegram menu correctly

### FP-18: Full Sessions Dashboard

**Parity target**

Reach `ccgram`-style operator visibility over all active bindings.

**Dev design**

- `/sessions` should show:
  - topic title
  - project
  - thread title
  - thread status
  - notification mode
  - recovery warnings
- Action row per session:
  - refresh
  - new thread
  - unbind
  - screenshot
  - restore

**Implementation plan**

1. Replace the current lightweight bindings dashboard.
2. Add callback handlers for the action set.
3. Add dashboard pagination when bindings exceed Telegram message limits.
4. Make dashboard rows resilient to missing/deleted topics.

**Test automation plan**

- Unit:
  - dashboard rendering and pagination
- Integration:
  - session action buttons dispatch correctly
- E2E:
  - dashboard reflects live status changes without manual refresh drift

### FP-18 verification
- Added a dedicated `sessions_dashboard.py` renderer/parser module for:
  - paginated dashboard text
  - per-session action rows
  - callback parsing
  - unbind-confirm prompt rendering
- Replaced the old lightweight bindings view with a full sessions dashboard that now shows:
  - topic title
  - project
  - current thread title
  - thread id and topic id
  - thread status
  - notification mode
  - recovery warnings
  - mirror details
  - pending mirror-topic creation jobs
- Added dashboard actions for:
  - refresh
  - new thread
  - unbind with confirmation
  - restore
  - screenshot compatibility messaging
  - page navigation
- Design decisions locked during implementation:
  - dashboard actions always route by persisted `chat_id + message_thread_id`, never by mutable topic titles
  - restore from the dashboard is a direct app-native repair action instead of reusing the topic-local restore widget, because the dashboard message can live in a different Telegram topic
  - screenshot is exposed as an explicit compatibility stub until FP-14 lands rather than pretending media capture exists already
  - mirror-detail lines and pending mirror-job lines were preserved in the new dashboard so the richer view stays a strict superset of the previous operator visibility
- Proofread fixes landed before sign-off:
  - removed stale legacy session-dashboard constants/helpers left over from the pre-FP-18 implementation
  - simplified impossible callback branches that were already prevented by the session callback parser
  - restored mirror-detail and pending-job text after the first full-suite regression exposed that the richer dashboard had accidentally dropped them
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_sessions_dashboard.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -k "sessions_dashboard or bindings_shows_dashboard or lists_mirrors_and_pending_jobs or status_icons_and_warnings"` -> `16 passed`
- Full suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `175 passed`
- Feature-specific coverage for tracked FP-18 source ranges:
  - `daemon.py` FP-18 ranges: `133/146 = 91.1%`
  - `sessions_dashboard.py`: `77/84 = 91.7%`

## Runtime Interaction Parity

### FP-19: Generic Interactive Prompt Bridge

**Parity target**

Support Telegram-side response widgets for Codex prompts that need user choice or text answers.

**Dev design**

- Introduce an abstraction over Codex interactive states:
  - approval request
  - multiple-choice request
  - free-text question
  - plan-mode exit/continue style prompt if surfaced by app-server
- Render Telegram inline keyboards where choices exist.
- If app-server lacks a write-back API for a prompt type, fall back to status + instructions rather than pretending support exists.

**Implementation plan**

1. Audit app-server support for prompt discovery and response submission.
2. Add `interactive_bridge.py` with normalized prompt model.
3. Extend `codex_api.py` with capability probes and optional submit methods.
4. Add callback handlers for supported prompt types.
5. Keep prompt state persisted so Telegram callbacks survive restart.

**Test automation plan**

- Unit:
  - prompt normalization
  - callback encoding and stale-state handling
- Integration:
  - fake approval prompt can be accepted/denied from Telegram
- E2E:
  - blocked turn shows prompt keyboard; callback resolves turn and clears typing

### FP-19 verification

- Branch and merge:
  - feature branch `feature/fp-19-generic-interactive-prompt-bridge`
  - feature commit `c69624b`
  - merge commit on `main` `18e7272`
- Added a dedicated `interactive_bridge.py` module for:
  - app-server prompt normalization
  - Telegram prompt rendering
  - callback parsing
  - multi-question answer collection
- Added Codex bridge support for three prompt families only:
  - `item/commandExecution/requestApproval`
  - `item/fileChange/requestApproval`
  - `item/tool/requestUserInput`
- Added persisted `InteractivePromptViewState` rows in SQLite and wired them through the gateway state/port interfaces so one active prompt widget per topic can be tracked and cleaned up safely.
- The daemon now:
  - discovers pending app-server prompts during normal sync
  - renders inline approval and multiple-choice keyboards in Telegram
  - accepts free-text answers for text questions
  - submits the normalized JSON-RPC response back to Codex App
  - clears stale prompt widgets on terminal-turn, rebind, new-thread, unbind, and restart-expired paths
- Implementation decisions locked during FP-19:
  - prompt routing is keyed by persisted topic identity and prompt id, never by mutable topic title text
  - app-server interactive prompts are tied to the live stdio session, so after a gateway restart the Telegram widget is marked expired instead of pretending the old server request can still be answered safely
  - unsupported prompt families such as permission approvals and MCP elicitation are intentionally left unsupported until the bridge can model them correctly
- Proofread fixes landed before sign-off:
  - free-text Telegram replies no longer accidentally answer approval prompts or option-only prompt steps; those now instruct the user to use the prompt buttons
  - text-only tool questions now reject image replies cleanly instead of silently consuming them
  - prompt reply markup is cleared during cleanup so stale approval buttons do not linger after the turn becomes healthy again
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_interactive_bridge.py tests/unit/test_codex_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py -k "interactive or prompt"` -> `17 passed, 139 deselected`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `261 passed`
- Feature-specific changed-statement coverage for tracked source diff:
  - `src/codex_telegram_gateway/codex_api.py`: `34/36 = 94.4%`
  - `src/codex_telegram_gateway/daemon.py`: `92/122 = 75.4%`
  - `src/codex_telegram_gateway/models.py`: `8/8 = 100.0%`
  - `src/codex_telegram_gateway/ports.py`: `0/0 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `TOTAL`: `146/178 = 82.0%`

### FP-20: Dedicated Status Bubble

**Parity target**

Provide a single per-topic status message that updates in place instead of scattering control state across reply widgets.

**Dev design**

- One status message per topic.
- Status bubble includes:
  - current thread/project
  - running/idle/approval/failed state
  - queued count
  - latest summary
  - control buttons
- Assistant reply widgets remain, but the status bubble becomes the main operator surface.

**Implementation plan**

1. Add `topic_status_message_id` to state.
2. Build `status_bubble.py` renderer.
3. Ensure only one status message exists per topic; recreate if deleted.
4. Update bubble on state transition, not every poll tick.

**Test automation plan**

- Unit:
  - status bubble render matrix
- Integration:
  - bubble created once and then edited in place
- E2E:
  - delete the status message in Telegram and verify it is recreated on next transition

### FP-20 verification

- Branch and merge:
  - feature branch `feature/fp-20-dedicated-status-bubble`
  - feature commit `ff1c6b8`
  - merge commit on `main` `698ef7e`
- Added a dedicated `status_bubble.py` renderer with a normalized `StatusBubbleSnapshot` model and a persistent `StatusBubbleViewState` SQLite row per topic.
- The new status bubble is a separate Telegram control message from assistant reply blocks and shows:
  - project name
  - current thread title
  - normalized topic state (`ready`, `running`, `approval`, `failed`, `closed`)
  - queued inbound count for the bound Codex thread
  - latest assistant-summary line when one exists
- The bubble reuses the existing `gw:resp:*` callbacks instead of introducing a second control protocol, and its control row stays visible during running and approval states rather than disappearing until idle.
- Implementation decisions locked during FP-20:
  - bubble state is persisted by `(chat_id, message_thread_id)` and edited in place whenever the rendered snapshot changes
  - assistant reply widgets remain on assistant messages, but the dedicated bubble becomes the stable topic-level operator surface
  - bubble rendering is skipped for deleted bindings and recreated automatically if Telegram reports that the tracked bubble message was removed
- Proofread fixes landed before sign-off:
  - fixed a stale-target bug where a topic rename failure that marked a binding deleted could still flow into the bubble sync pass using the pre-rename active binding object
  - unbind now clears persisted bubble view state and render cache so detached topics do not keep an active bubble binding internally
  - the recreate-on-edit-failure path now rechecks missing-topic errors on the fallback send path instead of assuming only the first edit can fail
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_status_bubble.py tests/unit/test_state.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `163 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `266 passed`
- Feature-specific changed-statement coverage for tracked executable source diff:
  - `src/codex_telegram_gateway/daemon.py`: `56/70 = 80.0%`
  - `src/codex_telegram_gateway/models.py`: `6/6 = 100.0%`
  - `src/codex_telegram_gateway/state.py`: `12/12 = 100.0%`
  - `src/codex_telegram_gateway/status_bubble.py`: `0/0 = 100.0%`
  - `TOTAL`: `74/88 = 84.1%`
- Coverage note:
  - `ports.py` changed only in `Protocol` interface declarations for the new status-bubble view methods, so those non-behavioral signatures were excluded from the executable changed-line denominator for FP-20 coverage accounting

### FP-21: Tool Batching, Failure Probing, Completion Summaries

**Parity target**

Make Telegram output concise and informative during long Codex runs.

**Dev design**

- Parse Codex thread items into:
  - assistant text blocks
  - tool invocations
  - tool results
  - terminal failure/success signals
- Batch adjacent tool calls into one compact status update.
- Emit a short completion summary when a turn finishes.

**Implementation plan**

1. Add `response_builder.py`.
2. Define batching heuristics:
   - contiguous tool sequence
   - max message length
   - meaningful status icons
3. Add failure probing heuristics from tool results and command exits.
4. Add end-of-turn summary builder.

**Test automation plan**

- Unit:
  - tool batching and summarization
  - failure/success classification
- Integration:
  - mixed assistant/tool sequences render as expected
- E2E:
  - long run with many tool calls produces compact output instead of message spam

### FP-21 verification

- Branch and merge:
  - feature branch `feature/fp-21-tool-batching-failure-probing-completion-summaries`
  - feature commit `20d8a36`
  - merge commit on `main` `4772ea0`
- Added a dedicated `response_builder.py` normalization layer for Codex App `thread/read` turns so Telegram can render more than raw assistant text:
  - contiguous `commandExecution` items now collapse into stable `tool_batch` events
  - terminal turns without a final assistant reply now emit a dedicated `completion_summary` event
  - command failure/success state is inferred from exit codes plus interesting output-line heuristics
- `CodexAppServerClient.list_events()` now delegates to the response builder, so the daemon receives a replayable outbound event stream instead of only assistant blocks.
- The daemon now treats `tool_batch` and `completion_summary` as first-class outbound events, which means:
  - long command-heavy turns edit a single Telegram message as the batch grows
  - tool-only turns still end with a concise terminal message instead of going silent
  - the status bubble can surface the latest meaningful summary even when no assistant message exists
- Replay logic for recreated topics now uses the latest visible event, not only the latest assistant event, so tool-batch and completion-summary output can be recovered after topic recreation.
- Implementation decisions locked during FP-21:
  - Codex App does not expose `ccgram`’s raw `tool_use` and `tool_result` transcript blocks, so this gateway adapts parity through `commandExecution` batching rather than pretending the tmux transcript model exists
  - a dedicated completion-summary event suppresses the old generic terminal failure alert for that turn to keep Telegram output concise
  - terminal summaries are emitted whenever the last rendered item in the turn is not an assistant reply, even if an earlier assistant planning note appeared before the final command batch
- Proofread fixes landed before sign-off:
  - failure probing now prefers concrete lines like `AssertionError: boom` over vague first-line summaries such as `tests failed`
  - completion-summary suppression was corrected so turns with an early assistant note and a final command batch still emit a terminal summary
  - the daemon keeps Telegram’s send/edit contract intact by applying inline widgets through reply-markup edits instead of changing the outbound text-delivery path
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_response_builder.py tests/unit/test_codex_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `164 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `274 passed`
- Feature-specific changed-executable coverage for FP-21 source work:
  - `src/codex_telegram_gateway/response_builder.py`: `117/138 = 84.8%`
  - `src/codex_telegram_gateway/codex_api.py` changed executable lines: `2/2 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `14/14 = 100.0%`
  - `src/codex_telegram_gateway/service.py` changed executable lines: `5/5 = 100.0%`
  - `TOTAL`: `138/159 = 86.8%`

### FP-22: Live View

**Parity target**

Offer an auto-refreshing visual stream similar to `ccgram`’s live mode.

**Dev design**

- Build on the screenshot adapter from FP-14.
- Maintain one live-view message per topic using `editMessageMedia`.
- Add stop/refresh controls.

**Implementation plan**

1. Add `live_view.py` with interval scheduler.
2. Store live-view message id and refresh state in DB.
3. Add `/live` or `/screenshot live` entry point.
4. Pause live view automatically when topic is muted or closed.

**Test automation plan**

- Unit:
  - live-view state transitions
- Integration:
  - repeated refresh edits the same Telegram message
- E2E:
  - manual macOS capture verification plus automated scheduler test

### FP-23: Remote Control Actions

**Parity target**

Bring over the most useful operator actions from `ccgram` where Codex App supports them.

**Dev design**

- Candidate actions:
  - stop current turn
  - steer with canned text
  - continue
  - retry last user message
  - answer current approval prompt
- Do not emulate arrow keys blindly; only implement actions backed by Codex APIs.

**Implementation plan**

1. Add capability-gated remote control buttons to the status bubble.
2. Extend `codex_api.py` with stop/retry if app-server exposes them.
3. Map unsupported actions to hidden buttons, not broken callbacks.

**Test automation plan**

- Unit:
  - capability gating
- Integration:
  - supported actions dispatch to the fake Codex bridge correctly
- E2E:
  - stop or retry from Telegram changes live thread state

## Media and Content Parity

### FP-24: General File Intake and Unsupported-Content UX

**Parity target**

Handle more than text and images on inbound Telegram messages.

**Dev design**

- Accept:
  - documents
  - text files
  - PDFs
  - audio/video as saved files plus descriptive prompt text
- Save inbound files under the gateway-local `.ccgram-uploads` directory with stable absolute paths.
- When Codex cannot ingest a raw media type directly, submit a companion text prompt with the saved path.
- Reply explicitly for unsupported content types instead of silently ignoring them.
- Keep direct images on the native `local_image_paths` path so existing image delivery to Codex App does not regress.

**Implementation plan**

1. Add `media_ingest.py` for user-facing prompt and unsupported-media notice rendering.
2. Extend `telegram_api.py` routing:
   - keep photos and image-documents on `local_image_paths`
   - download non-image documents/audio/video into `.ccgram-uploads`
   - synthesize a descriptive text prompt that includes the saved absolute path
   - normalize unsupported content into an explicit `unsupported_message` update
3. Reuse the existing inbound queue shape instead of expanding the DB schema:
   - image input remains `local_image_paths`
   - non-image attachments become text-only inbound prompts
4. Handle unsupported inbound media in `daemon.py` by replying immediately in-topic and skipping the Codex queue.
5. Keep the existing Telegram download size limit and current one-media-object-per-message normalization behavior.

**Test automation plan**

- Unit:
  - media prompt text for PDF/audio/video/text/generic files
  - unsupported notice wording for sticker, voice, and generic unsupported content
  - Telegram MIME/type routing helpers and generated attachment naming
- Integration:
  - PDF/document message creates queued Codex input with saved file path
  - unsupported content produces an immediate Telegram notice without queueing
- E2E:
  - send a supported document into a bound topic and verify the saved-path prompt reaches Codex

### FP-24 verification

- Branch and merge:
  - feature branch `feature/fp-24-general-file-intake-and-unsupported-content-ux`
  - feature commit `9bf226f`
  - merge commit on `main` `e69c4c8`
- Added `media_ingest.py` so inbound non-image attachments have one normalization layer for:
  - saved-attachment prompt text
  - supported media wording differences between PDF, text, audio, video, and generic documents
  - explicit unsupported-media notices
- `TelegramBotClient.get_updates()` now preserves the pre-existing direct image path for photos and image-documents, and adds a second inbound path for:
  - non-image documents
  - audio
  - video
  - unsupported Telegram content such as stickers, voice notes, and generic non-ingestable payloads
- Implementation decisions locked during FP-24:
  - Codex App currently supports native local-image inputs but not raw local document/audio/video attachments, so parity is adapted by downloading those files locally and passing an explicit absolute-path prompt to the thread
  - attachment metadata is intentionally not persisted in a new DB table for this feature; the saved-path prompt text is the durable handoff into the existing inbound queue
  - uploads currently land in gateway-local `.ccgram-uploads` rather than per-project storage because the gateway owns Telegram download state independently of Codex App project internals
- Proofread decisions and fixes before sign-off:
  - kept image handling untouched so FP-24 could not break the already-working photo flow
  - added explicit unsupported-user notices rather than silently dropping stickers, voice notes, or other non-ingestable Telegram payloads
  - rejected unauthorized unsupported-media updates before sending notices back to Telegram so the new UX does not widen the existing trust boundary
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_media_ingest.py tests/unit/test_telegram_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `176 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `288 passed`
- Feature-specific changed-executable coverage for FP-24 source work:
  - `src/codex_telegram_gateway/media_ingest.py`: `25/25 = 100.0%`
  - `src/codex_telegram_gateway/telegram_api.py` changed executable lines: `68/68 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `7/7 = 100.0%`
  - `TOTAL`: `100/100 = 100.0%`

### FP-25: Outbound Media and File Delivery

**Parity target**

Send generated screenshots, artifacts, and files from Codex back into Telegram.

**Dev design**

- Detect artifact candidates from:
  - Codex outbound text that explicitly references generated local files
  - tool outputs that mention saved/exported paths
- Send:
  - images as photos
  - binaries/text as documents
- Avoid exfiltrating arbitrary local files outside:
  - the bound project root
  - the gateway-local `.ccgram-uploads`
- Keep text-message syncing unchanged by emitting separate artifact events instead of overloading assistant/tool message editing.

**Implementation plan**

1. Add `artifact_detector.py`.
2. Expand `CodexAppServerClient.list_events()` so each assistant/tool/completion event can emit sibling artifact events when a safe local path is detected.
3. Extend the normalized `CodexEvent` model with optional `file_path` so artifact events can route through the same seen-event and outbound-message persistence.
4. Deliver artifact events from the daemon with:
   - `sendPhoto` for image-like files
   - `sendDocument` for everything else
5. Keep artifact captions short and path-based so the textual summary remains in the regular message stream.

**Test automation plan**

- Unit:
  - artifact detection for project-root and `.ccgram-uploads` paths
  - unsafe/non-signal path rejection
  - `thread/read` expansion into stable artifact events
  - daemon send-once behavior plus missing-file and send-failure edge cases
- Integration:
  - image and text artifact delivery through the daemon event-sync flow
- E2E:
  - append an artifact event to a bound thread and verify Telegram receives the file upload

### FP-25 verification

- Branch and merge:
  - feature branch `feature/fp-25-outbound-media-and-file-delivery`
  - feature commit `cfee857`
  - merge commit on `main` `851f48a`
- Reviewed `ccgram` outbound-file references before implementation:
  - `src/ccgram/handlers/send_command.py::_upload_file()` for the photo-versus-document split
  - `src/ccgram/handlers/screenshot_callbacks.py` for document upload behavior from generated bytes
- Added `artifact_detector.py` so outbound Codex text can be scanned for explicit saved/exported file paths and expanded into stable attachment events.
- `CodexAppServerClient.list_events()` now appends artifact events after the base assistant/tool/completion event, which keeps:
  - the existing text-message edit flow intact
  - artifact delivery idempotent via the existing seen-event bookkeeping
- Implementation decisions locked during FP-25:
  - Codex App `thread/read` does not currently expose first-class outbound attachment objects for generated files, so parity is adapted by detecting explicit file paths in the normalized outbound text
  - the allowlist is intentionally strict for this feature:
    - the bound project root
    - the gateway-local `.ccgram-uploads`
  - captions stay short and path-based because the conversational summary already ships in the adjacent assistant/tool message
- Proofread fixes before sign-off:
  - leading-dot path cleanup was corrected so `.ccgram-uploads/...` artifacts are not accidentally stripped and dropped
  - artifact sends now have explicit behavior for all three important failure cases:
    - missing file: skip without marking the event seen
    - missing topic: mark the binding deleted
    - unexpected Telegram failure: re-raise instead of hiding it
  - helper doubles used by unit and end-to-end tests now preserve `CodexEvent.file_path` during event replacement so artifact events remain stable under edits
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_artifact_detector.py tests/unit/test_codex_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `172 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `296 passed`
- Feature-specific changed-executable coverage for FP-25 source work:
  - `src/codex_telegram_gateway/artifact_detector.py`: `96/101 = 95.0%`
  - `src/codex_telegram_gateway/codex_api.py` changed executable lines: `7/7 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `25/25 = 100.0%`
  - `src/codex_telegram_gateway/models.py` changed executable lines: `1/1 = 100.0%`
  - `TOTAL`: `129/134 = 96.3%`

### FP-26: Voice Transcription Flow

**Parity target**

Match `ccgram`’s voice-message workflow with confirm/discard behavior.

**Dev design**

- Normalize Telegram voice notes into a dedicated `voice_message` update kind instead of routing them through the generic unsupported-media path.
- Keep transcription pluggable with an explicit provider boundary:
  - OpenAI-compatible HTTP providers for `openai` and `groq`
  - config-driven defaults for base URL, model, API key, and optional language
- Persist one active voice-confirmation widget per topic so callback routing survives daemon restart and cannot drift across threads.
- Reuse the existing queue and project-picker flows:
  - bound topic: confirmed transcript becomes a normal queued inbound Codex message
  - unbound topic: confirmed transcript opens the existing project picker with `pending_text`

**Implementation plan**

1. Add `voice_ingest.py`:
   - `TranscriptionProvider`
   - `TranscriptionResult`
   - OpenAI-compatible multipart transcription client
   - voice prompt rendering and callback parsing helpers
2. Extend gateway config, normalized models, and persistence:
   - add voice-transcription env vars to `GatewayConfig`
   - add `VoicePromptViewState`
   - persist voice prompt state in SQLite and the state protocol
3. Extend `telegram_api.py` voice intake:
   - download Telegram voice files into `.ccgram-uploads`
   - generate stable `.ogg` filenames
   - emit `voice_message` updates with local file paths
4. Wire `daemon.py` voice handling:
   - transcribe on receipt
   - show confirm/discard widget
   - on confirm, queue transcript or open the project picker
   - on discard, clear the widget state cleanly
5. Clear voice prompt state anywhere topic/thread ownership changes:
   - resume/rebind
   - bind-to-project
   - new-thread creation
   - unbind
   - deleted/missing Telegram topic handling

**Test automation plan**

- Unit:
  - voice prompt rendering and callback parsing
  - provider construction defaults and unknown-provider rejection
  - OpenAI-compatible multipart request generation and transcript parsing
  - SQLite voice-prompt persistence
  - Telegram voice download normalization
  - daemon confirm/discard and bound/unbound callback routing
- Integration:
  - fake transcriber returns a transcript and the daemon routes the confirmed text into the existing inbound queue
- E2E:
  - send a voice update into a topic, confirm the transcription widget, and verify the resulting transcript reaches the Codex thread

### FP-26 verification

- Branch and merge:
  - feature branch `feature/fp-26-voice-transcription-flow`
  - feature commit `040e4c0`
  - merge commit on `main` `9dc93ae`
- Reviewed `ccgram` voice-handling references before coding the parity path:
  - `src/ccgram/handlers/voice_handler.py`
  - `src/ccgram/handlers/voice_callbacks.py`
  - `src/ccgram/whisper/base.py`
  - `src/ccgram/whisper/__init__.py`
- Added `voice_ingest.py` so the voice-note parity path has one focused module for:
  - provider selection
  - OpenAI-compatible multipart uploads
  - confirm/discard widget rendering
  - callback parsing
- `TelegramBotClient.get_updates()` now downloads Telegram voice notes into `.ccgram-uploads` and emits dedicated `voice_message` updates instead of folding them into unsupported-media notices.
- `GatewayDaemon` now:
  - transcribes inbound voice notes through an injected or config-built transcriber
  - sends a confirm/discard widget into the same Telegram topic
  - persists one `VoicePromptViewState` per topic
  - routes confirmed transcripts either into the bound Codex thread queue or into the existing project-picker flow for unbound topics
- Implementation decisions locked during FP-26:
  - the gateway does not auto-submit transcripts; it matches `ccgram`’s explicit user-confirmation model
  - provider support is intentionally narrow for now:
    - `openai`
    - `groq`
    - other providers fail fast instead of silently degrading
  - unbound-topic voice notes intentionally reuse the existing project picker instead of introducing a second binding UX
  - only one active voice prompt is kept per topic to avoid stale callback routing
- Proofread fixes before sign-off:
  - stale voice prompt state is now cleared on resume, project rebind, new-thread creation, unbind, and deleted-topic cleanup so a transcript cannot land in the wrong Codex thread after topic ownership changes
  - voice download routing now runs before the generic attachment/unsupported path so voice notes are not silently swallowed by the broader media normalization logic
  - the multipart transcription request now writes explicit `Authorization` and `Content-Type` headers onto the `urllib` request object so the upload contract is stable and testable
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_voice_ingest.py tests/unit/test_config.py tests/unit/test_state.py tests/unit/test_telegram_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `210 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `306 passed`
- Feature-specific module coverage report:
  - `src/codex_telegram_gateway/voice_ingest.py`: `64/72 = 88.9%`
  - `src/codex_telegram_gateway/config.py`: `95/103 = 92.2%`
  - `src/codex_telegram_gateway/state.py`: `366/379 = 96.6%`
  - `src/codex_telegram_gateway/models.py`: `158/158 = 100.0%`
  - targeted changed-module set total: `2658/3199 = 83.1%`

### FP-27: Inline Query Support

**Parity target**

Support Telegram inline-query insertion as a fast way to send prepared text back into the current chat, matching the practical `ccgram` use case behind `switch_inline_query_current_chat`.

**Dev design**

- Keep the scope intentionally narrow and text-only:
  - echo the typed inline query as a sendable result
  - suggest matching gateway commands
  - suggest matching observed pass-through Codex commands
- Do not expose:
  - raw thread history
  - project ids or filesystem paths
  - direct control actions that would bypass existing topic-scoped callbacks

**Implementation plan**

1. Add `inline_query.py` with a small result builder for:
   - echo-text insertions
   - gateway command suggestions
   - remembered pass-through command suggestions
2. Extend the Telegram transport:
   - request `inline_query` updates from `getUpdates`
   - normalize inline-query updates
   - implement `answerInlineQuery`
3. Route inline queries through the daemon:
   - gate by authorized user id
   - answer with personal, no-cache results
4. Reuse existing pass-through command learning so inline suggestions reflect the Codex commands already seen in this gateway.

**Test automation plan**

- Unit:
  - result building, duplicate suppression, blank/slash-only edge cases, and max-result capping
  - Telegram inline-query normalization and `answerInlineQuery` payload encoding
  - daemon handling for authorized and unauthorized inline queries
- Integration:
  - fake inline query returns the expected sendable result set through the daemon
- E2E:
  - submit an inline query against the fake Telegram transport and verify the returned results include both the echo article and matching commands

### FP-27 verification

- Branch and merge:
  - feature branch `feature/fp-27-inline-query-support`
  - feature commit `bd51493`
  - merge commit on `main` `b9f368f`
- Reviewed `ccgram` inline-query references before implementation:
  - `src/ccgram/bot.py::inline_query_handler()`
  - `src/ccgram/handlers/command_history.py`
- Added `inline_query.py` so inline-query behavior is isolated from the main daemon flow and stays limited to safe text-insert result generation.
- `TelegramBotClient.get_updates()` now requests and normalizes `inline_query` updates, and the transport implements `answerInlineQuery`.
- `GatewayDaemon` now:
  - recognizes `inline_query` updates before topic-bound message routing
  - gates them by the same allowed-user list as the rest of the gateway
  - answers with personal, zero-cache results built from the current query text and remembered pass-through commands
- Implementation decisions locked during FP-27:
  - the feature is intentionally narrower than the original broad idea of project/binding search because Telegram inline query is best suited to safe text insertion, not stateful topic selection
  - current parity scope is:
    - echo typed text
    - gateway command suggestions
    - pass-through Codex command suggestions
  - project picking, binding recovery, and history replay remain on the existing callback-driven topic UI instead of being duplicated in inline query results
- Proofread fixes before sign-off:
  - duplicate suppression prevents `/status` from appearing twice when the raw query already matches a suggested command
  - slash-only queries now behave as a safe “show me suggestions” case instead of collapsing into an empty query
  - malformed inline-query updates without a sender or query id are skipped cleanly during Telegram normalization
  - unauthorized inline queries are ignored before result generation so the feature does not widen the gateway trust boundary
- Focused verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_inline_query.py tests/unit/test_telegram_api.py tests/unit/test_daemon.py tests/e2e/test_gateway_flow.py` -> `192 passed`
- Full-suite verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` -> `316 passed`
- Feature-specific changed-code coverage:
  - `src/codex_telegram_gateway/inline_query.py`: `30/30 = 100.0%`
  - `src/codex_telegram_gateway/telegram_api.py` changed executable lines: `13/13 = 100.0%`
  - `src/codex_telegram_gateway/daemon.py` changed executable lines: `12/12 = 100.0%`
  - `TOTAL`: `55/55 = 100.0%`

## Advanced Provider and Messaging Parity

### FP-28: Inter-Agent Messaging/Mailbox

**Parity target**

Replicate `ccgram`’s agent-to-agent messaging only if Codex App exposes a meaningful equivalent.

**Dev design**

- Treat this as a separate subsystem, not part of the main Telegram-thread bridge.
- If implemented, the mailbox should operate on `codex_thread_id` and project identities, not tmux windows.
- This requires a clear product requirement first.

**Implementation plan**

1. Defer until there is a confirmed user need and Codex-side API for thread-to-thread messaging semantics.
2. If revived later:
   - create mailbox schema
   - delivery queue
   - loop detection
   - Telegram notifications

**Test automation plan**

- No immediate implementation tests.
- Add only design-contract tests if this feature is greenlit later.

### FP-29: Shell/NL-to-Command Mode

**Parity target**

`ccgram` supports shell-provider sessions; this gateway currently targets Codex App threads only.

**Dev design**

- Keep this out of the main plugin.
- If needed later, implement as a sibling plugin or an optional adapter mode bound to a project-local shell service.

**Implementation plan**

1. Do not implement in the core parity pass.
2. Reserve command names and docs so future work does not conflict.

**Test automation plan**

- None in the current roadmap.

## Recommended Delivery Order

### Phase 1: Lifecycle and operator fundamentals

- FP-01 Topic close/reopen lifecycle
- FP-02 Bidirectional topic rename sync
- FP-04 Lifecycle sweeps
- FP-08 `/unbind`
- FP-09 `/restore`
- FP-17 Command/menu sync
- FP-18 Full sessions dashboard

### Phase 2: High-value command parity

- FP-06 `/history`
- FP-07 `/resume`
- FP-11 `/send`
- FP-13 `/verbose`
- FP-16 `/recall`

### Phase 3: Rich runtime UX

- FP-19 Interactive prompt bridge
- FP-20 Status bubble
- FP-21 Tool batching/failure probing/summaries
- FP-03 Topic emoji state
- FP-12 `/toolbar`

### Phase 4: Media parity

- FP-24 General file intake
- FP-25 Outbound media/file delivery
- FP-26 Voice transcription
- FP-14 `/screenshot`
- FP-22 Live view

### Phase 5: Lower-priority parity and compatibility

- FP-05 Multi-chat fanout/backoff
- FP-10 `/upgrade`
- FP-15 `/panes`
- FP-23 Remote control actions
- FP-27 Inline query support

### Deferred unless product scope changes

- FP-28 Inter-agent messaging/mailbox
- FP-29 Shell/NL-to-command mode

## Global Test Strategy

### Unit suite additions

- Add dedicated test modules per new subsystem:
  - `test_topic_lifecycle.py`
  - `test_history.py`
  - `test_resume.py`
  - `test_send_command.py`
  - `test_status_bubble.py`
  - `test_response_builder.py`
  - `test_voice.py`

### Integration suite additions

- Build reusable fakes:
  - `FakeTelegramBotClient`
  - `FakeCodexBridge`
  - `FakeScreenshotProvider`
  - `FakeTranscriptionProvider`
  - `FakeClock`
- Add DB migration tests that open prior schema snapshots and migrate in place.

### End-to-end suite additions

- Scenario-driven daemon tests:
  - topic close/reopen
  - resume existing thread
  - restore deleted topic
  - send/receive files
  - voice confirm/discard
  - approval prompt resolve
  - status bubble recreation

### Manual verification checklist

- Codex App on macOS with plugin loaded
- Telegram forum-enabled supergroup with bot admin rights
- one project with multiple threads
- one topic created from Telegram first-message path
- one recovered/deleted topic scenario

## Acceptance Criteria

- Every P0 feature has:
  - persisted state model
  - unit tests
  - integration tests
  - at least one end-to-end scenario
- Telegram lifecycle events do not produce duplicate topics or stale bindings.
- Operator commands stay namespaced or explicitly documented.
- Unsupported tmux-only features fail clearly, not silently.
- Existing live flows remain green:
  - topic sync from Codex App
  - queued `Steer`
  - typing indicator
  - image intake
  - in-place assistant message growth
