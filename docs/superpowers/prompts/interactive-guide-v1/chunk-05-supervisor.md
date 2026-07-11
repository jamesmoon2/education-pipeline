# Supervisor Prompt — Interactive Guide v1, Chunk 05

You are the supervisor agent for **Chunk 05: implement and accept the Wave 4
pipeline lifecycle, freshness, validation, and finalization work** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete only this chunk autonomously, including safe recovery from ordinary
implementation or verification failures. Do not begin Chunk 06. A human
controls the transition between chunks.

## Accepted base and frozen contracts

The accepted Wave 3 integration head is commit:

```text
28220bee44cc02f7f752e03a2546e4e871a04f7f
```

The accepted Wave 3 commits, in merge order, are:

```text
94c76ba0b4512f4af8e62ec56f89750e392e86c9  feat(prompts): add machine-readable guide contracts
eab948d0198ccbbc2e435a88b39f5adc8770283f  fix(prompts): enforce contract block safety and repair constraints
7627d8b58d4a59738fa1bc958e0dd7ea9be912fe  feat(runtime): add guide interactions and local persistence
28220bee44cc02f7f752e03a2546e4e871a04f7f  test(runtime): cover keyboard interaction paths
```

Confirm `28220be` is an ancestor of `HEAD`, inspect the live branch/worktree,
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

The accepted public Python entry points, exported from
`education_pipeline.guides`, are frozen:

```text
parse_guide(text: str | bytes) -> ParseResult
normalize_guide(parsed: ParseResult | Mapping[str, Any]) -> Guide
canonical_guide_bytes(guide: Guide) -> bytes
guide_sha256(guide: Guide) -> str
project_guide_markdown(guide: Guide) -> str
validate_guide(value, *, phase="final", private_values=(), context=ValidationContext()) -> ValidationReport
canonical_report_bytes(report: ValidationReport) -> bytes
apply_waivers(report: ValidationReport, waiver_set: WaiverSet | None) -> WaiverResult
assemble_guide_document(guide: Guide, assets: RuntimeAssets | None = None, mode: DocumentMode = "export") -> str
render_guide_markdown(markdown: str, known_ids: Iterable[str]) -> str
extract_spec_contract(markdown_text: str) -> dict[str, Any]
extract_outline_contract(markdown_text: str) -> dict[str, Any]
validate_spec_contract(data: Mapping[str, Any]) -> None
validate_outline_contract(data: Mapping[str, Any]) -> None
check_contract_conflict(spec_contract, outline_contract) -> None
build_guide_contract(spec_contract, outline_contract, *, publishable_profile_summary: str | None = None) -> bytes
```

Also frozen: `ContractError` in `education_pipeline.guides`;
`education_pipeline.guide_runtime.load_runtime_assets()` / `RuntimeAssets`;
`education_pipeline.runs.ContentContract` with `RunStore.content_contract()`;
and, at module level in `education_pipeline.prompts`, the guide-v1 prompt
compilers:

```text
compile_guide_v1_spec_prompt(spec_input: SpecPromptInput) -> PromptArtifact
compile_guide_v1_outline_prompt(topic, approved_spec, profile=None) -> PromptArtifact
compile_guide_v1_draft_prompt(topic, approved_outline, guide_contract: bytes, profile=None) -> PromptArtifact
compile_guide_v1_qa_prompt(topic, *, approved_spec, approved_outline, draft_guide_json, draft_findings_json, profile=None) -> PromptArtifact
compile_guide_v1_repair_prompt(topic, *, draft_guide_json, qa_findings_markdown, draft_findings_json, guide_contract: bytes, profile=None) -> PromptArtifact
```

Legacy prompt text is pinned byte-identical by SHA-256 snapshot tests in
`tests/test_prompts.py`; those pins must not change. The runtime interaction
markup contract between `education_pipeline/guides/document.py` and
`education_pipeline/guide_runtime/assets/runtime.js` (data-role /
data-interactive attributes) is accepted; do not modify runtime assets or the
document assembler in this chunk. Do not change any frozen signature, the
normalized fixture bytes, IDs, authored array order, or the hash without
stopping at the smallest safe state and reporting the exact contract blocker.

## Authoritative files to reopen completely

Before implementation, read:

```text
docs/product-requirements.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-schema.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md
docs/superpowers/plans/2026-07-11-interactive-guide-v1.md   (section 9, Wave 4, and the Chunk 04 completion record)
education_pipeline/runs.py
education_pipeline/prompts.py
education_pipeline/guides/__init__.py
education_pipeline/guides/contract.py
education_pipeline/guides/validation.py
education_pipeline/guides/waivers.py
education_pipeline/guides/projection.py
tests/test_runs.py
tests/test_prompts.py
tests/test_guide_contract.py
tests/fixtures/guides/feedback-loops.guide.json
```

Also inspect `pyproject.toml`, package/test conventions, Git state, and
repository-local agent instructions. Trust live code, not this prompt or a
chat summary, when implementation details differ.

## Objective and authorized scope

Implement, review, verify, and commit only Wave 4 (plan section 9): the
supervisor-owned run-lifecycle integration that makes guide-v1 runs flow
through the durable pipeline. This work is **supervisor-owned**: no sub-agent
may edit `education_pipeline/runs.py` concurrently with any other agent. You
may delegate bounded, non-overlapping sub-tasks (for example test authoring
against a frozen interface, or a self-contained helper module) only if each
delegation names an explicit disjoint file list and none of them includes
`runs.py` while another agent or you are editing it. Integration, review, and
acceptance stay with you.

Authorized work (all within `education_pipeline/runs.py`, its tests, and —
only where strictly required — small additive changes to
`education_pipeline/workspace.py`, `education_pipeline/cli.py` surface plumbing
for the explicit legacy override, and their tests):

1. Contract-aware stage artifact paths and content types: spec/outline/QA
   remain Markdown; draft/repair use `.json` response/approved paths for
   guide-v1 runs; legacy paths byte-for-byte unchanged.
2. Wire machine-contract extraction into spec and outline approval for
   guide-v1 runs using the frozen `extract_spec_contract` /
   `extract_outline_contract` / `check_contract_conflict` helpers; a
   missing, malformed, duplicated, or conflicting block is an
   approval-blocking error.
3. Write immutable `inputs/guide-contract.json` (bytes from the frozen
   `build_guide_contract`) when the guide-v1 draft prompt is created;
   atomic write, no-clobber.
4. Compile guide-v1 draft/QA/repair prompts through the frozen
   `compile_guide_v1_*` functions for guide-v1 runs; legacy runs keep the
   legacy compilers and byte-identical prompt text.
5. Insert deterministic draft validation after draft approval and before the
   QA prompt is written; a draft too malformed to parse produces a minimal
   report and blocks the QA prompt until corrected and reapproved. Reports
   are written to `reports/draft-validation.json` with canonical bytes from
   `canonical_report_bytes`.
6. Include the deterministic draft findings in the QA and repair prompts
   (via the frozen prompt compilers' untrusted-data parameters).
7. Insert final validation after repair approval
   (`reports/final-validation.json`), matched to the SHA-256 of the
   currently approved repair artifact.
8. Derive report state (`missing`, `current`, `stale`) from source hashes,
   never from file existence. Editing or reapproving an upstream artifact
   marks dependent reports/approvals/finals/exports stale through hashes and
   status; never delete stale files as invalidation.
9. Add `validate` and `resolve_findings` next actions per the
   validation-pipeline spec section 8: after final validation, no blockers →
   `finalize`; waivable blockers → `resolve_findings`; non-waivable blockers
   → `resolve_findings` (waivers must be rejected for them by the existing
   waiver engine semantics).
10. Record the replaced response hash in the manifest before any forced
    provider overwrite of an existing response.
11. Guarded guide-v1 finalization as a multi-artifact operation: verify a
    current final report and waivers; refuse remaining blockers; parse and
    normalize the approved repair JSON; write canonical `final/guide.json`
    atomically; write deterministic projected `final/guide.md` atomically;
    record source/report/output hashes and schema version in the manifest;
    report finalized only when every write succeeded (a partial failure must
    never report finalized).
12. Flip newly created manifests to `interactive_guide` schema `1.0` as the
    default **only after** the full guide lifecycle regression scenarios
    pass, and preserve an explicit legacy creation path (CLI/API parameter
    or store argument) for compatibility testing and recovery. A run's
    content contract remains immutable after its first prompt.

Required regression scenarios (from plan section 9): legacy byte-for-byte
compatibility where promised; legacy and guide-v1 runs coexisting in one
workspace; draft edit invalidating the draft report and downstream work;
repair edit invalidating final report/final/export; idempotent revalidation
with identical input; waivers becoming stale on guide-hash change;
non-waivable findings impossible to bypass; a partial finalization failure
never reporting the run finalized.

## Prohibited work

Do not:

- change the frozen fixture, normalized bytes, frozen public signatures,
  legacy prompt bytes, or canonical hash;
- edit `education_pipeline/guides/` modules, `guide_runtime/` assets, or the
  document assembler (Wave 3 surfaces are accepted and closed);
- add API/daemon routes, findings/waiver endpoints, guide-preview endpoints,
  export integration, run-status response-shape changes, or any
  `education_pipeline/daemon/` change — all of that is Wave 5 (Chunk 06);
- add HTML guide export (`final/guide.html`) — export integration is Wave 5;
- touch cockpit source (`web/src/`), e2e specs, or web dependencies;
- change provider adapters or daemon lifecycle beyond what the manifest
  hash-recording item strictly requires inside `runs.py`;
- install any dependency, or invoke providers/paid APIs;
- flip the new-run default before the full lifecycle regression scenarios
  pass, or remove the explicit legacy creation path;
- use file deletion as invalidation; or
- execute Chunk 06, create its worktrees, or begin its code.

If an acceptance criterion appears to require prohibited work, record the
exact blocker and stop rather than expanding scope.

## Acceptance criteria

1. A guide-v1 run walks the full state machine from the validation-pipeline
   spec section 8 (spec → outline → draft → draft validation → qa → repair →
   final validation → finalize → done) against fixture-derived responses,
   producing `inputs/guide-contract.json`, `.json` draft/repair artifacts,
   both validation reports, and canonical `final/guide.json` plus projected
   `final/guide.md` with recorded hashes.
2. Approval of a guide-v1 spec/outline response without exactly one valid
   contract block fails with a useful diagnostic and does not advance the
   run.
3. Report freshness is hash-derived: editing the approved draft or repair
   makes the dependent report/final stale without deleting files, and
   revalidation with identical input is idempotent.
4. `validate` and `resolve_findings` surface as next actions exactly per the
   spec's post-validation rules, and non-waivable blockers cannot be
   bypassed.
5. Finalization is atomic-in-effect: any injected partial failure leaves the
   run un-finalized with prior artifacts intact.
6. New runs default to guide v1 only after criteria 1–5 pass; the explicit
   legacy creation path produces a byte-compatible legacy run; existing
   legacy manifests remain legacy and untouched; mixed workspaces list and
   resume both kinds.
7. Every pre-existing test still passes, with intentional updates only where
   a test's contract was explicitly superseded by this wave (record each).

## Execution and verification

Start with at least:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 28220bee44cc02f7f752e03a2546e4e871a04f7f HEAD
git diff --check
python3 -m pytest   # baseline: 369 passed at the accepted Wave 3 head
```

Require focused verification:

```bash
python3 -m pytest tests/test_runs.py tests/test_guide_validation.py tests/test_prompts.py tests/test_guide_contract.py
```

Run the shared regression gate after integration:

```bash
git diff --check
python3 -m pytest
cd web && npm test && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts   # must remain 32 passed; web/ is out of scope for edits
```

If sandbox policy denies temporary loopback sockets, rerun the identical
command with the required permission and classify it as environmental only
when the unrestricted rerun passes. Do not change product code around sandbox
restrictions. Investigate other failures enough to distinguish regressions
from pre-existing environment failures and record exact evidence.

Before closeout, inspect the entire accepted diff and use targeted searches
to prove `education_pipeline/guides/`, `guide_runtime/`, `daemon/`, provider
code, legacy prompt bytes, legacy renderer behavior, web source, and the
fixture were not changed.

## Commits and recovery

- Fix ordinary defects within the authorized scope.
- Use explicit path lists for staging. Never stage unrelated files.
- Prefer clean logical commits, for example
  `feat(pipeline): contract-aware guide-v1 artifacts and prompts`,
  `feat(pipeline): validation lifecycle, freshness, and guarded finalization`,
  and `feat(pipeline): default new runs to interactive guide v1`.
- Do not amend accepted Wave 1–3 commits.
- Stop for human direction only when specs materially conflict, a frozen
  contract would need to change, or unrelated overlapping changes cannot be
  separated safely.

## Plan update and Chunk 06 prompt

After the acceptance criteria and shared gates pass, reopen the live
implementation plan. Set Chunk 05 to `Complete` and Chunk 06 to `Ready`.
Under Wave 4 record: completion date; every accepted commit; delivered
capabilities and state-machine decisions; mixed legacy/v1 evidence;
confirmation that the fixture hash remains
`99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`; exact
focused and shared verification results; deviations/decisions; and remaining
risks, or `None`.

Then create the complete next supervisor prompt at:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-06-supervisor.md
```

Derive it from the accepted Wave 4 commits and the live Wave 5 plan section
(plan section 10). It must freeze the fixture hash and all accepted APIs and
lifecycle behavior; authorize only Wave 5 work (Part A supervisor-owned
backend/API freeze: run-status validation summaries, stage `content_type`,
validate/findings/waiver operations, `POST /v1/guide-preview`, error-envelope
mappings, contract-aware final/download MIME types, and hash-gated guide HTML
export reading only `final/guide.json`; then Part B, Agent B's sandboxed
cockpit preview after the response shapes are frozen); prohibit Wave 6
findings/final-review cockpit work; define ownership and hot-file boundaries
(no sub-agent edits daemon route files or shared API types concurrently with
the supervisor; Agent B starts only after Part A is accepted); include
recovery, verification, plan-evidence, and commit rules; require
`chunk-07-supervisor.md` as its final substantive deliverable; and stop
without beginning Chunk 07.

Review the plan update and Chunk 06 prompt against the accepted
implementation commits, then commit only those closeout documentation files
in a separate commit such as:

```text
docs: close interactive guide chunk 05
```

## Human gate and final report

After the Wave 4 implementation commits and closeout commit exist, stop. Do
not invoke the Chunk 06 prompt, begin API/preview work, or cross the human
checkpoint.

Report:

- Chunk 05 outcome;
- all implementation and closeout commit hashes;
- exact focused/shared verification results;
- unchanged canonical fixture path and SHA-256;
- accepted lifecycle behavior and any new public surface;
- changed-scope summary;
- the path to `chunk-06-supervisor.md`; and
- a direct statement that Chunk 06 has not started.

If the chunk cannot be completed safely, report the exact blocker and
preserve all useful verified work. Do not fabricate the next prompt as though
Wave 4 had been accepted.
