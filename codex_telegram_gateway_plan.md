# Codex Telegram Gateway Plugin Plan

## 1. Objective

Build a Codex plugin that turns Telegram forum topics into remote gateways for Codex threads.

The intended user flow is:

1. Install the plugin in Codex from a local or published marketplace.
2. Configure a Telegram bot token from BotFather and one or more numeric Telegram user IDs allowed to send messages into Codex.
3. Link the current Codex thread to a Telegram topic.
4. Have the linked Telegram topic mirror important Codex thread activity.
5. Allow authorized Telegram users to send text into that linked Codex thread.

The design target is **one Codex thread = one Telegram topic = one persisted binding**.

---

## 2. Source Review Summary

### Official Codex plugin docs

The official docs establish the packaging model:

- `.codex-plugin/plugin.json` is required.
- `skills/`, `.mcp.json`, `.app.json`, and `assets/` live at the plugin root.
- Plugins are installed from marketplace manifests under `.agents/plugins/marketplace.json` or `~/.agents/plugins/marketplace.json`.
- MCP-backed plugins are first-class, and bundled MCP servers may need separate setup/auth after install.

Implication: this should be an **MCP-backed plugin**, not an app-backed plugin.

### Slack plugin reference

The Slack plugin is the best reference for packaging and skill shape:

- clean `plugin.json` metadata and interface copy
- small `.app.json` companion manifest
- one routing skill plus specialized workflow skills
- explicit guardrails for supported and unsupported actions

Implication: copy the **manifest quality, skill routing, and guardrail style**, but use `.mcp.json` instead of `.app.json`.

### ccgram reference

`ccgram` is the best reference for Telegram topic routing and operational hardening:

- strict topic-only architecture
- persisted forward and reverse binding tables
- numeric user allowlist
- optional group restriction
- topic creation backoff on Telegram flood control
- explicit cleanup on deleted topics / stale bindings
- message splitting for Telegram limits
- tests centered on routing, auth, group filters, and recovery

Implication: reuse the **binding model and Telegram operational patterns**, but replace tmux/session monitoring with Codex thread APIs.

### Local Codex runtime inspection

The local runtime in this environment materially changes feasibility:

- `CODEX_THREAD_ID` is present in the shell environment.
- `codex app-server generate-json-schema` exposes `thread/read`, `thread/list`, `thread/set-name`, `turn/start`, `turn/steer`, and related thread operations.

Implication: a true two-way gateway is feasible with a local bridge service, but this depends on runtime behavior that is not described in the reviewed public plugin docs. It must therefore be treated as a controlled dependency with a fallback mode.

---

## 3. Goals

### Primary goals

- Link the current Codex thread to a Telegram forum topic.
- Mirror Codex thread activity into the linked topic with low latency.
- Accept inbound Telegram text only from configured numeric user IDs.
- Route inbound Telegram text into the linked Codex thread.
- Persist mappings and cursors so restart does not break the bridge.
- Support multiple linked Codex threads concurrently.

### Secondary goals

- Auto-create Telegram topics when a default forum chat is configured.
- Sync a useful thread title into Telegram topic names.
- Provide good diagnostics, health checks, and recovery commands.
- Keep the plugin installable from a repo-local marketplace during development.

### Non-goals for v1

- Voice notes, stickers, photos, documents, or arbitrary binary attachments from Telegram to Codex.
- Rich Telegram inline keyboards, approval UIs, or status dashboards at ccgram parity.
- Full bidirectional formatting fidelity for every Codex item type.
- Cross-account or multi-tenant hosting.
- Remote webhook infrastructure.

---

## 4. Product Requirements

### Functional requirements

- `FR-1`: The plugin must install cleanly as a Codex plugin from a local marketplace.
- `FR-2`: The plugin must expose an MCP surface that can link the current Codex thread to Telegram.
- `FR-3`: The plugin must resolve the current thread identity automatically when `CODEX_THREAD_ID` is available.
- `FR-4`: The plugin must persist a unique binding between `codex_thread_id` and `(chat_id, message_thread_id)`.
- `FR-5`: The system must reject inbound Telegram messages from unauthorized Telegram user IDs.
- `FR-6`: The system must ignore Telegram updates from unbound topics.
- `FR-7`: The system must mirror new Codex thread content into the linked Telegram topic.
- `FR-8`: The system must enqueue inbound Telegram text and deliver it into the Codex thread when safe.
- `FR-9`: The system must survive daemon restart and resume from persisted offsets without duplicate floods.
- `FR-10`: The system must support more than one linked thread/topic concurrently.
- `FR-11`: The system must provide operator-facing status and doctor tooling.

### Operational requirements

- `OR-1`: Telegram long polling must be the default transport.
- `OR-2`: Topic creation must back off on Telegram `429 RetryAfter`.
- `OR-3`: Outbound Telegram messages must be split to Telegram-safe sizes.
- `OR-4`: The bridge must maintain a single daemon instance per machine/user config directory.
- `OR-5`: The bridge must use persisted storage suitable for concurrent daemon and MCP access.

### Security requirements

- `SR-1`: Secrets must not be stored in `plugin.json`, `.mcp.json`, or marketplace manifests.
- `SR-2`: Only configured numeric user IDs may send Telegram -> Codex messages.
- `SR-3`: Optional chat/group filtering must be supported.
- `SR-4`: All inbound text must be treated as untrusted content.
- `SR-5`: The bridge must not silently fall back to a broader auth scope.

### UX requirements

- `UX-1`: Linking a thread must be one explicit action from inside the thread.
- `UX-2`: The default Telegram sync mode should avoid excessive noise.
- `UX-3`: Error messages should be actionable: missing bot permission, bad token, missing topic, Codex bridge unavailable, unauthorized sender.

---

## 5. Required Configuration

### Required for v1

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`

### Required for auto-create flow

- `TELEGRAM_DEFAULT_CHAT_ID`

### Recommended

- `CODEX_TELEGRAM_STATE_DIR`
- `TELEGRAM_POLL_TIMEOUT_SECONDS`
- `CODEX_SYNC_INTERVAL_SECONDS`
- `TELEGRAM_SYNC_MODE`
- `CODEX_APP_SERVER_COMMAND`

### Telegram-side setup requirements

- Bot created in BotFather
- Bot added to a forum-enabled Telegram group
- Group topics enabled
- Bot privacy disabled if group messages must be visible
- Bot admin rights sufficient to create topics if auto-create is used

---

## 6. Proposed Architecture

## 6.1 High-level shape

Use a **plugin + local daemon** architecture:

- the **Codex plugin** provides skills and MCP tools for setup, binding, status, and manual actions
- the **gateway daemon** performs continuous Telegram polling and Codex thread synchronization
- the **Codex bridge client** talks to `codex app-server`
- the **Telegram bridge client** talks to the Telegram Bot API
- **SQLite** stores bindings, queues, and sync cursors

This is the simplest design that supports continuous Telegram -> Codex delivery while the user is away from the current Codex tool call.

## 6.2 Why this architecture

### Why MCP-backed plugin

- Telegram is not an existing Codex connector/app.
- The plugin needs local process control, persistent state, and custom transport logic.
- `.mcp.json` is the documented way to bundle custom tool surfaces.

### Why a daemon

- The plugin MCP server alone is not a sufficient always-on control loop.
- Telegram polling and Codex sync must continue even when the user is not actively invoking a tool.
- A daemon simplifies long polling, state recovery, and multi-thread concurrency.

### Why Codex app-server instead of transcript parsing

- `codex app-server` exposes structured thread and turn data.
- This avoids brittle parsing of rollout files or terminal logs.
- It gives a supported internal representation of agent messages, user messages, plans, command executions, and thread status.

### Why long polling instead of webhook

- Local developer workstations do not usually have a public HTTPS endpoint.
- Long polling is enough for v1 and matches ccgram's local-machine posture.

### Why SQLite instead of JSON state files

- Concurrent daemon + MCP access
- queue semantics
- dedupe keys
- crash-safe transactions
- easier migrations later

---

## 7. Detailed Design

## 7.1 Plugin package layout

```text
codex-telegram/
├── .codex-plugin/
│   └── plugin.json
├── .mcp.json
├── assets/
│   ├── app-icon.png
│   └── telegram-small.svg
├── skills/
│   ├── telegram/
│   │   └── SKILL.md
│   └── telegram-outgoing/
│       └── SKILL.md
├── pyproject.toml
├── src/codex_telegram_gateway/
│   ├── cli.py
│   ├── config.py
│   ├── daemon.py
│   ├── mcp_server.py
│   ├── state.py
│   ├── models.py
│   ├── telegram_api.py
│   ├── codex_app_client.py
│   ├── router.py
│   ├── render.py
│   ├── service.py
│   └── locks.py
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

## 7.2 `plugin.json`

The manifest should follow the Slack plugin style:

- `name`: `telegram-gateway`
- `skills`: `./skills/`
- `mcpServers`: `./.mcp.json`
- `interface.displayName`: `Telegram Gateway`
- `category`: likely `Productivity` or `Coding`
- `capabilities`: `Interactive`, `Read`, `Write`
- `defaultPrompt`: something like `Link this Codex thread to Telegram and keep the topic in sync`

Do not include `.app.json` in v1.

## 7.3 `.mcp.json`

Use a local stdio server.

Development shape:

```json
{
  "mcpServers": {
    "telegram-gateway": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        ".",
        "python",
        "-m",
        "codex_telegram_gateway.mcp_server"
      ]
    }
  }
}
```

Release packaging can switch to `uvx` or another stable launcher.

## 7.4 Skills

### `telegram`

Router skill for:

- setup
- link/unlink
- status checks
- general Telegram sync requests

Guardrails:

- do not claim support for arbitrary Telegram admin actions
- do not imply inbound remote control is available if the daemon is not healthy
- do not ask for secrets in chat if env/config is expected

### `telegram-outgoing`

Focused on outbound Telegram copy generation and explicit send flows.

The skill should mirror the Slack plugin pattern:

- identify destination binding first
- distinguish user-private summary from Telegram-ready post
- keep Telegram text concise and split-safe

## 7.5 Background daemon responsibilities

- ensure Telegram long polling is running
- ensure Codex app-server client session is available
- maintain binding table cache
- poll or subscribe for Codex thread updates
- mirror unseen Codex items to Telegram
- receive Telegram text updates
- authenticate sender
- queue inbound items
- deliver queued inbound items into Codex when the thread is idle
- expose health and status for MCP and CLI calls

## 7.6 Codex integration design

### Primary thread key

- Primary: `CODEX_THREAD_ID`
- Fallback: explicit thread key supplied by tool input when the env var is absent

### Codex bridge transport

Use a persistent client to `codex app-server`.

Needed operations:

- `thread/read` with `includeTurns=true`
- `thread/list` for diagnostics and recovery
- `thread/set-name` for optional title sync
- `turn/start` to inject inbound Telegram text into a thread

### Delivery strategy

- When thread status is `idle`, deliver the next queued Telegram message with `turn/start`.
- When thread status is `active`, keep the message queued.
- Do not use `turn/steer` in v1 unless active-turn semantics are explicitly verified; it is optional future work.

### Outbound sync strategy

V1 should use polling:

- poll only bound threads
- compare `updatedAt` and unseen item IDs
- emit new items in order

Future enhancement:

- use app-server notifications such as realtime item added / thread status change

## 7.7 Telegram integration design

### Topic identity

Use composite topic identity:

- `chat_id`
- `message_thread_id`

Never treat `message_thread_id` as globally unique by itself.

### Auto-create topic flow

When `TELEGRAM_DEFAULT_CHAT_ID` is configured:

1. `link_current_thread` reads current Codex thread metadata.
2. Derive a topic name from:
   - thread `name` if present
   - otherwise repo basename
   - otherwise thread preview prefix
3. Call `createForumTopic`.
4. Persist the binding.
5. Send a confirmation message into the topic.

### Bind-existing-topic flow

Allow manual binding by supplying:

- `chat_id`
- `message_thread_id`

This is the fallback when topic auto-create is not desired or permissions are missing.

### Inbound routing rules

- accept text messages only
- ignore bot/self messages
- ignore unauthorized users
- ignore topics without bindings
- ignore unsupported content in v1 with a short explanation

## 7.8 Rendering rules

Default sync mode should be `assistant_plus_alerts`, not `full`.

### Mirror by default

- assistant text
- explicit wait states / approval-needed alerts
- compact plan/status summaries
- clear error summaries

### Mirror only in verbose/full mode

- raw command execution logs
- large file change payloads
- low-signal incremental reasoning fragments

### Telegram formatting

- default to plain text or very conservative Markdown
- split messages at `4096` chars
- prefer semantic chunk boundaries
- keep a short prefix showing the source item type only when useful

## 7.9 State model

Use SQLite with migrations.

### `bindings`

- `codex_thread_id TEXT PRIMARY KEY`
- `chat_id INTEGER NOT NULL`
- `message_thread_id INTEGER NOT NULL`
- `topic_name TEXT`
- `sync_mode TEXT NOT NULL`
- `created_at INTEGER NOT NULL`
- `updated_at INTEGER NOT NULL`
- unique index on `(chat_id, message_thread_id)`

### `outbound_cursors`

- `codex_thread_id TEXT PRIMARY KEY`
- `last_thread_updated_at INTEGER`
- `last_emitted_event_key TEXT`
- `updated_at INTEGER NOT NULL`

### `seen_events`

- `event_key TEXT PRIMARY KEY`
- `codex_thread_id TEXT NOT NULL`
- `created_at INTEGER NOT NULL`

Event key format:

- `thread:{thread_id}:turn:{turn_id}:item:{item_id}`

### `telegram_updates`

- `bot_scope TEXT PRIMARY KEY`
- `last_update_id INTEGER NOT NULL`

### `inbound_queue`

- `id INTEGER PRIMARY KEY`
- `telegram_update_id INTEGER UNIQUE NOT NULL`
- `chat_id INTEGER NOT NULL`
- `message_thread_id INTEGER NOT NULL`
- `from_user_id INTEGER NOT NULL`
- `codex_thread_id TEXT NOT NULL`
- `text TEXT NOT NULL`
- `status TEXT NOT NULL`
- `error TEXT`
- `created_at INTEGER NOT NULL`
- `delivered_at INTEGER`

### `daemon_state`

- `name TEXT PRIMARY KEY`
- `pid INTEGER`
- `heartbeat_at INTEGER`
- `started_at INTEGER`
- `version TEXT`

## 7.10 Failure handling

### Telegram failures

- `401/403`: configuration or permission issue, surface in status/doctor
- `429`: honor backoff and retry-after
- network timeout: retry with bounded backoff

### Codex failures

- app-server unavailable: mark daemon degraded and keep inbound queue pending
- `turn/start` rejected because thread is active: keep queue pending and retry later
- thread missing/archived: mark binding degraded and stop delivery until resolved

### State corruption / restart

- daemon must rebuild in-memory caches from SQLite at startup
- outbound dedupe must rely on persisted event keys, not only RAM
- inbound queue items remain pending until positively delivered

---

## 8. MCP Tool Surface

Proposed v1 tools:

### `telegram_gateway_doctor`

Checks:

- required env vars
- Telegram bot reachability
- default chat visibility/permissions
- Codex app-server availability
- daemon health

### `telegram_link_current_thread`

Inputs:

- `chat_id` optional
- `message_thread_id` optional
- `topic_name` optional
- `create_if_missing` default `true`
- `sync_mode` default `assistant_plus_alerts`

Behavior:

- resolve current `codex_thread_id`
- ensure daemon is running
- bind or create topic
- persist mapping

### `telegram_unlink_current_thread`

Behavior:

- remove binding for current thread
- optionally keep the Telegram topic intact

### `telegram_gateway_status`

Returns:

- daemon health
- current thread binding if any
- queue depth
- last outbound sync timestamp
- last inbound delivery timestamp

### `telegram_sync_current_thread`

Behavior:

- force a poll/read and flush new outbound items immediately

### `telegram_send_message`

Behavior:

- send an explicit user-requested message to the linked topic
- useful for ad hoc summaries and smoke tests

### `telegram_list_bindings`

Returns:

- all known bindings
- status per binding

---

## 9. CLI Surface

Expose a small companion CLI for development and operations:

- `codex-telegram doctor`
- `codex-telegram daemon run`
- `codex-telegram daemon ensure`
- `codex-telegram daemon stop`
- `codex-telegram status`
- `codex-telegram bindings list`
- `codex-telegram bindings prune`
- `codex-telegram sync --thread-id ...`

This keeps operational testing possible even outside the Codex UI.

---

## 10. Implementation Plan

## Phase 1: Scaffold and packaging

### Deliverables

- plugin directory structure
- initial manifest files
- local marketplace entry
- minimal MCP server that answers health/status requests
- baseline Python package with importable modules

### Detailed implementation

1. Create the root layout exactly as described in Section 7.1.
   - create `.codex-plugin/`
   - create `skills/telegram/`
   - create `skills/telegram-outgoing/`
   - create `src/codex_telegram_gateway/`
   - create `tests/unit/`, `tests/integration/`, and `tests/e2e/`
   - create `.agents/plugins/marketplace.json` in the repo root for local install

2. Author `.codex-plugin/plugin.json`.
   - copy the metadata style from the Slack and Build Web Apps examples
   - include `skills: "./skills/"`
   - include `mcpServers: "./.mcp.json"`
   - keep descriptions realistic and narrowly scoped to Telegram thread linking and sync
   - add icons in `assets/` even if they are temporary placeholders

3. Author `.mcp.json`.
   - start with a stdio launcher using `uv run`
   - point to `python -m codex_telegram_gateway.mcp_server`
   - avoid embedding secrets or environment in this file

4. Add a repo-local marketplace entry.
   - set the marketplace plugin path relative to `.agents/plugins/marketplace.json`
   - ensure the marketplace display name is stable and human-readable
   - verify the plugin can be browsed via Codex `/plugins`

5. Create the Python packaging scaffold.
   - add `pyproject.toml` with:
     - package metadata
     - Python version floor
     - runtime dependencies such as `httpx`, `pydantic`, `aiosqlite` or `sqlite3`, `typer` or `click`, and an MCP library if used
     - dev dependencies for `pytest`, `pytest-asyncio`, `ruff`, and `mypy`
   - add `__init__.py` and empty module files for all planned components

6. Implement the thinnest possible MCP server first.
   - add `src/codex_telegram_gateway/mcp_server.py`
   - expose one tool such as `telegram_gateway_status`
   - return static placeholder output so the plugin surface can be validated before daemon work begins

7. Add first-pass skills.
   - `skills/telegram/SKILL.md`: router skill, supported actions, guardrails, install/setup cues
   - `skills/telegram-outgoing/SKILL.md`: explicit outbound Telegram message drafting rules
   - keep them intentionally narrow in v1; do not promise unsupported Telegram administration features

### Files primarily touched

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `.agents/plugins/marketplace.json`
- `pyproject.toml`
- `src/codex_telegram_gateway/mcp_server.py`
- `skills/telegram/SKILL.md`
- `skills/telegram-outgoing/SKILL.md`

### Verification and acceptance

- plugin is discoverable in `/plugins`
- MCP server launches without crashing
- both skills are visible in Codex
- `uv run python -m codex_telegram_gateway.mcp_server` starts locally
- local marketplace install works from the repo

## Phase 2: Core configuration and state

### Deliverables

- validated configuration layer
- SQLite schema and migration bootstrap
- doctor command and MCP doctor tool
- daemon liveness and lease model

### Detailed implementation

1. Implement configuration loading in `config.py`.
   - define a typed config model
   - support env vars first, then optional config file under `CODEX_TELEGRAM_STATE_DIR`
   - validate:
     - `TELEGRAM_BOT_TOKEN`
     - `TELEGRAM_ALLOWED_USER_IDS`
     - optional `TELEGRAM_DEFAULT_CHAT_ID`
     - optional `CODEX_APP_SERVER_COMMAND`
   - normalize allowed user IDs into a `set[int]`
   - reject malformed numeric IDs early with explicit error messages

2. Define storage layout.
   - choose a default state directory such as `~/.codex-telegram`
   - create:
     - `gateway.db`
     - `logs/`
     - `run/` or lock files if needed
   - centralize all path derivation in one module

3. Implement SQLite schema bootstrap in `state.py`.
   - add a schema version table
   - create migrations for:
     - `bindings`
     - `outbound_cursors`
     - `seen_events`
     - `telegram_updates`
     - `inbound_queue`
     - `daemon_state`
   - wrap writes in explicit transactions
   - expose repository helpers instead of raw SQL everywhere else

4. Add repository methods.
   - `BindingRepo`
   - `OutboundCursorRepo`
   - `InboundQueueRepo`
   - `DaemonStateRepo`
   - keep SQL localized so orchestration code stays readable

5. Implement doctor logic in `cli.py` and `service.py`.
   - checks should include:
     - required env/config presence
     - state dir writable
     - database can be opened and migrated
     - Telegram API reachable via `getMe`
     - bot can access configured default chat if configured
     - local Codex bridge command exists
   - expose the same doctor logic through both CLI and MCP tool surfaces

6. Implement daemon lease tracking in `locks.py` and `daemon.py`.
   - decide between:
     - SQLite lease row with heartbeat
     - lockfile + pid
     - or both
   - daemon startup should:
     - acquire or replace stale lease
     - persist PID and startup time
     - start heartbeat updates
   - daemon shutdown should cleanly mark itself stopped

### Files primarily touched

- `src/codex_telegram_gateway/config.py`
- `src/codex_telegram_gateway/state.py`
- `src/codex_telegram_gateway/models.py`
- `src/codex_telegram_gateway/service.py`
- `src/codex_telegram_gateway/locks.py`
- `src/codex_telegram_gateway/cli.py`

### Verification and acceptance

- malformed config fails fast with actionable errors
- database initializes from an empty directory
- rerunning initialization is idempotent
- migrations apply cleanly on an existing DB
- `doctor` reports both passing and failing conditions clearly
- a second daemon instance is prevented or clearly rejected

## Phase 3: Telegram transport

### Deliverables

- Telegram HTTP client wrapper
- long-polling update loop
- topic creation and outbound send primitives
- inbound update parsing and auth filtering
- retry and backoff behavior

### Detailed implementation

1. Build `telegram_api.py`.
   - implement a small typed client over the Telegram Bot API
   - first methods:
     - `get_me`
     - `get_updates`
     - `send_message`
     - `create_forum_topic`
     - `edit_forum_topic` or rename helper if used later
   - keep request/response models minimal and version-tolerant

2. Implement long polling in `daemon.py`.
   - load the last `update_id` from `telegram_updates`
   - call `getUpdates` with timeout
   - persist only after successful processing of a batch
   - keep the loop cancellation-safe

3. Implement update parsing.
   - extract:
     - `update_id`
     - `chat.id`
     - `message.message_thread_id`
     - `from.id`
     - message text
   - detect unsupported updates and drop them quietly or with debug logging
   - ignore messages without `message_thread_id` in v1 unless explicit support is added

4. Implement auth and routing guards.
   - reject if `from.id` not in allowlist
   - optionally reject if `chat.id` does not match configured default chat when strict chat scoping is enabled
   - reject if there is no binding for `(chat_id, message_thread_id)`
   - ignore bot-authored/self-authored messages to avoid loops

5. Implement send pipeline.
   - add `render.py::split_telegram_message()`
   - split at 4096 chars with newline preference
   - send chunks sequentially into the target topic with `message_thread_id`
   - classify retryable vs non-retryable Telegram failures

6. Implement topic creation backoff.
   - maintain per-chat retry windows
   - honor Telegram `RetryAfter`
   - store backoff in memory for v1; move to persisted backoff only if required

7. Implement a small smoke-test CLI path.
   - `codex-telegram doctor` should optionally call `send_message` into a test topic if requested
   - this is useful before full daemon integration

### Files primarily touched

- `src/codex_telegram_gateway/telegram_api.py`
- `src/codex_telegram_gateway/render.py`
- `src/codex_telegram_gateway/daemon.py`
- `src/codex_telegram_gateway/service.py`

### Verification and acceptance

- daemon receives topic messages from Telegram
- daemon can create topics in the configured forum chat
- daemon can send chunked topic messages
- unauthorized users are ignored
- Telegram 429 backoff works and prevents hot-loop retries

## Phase 4: Codex bridge

### Deliverables

- app-server client transport
- typed request/response wrappers for needed Codex operations
- thread polling engine
- normalized internal event model for outbound sync

### Detailed implementation

1. Choose the initial transport.
   - start with one supported mode only:
     - preferred: launch `codex app-server --listen stdio://`
   - defer websocket transport unless local stdio proves insufficient

2. Implement `codex_app_client.py`.
   - manage process startup and shutdown
   - implement JSON-RPC framing and request IDs
   - centralize timeout handling
   - convert transport and protocol failures into typed bridge errors

3. Add request wrappers for required methods.
   - `thread/read`
   - `thread/list`
   - `thread/setName`
   - `turn/start`
   - optionally `thread/start` for future manual creation flows
   - use the generated JSON schemas as the source of truth for field names

4. Implement thread identity resolution.
   - read `CODEX_THREAD_ID` from the MCP server and CLI process environment
   - if absent, allow explicit thread ID in tool args
   - expose one helper:
     - `resolve_current_thread_id(explicit: str | None) -> str`

5. Implement normalized event extraction.
   - define an internal event model such as:
     - `AssistantMessageEvent`
     - `PlanEvent`
     - `ApprovalWaitEvent`
     - `ErrorEvent`
     - `CommandSummaryEvent`
   - map from raw `ThreadReadResponse.thread.turns[].items[]`
   - keep item IDs and turn IDs for stable dedupe keys

6. Implement thread polling.
   - poll only currently bound thread IDs
   - for each thread:
     - read thread metadata and turns
     - compare `updatedAt`
     - if changed, normalize unseen items into outbound events
   - bound polling interval by config

7. Implement inbound delivery.
   - when a queued Telegram message is ready:
     - send it as `turn/start` with a `text` user input
   - keep the raw inbound message text unchanged except for optional lightweight provenance prefix if chosen

8. Implement thread status inspection.
   - treat `idle` as deliverable
   - treat `active` as not deliverable
   - treat `systemError` or `notLoaded` as degraded

### Files primarily touched

- `src/codex_telegram_gateway/codex_app_client.py`
- `src/codex_telegram_gateway/models.py`
- `src/codex_telegram_gateway/service.py`
- `src/codex_telegram_gateway/daemon.py`

### Verification and acceptance

- daemon can read a thread by `threadId`
- daemon can send a text turn into a thread
- polling sees new thread items
- broken app-server startup yields clear degraded status instead of silent failure

## Phase 5: Binding and sync orchestration

### Deliverables

- binding service
- MCP tools and CLI commands for bind lifecycle
- outbound dedupe and cursor advancement
- inbound queue processor
- idle-thread delivery policy

### Detailed implementation

1. Implement binding repository and service methods.
   - `create_binding(thread_id, chat_id, message_thread_id, topic_name, sync_mode)`
   - `delete_binding(thread_id)`
   - `get_binding_by_thread(thread_id)`
   - `get_binding_by_topic(chat_id, message_thread_id)`
   - `list_bindings()`
   - enforce one-to-one uniqueness both directions

2. Implement `link_current_thread`.
   - resolve current thread ID
   - if explicit topic coordinates are supplied:
     - bind directly
   - else if `TELEGRAM_DEFAULT_CHAT_ID` is configured and `create_if_missing=true`:
     - read thread metadata
     - derive topic name
     - create forum topic
     - persist binding
   - send confirmation message to the topic

3. Implement `unlink_current_thread`.
   - resolve current thread ID
   - remove binding row
   - optionally preserve topic untouched
   - clear outbound cursor and dedupe state for that thread if desired

4. Implement outbound sync orchestration.
   - for each bound thread:
     - poll thread
     - normalize items
     - for each item build deterministic event key
     - skip already-seen event keys
     - render and send new events
     - persist event key and cursor progress only after send succeeds

5. Implement rendering policy by sync mode.
   - `assistant_plus_alerts`
   - `assistant_only`
   - `full`
   - route event classes through a renderer that decides:
     - emit
     - summarize
     - suppress

6. Implement inbound queue ingestion.
   - upon valid inbound Telegram message:
     - insert queue row as `pending`
     - capture update ID, sender ID, topic coordinates, thread ID, and raw text
   - make insertion idempotent using unique `telegram_update_id`

7. Implement queue processing.
   - periodic worker selects oldest pending message per thread
   - inspect thread status
   - if `idle`, deliver and mark `delivered`
   - if `active`, leave `pending`
   - if bridge error, mark `error` or retryable state based on failure class

8. Implement MCP tool handlers.
   - `telegram_link_current_thread`
   - `telegram_unlink_current_thread`
   - `telegram_gateway_status`
   - `telegram_sync_current_thread`
   - `telegram_send_message`
   - `telegram_list_bindings`
   - each tool should call the service layer, not raw repositories

9. Implement status summarization.
   - include:
     - current thread binding
     - daemon health
     - queue depth
     - last successful outbound sync
     - last successful inbound delivery
     - degraded reasons if any

### Files primarily touched

- `src/codex_telegram_gateway/router.py`
- `src/codex_telegram_gateway/service.py`
- `src/codex_telegram_gateway/daemon.py`
- `src/codex_telegram_gateway/mcp_server.py`
- `src/codex_telegram_gateway/cli.py`

### Verification and acceptance

- current thread can be linked to a Telegram topic
- link can either bind an existing topic or auto-create one
- new Codex messages appear in that topic only once
- inbound Telegram text reaches the linked thread when idle
- repeated daemon restarts do not replay old mirrored items

## Phase 6: Skills and UX hardening

### Deliverables

- final skill wording
- explicit UX behavior for supported vs unsupported requests
- polished status output
- stable default message rendering and naming behavior

### Detailed implementation

1. Finalize `skills/telegram/SKILL.md`.
   - describe plugin scope clearly
   - route users to:
     - setup
     - linking
     - status checks
     - explicit Telegram sends
   - state limitations:
     - text only
     - no arbitrary admin actions
     - no unsupported media relay in v1

2. Finalize `skills/telegram-outgoing/SKILL.md`.
   - mirror Slack's drafting discipline
   - require clear destination before sending
   - distinguish:
     - mirror/system messages
     - explicit user-authored Telegram posts

3. Harden tool outputs.
   - all MCP tools should return concise, user-facing text plus structured fields where useful
   - status output should avoid dumping raw database state
   - doctor output should prioritize actionable remediation steps

4. Tune topic naming.
   - prefer `thread.name`
   - fallback to repo basename
   - fallback to thread preview fragment
   - cap topic name length to a Telegram-safe limit

5. Tune renderer output.
   - large command execution items should collapse into short summaries by default
   - approval-wait states should be surfaced prominently
   - repeated low-signal planning or reasoning fragments should be coalesced

6. Add explicit unsupported-action responses.
   - unsupported media inbound
   - missing bot permissions
   - missing current-thread identity
   - unavailable daemon or app-server

### Files primarily touched

- `skills/telegram/SKILL.md`
- `skills/telegram-outgoing/SKILL.md`
- `src/codex_telegram_gateway/render.py`
- `src/codex_telegram_gateway/mcp_server.py`
- `src/codex_telegram_gateway/service.py`

### Verification and acceptance

- plugin behaves predictably under natural-language requests
- noisy or unsupported actions are handled explicitly
- the default sync mode is readable in a real Telegram topic
- user-facing tool output is concise and actionable

## Phase 7: Hardening and release prep

### Deliverables

- structured logging and error taxonomy
- stable restart behavior
- release-oriented packaging docs
- migration and upgrade guidance

### Detailed implementation

1. Add structured logging.
   - include component names such as:
     - `daemon`
     - `telegram_api`
     - `codex_bridge`
     - `binding_service`
   - log identifiers:
     - `thread_id`
     - `chat_id`
     - `message_thread_id`
     - `telegram_update_id`
   - never log bot token or other secrets

2. Introduce typed errors.
   - `ConfigError`
   - `TelegramAuthError`
   - `TelegramPermissionError`
   - `TelegramRetryableError`
   - `CodexBridgeUnavailableError`
   - `ThreadNotDeliverableError`
   - `BindingConflictError`
   - map these to retry, fail-fast, or degraded states consistently

3. Harden restart and recovery.
   - startup should:
     - recover daemon lease
     - resume Telegram offsets
     - resume pending inbound queue
     - resume outbound cursor state
   - verify that a crash during outbound send does not mark events as seen prematurely

4. Add migration discipline.
   - version every schema change
   - keep SQL migration files or explicit migration functions
   - document how to upgrade existing state without data loss

5. Prepare release launcher paths.
   - validate whether `.mcp.json` should remain `uv run --directory .` for local development only
   - define a release form such as:
     - `uvx codex-telegram-gateway`
     - or a console script installed by `pipx`
   - update packaging docs accordingly

6. Write install and operator docs.
   - local marketplace installation
   - required env vars
   - Telegram bot setup
   - daemon troubleshooting
   - known limitations for v1

7. Add CI checks.
   - lint
   - unit/integration tests
   - schema contract tests against `codex app-server generate-json-schema`
   - packaging smoke test for plugin layout

### Files primarily touched

- `src/codex_telegram_gateway/*.py`
- `README.md` or `docs/`
- migration files
- CI workflow files if the repo gains them

### Verification and acceptance

- restart recovery works from persisted state
- release install path is documented and reproducible
- logs are useful for diagnosing both Telegram and Codex bridge failures
- schema drift in required app-server endpoints fails CI early

---

## 11. Test Plan

## 11.1 Unit tests

- config parsing
- env precedence
- `CODEX_THREAD_ID` resolution and fallback
- binding CRUD and uniqueness
- Telegram message splitting
- Telegram retry/backoff handling
- inbound auth filter
- event dedupe key generation
- outbound cursor advancement
- rendering of major Codex item types
- app-server request/response framing

## 11.2 Integration tests

Use mocked Telegram HTTP and a fake or fixture-backed Codex bridge.

- link current thread to existing topic
- auto-create new topic in configured forum chat
- reject unauthorized Telegram users
- ignore unbound topics
- outbound thread read -> Telegram mirror
- inbound queue while thread active
- queued inbound delivery after idle
- daemon restart resumes from persisted state
- stale binding detection when topic is deleted
- stale binding detection when Codex thread is missing

## 11.3 Contract tests against local Codex schemas

- generate app-server JSON schema in CI
- verify the client-side request/response models still match required endpoints
- fail fast if key shapes for `thread/read`, `turn/start`, or thread status materially change

This is important because the bridge depends on runtime surfaces not covered by the reviewed plugin docs.

## 11.4 Plugin/MCP tests

- MCP server startup smoke test
- each tool validates inputs and returns useful errors
- daemon ensure/status flows work from MCP

## 11.5 End-to-end tests

Manual or staged real-environment tests:

1. Install plugin from repo-local marketplace.
2. Configure bot token, allowed user, and default chat.
3. Link current thread.
4. Verify topic creation and outbound mirror.
5. Send Telegram text from allowed user and verify Codex receives it.
6. Verify denied user is ignored.
7. Restart daemon and verify no duplicate replay.
8. Link a second Codex thread and verify topic isolation.

## 11.6 Failure-path tests

- invalid token
- missing bot admin rights
- missing topics support in group
- Telegram 429 during topic creation
- app-server unavailable
- app-server restart while queue contains pending items
- deleted topic
- archived or missing Codex thread

---

## 12. Risks and Mitigations

### Risk 1: `CODEX_THREAD_ID` is not guaranteed by public docs

Mitigation:

- treat it as primary, not sole, identity source
- support explicit fallback thread key input
- add doctor warning when env-based identity is unavailable

### Risk 2: app-server thread APIs are experimental

Mitigation:

- isolate all Codex bridge logic behind one module
- add schema contract tests
- support degraded manual-sync mode if bridge health fails

### Risk 3: background daemon lifecycle from a plugin is awkward

Mitigation:

- make daemon lazy-started and idempotent
- persist heartbeat and pid
- expose explicit `status` and `stop`

### Risk 4: Telegram topic creation permissions vary

Mitigation:

- support bind-existing-topic flow
- make auto-create optional
- surface permission problems clearly

---

## 13. Recommended v1 Scope Cut

To get to a usable first release quickly, ship this exact slice:

- MCP-backed plugin with local marketplace install
- daemon + SQLite state
- required config: bot token, allowed user IDs, default chat ID
- `CODEX_THREAD_ID`-based current-thread linking
- Telegram long polling
- Codex polling via `thread/read`
- inbound delivery via `turn/start` when thread is idle
- default sync mode `assistant_plus_alerts`
- text-only inbound/outbound
- doctor/status/link/unlink/sync/send/list-bindings tools

Defer until after v1:

- `turn/steer`
- webhook mode
- media/attachments
- topic rename from Telegram back into Codex
- realtime notifications instead of polling
- rich approval keyboards

---

## 14. Acceptance Criteria

The project is done for v1 when all of the following are true:

- The plugin installs from a local marketplace and its tools are usable in Codex.
- A thread can be linked from inside Codex without manually typing a thread ID.
- A linked Telegram topic receives new Codex assistant output within the configured poll interval.
- Text from an allowed Telegram user reaches the linked Codex thread.
- Unauthorized Telegram users cannot inject messages.
- Restarting the daemon does not create duplicate mirror spam or lose pending inbound messages.
- Two linked threads can run simultaneously without cross-routing.

---

## 15. Recommended Next Step

Implement a proof-of-viability spike before full build-out:

1. Scaffold the plugin and `.mcp.json`.
2. Write a tiny Python daemon that:
   - reads `CODEX_THREAD_ID`
   - creates or binds one Telegram topic
   - calls `thread/read`
   - sends one test message to Telegram
3. Confirm `turn/start` can inject a message back into the same thread.

If that spike works, proceed with the full v1 plan above.
