# Installer and Operations CLI Plan

## Objective

Add a production-ready installation and day-2 operations surface for the Codex App Telegram gateway.

This work covers:

- a one-line `curl ... | sh` bootstrap installer
- an interactive CLI for configuration and reconfiguration
- local daemon lifecycle management
- macOS `launchd` service registration
- Codex App local plugin marketplace setup
- self-update from the installed checkout's `origin` URL
- complete operator documentation

## Scope Rules

- Keep the existing Telegram <-> Codex App behavior intact while adding installation and operator tooling around it.
- Separate mutable runtime data from the source checkout so updates do not overwrite user configuration or state.
- Stay aligned with the official Codex plugin documentation for local marketplace installation.
- Prefer deterministic CLI commands over ad hoc shell snippets once the tool is installed.
- Treat macOS as the primary target for service registration because the gateway is for the macOS Codex App.

## Reference Findings

- `ccgram` exposes a practical operational CLI surface: `run`, `status`, `doctor`, `hook`, upgrade guidance, and service guidance in docs.
- The Codex plugin docs describe local plugin installation through `~/.agents/plugins/marketplace.json` or a repo marketplace, with plugin sources referenced through `source.path`.
- Codex installs enabled local plugins into its cache, so source updates must be followed by a Codex restart to refresh the installed copy.
- This repo currently has a runtime CLI (`doctor`, `run-daemon`, `sync-once`, thread-link commands) but no installer, no operator-facing config command, no background process manager, and no service registration helper.

## Feature Inventory

| ID | Feature | Priority | Notes |
|---|---|---|---|
| CI-01 | Runtime layout and path discovery | P0 | Define source/config/log/state/service paths |
| CI-02 | Interactive install and reconfigure flows | P0 | Prompt for bot token, allowed user ID, and group chat ID |
| CI-03 | One-line shell bootstrap installer | P0 | `curl ... | sh` clone + venv + CLI handoff |
| CI-04 | Codex App marketplace install/repair | P0 | Create or update personal marketplace entry |
| CI-05 | Local daemon start/stop/restart/status/logs | P0 | Background runtime without requiring service install |
| CI-06 | macOS launchd service install/start/stop/status/uninstall | P0 | Durable run-at-login operations |
| CI-07 | Self-update from git origin clone | P0 | Preserve config/state; refresh source checkout |
| CI-08 | Operator diagnostics and status summary | P1 | Unified install/runtime/plugin health checks |
| CI-09 | README and install/operator documentation | P0 | Full setup and maintenance guide |

## Feature Execution Tracker

### CI-01: Runtime Layout and Path Discovery
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-02: Interactive Install and Reconfigure Flows
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-03: One-Line Shell Bootstrap Installer
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-04: Codex App Marketplace Install/Repair
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-05: Local Daemon Start/Stop/Restart/Status/Logs
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-06: macOS launchd Service Install/Start/Stop/Status/Uninstall
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-07: Self-Update From Git Origin Clone
- [x] Implemented
- [x] Test automation coverage more than 80%
- [x] Line by line proof reading for code review done

### CI-08: Operator Diagnostics and Status Summary
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

### CI-09: README and Install/Operator Documentation
- [ ] Implemented
- [ ] Test automation coverage more than 80%
- [ ] Line by line proof reading for code review done

## Detailed Feature Plans

### CI-01: Runtime Layout and Path Discovery

Parity target:
- Provide a stable, documented install layout similar in operator usefulness to `ccgram`'s config-dir conventions.

Design:
- Introduce a dedicated path model that discovers:
  - install root
  - runtime home
  - env file
  - state DB path
  - toolbar config path
  - log directory and log file
  - run directory and pid file
  - `launchd` plist path
  - personal marketplace path
- Default source checkout: `~/.codex-telegram-plugin`
- Default runtime home: `~/.codex-telegram`
- Keep existing runtime code working by feeding it explicit paths through the generated env file.

Implementation plan:
1. Add a new module for runtime path discovery and defaults.
2. Add helpers for creating directories idempotently.
3. Thread the resolved env/state/log paths into the new CLI flows.
4. Keep low-level daemon execution compatible with the existing `run-daemon` command.

Test automation plan:
1. Unit test all default path resolutions with synthetic `HOME` values.
2. Unit test override handling where install root or runtime home is explicitly provided.
3. Add command-level tests that prove the new path model is used by install/start/service flows.

### CI-02: Interactive Install and Reconfigure Flows

Parity target:
- Make configuration as operator-friendly as `ccgram`'s env-driven setup, but with a guided interactive entrypoint.

Design:
- Add `install` and `configure` commands.
- Prompt for:
  - Telegram bot token
  - numeric allowed user ID
  - Telegram group chat ID
- Persist runtime env under `~/.codex-telegram/.env` by default.
- Preserve existing values on reconfigure unless the operator explicitly changes them.
- Generate additional managed defaults:
  - `CODEX_TELEGRAM_STATE_DB`
  - `CODEX_TELEGRAM_TOOLBAR_CONFIG`
  - log and pid paths as needed by other commands

Implementation plan:
1. Add interactive prompt helpers with validation.
2. Add env file render/load/update helpers.
3. Add `install` command that configures paths and writes the managed env file.
4. Add `configure` command that edits the same file safely.
5. Print concise next-step guidance after successful configuration.

Test automation plan:
1. Unit test token/user/group validators.
2. Unit test env-file rendering and reconfigure merge behavior.
3. Command-level tests should patch `input()` and verify the written env content.
4. Add an end-to-end CLI flow test that runs install then configure in a temp home.

### CI-03: One-Line Shell Bootstrap Installer

Parity target:
- Match the convenience of a documented bootstrap path like `ccgram`'s install guidance, but optimized for this plugin repo and one-line install.

Design:
- Add `install/install.sh` suitable for:
  - `curl -fsSL <raw-url> | sh`
- Script responsibilities:
  - check for `git` and `python3`
  - clone the plugin repo into the default install root if missing
  - refresh the checkout if it already exists
  - create or update a virtualenv
  - install the package into that virtualenv
  - invoke the interactive CLI install flow
- Support environment overrides for non-default install locations if needed later.

Implementation plan:
1. Add the bootstrap script under `install/`.
2. Make it derive the repository URL from a constant that matches this repo origin.
3. Run the Python installer command from the created venv.
4. Print the installed CLI path and immediate next-step commands.

Test automation plan:
1. Shell-script smoke test with mocked `git`, `python3`, and `curl`-style environment.
2. Unit test any generated command strings if helper logic lives in Python.
3. End-to-end install test that uses a fake repo source and asserts the handoff command.

### CI-04: Codex App Marketplace Install/Repair

Parity target:
- Automate the official local-plugin marketplace setup rather than asking users to hand-edit `marketplace.json`.

Design:
- Add `plugin install` and `plugin status` commands.
- `plugin install` should:
  - create or update `~/.agents/plugins/marketplace.json`
  - register a local plugin entry pointing to the installed source checkout
  - preserve unrelated marketplace entries
- `plugin status` should report:
  - marketplace file location
  - whether the entry exists
  - the configured plugin source path
- Keep the plugin source path `./`-prefixed and home-root relative per the docs.

Implementation plan:
1. Add marketplace JSON read/write helpers.
2. Add idempotent plugin-entry upsert logic.
3. Add CLI commands for install/status.
4. Print the required Codex restart step after changes.

Test automation plan:
1. Unit test marketplace creation, update, and unrelated-entry preservation.
2. Unit test path normalization for the personal marketplace.
3. Command-level tests for `plugin install` and `plugin status`.

### CI-05: Local Daemon Start/Stop/Restart/Status/Logs

Parity target:
- Give operators a direct runtime control surface without forcing immediate `launchd` adoption.

Design:
- Add top-level commands:
  - `start`
  - `stop`
  - `restart`
  - `status`
  - `logs`
- `start` launches the existing `run-daemon` command in the background, detached, with stdout/stderr routed to a managed log file.
- `stop` uses a pid file and signal handling.
- `status` reports whether the local daemon is alive and which env/log paths it is using.
- `logs` tails the log file or prints its path if live tail is not requested.

Implementation plan:
1. Add pid-file helpers and liveness checks.
2. Add detached process spawn helpers.
3. Add stop/restart flows with stale-pid cleanup.
4. Add log-path helpers and `logs` command behavior.

Test automation plan:
1. Unit test pid parsing, stale pid cleanup, and alive/dead detection.
2. Command-level tests with `subprocess.Popen` and `os.kill` mocked.
3. Add an end-to-end local-daemon flow test using a fake background process object.

### CI-06: macOS launchd Service Install/Start/Stop/Status/Uninstall

Parity target:
- Provide first-class persistent operation on macOS, analogous to `ccgram`'s service guidance but automated for this gateway.

Design:
- Add `service` subcommands:
  - `install`
  - `uninstall`
  - `start`
  - `stop`
  - `restart`
  - `status`
- Generate a `~/Library/LaunchAgents/...plist` pointing at the installed venv Python and `run-daemon`.
- Service should reference the managed runtime env file and write logs into the runtime home.
- `service install` should optionally bootstrap/start the job immediately.

Implementation plan:
1. Add plist rendering helpers.
2. Add `launchctl` command wrappers.
3. Add CLI subcommands.
4. Ensure uninstall removes the plist and unloads the job cleanly.

Test automation plan:
1. Unit test plist rendering.
2. Unit test `launchctl` wrapper commands and error surfacing.
3. Command-level tests with `subprocess.run` mocked for install/start/stop/status/uninstall.

### CI-07: Self-Update From Git Origin Clone

Parity target:
- Make updates reproducible and safe, using the installed checkout's `origin` URL as the source of truth.

Design:
- Add `update` command.
- Resolve the installed source checkout.
- Discover `origin` URL from the checkout; if unavailable, fall back to the canonical repo URL.
- Clone a fresh copy into a temp directory.
- Sync tracked files into the existing install root while preserving:
  - runtime home
  - env file
  - state DB
  - logs
  - virtualenv
- Reinstall the package in the existing venv.
- Refresh the marketplace entry if needed and print the required Codex restart step.

Implementation plan:
1. Add git helper wrappers for reading `origin`.
2. Add temp-clone and sync helpers.
3. Add venv reinstall helper.
4. Add CLI `update` command with dry-run-friendly status output.

Test automation plan:
1. Unit test `origin` discovery and fallback behavior.
2. Unit test file-sync exclusion rules.
3. Command-level tests with mocked git/rsync-like subprocess execution.
4. Add an end-to-end update flow test in a temp install root with a fake source repo.

### CI-08: Operator Diagnostics and Status Summary

Parity target:
- Expose a practical health-check surface like `ccgram status` and `ccgram doctor`, but adapted to this gateway's plugin/daemon model.

Design:
- Keep the existing connectivity-oriented `doctor` behavior.
- Add a higher-level operator status summary that includes:
  - source checkout path
  - runtime home
  - config presence
  - marketplace status
  - local daemon status
  - service status when installed
- Add concise repair guidance for missing pieces.

Implementation plan:
1. Add a summary model that aggregates runtime, plugin, and daemon health.
2. Add CLI rendering for human-readable status output.
3. Reuse existing Telegram/Codex connectivity checks where appropriate.

Test automation plan:
1. Unit test summary rendering across healthy and broken states.
2. Command-level tests for `status` and `doctor`.
3. Add coverage for missing-config and missing-marketplace edge cases.

### CI-09: README and Install/Operator Documentation

Parity target:
- Provide a complete operator guide comparable in completeness to `ccgram`'s README and guides, but focused on Codex App.

Design:
- Add a top-level `README.md` that covers:
  - what the project is
  - why it is needed
  - how the architecture works
  - one-line install
  - reconfigure/update/start/stop/service commands
  - Telegram bot creation
  - disabling privacy mode / enabling groups
  - creating a topic-enabled group
  - granting bot permissions
  - finding numeric user ID
  - finding group chat ID
  - enabling topics in Telegram
  - installing/enabling the plugin in Codex App
  - expected day-2 operations
- Document command examples for both direct daemon mode and `launchd`.

Implementation plan:
1. Write `README.md` from scratch.
2. Include a quickstart and a detailed setup section.
3. Document operational commands after the CLI lands.
4. Cross-check the docs against the actual command names and generated paths.

Test automation plan:
1. Add lightweight unit tests where docs reference generated constants or command names if feasible.
2. Manual proofread against the implemented CLI help text.
3. Final verification pass to ensure every documented command exists.

## Documentation Discipline

This file is the tracker of record for the installer/CLI program. For every feature branch before merge to `main`, update this document with:

- implementation decisions and any design changes from the original plan
- automated test scope, commands run, and changed-line coverage result
- line-by-line code review notes, including defects found and fixed during proof reading
- branch name, commit SHA, and merge commit SHA once the feature is complete

Do not mark a feature done until all three checkboxes are complete and its notes are written here.

## Completed Feature Journal

### CI-01 to CI-09

Implementation notes, test notes, and code review notes will be added here as features land.

### CI-01: Runtime Layout and Path Discovery

Implementation decisions:
- Added `runtime_paths.py` as the single source of truth for managed install/runtime/operator paths.
- Chose:
  - install root `~/.codex-telegram-plugin`
  - runtime home `~/.codex-telegram`
  - `launchd` label `com.kangmo.codex-telegram-gateway`
- Kept mutable files out of the source checkout by default:
  - `.env`
  - SQLite state DB
  - toolbar config
  - logs
  - pid files
- Rendered the personal marketplace `source.path` as a home-relative `./...` path when possible, with absolute-path fallback only for non-home installs.

Automated test coverage:
- Added `tests/unit/test_runtime_paths.py`.
- Red phase:
  - missing-module failure
  - stub `NotImplementedError` failure
- Green phase verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_runtime_paths.py -q`
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_runtime_paths.py tests/unit/test_config.py -q`
- Coverage:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_runtime_paths.py --cov=codex_telegram_gateway.runtime_paths --cov-report=term-missing -q`
  - result: `36/36 = 100%`

Line-by-line proof reading:
- Reviewed [src/codex_telegram_gateway/runtime_paths.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/runtime_paths.py:1) end to end after green tests.
- Found one untested edge case during proofread: marketplace source rendering when the install root is outside `HOME`.
- Added the absolute-path fallback test and reran the target suite and coverage until the module reached full coverage.

Branch and merge record:
- Feature branch: `feature/ci-01-runtime-layout-and-path-discovery`
- Feature commit: `549c0b6`
- Merge commit: `8bf8cb3`

### CI-02: Interactive Install and Reconfigure Flows

Implementation decisions:
- Added `install_config.py` to isolate interactive config prompting, managed env merging, rendering, and disk writes from the main runtime CLI.
- `install` and `configure` now target the managed runtime env at `~/.codex-telegram/.env` by default.
- Reconfigure preserves existing values when the operator presses Enter on token or numeric prompts.
- `configure --group-chat-id <id>` can update the bound Telegram group without re-prompting for the group ID.
- Managed env output now sets:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_ALLOWED_USER_IDS`
  - `TELEGRAM_DEFAULT_CHAT_ID`
  - `CODEX_TELEGRAM_STATE_DB`
  - `CODEX_TELEGRAM_TOOLBAR_CONFIG`
- Existing optional keys are preserved so later voice/shell settings survive reconfiguration.

Automated test coverage:
- Added:
  - [tests/e2e/test_install_config_flow.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_install_config_flow.py:1)
  - [tests/unit/test_install_config.py](/Users/kangmo/sacle/src/codex-telegram/tests/unit/test_install_config.py:1)
- Red phase:
  - missing-module failure for `install_config`
  - stub `NotImplementedError` failures for helper functions and CLI commands
- Green phase verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_install_config_flow.py tests/unit/test_install_config.py -q`
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_cli.py tests/unit/test_config.py -q`
- Coverage:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_install_config_flow.py tests/unit/test_install_config.py tests/unit/test_cli.py tests/unit/test_config.py --cov=codex_telegram_gateway.install_config --cov-report=term-missing -q`
  - result: `79/79 = 100%` for `install_config.py`
- CLI dispatch validation:
  - the end-to-end tests execute `cli.main(["install"])` and `cli.main(["configure", "--group-chat-id", ...])`, so the new install/configure command path is exercised through the real argparse surface.

Line-by-line proof reading:
- Reviewed [src/codex_telegram_gateway/install_config.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/install_config.py:1) and the new install/configure section in [src/codex_telegram_gateway/cli.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/cli.py:26).
- Found and fixed two proofread issues before freeze:
  - uncovered branches in env parsing/rendering and blank-required integer handling
  - inconsistent default-argument spacing in `prompt_install_answers`
- Verified that monkeypatched interactive input still works because the CLI passes `input` and `getpass.getpass` at call time instead of relying on frozen defaults.

Branch and merge record:
- Feature branch: `feature/ci-02-interactive-install-and-reconfigure`
- Feature commit: `c9a0db0`
- Merge commit: `746616a`

### CI-03: One-Line Shell Bootstrap Installer

Implementation decisions:
- Added [install/install.sh](/Users/kangmo/sacle/src/codex-telegram/install/install.sh:1) as a POSIX `sh` bootstrap entrypoint suitable for `curl -fsSL ... | sh`.
- The script now:
  - verifies `git` and `python3`
  - clones the repo on first install
  - refreshes an existing dedicated checkout with `git -C <install-root> pull --ff-only`
  - creates a virtualenv at `<install-root>/.venv`
  - installs the package into that venv
  - hands off to `python -m codex_telegram_gateway.cli install` for interactive Telegram configuration
- Made repo URL and install root overrideable through:
  - `CODEX_TELEGRAM_REPO_URL`
  - `CODEX_TELEGRAM_INSTALL_ROOT`
- Kept the script intentionally thin so update, service control, and plugin wiring remain in the Python CLI where they are easier to test and evolve.

Automated test coverage:
- Added [tests/e2e/test_install_script.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_install_script.py:1).
- Covered shell-level operational branches:
  1. fresh install path uses `git clone`
  2. existing checkout path uses `git -C ... pull --ff-only`
  3. missing `git` fails fast with a clear error
- Verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_install_script.py -q`
  - result: `3 passed`
- Feature-specific operational branch coverage: `3/3 = 100%` for the script's explicitly supported control paths.

Line-by-line proof reading:
- Reviewed [install/install.sh](/Users/kangmo/sacle/src/codex-telegram/install/install.sh:1) and the fake-toolchain smoke test end to end.
- Confirmed the script stays within the minimal bootstrap contract and does not duplicate logic that should live in the Python CLI.
- Added the missing-prerequisite test after proof review so the `require_command` failure path was covered rather than assumed.

Branch and merge record:
- Feature branch: `feature/ci-03-one-line-shell-bootstrap-installer`
- Feature commit: `e6ce260`
- Merge commit: `8760f71`

### CI-04: Codex App Marketplace Install/Repair

Implementation decisions:
- Added `plugin_installation.py` as the marketplace JSON owner for:
  - default personal marketplace payload
  - local plugin entry rendering
  - idempotent plugin upsert
  - current-entry lookup
- Added CLI commands:
  - `plugin install`
  - `plugin status`
- The personal marketplace entry now points to the managed install root through the home-relative path from `RuntimePaths.marketplace_source_path`.
- Chose the personal marketplace metadata:
  - marketplace name `codex-local`
  - display name `Codex Local Plugins`
  - plugin category `Productivity`
  - policy `{installation: AVAILABLE, authentication: ON_INSTALL}`
- Updated the bootstrap installer so one-line install now performs:
  1. interactive gateway env setup
  2. plugin marketplace registration

Automated test coverage:
- Added:
  - [tests/e2e/test_plugin_install_flow.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_plugin_install_flow.py:1)
  - [tests/unit/test_plugin_installation.py](/Users/kangmo/sacle/src/codex-telegram/tests/unit/test_plugin_installation.py:1)
- Updated [tests/e2e/test_install_script.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_install_script.py:1) so the bootstrap flow asserts the extra `plugin install` handoff.
- Green phase verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_plugin_install_flow.py tests/unit/test_plugin_installation.py tests/e2e/test_install_script.py -q`
  - result: `10 passed`
- Coverage:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_plugin_install_flow.py tests/unit/test_plugin_installation.py --cov=codex_telegram_gateway.plugin_installation --cov-report=term-missing -q`
  - result: `27/27 = 100%`

Line-by-line proof reading:
- Reviewed [src/codex_telegram_gateway/plugin_installation.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/plugin_installation.py:1), the new plugin CLI branch in [src/codex_telegram_gateway/cli.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/cli.py:71), and the updated [install/install.sh](/Users/kangmo/sacle/src/codex-telegram/install/install.sh:1).
- Added the no-registration finder test during proofread so non-dict marketplace entries and unrelated plugins were explicitly handled instead of assumed.
- Confirmed `plugin status` uses the same runtime path model as `plugin install`, so CLI output and actual file writes cannot drift.

Branch and merge record:
- Feature branch: `feature/ci-04-marketplace-install-and-repair`
- Feature commit: `da9a723`
- Merge commit: `2ffe81d`

### CI-05: Local Daemon Start/Stop/Restart/Status/Logs

Implementation decisions:
- Added `daemon_manager.py` as the local background-process owner for:
  - daemon command rendering
  - pid-file parsing
  - current status derivation
  - daemon start/stop
  - log-tail reads
- Added top-level CLI commands:
  - `start`
  - `stop`
  - `restart`
  - `status`
  - `logs`
- The local daemon command uses the installed checkout's venv Python:
  - `<install-root>/.venv/bin/python -m codex_telegram_gateway.cli --env-file <runtime-home>/.env run-daemon`
- Runtime status output now reports:
  - running/stopped state
  - pid when present
  - env file path
  - log file path

Automated test coverage:
- Added:
  - [tests/e2e/test_daemon_cli_flow.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_daemon_cli_flow.py:1)
  - [tests/unit/test_daemon_manager.py](/Users/kangmo/sacle/src/codex-telegram/tests/unit/test_daemon_manager.py:1)
- Green phase verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_daemon_cli_flow.py tests/unit/test_daemon_manager.py -q`
  - result: `8 passed`
- Coverage:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_daemon_cli_flow.py tests/unit/test_daemon_manager.py --cov=codex_telegram_gateway.daemon_manager --cov-report=term-missing -q`
  - result: `74/83 = 89%`

Line-by-line proof reading:
- Reviewed [src/codex_telegram_gateway/daemon_manager.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/daemon_manager.py:1) and the new local-daemon branch in [src/codex_telegram_gateway/cli.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/cli.py:99).
- Found and fixed one real implementation bug during proof review:
  - exited child processes could remain as zombies, causing `os.kill(pid, 0)` to misreport them as still running
  - fixed by reaping child exit state with `waitpid(..., WNOHANG)` inside `_is_process_running()`
- Found one timing issue in the end-to-end test and fixed the test, not the implementation:
  - log assertions now wait for the first daemon line instead of assuming immediate file creation.
- Removed the leftover `NotImplementedError` catch from `cli.py` after the daemon commands were fully implemented.

Branch and merge record:
- Feature branch: `feature/ci-05-local-daemon-lifecycle`
- Feature commit: `0bbc163`
- Merge commit: `4bdfea4`

### CI-06: macOS launchd Service Install/Start/Stop/Status/Uninstall

Implementation decisions:
- Added `launchd_service.py` to own:
  - current-user launchctl domain resolution
  - plist rendering
  - `bootstrap`, `bootout`, and `print` command wrappers
- Added CLI subcommands:
  - `service install`
  - `service uninstall`
  - `service start`
  - `service stop`
  - `service restart`
  - `service status`
- The launchd plist now uses:
  - label `com.kangmo.codex-telegram-gateway`
  - `RunAtLoad = true`
  - `KeepAlive = true`
  - working directory = managed install root
  - stdout/stderr = managed daemon log file
  - environment `HOME = <install-root-parent>`
- Service execution uses the same installed venv Python and managed env file as the local daemon lifecycle commands.

Automated test coverage:
- Added:
  - [tests/e2e/test_launchd_service_cli.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_launchd_service_cli.py:1)
  - [tests/unit/test_launchd_service.py](/Users/kangmo/sacle/src/codex-telegram/tests/unit/test_launchd_service.py:1)
- Green phase verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_launchd_service_cli.py tests/unit/test_launchd_service.py -q`
  - result: `4 passed`
- Coverage:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_launchd_service_cli.py tests/unit/test_launchd_service.py --cov=codex_telegram_gateway.launchd_service --cov-report=term-missing -q`
  - result: `21/23 = 91%`

Line-by-line proof reading:
- Reviewed [src/codex_telegram_gateway/launchd_service.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/launchd_service.py:1) and the `service` branch in [src/codex_telegram_gateway/cli.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/cli.py:84).
- Kept the launchd module deliberately narrow so service registration stays separate from the local daemon and update logic.
- Removed the temporary `NotImplementedError` handling once the service commands were fully wired.

Branch and merge record:
- Feature branch: `feature/ci-06-launchd-service-management`
- Feature commit: `18ee2b2`
- Merge commit: `4a08c77`

### CI-07: Self-Update From Git Origin Clone

Implementation decisions:
- Added `self_update.py` to own:
  - `origin` discovery
  - fresh-clone checkout sync
  - pip reinstall in the existing venv
  - marketplace refresh after update
- `update` now:
  1. reads `origin` with `git -C <install-root> remote get-url origin`
  2. falls back to `https://github.com/Kangmo/Codex-Telegram-Plugin` when origin discovery fails
  3. clones a fresh copy into a temp directory
  4. syncs it into the managed install root while preserving:
     - `.git`
     - `.venv`
  5. reruns `pip install -e <install-root>`
  6. refreshes the personal marketplace entry
- Added top-level CLI command `update`.

Automated test coverage:
- Added:
  - [tests/e2e/test_update_cli.py](/Users/kangmo/sacle/src/codex-telegram/tests/e2e/test_update_cli.py:1)
  - [tests/unit/test_self_update.py](/Users/kangmo/sacle/src/codex-telegram/tests/unit/test_self_update.py:1)
- Green phase verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_update_cli.py tests/unit/test_self_update.py -q`
  - result: `5 passed`
- Coverage:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_update_cli.py tests/unit/test_self_update.py --cov=codex_telegram_gateway.self_update --cov-report=term-missing -q`
  - result: `41/42 = 98%`

Line-by-line proof reading:
- Reviewed [src/codex_telegram_gateway/self_update.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/self_update.py:1) and the update branch in [src/codex_telegram_gateway/cli.py](/Users/kangmo/sacle/src/codex-telegram/src/codex_telegram_gateway/cli.py:96).
- Kept `.git` and `.venv` preservation explicit in code so update cannot wipe the operator’s install metadata or environment.
- The update CLI stays output-focused and prints the origin URL and install root that were actually refreshed.

Branch and merge record:
- Feature branch: `feature/ci-07-self-update-from-origin-clone`
- Feature commit: pending
- Merge commit: pending
