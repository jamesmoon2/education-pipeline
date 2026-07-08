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
- Done: stronger spec prompt contract and tests.
- Done: the run prompt writer (`RunStore`) creates run directories, writes the
  spec prompt, drops a `SAVE_RESPONSE_HERE` stub, and logs manifest events;
  stubs never count as ingested responses.
- Done: topic artifact model (`Topic`), TOML parser, and workspace-local
  `TopicStore` that preserves imported TOML text.
- Done: stored topics drive spec prompt compilation
  (`compile_topic_spec_prompt` and `RunStore.write_topic_spec_prompt`), rendering
  rich topic fields into the prompt's Topic section.
- Next: extend prompt compilation and the run writer to outline, draft, QA, and
  repair stages.

## Phase 4: Model Plan UI

- Add provider/runtime selection for Claude Code, Codex, and manual prompt-only
  workflows.
- Add per-stage model dropdowns with recommendations.
- Keep model catalogs configurable because provider model names change.

## Phase 5: Local App Polish

- Add project settings, stage logs, file links, final preview, and robust port
  handling.
