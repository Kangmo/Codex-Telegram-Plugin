# Task Plan: ccgram Feature Sweep

## Goal
Adopt as many high-value Telegram gateway behaviors from `ccgram` as fit the current Codex App architecture, with working code and tests.

## Phases
- [x] Phase 1: Review current gateway and `ccgram` source
- [x] Phase 2: Port the highest-value missing behaviors
- [x] Phase 3: Test and document the sweep

## Key Questions
1. Which `ccgram` behaviors transfer directly to a Codex App gateway without tmux/session infrastructure?
2. Which missing Telegram-side UX pieces matter most right now?
3. Which `ccgram` features depend on tmux/provider hooks and therefore should not be copied blindly?

## Decisions Made
- Focus this pass on Telegram-native features that fit the current architecture: command handling, command menu registration, topic/title sync, and in-place message growth.
- Do not try to port tmux-, pane-, or provider-specific `ccgram` flows into this Codex App gateway.
- Keep one topic mapped to one Codex thread, and use commands to create/rebind threads within that constraint.

## Errors Encountered

## Status
**Completed** - the gateway now includes a broader `ccgram`-style Telegram UX surface on top of the Codex App bridge:
- bot command menu registration
- topic commands: `/new`, `/start`, `/project`, `/status`, `/sessions`, `/sync`, `/commands`, `/help`
- in-place Telegram message growth for active Codex assistant blocks
- automatic adoption of newly loaded Codex App threads during sync
- `/sync` audit and fix flow for unbound loaded threads and deleted Telegram topics
- `/sessions` dashboard with refresh

Remaining live step:
- restart or reload the running Codex App plugin process if you want the installed plugin instance to pick up the latest code immediately
