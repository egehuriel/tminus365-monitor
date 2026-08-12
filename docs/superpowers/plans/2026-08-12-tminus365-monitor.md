# T-Minus365 Monitor Implementation Plan

**Goal:** Verify cloud transcript extraction through Supadata, then enable safe
scheduled monitoring without duplicate transcript requests.

## Phase 1: Controlled cloud proof

- [x] Keep the existing T-Minus365 RSS/channel ID.
- [x] Replace the YouTube transcript library with Supadata's authenticated API.
- [x] Read `SUPADATA_API_KEY` only from the Actions secret environment.
- [x] Parse RSS and call Supadata with Python's standard library.
- [x] Add network-free tests for Atom parsing, request construction, transcript
  parsing, missing configuration, and output formatting.
- [x] Make the workflow manual-only during the first Supadata test.
- [ ] Push and manually dispatch the workflow.
- [ ] Confirm the cloud log contains a nonempty English transcript.

## Phase 2: Safe schedule

- [x] Add a persisted last-processed video ID.
- [x] Skip Supadata when the latest feed video was already processed.
- [x] Persist state only after transcript extraction succeeds.
- [x] Restore the 30-minute GitHub Actions schedule.
- [ ] Verify one new-video run and one duplicate-skip run.

## Deferred

- Power Automate handoff
- AI classification
- Teams delivery
