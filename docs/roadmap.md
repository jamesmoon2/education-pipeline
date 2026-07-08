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
- Done: outline stage. `RunStore.approve_stage` promotes an ingested response
  into `approved/`, and `compile_outline_prompt` /
  `RunStore.write_outline_prompt` build the outline prompt from the approved
  spec plus the topic and profile.
- Done: draft stage. `compile_draft_prompt` / `RunStore.write_draft_prompt` build
  the draft prompt from the approved outline, reusing the shared
  approved-upstream prompt builder that outline uses.
- Done: resumable run state. Every artifact (topic, profile snapshot, prompts,
  responses, approved copies, manifest events) is persisted per stage, and the
  writers refuse to clobber saved work by default. `RunStore.run_status` /
  `stage_status` / `list_run_ids` read only the workspace filesystem, so a fresh
  session (for example after running out of tokens) recovers exactly where work
  left off and `next_action` names the next step to take.
- Next: extend prompt compilation and the run writer to QA and repair stages,
  reusing the same approval-driven chaining.

## Phase 4: Model Plan UI

- Add provider/runtime selection for Claude Code, Codex, and manual prompt-only
  workflows.
- Add per-stage model dropdowns with recommendations.
- Keep model catalogs configurable because provider model names change.

## Phase 5: Local App Polish

- Add project settings, stage logs, file links, final preview, and robust port
  handling.
