# Roadmap

## Phase 1: Public Skeleton

- Establish package, docs, tests, examples, and config directories.
- Add license, contributing guide, security policy, and CI.
- Add fixture-only test data.

## Phase 2: Generic Core Extraction

- Extract reusable pipeline code.
- Keep user workspace data out of the package repo.
- Add tests before changing stage behavior.

## Phase 3: Learner Profile Stage

- Add `profile -> spec` as the first pipeline stage.
- Store profiles locally by default.
- Thread profile context into prompts without publishing private details.

Current status:

- Done: learner profile parser and synthetic fixture.
- Done: learning preferences, including visual-aid preferences.
- Done: private prompt-context rendering and explicit public-summary guardrail.
- Done: workspace-local profile storage and snapshot attachment to
  `runs/<topic-id>/inputs/profile.toml`.
- Done: spec prompt compilation from topic fields plus attached profile
  snapshot.
- In progress: stronger spec prompt contract and tests.
- Next: add the generic stage/run prompt writer that creates run directories,
  prompt files, response stubs, and manifest events.

## Phase 4: Model Plan UI

- Add provider/runtime selection for Claude Code, Codex, and manual prompt-only
  workflows.
- Add per-stage model dropdowns with recommendations.
- Keep model catalogs configurable because provider model names change.

## Phase 5: Local App Polish

- Add project settings, stage logs, file links, final preview, and robust port
  handling.
