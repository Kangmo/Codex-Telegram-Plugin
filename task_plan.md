# Task Plan: Installer and Operations CLI

## Goal
Ship a production-ready installer and operator CLI for the Codex App Telegram gateway, including one-line install, reconfiguration, update, daemon control, launchd service registration, plugin marketplace wiring, and complete operator documentation.

## Phases
- [x] Phase 1: Review current gateway runtime, existing docs, official Codex plugin install docs, and `ccgram` CLI/service patterns
- [x] Phase 2: Write the dedicated installer/CLI feature tracker markdown
- [ ] Phase 3: Implement installer and operations features one by one with tests, code review notes, and branch/merge discipline
- [ ] Phase 4: Update `README.md` with complete setup and operating instructions
- [ ] Phase 5: Run full verification and finalize deliverables

## Key Questions
1. What runtime layout cleanly separates source, config, logs, and state for a user-installed gateway?
2. Which CLI commands are needed for a practical day-2 operations surface on macOS?
3. How should plugin marketplace installation be automated while staying consistent with Codex plugin docs?
4. How should self-update preserve user configuration and local runtime state?

## Decisions Made
- Keep the gateway source checkout separate from mutable runtime data.
- Use a dedicated interactive CLI flow for first install and later reconfiguration instead of asking users to hand-edit `.env`.
- Support both direct background daemon control and `launchd` registration on macOS.
- Base the local plugin install flow on the official personal marketplace mechanism in the Codex plugin docs.
- Make `update` refresh from the repository `origin` URL by cloning a fresh checkout, then syncing files into the installed source tree.

## Errors Encountered
- The repo currently has no top-level `README.md`; the new operator guide will need to be written from scratch rather than updated in place.

## Status
**Phase 3** - CI-03 one-line bootstrap installer is complete on its feature branch; next up is Codex App marketplace install and repair commands.
