# Archived Roadmap

> Archived on 2026-07-11. This roadmap records the initial extraction and
> pipeline build. It is superseded by `../product-requirements.md`.

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
- Done: QA stage. `compile_qa_prompt` / `RunStore.write_qa_prompt` build a review
  prompt that embeds the approved spec, outline, and draft (via a multi-section
  builder) and asks for a findings report with a verdict, outcome coverage, and
  repair instructions.
- Done: repair stage. `compile_repair_prompt` / `RunStore.write_repair_prompt`
  build a prompt that applies the approved QA findings to the approved draft and
  returns the corrected draft in full. This closes the authoring loop:
  `spec -> outline -> draft -> qa -> repair` runs end to end through approvals.
- Done: finalize step. `RunStore.finalize_run` is a deterministic local step (not
  an LLM prompt stage) that assembles the approved repair draft into
  `final/guide.md`, records a `finalized` manifest event, and flips
  `run_status.finalized`; `next_action` reports `finalize` once every stage is
  approved and `done` once the guide is written.
- Done: run driver. `RunStore.advance` performs the run's next machine step
  (writing the next stage prompt, or finalizing) and pauses at human steps
  (saving a response, approving it). Called repeatedly it drives a run forward
  and resumes it from disk, so a fresh session picks up exactly where an earlier
  one stopped. This is the API a CLI or UI would sit on.
- Done: export. `RunStore.export_run(topic_id, format=...)` is an optional
  deterministic step after finalize. `format="markdown"` writes a
  `final/guide.bundle.md` with a front-matter provenance block; `format="html"`
  writes a self-contained `final/guide.html` via a stdlib-only Markdown-subset
  renderer (`render_markdown_to_html`). Both formats stay dependency-free.
- Done: resumable run state. Every artifact (topic, profile snapshot, prompts,
  responses, approved copies, manifest events) is persisted per stage, and the
  writers refuse to clobber saved work by default. `RunStore.run_status` /
  `stage_status` / `list_run_ids` read only the workspace filesystem, so a fresh
  session (for example after running out of tokens) recovers exactly where work
  left off and `next_action` names the next step to take.
- Done: CLI. `education_pipeline.cli` (also `python -m education_pipeline` and the
  `education-pipeline` console script) is a stdlib-only argparse wrapper over the
  API: `topic`/`profile` import/list/attach, plus `status`, `advance`, `approve`,
  `finalize`, and `export`. It drives a whole run from the terminal and doubles
  as an end-to-end check of the engine.
- Next: the GUI over the same API (`run_status`/`advance`/`approve`/`export`),
  plus profile privacy warnings for API/UI consumers.

## Phase 4: Model Plan UI

- Add provider/runtime selection for Claude Code, Codex, and manual prompt-only
  workflows.
- Add per-stage model dropdowns with recommendations.
- Keep model catalogs configurable because provider model names change.

## Phase 5: Local App Polish

- Add project settings, stage logs, file links, final preview, and robust port
  handling.
