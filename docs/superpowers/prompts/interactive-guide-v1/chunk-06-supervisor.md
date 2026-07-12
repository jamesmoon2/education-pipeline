# Supervisor Prompt — Interactive Guide v1, Chunk 06

You are the supervisor agent for **Chunk 06: implement and accept the Wave 5
export/preview API freeze and the sandboxed cockpit guide preview** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete only this chunk autonomously, including safe recovery from ordinary
implementation or verification failures. Do not begin Chunk 07. A human
controls the transition between chunks.

## Accepted base and frozen contracts

The accepted Wave 4 integration head is commit:

```text
e9b7fad01f563f2f1d932eead40867fe130a4348
```

The accepted Wave 4 commits, in merge order, are:

```text
c08eb9c5e7658ad9440c1f16efade15e3c15b5ca  feat(pipeline): contract-aware guide-v1 artifacts and prompts
8811a91360638a6fa61e790998cc2a4ddf5166f2  feat(pipeline): validation lifecycle, freshness, and guarded finalization
e9b7fad01f563f2f1d932eead40867fe130a4348  feat(pipeline): default new runs to interactive guide v1
```

Confirm `e9b7fad` is an ancestor of `HEAD`, inspect the live branch/worktree,
and preserve every unrelated user change. Do not reset, pull, switch branches,
rewrite history, push, or open a pull request unless the human separately
authorizes it.

The canonical fixture is:

```text
tests/fixtures/guides/feedback-loops.guide.json
```

Its normalized canonical SHA-256 is frozen as:

```text
99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07
```

Frozen public Python surfaces (do not change signatures or behavior):

- From `education_pipeline.guides`: `parse_guide`, `normalize_guide`,
  `canonical_guide_bytes`, `guide_sha256`, `project_guide_markdown`,
  `validate_guide`, `canonical_report_bytes`, `apply_waivers`,
  `assemble_guide_document`, `render_guide_markdown`, `ContractError`,
  `extract_spec_contract`, `extract_outline_contract`,
  `validate_spec_contract`, `validate_outline_contract`,
  `check_contract_conflict`, `build_guide_contract`, plus the exported
  types (`Guide`, `Finding`, `ValidationReport`, `ValidationSummary`,
  `ValidationContext`, `Waiver`, `WaiverSet`, `WaiverResult`,
  `DocumentMode`, `GuideDocumentError`).
- `education_pipeline.guide_runtime.load_runtime_assets()` / `RuntimeAssets`
  and the packaged runtime assets (`runtime.js`, `runtime.css`), including
  the data-role / data-interactive markup contract with
  `education_pipeline/guides/document.py`.
- The module-level guide-v1 prompt compilers in `education_pipeline.prompts`
  (`compile_guide_v1_spec_prompt`, `compile_guide_v1_outline_prompt`,
  `compile_guide_v1_draft_prompt`, `compile_guide_v1_qa_prompt`,
  `compile_guide_v1_repair_prompt`). Legacy prompt text remains pinned
  byte-identical by SHA-256 snapshot tests in `tests/test_prompts.py`.
- The accepted Wave 4 `RunStore` lifecycle behavior in
  `education_pipeline/runs.py`: `ContentContract` with the
  interactive-guide new-run default and the explicit legacy creation path
  (store argument and `education-pipeline create <topic>
  [--legacy-markdown]`); contract-gated spec/outline approval; immutable
  `inputs/guide-contract.json`; `validate_run(topic_id, phase)`;
  `report_state(topic_id, phase)` returning `missing`/`current`/`stale`
  derived from content hashes; `draft_report_path` / `final_report_path` /
  `waivers_path`; the `validate` / `resolve_findings` next actions; the
  hash-bound waiver file `reports/validation-waivers.json`; guarded
  multi-artifact finalization writing canonical `final/guide.json` and
  projected `final/guide.md` with hash-recorded `finalized` events;
  hash-derived `is_finalized`; `StageStatus.stale`; the
  `response_replaced` manifest event on forced ingest; and the Wave 4
  refusal of guide-v1 `export_run` (which THIS chunk replaces with the real
  hash-gated guide HTML export — that refusal is the only accepted Wave 4
  behavior you are authorized to change).

Do not change any frozen signature, the normalized fixture bytes, IDs,
authored array order, or the hash without stopping at the smallest safe
state and reporting the exact contract blocker.

## Authoritative files to reopen completely

Before implementation, read:

```text
docs/product-requirements.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md   (sections 8, 10)
docs/superpowers/plans/2026-07-11-interactive-guide-v1.md   (section 10, Wave 5, and the Chunk 05 completion record)
education_pipeline/runs.py
education_pipeline/guides/document.py
education_pipeline/daemon/server.py
education_pipeline/daemon/read_api.py
education_pipeline/daemon/write_api.py
tests/test_server.py
tests/test_write_api.py
web/src/api/ (types and client)
web/e2e/guide-runtime.spec.ts
```

Also inspect `pyproject.toml`, package/test conventions, Git state, and
repository-local agent instructions. Trust live code, not this prompt or a
chat summary, when implementation details differ.

## Objective and authorized scope

Implement, review, verify, and commit only Wave 5 (plan section 10), in two
strictly ordered parts.

### Part A — Backend/API freeze (supervisor-owned)

All daemon route files (`education_pipeline/daemon/server.py`,
`read_api.py`, `write_api.py`), `education_pipeline/runs.py`, and shared API
types are hot files: no sub-agent may edit them concurrently with you or
with each other. Authorized work:

1. Add the content contract and validation summaries to run status
   (additively): `content_contract` and a `validations` object with
   per-phase `state` (`missing`/`current`/`stale`) and blocking/errors/
   warnings counts, per validation-pipeline spec section 10.
2. Add stage `content_type` to stage-content responses
   (`text/markdown` or
   `application/vnd.education-pipeline.guide+json;version=1.0`).
3. Add validate, findings, and waiver operations
   (`POST /v1/runs/{topic}/validate` with `{"phase": "draft"|"final"}`,
   `GET /v1/runs/{topic}/validation/{phase}`,
   `POST /v1/runs/{topic}/validation/{phase}/waivers`). Validate is guarded
   against an active job touching the relevant stage and is idempotent for
   identical input. Waiver creation requires finding ID, exact guide hash,
   and a non-empty reason; return `409` for stale report/input and `422`
   for a non-waivable finding.
4. Add `POST /v1/guide-preview` using the shared
   `assemble_guide_document` assembler (per the runtime-export spec).
5. Map errors through the existing envelope: malformed JSON → `400`;
   safe-but-invalid/unrenderable guide input → `422`; stale state → `409`;
   missing resources → `404`. Ensure request JSON roots are objects before
   accessing fields.
6. Branch final/download MIME types by content contract; preserve
   `/v1/preview` and legacy downloads unchanged.
7. Integrate guide HTML export (replacing the Wave 4 `export_run` refusal):
   it reads ONLY `final/guide.json`, verifies a current final
   report/hash/waivers and the packaged runtime assets, writes the export
   atomically, and records deterministic provenance hashes in the manifest.
8. Make the daemon's next-stage/enqueue logic aware of the `validate` and
   `resolve_findings` next actions only to the extent required so guide-v1
   runs are not mis-enqueued; do not redesign job semantics.

Freeze and document the additive response shapes (a short section in the
plan update or a checked-in note) before any frontend work begins.

Part A gate:

```bash
python3 -m pytest tests/test_write_api.py tests/test_server.py
python3 -m pytest
```

### Part B — Sandboxed cockpit preview (Agent B, only after Part A is accepted)

Agent B (or a delegated sub-agent) may start only after Part A is committed
and its response shapes are frozen. Agent B owns `web/src/` and web tests
and must not edit daemon route files, shared Python API code, or
`education_pipeline/` modules. Authorized work:

1. Extend the web API types/client for content contract, stage content
   type, validation summaries, findings, validate, waivers, and guide
   preview.
2. Preserve the existing stale editor-buffer behavior; add JSON syntax
   feedback without replacing or discarding the buffer.
3. Add `GuidePreviewFrame` using a sandboxed `iframe srcDoc` with scripts
   allowed but WITHOUT same-origin privileges. The executable guide runtime
   must never enter the current `dangerouslySetInnerHTML` preview path —
   that stays legacy Markdown only.
4. Make preview persistence explicitly disposable and exception-safe.

Part B gate:

```bash
cd web && npm test
cd web && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts   # must remain 32 passed
```

## Prohibited work

Do not:

- change the frozen fixture, normalized bytes, frozen public signatures,
  legacy prompt bytes, or canonical hash;
- edit `education_pipeline/guides/` modules or `guide_runtime/` assets
  (the assembler and runtime are accepted; the API consumes them);
- begin Wave 6 work: cockpit findings lists/filtering, waiver dialogs,
  final-review flow, run-board validation milestones, or the
  edit→reapprove→revalidate→finalize recovery UI — all of that is Chunk 07;
- let any sub-agent edit daemon route files, `runs.py`, or shared API
  types concurrently with the supervisor, or start Agent B before Part A
  is accepted and committed;
- change provider adapters beyond what enqueue-awareness strictly requires;
- install any Python dependency, or invoke providers/paid APIs;
- remove the explicit legacy creation path or the legacy `/v1/preview`
  and download behavior;
- use file deletion as invalidation; or
- execute Chunk 07, create its worktrees, or begin its code.

If an acceptance criterion appears to require prohibited work, record the
exact blocker and stop rather than expanding scope.

## Acceptance criteria

1. Run-status responses for guide-v1 runs carry the content contract and
   hash-derived draft/final validation summaries; legacy runs keep their
   existing shape plus only the documented additive fields.
2. Stage-content responses carry the correct `content_type` for both run
   kinds.
3. Validate/findings/waiver endpoints enforce the spec's guard, idempotency,
   and error-code semantics (`400`/`404`/`409`/`422`), and non-waivable
   findings are rejected with `422`.
4. `POST /v1/guide-preview` renders the fixture through the shared assembler
   and rejects malformed (`400`) and invalid-but-safe (`422`) input without
   executing model-authored HTML/JS.
5. Guide HTML export reads only `final/guide.json`, is hash-gated on a
   current final report and waivers, records provenance hashes, and legacy
   export remains byte-compatible.
6. The cockpit renders a guide preview only inside the sandboxed iframe
   (no same-origin privileges), JSON syntax feedback never discards the
   buffer, and the legacy Markdown preview path is unchanged.
7. Every pre-existing test still passes, with intentional updates only where
   a test's contract was explicitly superseded by this wave (record each).

## Execution and verification

Start with at least:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor e9b7fad01f563f2f1d932eead40867fe130a4348 HEAD
git diff --check
python3 -m pytest   # baseline: 400 passed at the accepted Wave 4 head
```

Run the shared regression gate after integration:

```bash
git diff --check
python3 -m pytest
cd web && npm test && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts   # must remain 32 passed
```

If sandbox policy denies temporary loopback sockets, rerun the identical
command with the required permission and classify it as environmental only
when the unrestricted rerun passes. Do not change product code around
sandbox restrictions. Investigate other failures enough to distinguish
regressions from pre-existing environment failures and record exact
evidence. Known pre-existing risk (recorded in the Chunk 05 completion
record): `web/e2e/full-run.spec.ts` drives a new run through the legacy
cockpit flow and will fail against the guide-v1 default until cockpit
support lands; decide within Wave 5 scope whether Part B minimally
addresses run creation, or record it as remaining Wave 6 work — do not
silently delete or skip the spec.

Before closeout, inspect the entire accepted diff and use targeted searches
to prove `education_pipeline/guides/`, `guide_runtime/`, provider code,
legacy prompt bytes, legacy preview/download behavior, and the fixture were
not changed.

## Commits and recovery

- Fix ordinary defects within the authorized scope.
- Use explicit path lists for staging. Never stage unrelated files.
- Prefer clean logical commits, for example
  `feat(api): guide export, preview, findings, and waiver endpoints` and
  `feat(web): isolated guide preview and JSON editing feedback`.
- Do not amend accepted Wave 1–4 commits.
- Stop for human direction only when specs materially conflict, a frozen
  contract would need to change, or unrelated overlapping changes cannot be
  separated safely.

## Plan update and Chunk 07 prompt

After the acceptance criteria and shared gates pass, reopen the live
implementation plan. Set Chunk 06 to `Complete` and Chunk 07 to `Ready`.
Under Wave 5 record: completion date; every accepted commit; the frozen
additive API response shapes; preview-isolation evidence; export provenance
behavior; confirmation that the fixture hash remains
`99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`; exact
focused and shared verification results; deviations/decisions; and
remaining risks, or `None`.

Then create the complete next supervisor prompt at:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-07-supervisor.md
```

Derive it from the accepted Wave 5 commits and the live Wave 6 plan section
(plan section 11). It must freeze the fixture hash, the accepted API
response shapes, and all accepted lifecycle/runtime behavior; authorize
only Wave 6 work (cockpit findings summaries and filtering, JSON-Pointer /
related-ID navigation, the guarded waiver dialog, current/waived/stale
finding separation, finalize gating with concrete reasons, provider
rerun/replace confirmation and provenance display, and the complete
edit → reapprove → revalidate → finalize recovery loop, with the
supervisor owning run-board action semantics and shared API coordination
and Agent B owning leaf React components after their props are fixed);
prohibit Wave 7 CI/packaging/accessibility-closeout work; define ownership
and hot-file boundaries; include recovery, verification, plan-evidence,
and commit rules; require `chunk-08-supervisor.md` as its final
substantive deliverable; and stop without beginning Chunk 08.

Review the plan update and Chunk 07 prompt against the accepted
implementation commits, then commit only those closeout documentation files
in a separate commit such as:

```text
docs: close interactive guide chunk 06
```

## Human gate and final report

After the Wave 5 implementation commits and closeout commit exist, stop. Do
not invoke the Chunk 07 prompt, begin findings/final-review cockpit work,
or cross the human checkpoint.

Report:

- Chunk 06 outcome;
- all implementation and closeout commit hashes;
- exact focused/shared verification results;
- unchanged canonical fixture path and SHA-256;
- the frozen additive API response shapes and any new public surface;
- preview-isolation and export-provenance evidence;
- changed-scope summary;
- the path to `chunk-07-supervisor.md`; and
- a direct statement that Chunk 07 has not started.

If the chunk cannot be completed safely, report the exact blocker and
preserve all useful verified work. Do not fabricate the next prompt as
though Wave 5 had been accepted.
