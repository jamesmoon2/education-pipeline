# Per-Module Drafting and Section-Level Repair — Design

- **Date:** 2026-09-18
- **Status:** Draft for review — plan at
  [`docs/superpowers/plans/2026-09-18-phase-2-per-module-drafting.md`](../plans/2026-09-18-phase-2-per-module-drafting.md)
- **Branch:** `claude/p2-engineering-manager-t3zfhe`
- **Source:** the 2026-09-17 opportunity map (item A, "Build plan · Phase 2").
- **Related:** stage graph ([`../plans/2026-09-17-phase-1-stage-graph.md`](../plans/2026-09-17-phase-1-stage-graph.md)),
  blueprint pedagogy and the module splice
  ([`2026-07-16-blueprint-pedagogy-design.md`](2026-07-16-blueprint-pedagogy-design.md)),
  provider run daemon ([`2026-07-09-provider-run-daemon-design.md`](2026-07-09-provider-run-daemon-design.md)),
  guide schema ([`2026-07-11-interactive-guide-v1-schema.md`](2026-07-11-interactive-guide-v1-schema.md)).

## Summary

Today the `draft` stage asks the model for the entire guide JSON in one
response, and `repair` re-emits either the whole guide or one module. Course
length is therefore bounded by what one model response can carry, a failed
draft costs the whole course, and the single worker thread has nothing to
parallelize.

This design lets a run opt into a **modular draft strategy**: the draft stage
becomes one small *frame* job (course, outcomes, glossary, sources, module
stubs) followed by *N module jobs* that run in parallel against the outline's
per-module contract. A deterministic assembly step splices the parts into the
one `responses/draft.response.json` the rest of the pipeline already consumes.
Everything downstream of that file (draft validation, approval, qa, factcheck,
repair, finalize, export) is unchanged, and approval stays one explicit human
gate over the assembled guide. Repair additionally gains a **section** scope
so that a finding at `/modules/N/sections/M` can be fixed by regenerating one
section instead of one module.

```
whole   (today):   outline ──► draft prompt ──► one response ──► approve
modular (new):     outline ──► frame prompt ──► frame response ─┐
                                     ├─► module m1 prompt ──► m1 response ─┤
                                     ├─► module m2 prompt ──► m2 response ─┼─► assemble ──► responses/draft.response.json ──► validate ──► approve
                                     └─► module mN prompt ──► mN response ─┘
```

## Goal and exit criterion

A guide-v1 run created with `draft_strategy = "modular"` reaches an approved
draft through N+1 model responses, each bounded by one module's size rather
than the course's; the shipped example regenerates byte-identically through
that path; a validation finding inside one section can be repaired by
regenerating only that section, with every other byte of the guide preserved.
Nothing auto-approves. Runs that never opt in behave exactly as today.

## Current state (verified 2026-09-18 at `55cfc82`)

- `compile_guide_v1_draft_prompt(topic, approved_outline, guide_contract, profile=None, *, blueprint=None)`
  (`prompts.py:856`) embeds the whole approved outline and the contract JSON
  and demands one whole guide object (`_GUIDE_DRAFT_OUTPUT_AND_QUALITY_LINES`,
  `prompts.py:530`).
- The outline carries a machine-readable module contract
  (`prompts.py:462`, validated by `guides/contract.py:201`): `modules:
  {<id>: {outcome_ids, estimated_minutes, interaction_types}}`, merged with the
  spec contract into `inputs/guide-contract.json` by `build_guide_contract`
  (`contract.py:331`). Module ids match `^[a-z][a-z0-9-]{0,63}$`.
- Module repair already has the shape a module job needs:
  `compile_guide_v1_module_repair_prompt` (`prompts.py:1188`) asks for exactly
  one module object with the same `id`, and `splice_module`
  (`guides/canonical.py:50`) replaces it in place, refuses renames, re-parses
  the merged guide strictly and returns canonical bytes.
  `write_module_repair_prompt` (`runs.py:1776`) records
  `{"repair_module": id}` on the `prompt_written` event; `approve_stage`
  (`runs.py:1051`) splices on approve via `repair_scope` (`:1110`) and
  `_spliced_scoped_repair` (`:1124`).
- Stage files: `stage_paths` (`runs.py:350`) yields
  `prompts/<stage>.prompt.md`, `responses/<stage>.response.json`,
  `approved/<stage>.json`. Manifest events (`_append_event_locked`,
  `runs.py:2050`) carry `{stage, action, <label>, <label>_sha256, …extra,
  recorded_at}`.
- `NextAction(topic_id, stage, action, detail)` (`run_core.py:88`); `advance`
  (`runs.py:641`) performs only machine steps (`write_prompt`, `validate`,
  `finalize`) and never approves.
- The draft row in `stage_graph.STAGES` (`stage_graph.py:68`) has
  `sources=()`: draft is not stale-tracked against the outline today.
- `Job` (`daemon/jobs.py:46`) has no batch or part notion; `Worker`
  (`:703`) is one thread over a FIFO queue; `JobStore.active_for` (`:258`)
  refuses a second job for the same topic and stage. Enqueue is
  `POST /v1/jobs` `{topic_id, stage?, force?}` (`server.py:600`) via
  `DaemonContext.enqueue_stage` (`server.py:88`). Timeouts come from the plan
  (`effective_timeout_seconds`, `jobs.py:862`).
- Module repair has no route of its own: `POST /v1/runs/{id}/advance` with
  `{"repair_module": id}` (`server.py:659`, `write_api.py:118`). The scope
  picker is `GET /v1/runs/{id}/repair/modules` (`read_api.py:545`), which
  keys findings by the path prefix `^/modules/(\d+)`.
- Cross-module validation rules (id uniqueness, one interaction per module,
  outcome coverage) live in `guides/parse.py:159-172, 709-737`; finding paths
  are index-based (`/modules/<i>/sections/<j>/blocks/<k>`).
- `ModuleRepairControl` is mounted only on the stage viewer
  (`web/src/pages/StageViewerPage.tsx:298`); `PrimaryAction.tsx:59` dispatches
  on `next_action.action`; `continueRun.ts` loops `advance` for machine steps.
- `scripts/build_example.py` drives `examples/feedback-loops/` through the
  whole-guide path; `tests/test_example_project.py` pins byte equality.

## Decisions

### D1. Draft strategy is a per-run, immutable setting; `modular` is opt-in

- `manifest["draft_strategy"]` is `"whole"` or `"modular"`, recorded by
  `create_run` and immutable afterwards (same rule as `content_contract`).
  A manifest without the key reads as `"whole"`, so every existing workspace
  is unchanged. Legacy Markdown runs refuse `modular`.
- Selected at creation: CLI `create --draft-strategy modular`; API
  `POST /v1/runs/{id}/advance` body `draft_strategy`, recorded through
  `create_run` before the step runs exactly as `blueprint` is today
  (`write_api.py:113-117`; there is no create-run route, runs are created by
  the first advance); a radio in the New Run wizard, which already passes
  `blueprint` this way. A later `create_run` without the key on an existing
  manifest leaves it unchanged; a conflicting value raises, as
  `content_contract` does (`runs.py:465-500`). `LegacyMarkdownMode` gets a
  `supports_modular_draft = False` capability flag. The strategy is resolved
  once into a `WholeDraft` / `ModularDraft` object (`draft_strategies.py`,
  selected by `RunStore._draft_strategy(topic)`), with the methods
  `draft_next_action`, `write_prompts(parts=None)`, `part_states(snapshot)`,
  `assemble(force)` and `stage_flags`; `advance`, `_write_stage_prompt`,
  `_next_action_guide_v1` and `stage_status` call the strategy instead of
  branching on the manifest, so each axis (content mode, draft strategy)
  keeps exactly one dispatch site. `write_draft_prompt` on a modular run
  raises `ConfigError` naming the part prompts, since `stage_graph` still
  lists it as the draft `prompt_writer` and the characterization helpers call
  it directly. The default stays `whole` in this phase. Flipping the default is an owner
  decision recorded in the audit ledger, because it multiplies the manual
  copy/paste loop by N+1 and the right default depends on who the users are.

### D2. Two waves: one frame, then N modules in parallel

- **Frame** response: a guide JSON object with `course`, `outcomes`,
  `glossary`, `sources` and one **stub** per contract module, in contract
  order, each carrying `id`, `title`, `summary`, `outcome_ids`,
  `estimated_minutes`, optional `serves_goals`, and `"sections": []`.
- **Module** response: exactly one module object with the contract's `id`
  (the module-repair output contract, reused verbatim). The prompt embeds the
  approved outline, the guide contract, the frame (so the module can cite the
  frame's `sources` and reuse `glossary` ids and knows its siblings), the
  blueprint and the private profile section, and names the one module to
  write.
- Modules cite only sources the frame declared. A module response that needs
  a source the frame lacks is a quality problem for fact-check and repair to
  catch, not an assembly failure. Recorded as an accepted limitation; a later
  additive envelope (`{module, sources, glossary}`) could lift it without
  changing the lifecycle.
- The frame is **never** run through `parse_guide`: the parser requires at
  least one section per module (`guides/parse.py:368`, `c.array(..., 1)`), so
  stubs cannot pass strict parsing. Frame ingest and assembly do one lenient
  shape check on `json.loads` output: a top-level object with exactly the
  root keys `schema_version`, `course`, `outcomes`, `modules`, `glossary`,
  `sources`; `modules` a list of objects whose string `id` values equal the
  contract's module ids in contract order; every stub has `"sections": []`.
  Every other key passes through opaquely; strict validation happens on the
  merged guide at assembly and again at draft validation.
- Why a frame rather than deriving the skeleton from the outline: `course.
  description`, `learner_summary`, module `summary`, glossary definitions and
  the source list are model-written prose that the contract does not carry,
  and parsing them out of the outline Markdown would be brittle. The frame
  is small (no section bodies) and fast.

### D3. Files and the assembled response

```
prompts/draft/frame.prompt.md
prompts/draft/modules/<module-id>.prompt.md
responses/draft/frame.response.json
responses/draft/modules/<module-id>.response.json
responses/draft.response.json            # assembled; unchanged downstream path
approved/draft.json                      # unchanged
```

- `assemble_guide(frame_json, modules: Mapping[str, str], *, module_ids:
  Sequence[str]) -> bytes` (`guides/canonical.py`) is pure: it checks the
  frame stubs are exactly `module_ids` in order, replaces each stub with the
  module object (id must match, `SpliceError` otherwise), re-parses the
  merged guide strictly (so duplicate ids and unknown outcome references are
  refused with parser diagnostics, as `splice_module` does today) and returns
  canonical bytes. Identical inputs yield identical bytes.
- Assembly is a **machine step performed by `advance`** (`NextAction.action
  == "assemble"`), never a side effect of the worker ingesting the last part.
  That keeps one trigger, keeps `advance` the only writer of
  `responses/draft.response.json` on the modular path, and lets the existing
  approve-and-continue chain and CLI `advance` pick it up unchanged.
- `assemble` writes `responses/draft.response.json` through `atomic_io` and
  records `{"stage": "draft", "action": "draft_assembled", "response_file",
  "response_file_sha256", "parts": {"frame": <sha>, "modules": {<id>:
  <sha>}}}`. A later `assemble` compares the file's **current** sha with the
  last `draft_assembled` record's `response_file_sha256`; a difference means
  a hand edit (`edit_response`, or an external write) and raises
  `StaleContentError` unless `force`, which records `response_replaced` as
  ingest does today. Part shas are not part of that check; they decide
  whether assembly is *needed* (D4), not whether it is *safe*. The assembled
  file therefore has three states: `absent`, `matches_record` and `edited`
  (digest differs from the last `draft_assembled` record). `edited` is a
  deliberate hand edit and the walk proceeds to `validate` / `approve`; it
  never yields `assemble` again, so `advance` cannot be steered into an
  action that always raises. The whole-draft response routes
  (`POST`/`PUT /v1/runs/{id}/stages/draft/response`) refuse modular runs
  with `draft_is_modular`; `edit_response` on the assembled file stays
  allowed.
- The final-validation cache (`runs_reports.py`) is keyed on the digest of
  the approved guide bytes, never on the response file, so assembly cannot
  serve a stale report.
- `assemble` joins `write_prompt`, `validate` and `finalize` as a machine
  step in `advance` (`runs.py:641-673`), in the cockpit chain's continue set
  (`web/src/lib/continueRun.ts`) and in the Advance arm of `PrimaryAction`
  (`PrimaryAction.tsx:59`); the `advance` route needs no body for it.
- After assembly the draft stage is exactly where a whole-guide draft is
  after `ingest_response`: `validate` → `approve` → qa, untouched.

### D4. Manifest events per part and per-part staleness

- Draft `prompt_written` / `response_ingested` / `response_replaced` events
  on a modular run carry `part`: `{"kind": "frame"}` or
  `{"kind": "module", "module_id": <id>}`, plus the part's `prompt_file` /
  `response_file` paths and hashes.
- The frame prompt binds `source_outline_file` (approved outline sha) and
  `contract_file` (sha of `inputs/guide-contract.json`). A module prompt binds
  the same two plus `frame_file` (sha of the frame response) and
  `contract_module_sha256`, the sha of the canonical JSON of
  `contract["modules"][<id>]`.
- A **part is stale** when the sha recorded on its latest `prompt_written`
  event differs from the current value: re-approving the outline with an
  unchanged entry for module `m2` leaves `m2` current; a changed entry makes
  only `m2` stale; a changed frame makes every module stale (they embed it).
  Removing a module from the contract orphans its part files (ignored, never
  deleted); adding one creates a missing part.
- Every helper that reads "the latest draft `prompt_written` /
  `response_approved` event" today (`_stale_stage_rebuild_action`
  `runs.py:885`, `_prompt_bound_source_hashes` `:1979`,
  `_recorded_source_shas` `:2108`) picks `events[-1]` by stage and action
  with no notion of parts. One helper, `_latest_event(manifest, stage,
  action, *, part)`, replaces those lookups; whole-draft callers pass
  `part=None` explicitly and therefore never see a part event, and part
  staleness reads events filtered by their part. `approve_stage` on a
  modular run binds nothing from part events (draft has no sources).
- Part status is computed from the manifest snapshot that `read_scope`
  already takes for `run_status_payload` (`read_api.py:389-447`) plus the
  part files' hashes, never by re-reading the manifest per part: one reverse
  pass over `events` builds `{part: latest prompt_written /
  response_ingested}` so a poll tick stays O(events), not O(parts × events).
- `StageStatus` for a modular draft (`stage_status`, `runs.py:599`, today
  keyed on `prompts/draft.prompt.md` and `responses/draft.response.json`
  existence): `prompt_written` is true when every required part prompt is
  current, `response_ingested` when the assembled file is present (any state
  but `absent`); `approved` and `stale` are unchanged. The modular branch
  replaces `draft` **inside** the `_unbound_stages` loop of
  `_next_action_guide_v1` (`runs.py:725-730`), not after it, so
  `_pending_stage_action` never advertises a whole-draft `write_prompt` on a
  modular run.
- The **assembled response is stale** when any part's current response sha
  differs from the `draft_assembled` record, or a contract module has no
  part. `next_action` then reads `assemble` (after the missing or stale parts
  are re-drafted).
- The draft **stage** row in `stage_graph` keeps `sources=()`; the approved
  draft's staleness against the outline stays out of scope (it is not
  tracked today for whole drafts either). Modular staleness is a property of
  parts, surfaced on the status payload, not a change to `StageStatus.stale`.

### D5. Next action and `advance` mid-fan-out

`NextAction` gains one optional field, `wave: str | None = None`
(`"frame"`, `"modules"`, or `None` for every existing case). It is named
`wave` because `part` everywhere else means one `{kind, module_id}` part. On a modular
run whose draft is not yet approved, `_next_action_guide_v1` yields, in order:

| State | `stage` | `action` | `wave` | `detail` |
| --- | --- | --- | --- | --- |
| no frame prompt, or frame stale | draft | `write_prompt` | frame | "draft frame: write prompt" |
| frame prompt current, no response | draft | `save_response` | frame | "draft frame: save the model response to …" |
| frame response current, some module prompt missing or stale | draft | `write_prompt` | modules | "draft modules: write prompts (m2, m4)" |
| every module prompt current, some response missing or stale | draft | `save_response` | modules | "draft modules: 2 of 5 responses saved (waiting: m3, m4, m5)" |
| every part current, assembled file missing or stale | draft | `assemble` | modules | "draft: assemble 5 modules" |
| assembled and current | draft | `validate` / `approve` | None | as today |

`advance` performs `write_prompt` for a part (frame: one prompt; modules:
every missing or stale module prompt in one step) and `assemble`. It never
writes a module prompt before the frame response exists. A `parts` filter
(`advance --parts m2,m4` / body `{"parts": [...]}`) restricts a modules
`write_prompt` to a subset, for reruns. `parts` filters name **module ids
only**; the frame is never a member of a modules-wave filter, so a module
legitimately named `frame` (the id pattern allows it) is unambiguous. The
same rule applies to `POST /v1/jobs/batch` `parts`.

`NextAction` is constructed by keyword everywhere and compared field-wise in
the characterization tests, so the defaulted field is backward compatible;
the three sites that spell its fields out (`run_status_payload`,
`web/src/api/types.ts`, CLI `status`) add `wave`. On the web side
`NextAction.action` and `AdvanceResult.performed` are closed unions
(`types.ts`), so `assemble` is added to both; `continueRun.ts` gains an
`assemble` case, routes a modular draft's `save_response` to the batch
route instead of `POST /v1/jobs`, and raises `MAX_CONTINUE_STEPS` to cover
N+1 parts. `PrimaryAction`'s single-active-job early return becomes
batch-aware.

### D6. Provider execution: batches and a bounded worker pool

- `Job` gains `batch_id: str | None` and `part: {"kind": "frame"} |
  {"kind": "module", "module_id": str} | None`. A part job's prompt and
  response paths are the part's, and its ingest calls
  `RunStore.ingest_part_response(topic, part, text, force=…)`.
- New route `POST /v1/jobs/batch` `{topic_id, stage: "draft", parts?: [...],
  force?}` enqueues the current wave: one frame job, or one job per module
  whose prompt is current and whose response is missing or stale (or the
  `parts` subset, or every module with `force`). Returns `{batch_id, jobs}`.
  `POST /v1/jobs` on a modular draft refuses with catalog error
  `draft_is_modular` pointing at the batch route, so the two enqueue paths
  never race. `POST /v1/jobs/batch/{batch_id}/cancel` cancels every queued or
  running job in the batch. CLI `run` calls the batch route on modular
  drafts and prints the job list; `cancel --batch <id>` maps to batch cancel.
- `Worker` becomes a pool of `parallelism` threads over the same queue.
  `parallelism` is read from the model plan (`[jobs] parallelism = 2`,
  integer 1..4, default 2, validated in `parse_model_plan`; the settings
  page exposes it). Admission: jobs in one batch may run concurrently;
  otherwise `active_for(topic, stage)` keeps refusing a second job for the
  same topic and stage, and a batch is refused while a non-batch job for the
  same topic is active. Jobs for different topics may run concurrently up to
  the pool size (an intended consequence, bounded by the same setting).
- Admission key becomes `(topic, stage, part)` (`Worker.enqueue` refuses a
  duplicate per key, `jobs.py:738`); a batch is admitted all-or-nothing
  inside one `Worker._lock` critical section, so a partially admitted batch
  cannot exist. `Worker.stop` enqueues one sentinel per thread and joins
  every thread. Every pool thread uses the one shared `DaemonContext.runs`
  store (as `_runner_for` already does, `daemon/__init__.py:140`) because
  `_manifest_write_lock` is per instance and the workspace file lock is
  reentrant per process, so it gives no thread exclusion.
- `[jobs] parallelism` is round-tripped as one unit by `parse_model_plan`,
  `emit_model_plan_toml`, `plan_payload`, `PUT /v1/config/plan` and the
  settings page (today the settings save rewrites the file from
  `{provider, stages}` only, `write_api.py:783`, and would drop it). The pool
  size is read at `worker.start()`; a change takes effect on daemon restart
  and the settings page says so.
- Part salvage files live beside the part
  (`responses/draft/modules/<id>.failed.<ts>.txt`,
  `responses/draft/frame.failed.<ts>.txt`); the resolver
  (`_require_failed_output`, `write_api.py:330`) gains a part-aware variant
  keyed to the part directory, and they are listed on
  `draft_parts[].failed_outputs`, not `stages[].failed_outputs`.
- Pool internals: `Worker` keeps `_running: dict[str, Job]` instead of a
  single current job so `cancel` can signal any running job's event;
  `batch_id` and `part` are persisted in `job.json` so `reconcile` restores a
  batch after a restart as queued members in `created_at` order (running
  members are marked `interrupted` exactly as today). Concurrent part
  ingests for one topic serialise on the run's manifest write lock, which
  already exists.
- `_require_no_active_job` is topic-wide (`jobs.any_active_for`,
  `write_api.py:68`) and stays so for every whole-run mutator (`advance`,
  `approve`, `validate`, `edit_response`, salvage, finalize, waivers): while
  a batch runs, the run waits. The one exception is the part-response routes
  (D7), which use `JobStore.active_for_part(topic, part)` and refuse with
  `job_conflict` only while **that** part's job is queued or running, so a
  manual paste for `m3` is allowed while `m4` runs.
- Failure isolation: one part job failing (exit code, timeout, parse error,
  salvage) leaves its siblings running; the batch has no state of its own
  beyond its jobs, and `next_action` reports the failed part as missing so
  the rerun path is the ordinary one. Per-job logs and salvage files keep
  their existing shapes with the part in the file name
  (`responses/draft/modules/<id>.failed.<ts>.txt`).
- Timeouts stay per stage and per model from the plan; a module job gets the
  draft stage's timeout, which now covers one module rather than a course.

### D7. Manual providers

Manual users get N+1 prompt files on disk and paste N+1 responses. The CLI
`status` lists each part with its state and the path to save to; the cockpit
draft step lists parts with copy-prompt and paste-response controls per part
(`POST /v1/runs/{id}/stages/draft/parts/frame/response` and
`.../parts/modules/<id>/response`, `PUT` for edits with `base_sha256` as
today). Assembly, validation and approval are then the same as for provider
runs. A `module_id` taken from a URL or body is validated against the id
pattern **and** the current contract's module set before any path join
(topic ids get `_artifact_id`; module ids have no equivalent today);
anything else is a 404.

### D8. Section-scoped repair

- Scope becomes `RepairScope(module_id: str, section_id: str | None)`.
  Manifest: `repair_module` (unchanged) plus `repair_section` when set, on the
  repair `prompt_written` and `response_approved` events, so pre-existing
  workspaces read as module scope.
- `splice_section(base_guide_json, module_id, section_id, section_json) ->
  bytes` mirrors `splice_module`: the section must exist in that module, its
  id must not change, every other byte of the guide is preserved, and the
  merged guide is re-parsed strictly.
- `compile_guide_v1_section_repair_prompt(...)` mirrors the module prompt:
  embeds the one section, the enclosing module's stubs (id, title, summary,
  outcome ids, sibling section titles), deterministic findings filtered by
  the `/modules/<i>/sections/<j>` prefix, matching QA items, the whole
  fact-check report, and asks for exactly one section object with the same
  `id`. It instructs the model to keep the module's only interactive block if
  this section holds it; if the model drops it, draft validation reports
  `module.no_interaction` as it would for any repair (accepted limitation).
- `GET /v1/runs/{id}/repair/modules` gains `sections: [{id, title,
  open_findings}]` per module, keyed by the `^/modules/(\d+)/sections/(\d+)`
  prefix; `repair_scope` returns `{module_id, section_id}`. `advance` accepts
  `repair_section` alongside `repair_module`; CLI `advance --repair-module M
  --repair-section S`.
- **Scoped base.** `_spliced_scoped_repair` (`runs.py:1124`) and
  `_require_repair_ready` (`runs.py:1673`) use the approved draft as the
  base today, so a second scoped repair after an approved repair would
  silently discard the first (a latent defect of module repair that section
  scope makes likely). From this phase the scoped base is the current
  approved repair when one exists, else the approved draft; the prompt embeds
  the base's module or section and the findings of the report over that
  base (final report when the base is the approved repair, draft report
  otherwise); the manifest binds `source_repair_file_sha256` or
  `source_draft_file_sha256` accordingly and the approve-time drift check
  compares against the same file. Whole-guide repair is unchanged.
- Scope is whatever the **latest** repair `prompt_written` event carries:
  `(module, section)`, `(module, None)` or none; a whole-guide
  `write_repair_prompt(overwrite=True)` appends an event without either key
  and so resets the scope to whole, as today. `_spliced_scoped_repair`
  dispatches on that triple, reads `repair_module` and `repair_section`
  from that one event (never merged across events), and `approve_stage`
  records both on `response_approved`.
- The cockpit `ModuleRepairControl` becomes a scope picker (module, then
  optional section) with the finding counts preselecting the narrowest scope
  that holds an open finding.

### D9. What does not change

- Approval semantics: one `approve draft` over the assembled guide; one
  `approve repair` over the spliced guide. `advance` never approves.
- The stage graph, qa, factcheck, repair sources, finalize, export, waivers,
  cost aggregation, personalization trace, legacy Markdown mode.
- Whole-guide drafting: every existing test keeps passing without edits;
  `T10` characterization cases are extended, not changed.

## API and CLI surface (summary)

| Surface | Change |
| --- | --- |
| `POST /v1/runs/{id}/advance` (first call) | body `draft_strategy?: "whole" \| "modular"`, recorded like `blueprint` |
| `GET /v1/runs/{id}` | `draft_strategy`; on modular runs `draft_parts: {frame: {state, stale, job?, failed_outputs}, modules: [{id, title?, state, stale, job?, failed_outputs}], assembled: {state: absent \| matches_record \| edited, stale}}`; `next_action.wave` |
| `POST /v1/runs/{id}/advance` | body `parts?: [module ids]`; performs `assemble`; body `repair_section?` with `repair_module` |
| `POST /v1/jobs`, `POST/PUT /v1/runs/{id}/stages/draft/response` | refuse modular drafts with `draft_is_modular` |
| `POST /v1/jobs/batch` | `{topic_id, stage, parts?, force?}` → `{batch_id, jobs}` |
| `POST /v1/jobs/batch/{batch_id}/cancel` | cancels the batch |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | job records carry `batch_id`, `part` |
| `POST/PUT /v1/runs/{id}/stages/draft/parts/frame/response`, `.../parts/modules/{module_id}/response` | manual part responses; refuse while that part's job is active |
| `GET /v1/runs/{id}/repair/modules` | per-module `sections`, `repair_scope.section_id` |
| CLI | `create --draft-strategy`, `status` part listing, `advance --parts`, `advance --repair-section`, `run` on modular drafts, `cancel --batch` |
| `model-plan.toml`, `PUT /v1/config/plan`, settings page | `[jobs] parallelism`, round-tripped; effective on daemon restart |

Part states: `missing` (no prompt), `prompted` (prompt current, no response),
`responded` (response current), `stale` (prompt or response bound to
superseded inputs), `failed` (latest job for the part failed and no current
response).

## Non-goals

- Changing the default strategy (owner decision).
- Modular repair beyond section scope (block scope) and modular qa/factcheck.
- A module response that adds sources or glossary entries (D2).
- Draft staleness against the outline for whole-guide runs.
- Multi-course queues and headless run-to-judgment (Phase 3).

## Risks and disproof tests

- **The frame under-declares sources.** Disproof: regenerate the shipped
  example through the modular path and count `source_ids` that survive
  fact-check; if modules routinely need sources the frame lacks, promote the
  envelope from D2.
- **Index-based finding paths shift when modules are re-drafted.** They do
  not: assembly fixes module order to the contract order, and the contract
  is the same input for every part.
- **Pool concurrency exposes provider rate limits.** Bounded by
  `parallelism` (cap 4); the default 2 matches what a user could do by hand
  with two terminals.
- **Two enqueue routes race.** Prevented by refusing `POST /v1/jobs` on
  modular drafts and by `active_for` admission for non-batch jobs.

## Open questions for the owner

1. Flip the default to `modular` for new interactive-guide runs once the
   example regenerates cleanly? (This spec: no, opt-in.)
2. Should `parallelism` live in `model-plan.toml` (chosen: it is the file the
   settings page already edits) or a new daemon config?

## Thread map

| Thread | This spec |
| --- | --- |
| T21 | D2 prompts, D3 `assemble_guide` |
| T22 | D1, D3, D4, D5 (RunStore, manifest, next action, advance) |
| T23 | D6 (jobs, batches, pool, part ingest) |
| T24 | API and CLI surface, D7 routes |
| T25 | cockpit: wizard option, part list, batch run, rerun |
| T26 | D8 engine (`splice_section`, prompt, scope, payload, CLI) |
| T27 | D8 cockpit scope picker |
| T28 | example through the modular path, docs, audit |
