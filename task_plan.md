# Task Plan: ccgram Parity Planning

## Goal
Produce a feature-by-feature parity plan for the missing `ccgram` Telegram gateway behaviors, with detailed design, implementation, and automated test strategy.

## Phases
- [x] Phase 1: Review current gateway and `ccgram` source
- [x] Phase 2: Enumerate missing and partial-parity features
- [x] Phase 3: Write the dedicated parity plan document
- [x] Phase 4: Update notes and deliver the plan path

## Key Questions
1. Which `ccgram` features are directly portable to a Codex App gateway?
2. Which features need an app-native redesign rather than a tmux-style port?
3. Which features should remain compatibility-only or deferred?

## Decisions Made
- Keep the parity plan separate from the older implementation plan so the `ccgram` gap review stays actionable.
- Preserve `codex_thread_id <-> telegram topic id` as the primary routing model.
- Mark tmux-only features as adapted or compatibility-only rather than pretending direct parity exists.

## Errors Encountered

## Status
**In progress** - parity implementation is underway from highest priority to lowest priority. `ccgram_feature_parity_plan.md` is the tracker of record and implementation journal. FP-01 through FP-09, FP-11, FP-13, FP-17, FP-18, FP-19, FP-20, FP-21, FP-24, FP-25, and FP-26 are complete and merged to `main`. The next highest-priority unfinished feature is FP-27 inline query support.
