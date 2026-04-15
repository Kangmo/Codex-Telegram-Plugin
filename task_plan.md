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
- Run repo validation with `.venv/bin/pytest` because the shell default `python` points at Anaconda 3.9 while this project requires Python 3.11.

## Errors Encountered
- Shell defaulted to `/opt/anaconda3/bin/python` (Python 3.9), which caused false collection failures on `str | None` annotations; resolved by using the repo-local `.venv` and its Python 3.11 toolchain.

## Status
**In progress** - parity implementation is underway from highest priority to lowest priority. `ccgram_feature_parity_plan.md` is the tracker of record and implementation journal. FP-01 through FP-09, FP-11, FP-12, FP-13, FP-14, FP-16, FP-17, FP-18, FP-19, FP-20, FP-21, FP-24, FP-25, FP-26, and FP-27 are complete. The next highest-priority unfinished feature is FP-22 live view.
