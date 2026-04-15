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
| FP-11 | `/send` file browser/upload | P0 | Native | Missing |
| FP-12 | `/toolbar` configurable action bar | P1 | Adapted | Missing |
| FP-13 | `/verbose` and notification modes | P0 | Native | Missing |
| FP-14 | `/screenshot` | P1 | Adapted | Missing |
| FP-15 | `/panes` compatibility | P2 | Compatibility only | Codex App has no pane model |
| FP-16 | `/recall` top-level recall flow | P1 | Native | Partial via reply widget only |
| FP-17 | Command discovery and Telegram menu sync | P0 | Adapted | Partial today |
| FP-18 | Full sessions dashboard | P0 | Native | Partial today |
| FP-19 | Generic interactive prompt bridge | P0 | Depends on app-server support | Missing |
| FP-20 | Dedicated status bubble | P0 | Native | Missing |
| FP-21 | Tool batching, failure probing, completion summaries | P0 | Native | Missing |
| FP-22 | Live view | P1 | Adapted | Missing |
| FP-23 | Remote control actions | P1 | Depends on app-server support | Missing |
| FP-24 | General file intake and unsupported-content UX | P0 | Native | Partial today |
| FP-25 | Outbound media/file delivery | P0 | Native | Missing |
| FP-26 | Voice transcription flow | P1 | Native | Missing |
| FP-27 | Inline query support | P2 | Native | Missing |
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
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-10: `/upgrade`
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-11: `/send` File Browser and Upload
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-12: `/toolbar` Configurable Action Bar
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-13: `/verbose` and Notification Modes
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-14: `/screenshot`
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-15: `/panes` Compatibility
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-16: `/recall`
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-17: Command Discovery and Telegram Menu Sync
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-18: Full Sessions Dashboard
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-19: Generic Interactive Prompt Bridge
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-20: Dedicated Status Bubble
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-21: Tool Batching, Failure Probing, Completion Summaries
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-22: Live View
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-23: Remote Control Actions
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-24: General File Intake and Unsupported-Content UX
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-25: Outbound Media and File Delivery
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-26: Voice Transcription Flow
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### FP-27: Inline Query Support
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

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
- Feature commit: to be filled after branch commit
- Merge commit on `main`: to be filled after merge

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
- Show recent user messages as callback buttons.
- On selection:
  - if turn idle, enqueue as normal user input
  - if turn active, enqueue and show `Steer` option

**Implementation plan**

1. Add `/recall` command.
2. Build paginated recall keyboard from `topic_history`.
3. Share callback logic with existing response-widget recall.

**Test automation plan**

- Unit:
  - history label generation and truncation
- Integration:
  - recall during idle and active-turn states
- E2E:
  - recall a prior message with attached image references

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
- Save inbound files under project-scoped upload directories.
- When Codex cannot ingest a raw media type directly, submit a companion text prompt with the saved path.
- Reply explicitly for unsupported content types instead of silently ignoring them.

**Implementation plan**

1. Generalize current image intake pipeline into `media_ingest.py`.
2. Add MIME/type routing:
   - direct attach
   - file path prompt
   - unsupported with explanation
3. Persist attachment metadata with queued inbound messages.
4. Add size and file-count limits per message.

**Test automation plan**

- Unit:
  - MIME routing decisions
  - upload path generation
- Integration:
  - PDF/document message creates queued Codex input with saved file path
- E2E:
  - send supported and unsupported media types and verify user-facing response

### FP-25: Outbound Media and File Delivery

**Parity target**

Send generated screenshots, artifacts, and files from Codex back into Telegram.

**Dev design**

- Detect artifact candidates from:
  - explicit file attachments if app-server exposes them
  - tool outputs that reference generated local files
  - configured artifact directories
- Send:
  - images as photos
  - binaries/text as documents
- Avoid exfiltrating arbitrary local files outside project roots unless explicitly allowed.

**Implementation plan**

1. Add `artifact_detector.py`.
2. Extend `telegram_api.py` with `send_photo` and `send_document`.
3. Add safe-path policy:
   - project root
   - `.ccgram-uploads`
   - explicit allowlist
4. Attach a short caption linking the file to the turn summary.

**Test automation plan**

- Unit:
  - artifact path allowlist checks
- Integration:
  - image and text artifact delivery
- E2E:
  - generate a file in the project and verify Telegram receives it as a document

### FP-26: Voice Transcription Flow

**Parity target**

Match `ccgram`’s voice-message workflow with confirm/discard behavior.

**Dev design**

- Transcribe voice notes using a pluggable provider:
  - local Whisper
  - API-based transcription
- Show inline keyboard:
  - send
  - discard
  - optionally edit text before send in a future iteration

**Implementation plan**

1. Add `voice_ingest.py` and `voice_callbacks.py`.
2. Define `TranscriptionProvider` interface.
3. Save pending transcript state by topic/message id.
4. On confirm, send transcript into Codex as a normal queued user message.

**Test automation plan**

- Unit:
  - transcript persistence and callback flow
- Integration:
  - fake transcriber returns text and Telegram callback sends it to Codex
- E2E:
  - send a short voice note, confirm send, verify thread receives transcript text

### FP-27: Inline Query Support

**Parity target**

Allow Telegram inline query usage for quick inserts like bindings, recent projects, or commands.

**Dev design**

- Keep scope narrow:
  - current bindings
  - recent projects
  - canned commands/steers
- Do not expose raw thread history through inline query.

**Implementation plan**

1. Add inline query handler module.
2. Add result builders for:
   - project insert
   - binding insert
   - command insert
3. Gate by authorized user id.

**Test automation plan**

- Unit:
  - query parsing and result building
- Integration:
  - fake inline query returns expected result set

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
