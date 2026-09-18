# Per-Module Drafting and Section-Scoped Repair — Design

- **Date:** 2026-09-18
- **Status:** Draft for owner review — implementation plan at
  [`docs/superpowers/plans/2026-09-18-phase-2-per-module-drafting.md`](../plans/2026-09-18-phase-2-per-module-drafting.md)
- **Branch:** `claude/p2-engineering-manager-90ex44` (one local branch per thread, merged in)
- **Source:** the 2026-09-17 opportunity map, tier-1 item A and "Build plan · Phase 2"
- **Related:** stage graph
  ([`2026-09-17-phase-1-stage-graph-post-milestone-audit.md`](2026-09-17-phase-1-stage-graph-post-milestone-audit.md)),
  interactive-guide schema
  ([`2026-07-11-interactive-guide-v1-schema.md`](2026-07-11-interactive-guide-v1-schema.md)),
  validation pipeline
  ([`2026-07-11-interactive-guide-v1-validation-pipeline.md`](2026-07-11-interactive-guide-v1-validation-pipeline.md)),
  provider run daemon
  ([`2026-07-09-provider-run-daemon-design.md`](2026-07-09-provider-run-daemon-design.md))

## Summary

Today the draft stage asks the model for the whole guide JSON in one
response, and repair asks for the whole guide again (or one whole module).
Course length is therefore bounded by one model response, a retry costs the
whole course, and the single worker thread cannot overlap anything.

This design splits the draft stage's *model work* into units while leaving
the draft stage's *lifecycle* (one prompt-written state, one response file,
one approval, one validation) exactly where it is:

```
before:  advance → draft.prompt.md → [one model call] → draft.response.json → approve
after:   advance → draft/skeleton/prompt.md → [1 call] → skeleton response
               → advance → draft/modules/<id>/prompt.md × N → [N calls, ≤P at once]
               → assemble (deterministic) → draft.response.json → approve   (unchanged from here)
```

Everything downstream of `responses/draft.response.json` — approval, draft
validation, qa, factcheck, repair, finalize, export, staleness of later
stages — is untouched. The stage graph is untouched. Legacy Markdown runs are
untouched. Repair gains a section scope alongside the existing module scope,
using the same splice-on-approve mechanism.

## Goal

A guide-v1 run can draft a course of any length the outline allows, one
module per model call, with bounded parallel execution in the daemon, a
per-module rerun that costs one module, and a repair that can replace one
section. Approval gates stay after every model stage; nothing here
auto-approves.

**Exit criterion.** For a guide-v1 run with an approved outline of N
modules, `advance` writes the skeleton prompt; after its response, `advance`
writes N module prompts; the daemon runs them at most `parallelism` at a
time; when all N responses are present the engine writes the assembled guide
to the ordinary draft response path and `next_action` is `approve` for
`draft`, exactly as today. `education-pipeline status` reports
`draft: k of N modules`. A repair prompt can be scoped to
`/modules/<i>/sections/<j>` and its approval splices only that section.

## Current state (verified 2026-09-18 against `55cfc82`, post Phase 1)

- `write_draft_prompt` (`runs.py:1480`) reads the approved outline, writes
  the immutable `inputs/guide-contract.json` (`runs_personalization.py:96`)
  and calls `compile_guide_v1_draft_prompt` (`prompts.py:856`), which asks for
  exactly one whole-guide JSON object (`_GUIDE_DRAFT_OUTPUT_AND_QUALITY_LINES`,
  `prompts.py:530`). Prompt at `<run>/prompts/draft.prompt.md`, response at
  `<run>/responses/draft.response.json`, approved copy at
  `<run>/approved/draft.json` (`stage_paths`, `runs.py:350`).
- The outline's machine-readable contract (`guides/contract.py:321`
  `extract_outline_contract`) maps stable module ids to
  `{outcome_ids, estimated_minutes, interaction_types}`; its key order is the
  authored module order (`json.loads` preserves it). `build_guide_contract`
  (`contract.py:331`) re-emits the map with `sort_keys=True`, so
  `inputs/guide-contract.json` does **not** preserve module order; the
  approved outline does. Nothing today validates that draft module ids equal
  contract module ids.
- The guide's non-module parts are model-authored prose: `Course`
  (`guides/model.py:25`: title, subtitle, description, language, blueprint,
  estimated_minutes, difficulty, learner_summary, goal_exclusions),
  `Outcome.serves_goals` (`model.py:39`), `glossary`, `sources`. The spec
  contract carries outcome ids and text only. No deterministic step can
  produce a course header.
- Module repair already does "one unit in, splice on approve":
  `write_module_repair_prompt` (`runs.py:1776`) writes to the **repair**
  stage's ordinary paths with `extra_event={"repair_module": id}`;
  `compile_guide_v1_module_repair_prompt` (`prompts.py:1188`) filters
  deterministic findings by the `/modules/<index>` path prefix
  (`prompts.py:1260`) and demands exactly one module object with the same id;
  `approve_stage` → `repair_scope` (`runs.py:1110`) → `_spliced_scoped_repair`
  (`runs.py:1124`) → `splice_module` (`guides/canonical.py:50`), which refuses
  renames, `modules` keys and any merged guide that fails a strict re-parse.
- Daemon jobs: `Job` (`daemon/jobs.py:45`) is keyed by `(topic_id, stage)`;
  `Worker` (`jobs.py:703`) is one thread over a FIFO; `enqueue` refuses a
  second active job for the same `(topic, stage)` (`jobs.py:729-745`);
  `JobRunner.execute` (`jobs.py:367`) reads
  `runs.stage_paths(topic, stage).prompt_path`, pipes it to the provider and
  calls `runs.ingest_response(topic, stage, text, force=...)` (`jobs.py:423`).
  Per-stage timeout comes from the effective plan (`jobs.py:862`).
  `DaemonContext.enqueue_stage` (`daemon/server.py:88`) defaults the stage to
  `next_action.stage` and, when the stage is omitted, requires
  `next_action.action == "save_response"` (`server.py:131-136`).
- Status: `run_status_payload` (`daemon/read_api.py:389`) reports one
  `state` per stage (`stale|approved|response_ingested|prompt_written|not_run|pending`)
  and `next_action = {topic_id, stage, action, detail}`. The cockpit derives
  its primary action solely from `next_action.action`
  (`web/src/components/PrimaryAction.tsx:84-220`), and `continueRun`
  (`web/src/lib/continueRun.ts:96`) enqueues on `save_response`.
- Manual providers: there is no CLI ingest command; users write the response
  to the stub path (`SAVE_RESPONSE_HERE.*`) or paste through the cockpit,
  which calls `POST /v1/runs/{id}/stages/{stage}/response`.
- Findings → module mapping for the repair picker is a regex on
  `^/modules/(\d+)(?:/|$)` (`read_api.py:585-591`); validation paths already go
  down to `/modules/i/sections/j/blocks/k` (`parse.py:344-382`).

## Decisions (subject to owner review)

1. **Draft stays one stage with one approval.** The unit layer sits *before*
   `responses/draft.response.json`; approval, `edit_response`,
   `validate_run(phase="draft")`, and every downstream source binding read
   that file unchanged. No new stage; `stage_graph.STAGES` is not edited.
2. **Skeleton first, then modules.** Units are one `skeleton` and N
   `module` units, N = the current approved outline contract's modules.
   The skeleton call returns the whole guide *without section content*:
   course header, outcomes (with `serves_goals`), glossary seed, sources
   seed, and one stub per contract module (`id, title, summary, outcome_ids,
   estimated_minutes, sections: []`, plus `serves_goals` only on schema 1.1,
   where `parse.py:216,352` allow it). Module calls receive the
   skeleton and return one full module object. Rationale: the course header
   is prose no deterministic step can write (see Current state), and giving
   every module the same header, outcome texts and sibling stubs is what
   keeps N independent calls coherent. Cost: N+1 calls instead of 1, the
   skeleton being small.
3. **Module order is the authored outline order**, read from the approved
   outline's contract block at assembly time — never from
   `inputs/guide-contract.json`, whose keys are sorted. The skeleton prompt
   states the order and the skeleton response must list stubs in it;
   assembly refuses a skeleton whose stub ids are not exactly the contract
   ids in that order.
4. **Assembly is deterministic and refuses drift.** `assemble_guide(skeleton,
   modules)` replaces each stub with its module object (id must match; a
   fragment with a `modules` key, a different id, or a missing/extra module is
   an `AssemblyError`), merges optional per-module `glossary` and `sources`
   contributions by id (skeleton first, then modules in order; the same id
   with different content is an error), and re-parses the result strictly,
   exactly as `splice_module` does. Output is canonical bytes. Because the
   parser keeps **one id namespace** across outcomes, modules, sections,
   blocks, glossary and sources (`parse.py:78,164-172`), N independent calls
   can collide on ids like `intro` or `check-1`; the module prompt therefore
   requires every section and block id to start with `<module-id>-`, and
   assembly checks cross-module id uniqueness *before* the strict parse so
   the `AssemblyError` names both colliding modules and only those rerun.
5. **The whole-guide prompt keeps being written** at `prompts/draft.prompt.md`
   as the documented single-call alternative for short courses and manual
   users. The daemon never runs it for guide-v1 runs; a whole guide pasted or
   dropped into `responses/draft.response.json` is accepted as today. This
   keeps every existing draft test, `scripts/build_example.py`, and legacy
   runs untouched. Alternative considered: a `draft_mode` plan setting
   (`whole|per_module`) — rejected for now as surface without a user asking
   for it; the owner can add it later without touching the unit layer.
6. **The response file wins.** Whenever `responses/draft.response.json`
   exists, `next_action` falls through to today's arms (`approve`), whether
   the file came from assembly, a whole-guide paste, or an edit. If its bytes
   are not the last assembled bytes (per the manifest), the unit layer
   reports the modules as `superseded` and never overwrites the file.
   Re-running a module then requires `force`, which re-assembles, overwrites,
   and records `response_replaced` — the same rule `ingest_response(force=)`
   applies today.
7. **A module is stale when the inputs its prompt embedded changed.** Per
   module the engine records, at prompt time, the SHA-256 of its entry in
   `inputs/guide-contract.json` (the bytes the prompt embeds, canonical JSON)
   and of its skeleton stub. A module whose recorded hashes differ from the
   current contract file and skeleton response is `stale`; a contract module
   with no prompt is `not_run`; a prompt whose module id is no longer in the
   contract is `orphaned` and ignored by assembly. Course-level skeleton
   edits (description, glossary) do not stale modules. The hashes are
   deliberately **not** taken against the live approved outline:
   `_write_guide_contract` (`runs_personalization.py:95-125`) refuses
   divergent bytes without `overwrite`, and after the draft prompt exists no
   arm rewrites it, so hashing against the outline would mark every module
   stale with no action that clears it.
   **7b. Outline re-approval before draft approval rebuilds the draft
   inputs.** Today nothing rebuilds the contract after an outline is
   re-approved (draft has no graph sources; `stage_status` never marks it
   stale, as Phase 1 pinned). This design adds one arm, scoped to an
   *unapproved* draft: when the approved outline's SHA differs from the
   `source_outline_file_sha256` recorded by the draft `prompt_written` event,
   `next_action` is `write_prompt` ("outline changed; rebuild draft inputs")
   and `advance` calls `write_draft_prompt(overwrite=True)`, which rewrites
   the contract, the whole-guide prompt and the skeleton prompt, and moves
   existing unit responses aside as `orphaned`. An approved draft is left
   alone (downstream qa/factcheck/repair staleness is unchanged). T22 checks
   this arm against the Phase 1 characterization table; a contrary pin is
   updated and the behaviour change is flagged in the PR, as T11 did.
8. **`next_action` keeps its shape, and gains exactly one action.**
   Mid-fan-out it is `{stage: "draft", action: "save_response", detail:
   "draft: k of N module responses saved; …"}`. This keeps `enqueue_stage`'s
   structural gate, `continueRun` and `PrimaryAction` valid, and
   `POST /v1/jobs` with no stage naturally means "run whatever draft units
   are outstanding". A new status object `draft_progress` (below) carries the
   per-unit detail. `NextAction` gains no field; where `advance` needs to
   know *which* prompt to write it re-derives that from `draft_progress`.
   **8b (revised in T22).** The one state this cannot express is "every
   module response is saved, nothing is assembled yet", which the manual
   file-drop path reaches whenever no ingest ran. Assembly is deterministic —
   no model call — so it belongs with `validate` and `finalize` as a step
   `advance` performs, not with the human steps. The action vocabulary
   therefore gains `assemble`: `next_action` is `{stage: "draft", action:
   "assemble"}` in that state, `advance` calls `assemble_draft` and reports
   `performed: "assemble"`, and an `AssembleResult` with `ok=False` is raised
   as a `ConfigError` rather than silently leaving no draft response. The
   assembly-*failure* arm is unchanged and still reports `save_response`
   naming the module(s): re-running a broken module is a human step.
9. **Skeleton ingest writes the module prompts.** Writing prompts is a
   machine step, so the job runner (and the ingest route) call
   `write_module_draft_prompts` right after the skeleton response lands; on
   the file-drop path `advance` does it (`next_action` says `write_prompt`
   with a module detail). Nothing approves.
10. **Bounded parallelism is one workspace setting.** `parallelism` (int,
    1–4, default 2) is a top-level key in `model-plan.toml` beside
    `provider`, exposed through `GET/PUT /v1/config/plan`. It bounds
    concurrently *running* module jobs of one batch; every other job still
    runs alone. Timeout stays per job from the stage plan, so a slow module
    no longer fails the whole draft.
11. **Section repair reuses module repair wholesale.** A repair scope is
    `(module_id, section_id | None)`; the prompt, manifest keys, splice and
    approval branch on `section_id`. Module-level findings
    (`module.no_interaction` at `/modules/i`, guide-wide findings) cannot be
    fixed by a section repair, and the picker says so by preselecting module
    scope for them.

## Design

### 1. On-disk layout and manifest

```
<run>/
  prompts/draft.prompt.md               # unchanged (whole-guide alternative)
  responses/draft.response.json         # unchanged; written by assembly or by hand
  draft/
    skeleton/
      prompt.md
      SAVE_RESPONSE_HERE.json           # stub, removed once response.json exists
      response.json
    modules/<module-id>/
      prompt.md
      SAVE_RESPONSE_HERE.json
      response.json
      response.previous.json            # kept on force rerun for the viewer's diff
```

Unit paths come from one helper, `RunStore.draft_unit_paths(topic_id, unit,
module_id=None) -> DraftUnitPaths(prompt_path, response_path, stub_path)`;
nothing else spells the layout. Module ids are already validated slugs by
`validate_outline_contract` (`contract.py:93-98`), so they are safe as
directory names. The stage-level stub `responses/draft.SAVE_RESPONSE_HERE.json`
stays (it is the whole-guide alternative's drop target) but, on guide runs,
its text points at `draft/skeleton/` and `draft/modules/` as the primary
path, so a manual user is not told to paste a whole guide by default.

Manifest events (all `stage: "draft"`, all appended under the manifest
lock, all carrying `recorded_at`):

| event | keys |
| --- | --- |
| `unit_prompt_written` | `unit` (`skeleton`\|`module`), `module_id`?, `prompt_file`, `response_file`, `source_outline_file` + `_sha256`, `contract_file` + `_sha256`, `contract_entry_sha256` (module), `skeleton_stub_sha256` (module), `skeleton_response_sha256` (module) |
| `unit_response_replaced` | `unit`, `module_id`?, `response_file`, `response_sha256`, `previous_sha256` |
| `unit_response_edited` | `unit`, `module_id`?, `response_file`, `response_sha256`, `base_sha256` |
| `draft_assembled` | `response_file`, `response_sha256`, `skeleton_sha256`, `module_ids` (ordered), `module_sha256` (map) |
| `draft_assembly_failed` | `error`, `module_id`? |

The last `draft_assembled.response_sha256` is what decision 6 compares
against the current response bytes. Existing `prompt_written` /
`response_approved` events for draft are unchanged, so every manifest reader
that predates this design keeps working; a pre-Phase-2 run has no unit events
and reads as "whole-guide draft" throughout.

### 2. Prompts (`prompts.py`)

- `compile_guide_v1_skeleton_prompt(topic, approved_outline, guide_contract,
  profile=None, *, blueprint=None, module_order: tuple[str, ...])`. Built from
  `compile_guide_v1_draft_prompt`'s sections (same schema reference, contract
  and blueprint sections, same personalization lines) with the output
  contract replaced: return the full guide object with every module present
  as a stub in `module_order`, `sections: []`, plus glossary and sources the
  whole course needs. The schema-reference lines are shared, not copied.
- `compile_guide_v1_module_draft_prompt(topic, *, module_id, skeleton_json,
  guide_contract, approved_outline, profile=None, blueprint=None)`. Built
  from `compile_guide_v1_module_repair_prompt`'s structure: embeds the
  skeleton (so the model sees the header, outcomes, and sibling stubs), the
  module's contract entry (outcomes, minutes, required interaction types),
  and the outline's prose for that module; demands exactly one module object
  with the same `id`, optionally followed by no other top-level keys except
  `glossary` and `sources` additions. Every section and block id must start
  with `<module-id>-`; any source or glossary entry the module cites that the
  skeleton lacks must be returned in the contribution lists (blocks resolve
  `source_ids` against root `sources`, `parse.py:664-668`). Position
  ("module 2 of 5") is stated.
- Prompt snapshot tests pin both; `blueprint is None` and profile-less
  variants stay byte-stable across the phase.

### 3. Assembly (`guides/canonical.py`)

```
assemble_guide(skeleton_json: bytes | str,
               modules: Mapping[str, bytes | str],
               *, module_order: Sequence[str]) -> bytes
```

A skeleton **cannot** pass `parse_guide`: `sections` has cardinality ≥ 1
(`parse.py:368`), `module.no_interaction` fires per module (`parse.py:709`),
`interaction.missing_required_type` at `/modules` (`parse.py:715`) and
`outcome.untaught`/`outcome.unassessed` (`parse.py:730-740`), and
`ParseResult.ok` means zero diagnostics with no lenient mode
(`parse.py:60-62`). So the skeleton gets its own check, `check_skeleton`
(in `guides/parse.py`, reusing `_check_modules` with a `skeleton=True` flag
that requires `sections == []` and skips the coverage and interaction arms):
`json.loads`, top-level keys and types as for a guide, modules are stubs, all
ids unique, stub ids == `module_order` exactly. Then for each id parse the
fragment (single object, `id` equal, no `modules` key — the `splice_module`
rules), lift optional `glossary`/`sources` lists, replace the stub; check
id uniqueness across the merged document and name both owners of a
collision; merge contributions by id; canonicalize; strict `parse_guide`
on the result. Any failure raises `AssemblyError(module_ids, message)`, a
subclass of the existing `SpliceError` so callers that already map
`SpliceError` → `ConfigError` keep working. `splice_module` is reimplemented
as the single-module case of the same internals; `splice_section` (§7)
joins it.

### 4. Engine lifecycle (`RunStore`, new mixin `runs_draft_units.py`)

Capability: `_RunMode.supports_draft_units` (true for
`InteractiveGuideMode`, false for legacy). Every method below refuses with
`ConfigError` on a legacy run.

- `write_draft_prompt` is unchanged in what it writes today and, on guide
  runs, additionally writes the skeleton prompt (event
  `unit_prompt_written{unit: skeleton}`). Its return value is unchanged.
- `write_module_draft_prompts(topic_id, *, module_ids=None, overwrite=False)
  -> tuple[DraftUnitPaths, ...]`: requires a skeleton response that passes
  `check_skeleton` (§3); module set defaults to the contract's; writes
  prompts and stubs; records the hashes of decision 7. The unit writers are
  idempotent and ignore the stage-level `prompt_overwrite_on_advance` flag
  (`run_modes.py:365`) — only the 7b rebuild arm passes `overwrite=True`,
  and only `write_draft_prompt` rewrites the contract.
- `ingest_draft_unit(topic_id, unit, text, *, module_id=None, force=False)`
  and `edit_draft_unit(..., base_sha256)`: the unit-level twins of
  `ingest_response` / `edit_response`, same empty-text and
  `StaleContentError` rules; a module ingest that replaces an existing
  response keeps it as `response.previous.json`. After a skeleton ingest,
  module prompts are written (decision 9); after a module ingest,
  `assemble_draft` is attempted.
- `assemble_draft(topic_id, *, force=False) -> AssembleResult(ok, response_sha256,
  error, module_id)`: no-op unless every current module has a non-stale
  response; refuses (decision 6) when the response file was hand-edited and
  `force` is false; writes `responses/draft.response.json` atomically, removes
  the draft stub, records `draft_assembled` or `draft_assembly_failed`. It
  never approves.
- `draft_progress(topic_id) -> DraftProgress` (pure read, cached like the
  final-validation memo, keyed on the manifest tail and unit file hashes):
  skeleton state, ordered module states, `assembled` info, `superseded`
  flag. States per unit: `not_run | prompt_written | response_ingested |
  stale | orphaned | superseded`.
- `next_action` for draft on guide runs: the unit arms live *inside* the
  draft slot of the existing `_unbound_stages` loop (`runs.py:727`), so they
  are reached only once spec and outline are approved and draft is not, and
  only while `responses/draft.response.json` is absent. In that window:
  outline changed since the draft prompt (7b) → `write_prompt`; no skeleton
  prompt → `write_prompt`; skeleton prompt, no response → `save_response`
  ("skeleton"); skeleton response, module prompts missing for some contract
  module → `write_prompt` ("module prompts"); any module
  `not_run`/`prompt_written`/`stale` → `save_response` ("k of N"); all present
  but assembly failed → `save_response` naming the module(s); all present and
  assembly would succeed → `assemble` (decision 8b). Once the
  response file exists — assembled, pasted whole, or edited — control falls
  through to `_pending_stage_action` (`runs.py:856`) and today's `approve`
  arm, which is what keeps the whole-guide drop pinned by
  `tests/test_characterization_guide_v1.py:329-330` intact. `advance` at
  draft re-derives which writer to call from `draft_progress`.
- Resume from the workspace alone holds: every state above is a function of
  files under `<run>/draft/`, the manifest, and the approved outline.

### 5. Daemon (`daemon/jobs.py`, `daemon/server.py`)

- `Job` gains `unit: str | None`, `module_id: str | None`, `batch_id: str |
  None`; `to_dict` carries them; old records load with `None`.
- `JobStore.active_for(topic, stage)` keeps matching **any** job of that
  stage, module jobs included, so `enqueue_stage`'s guard (`server.py:137`)
  and `validate_run`'s (`write_api.py:186`) still refuse mid-batch; a new
  `active_unit_for(topic, stage, module_id)` serves only the duplicate check
  in `Worker.enqueue` (`jobs.py:738`). `any_active_for(topic)` is unchanged.
- `JobRunner.execute` picks the prompt path from `draft_unit_paths` when
  `job.unit` is set and ingests through `ingest_draft_unit`; the salvage path
  (`<stage>.failed.<ts>.txt`) writes `draft.<module_id>.failed.<ts>.txt`.
- `Worker` becomes a pool: `parallelism` threads over the same FIFO, with one
  admission rule — a job starts only if nothing is running, or if every
  running job shares its `batch_id`. The rule is evaluated **dispatcher-side
  in `_loop` after dequeue**, never in `enqueue` (which runs under the
  workspace lock, `server.py:101,148`, and must stay non-blocking). A thread
  holding an inadmissible job waits on a condition variable signalled at
  every job completion; it never re-queues to the tail (that spins when a
  non-batch job sits between batch jobs). Waiting cannot deadlock because
  running jobs always terminate (timeout, cancel, or exit). Non-batch jobs
  are therefore exactly as serialized as today. `cancel_batch(batch_id)`
  cancels every queued and running job of a batch. `reconcile` is per job
  and unchanged; re-queued batch jobs keep their `batch_id`.
- `enqueue_stage(topic, stage=None, force=False, modules=None)`: for draft on a
  guide run, when the skeleton lacks a response → one skeleton job (response
  is the job dict, as today); otherwise → one batch of module jobs for the
  outstanding (or the requested) modules. The batch response is
  **job-shaped at the top level** (the first job's dict, so `cli.py:791-806`
  and the web client keep reading `id`/`stage`/`status`) plus `batch_id` and
  `jobs: [...]`. `modules` on a stage other than draft is a `ConfigError`. The
  structural gate (`next_action.action == "save_response"` when the stage is
  omitted) is unchanged.
- Routes: `POST /v1/jobs` (body gains `modules?: [id]`),
  `POST /v1/jobs/batch/{batch_id}/cancel`,
  `POST /v1/runs/{id}/draft/{unit}/response` and `PUT …/response` (body
  `{text, force}` / `{text, base_sha256}`; `unit` is `skeleton` or
  `modules/<id>`), `POST /v1/runs/{id}/draft/assemble` (`{force}`).
- `GET /v1/runs/{id}` gains `draft_progress` (guide runs only):

```json
{"skeleton": {"state": "response_ingested", "job_id": null},
 "modules": [{"id": "loop-basics", "title": "How loops behave",
              "state": "response_ingested", "response_sha256": "…",
              "job_id": "…"}, …],
 "assembled": {"ok": true, "response_sha256": "…", "error": null},
 "superseded": false, "parallelism": 2,
 "counts": {"total": 5, "saved": 3, "stale": 0}}
```

### 6. CLI

- `run` prints `enqueued batch <id> (draft, 5 modules)` for a batch;
  `--wait` waits for the batch; `--modules a,b` reruns a subset.
- `status` prints `draft: 3 of 5 modules` under the stage line for guide
  runs (and `skeleton: pending` before the fan-out).
- `advance` writes the skeleton prompt or the module prompts as
  `next_action` dictates. `cancel --batch <id>` joins `cancel`.
- Manual users drop files onto the stub paths under `<run>/draft/` exactly
  as they do for stages, then `advance`.

### 7. Section-scoped repair

- `RepairScope(module_id: str, section_id: str | None)` replaces the bare
  module id in `repair_scope()`; the manifest gains `repair_section` next to
  `repair_module`. `write_scoped_repair_prompt(topic, scope, *, overwrite)`
  is the one writer; `write_module_repair_prompt` stays as a thin alias.
- `compile_guide_v1_section_repair_prompt` filters deterministic findings by
  the `/modules/<i>/sections/<j>` prefix, embeds the whole module for
  context, and demands exactly one section object with the same id. It
  states that module-level and guide-level findings are out of scope for the
  call.
- `splice_section(base_guide_json, module_id, section_id, section_json) ->
  bytes` mirrors `splice_module`: single object, same id, no `sections`/
  `modules` keys, replaced in place, strict re-parse; every other byte of the
  canonical guide is unchanged.
- `GET /v1/runs/{id}/repair/modules` adds per module `sections: [{id, title,
  open_findings}]` and `module_level_findings` (count); `POST …/advance` body
  gains `repair_section` (requires `repair_module`). CLI `advance
  --repair-module M --repair-section S`.
- Cockpit `ModuleRepairControl` becomes a scope picker: module select, then
  a section select defaulting to "whole module"; a finding with a section
  path preselects the section, a module-level finding preselects the module.

### 8. Cockpit (T25)

- Draft stage on the board renders `draft_progress`: skeleton row, one row
  per module with state badge, "Run modules with provider" (batch), per-row
  "Rerun" (single-module batch, `force` when a response exists), per-row
  paste. `ActiveJobStatus` shows batch progress ("3 of 5 running/done") and a
  batch cancel.
- Stage viewer for draft shows the assembled guide with module boundary
  anchors; when `response.previous.json` exists for a module, a "changes
  since last run" diff for that module.
- Settings gains the `parallelism` field.
- `continueRun` treats a batch enqueue response like a job enqueue (`started`
  stop reason with `count`).

### 9. Migration and compatibility

- Runs created before this phase have no `<run>/draft/` directory and no
  unit events; every new method treats that as "whole-guide draft" and
  `draft_progress` reports `superseded: false, modules: []` with the stage
  state as today. Nothing is rewritten on upgrade.
- A run mid-draft at upgrade time (whole prompt written, no response) gets
  the skeleton prompt on its next `advance` (idempotent, `overwrite=False`);
  pasting a whole guide still works.
- `scripts/build_example.py` moves to the unit path (skeleton + module
  responses split deterministically from the committed `draft.guide.json`).
  The committed `draft.guide.json` is not canonical, so assembly changes the
  approved draft bytes; the export derives from the repair response and is
  unaffected, but `tests/test_example_project.py:84` compares the two
  committed response files byte-for-byte, so T28 canonicalizes both
  `draft.guide.json` and `repair.guide.json` together and any round-trip
  test compares canonical forms, not the committed text.
- Job records without the new fields load as before; the batch id is `None`.

### 10. Testing strategy (TDD; tests before behaviour)

- `test_guide_canonical.py` / `test_guide_parse.py`: `check_skeleton`
  accepts a sectionless guide and rejects content, missing stubs and wrong
  order; `assemble_guide` determinism (same inputs → same bytes, twice),
  refusal matrix (missing/extra/renamed module, `modules` key in a fragment,
  glossary id conflict, cross-module id collision naming both modules,
  dangling `source_ids`), and `splice_section` byte-preservation of every
  sibling.
- `test_prompts.py`: snapshots for skeleton, module draft and section repair
  prompts; `blueprint is None` byte-stability.
- `test_characterization_guide_v1.py` (extended in T22): a table of unit
  states × expected `next_action`, plus superseded-by-edit and
  outline-re-approval (module added / removed / entry changed) cases.
- `test_worker.py` / `test_job_runner.py`: N fake-provider jobs, concurrency
  never exceeding `parallelism` (a counting fake with `FAKE_DELAY`), one
  failing module leaving the others `succeeded`, batch cancel, non-batch jobs
  never overlapping a batch.
- `test_server.py` / `test_write_api.py` / `test_cli.py`: payload shapes,
  the `modules` subset, unit ingest routes, `status` text.
- Playwright: `full-run.spec.ts` gains the unit paste path; `blueprints.spec.ts`
  gains a section repair.

### 11. Open questions (defaults chosen; non-blocking)

1. Should the skeleton have its own approval gate? Default **no** — gates
   are per stage, and the assembled guide is reviewed once. The cockpit lets
   a user read and edit the skeleton before pressing "Run modules".
2. Should `parallelism` be overridable per run? Default **no** — workspace
   only; add to `_STAGE_OVERRIDE_KEYS` later if asked.
3. Should the whole-guide prompt stop being written once the unit path has
   been used in anger? Default **keep** (decision 5); revisit at the v0.2
   release.
4. Does the module prompt let the model revise the stub's title/summary?
   Default **yes** (the module object replaces the stub wholesale, id fixed);
   the skeleton's stub text is guidance, not contract.

## Non-goals (this phase)

- Parallelism across topics or across stages; only module batches overlap.
- A `draft_mode` setting; block-scoped repair; streaming partial modules to
  the cockpit; any change to qa/factcheck granularity; headless
  run-to-judgment (Phase 3).

## Success metrics

- A 12-module outline drafts to an assembled, approvable guide with no single
  model response larger than one module.
- Rerunning one module after a bad response costs one job and leaves every
  other module's bytes unchanged (pinned by test).
- With `parallelism = 2`, a 4-module fake-provider batch with a 0.5 s delay
  completes in about two delays, never one.
- Pre-existing pytest cases pass unmodified except where a thread flags a
  deliberate behaviour change (7b) or a widened manifest event list.
