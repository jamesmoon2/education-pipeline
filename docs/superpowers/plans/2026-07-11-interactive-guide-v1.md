# Interactive Guide v1 — Implementation Plan

**Status:** Ready for execution
**Date:** 2026-07-11
**Milestone spec:**
`docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md`

## 1. Recommendation

Use one supervisor agent and two implementation agents, working in staged waves
from separate Git worktrees.

Do not give each agent one third of the full milestone and let all three edit
freely. This milestone has several high-conflict seams—`runs.py`, daemon routes,
shared API types, stage status, and end-to-end fixtures. Parallelism is valuable
only after the shared content contract is executable and frozen.

Recommended ownership:

| Role | Owns | Must not edit concurrently |
| --- | --- | --- |
| Supervisor / integrator | Contract decisions, canonical fixture acceptance, `runs.py`, manifest/state transitions, daemon routes, shared API types, cockpit orchestration, merge order, final acceptance | No other agent edits these hot files while integration is active |
| Agent A — guide core | Python guide types, parser, canonical serializer, Markdown projection, deterministic validation, waiver engine, prompt-contract extraction and tests | Does not edit `runs.py`, daemon server routes, or cockpit |
| Agent B — runtime | Packaged guide runtime assets, document assembler, safe renderer, interactions, persistence, print, runtime browser tests; later sandboxed cockpit preview after API freeze | Does not edit `runs.py`, validation rules, or daemon routes |

This is not a three-way race. The supervisor opens and closes each wave, freezes
the integration surface, and accepts or rejects agent work before the next wave.

## 2. Working model

### Branches and worktrees

First land the current PRD/spec/archive documentation as its own commit or PR.
Then create a short-lived integration branch:

```text
codex/interactive-guide-v1
```

Create agent worktrees from the latest accepted integration point:

```text
/private/tmp/education-guide-core       codex/guide-v1-core
/private/tmp/education-guide-runtime    codex/guide-v1-runtime
```

For later waves, recreate or rebase the agent branches from the integration
branch after the preceding contracts merge. Do not keep a long-running agent
branch across several upstream contract changes.

Each agent should:

- receive a bounded file/behavior assignment;
- commit logical slices on its own branch;
- report exact verification commands and results;
- avoid formatting or cleanup outside its ownership; and
- stop when the assigned acceptance boundary is green.

The supervisor should review and merge/cherry-pick each slice, rerun the shared
test gate, and only then issue the next assignment.

### Why this shape

- Agent A and Agent B can work independently once they share one normalized JSON
  fixture.
- The supervisor protects the current durable pipeline and legacy compatibility
  from conflicting state-machine edits.
- Runtime work can advance without waiting for every API detail.
- Cockpit work waits until additive server response shapes are fixed, preventing
  TypeScript and Python from chasing each other.
- Every merge point leaves the integration branch runnable and reviewable.

### Human-gated chunk relay

Execution is automated inside a logical chunk and deliberately pauses between
chunks. The human starts each chunk by giving its checked-in prompt to a fresh
supervisor agent. That supervisor may delegate only the bounded work authorized
by the prompt, completes and verifies the chunk, updates this plan, writes the
next chunk's complete prompt, and stops.

The human checkpoint exists to:

- inspect the completed diff and verification evidence;
- monitor token and elapsed-time budgets;
- decide when to continue;
- adjust scope or priorities before starting the next chunk; and
- replace the next prompt if product direction changes.

No supervisor may start the following chunk merely because it finished the
current one. “Continue automatically” means continue through the current
chunk’s safe implementation and recovery steps—not cross the human gate.

Prompt files live under:

```text
docs/superpowers/prompts/interactive-guide-v1/
```

Naming is stable:

```text
chunk-01-supervisor.md
chunk-02-supervisor.md
...
chunk-09-post-milestone-supervisor.md
```

Each chunk prompt must be self-contained and must instruct the next supervisor
to reopen the live plan/specs/code rather than trust a chat summary.

### Required terminal sequence for every chunk

The final steps of every logical chunk are mandatory and happen in this order:

1. Reopen the live diff and confirm the chunk stayed within scope.
2. Run the chunk’s focused checks and the shared regression gate.
3. Resolve failures that are within scope; if genuinely blocked, record exact
   evidence instead of beginning unrelated work.
4. Update the chunk ledger and the completed wave section in this plan with:
   - status;
   - completion date;
   - commit(s), if available;
   - files/capabilities delivered;
   - exact verification commands and outcomes;
   - deviations and decisions; and
   - any remaining risks.
5. Write the complete prompt for the next logical chunk at the stable path. The
   prompt must include the accepted base, objective, scope, ownership/delegation,
   prohibited work, verification, recovery rules, plan-update requirement, and
   the same human-gated stop instruction.
6. Review the next prompt against the newly updated plan and live repository.
7. Commit the current chunk’s implementation, plan update, and next prompt as
   the chunk’s final durable state, unless the human explicitly requested a
   staged-only handoff.
8. Stop and report the outcome plus the next prompt path. Include the next
   prompt verbatim in the final response when practical. Do not execute it.

For the final milestone chunk, the “next prompt” is a post-milestone audit and
next-milestone planning prompt. It must still stop for human review before any
new milestone begins.

### Chunk ledger

| Chunk | Plan wave | Deliverable | Status | Prompt |
| --- | --- | --- | --- | --- |
| 01 | Wave 0 | Documentation baseline landed | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-01-supervisor.md` |
| 02 | Wave 1 | Guide contract core and canonical fixture | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-02-supervisor.md` |
| 03 | Wave 2 | Validators, runtime shell, content-contract foundation | Ready | `docs/superpowers/prompts/interactive-guide-v1/chunk-03-supervisor.md` |
| 04 | Wave 3 | Prompt contracts and runtime interactions | Planned | Generated by Chunk 03 |
| 05 | Wave 4 | Pipeline lifecycle, freshness, validation, finalization | Planned | Generated by Chunk 04 |
| 06 | Wave 5 | Export/preview API and sandboxed cockpit preview | Planned | Generated by Chunk 05 |
| 07 | Wave 6 | Findings, waivers, final review, acceptance loop | Planned | Generated by Chunk 06 |
| 08 | Wave 7 | CI, packaging, accessibility, docs, closeout | Planned | Generated by Chunk 07 |
| 09 | Post-milestone | Independent audit and next-milestone proposal | Planned | Generated by Chunk 08 |

## 3. Contract lock before implementation

The specs now resolve the four contract questions that must not be delegated:

1. Canonical JSON sorts keys lexicographically at every object level.
2. Every `id` field, including choices and reveal steps, is globally unique.
3. Approved spec and outline Markdown contain exactly one typed fenced JSON
   contract block; the pipeline never derives stable IDs by slugging prose.
4. Existing manifests without `content_contract` are legacy Markdown; new runs
   default to immutable interactive guide schema `1.0` after the milestone
   integration flips the default.

The first code slice must prove these decisions with a canonical fixture and
hash. No runtime, pipeline, or cockpit integration begins before that fixture is
accepted.

## 4. Delivery map

```text
Wave 0  Documentation baseline
   ↓
Wave 1  Guide contract core + canonical fixture
   ↓
Wave 2  ┌─ Agent A: validators/waivers
        ├─ Agent B: runtime shell/assembler
        └─ Supervisor: content-contract manifest foundation
   ↓
Wave 3  ┌─ Agent A: prompt/contract integration
        └─ Agent B: interactions/persistence/browser tests
   ↓
Wave 4  Supervisor: run lifecycle, freshness, validation gates, finalization
   ↓
Wave 5  Supervisor + Agent B: export/preview API, then sandboxed cockpit preview
   ↓
Wave 6  Cockpit findings, waivers, final review, mixed legacy/v1 acceptance
   ↓
Wave 7  CI, accessibility record, packaging, docs, milestone closeout
```

## 5. Wave 0 — Land the documentation baseline

### Owner

Supervisor.

### Work

- Review and commit the archived plans, product PRD, four milestone specs, and
  this implementation plan.
- Confirm all relative links resolve.
- Keep this documentation change separate from implementation code.
- Record the integration base commit in the first code PR.

### Gate

```bash
git diff --check
python3 -m pytest
```

No code agent begins from an uncommitted shared documentation worktree.

### Chunk 01 relay closeout

After the gate passes, update Chunk 01 in the ledger to `Complete`, record the
documentation commit and verification, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-02-supervisor.md`, commit
that prompt with the plan update, and stop for human review. Do not begin the
guide contract core.

### Chunk 01 completion record

- **Completed:** 2026-07-11
- **Baseline commit:** `e35f9c82a620e89e27dcb846a240a09bb73cdf10`
- **Delivered:** authoritative whole-product PRD; four Interactive Guide v1
  milestone specs; checkpointed implementation plan and Chunk 01 prompt;
  archived roadmap, open-source readiness, and frontend plans; README status
  corrections; and archived-path repairs in historical specs.
- **Verification:** `git diff --check` passed; the scoped local-Markdown link
  checker reported `All local Markdown links resolve`; archive comparison and
  review confirmed the archived files retain their historical content with an
  archive notice; and
  `rg -n "docs/(roadmap|open-source-readiness-plan)\\.md|frontendplan\\.md" -g '*.md'`
  returned only intentional archive/self-reference and Chunk 01 historical-path
  wording. The first sandboxed `python3 -m pytest` run produced `200 passed`,
  `4 failed`, and `59 errors` because loopback socket binds were denied with
  `PermissionError: [Errno 1] Operation not permitted`; rerunning the identical
  command with loopback permission passed: `263 passed in 33.66s`.
- **Decisions/deviations:** clarified that guide v1 becomes the immutable
  new-run default only after lifecycle integration, with an explicit legacy
  override for compatibility testing and recovery; removed Markdown trailing
  whitespace found by the staged diff check. No production or test code changed.
- **Remaining risks:** None for the documentation baseline. Implementation
  risks remain governed by the Wave 1 contract gate and later stop/go checkpoints.

## 6. Wave 1 — Guide contract core

### Owner

Agent A, reviewed by the supervisor. Agent B waits for the accepted normalized
fixture rather than independently interpreting prose specs.

### Proposed files

```text
education_pipeline/guides/__init__.py
education_pipeline/guides/model.py
education_pipeline/guides/parse.py
education_pipeline/guides/canonical.py
education_pipeline/guides/projection.py
tests/fixtures/guides/feedback-loops.guide.json
tests/test_guide_parse.py
tests/test_guide_canonical.py
tests/test_guide_projection.py
```

Names may change during implementation, but the package boundary should remain
isolated from the legacy `education_pipeline/export.py` renderer.

### Work

1. Check in the complete “Thinking in Feedback Loops” fixture from the milestone
   acceptance scenario.
2. Implement a parser that:
   - reports multiple structural findings when possible;
   - rejects unknown fields/types and unsupported versions;
   - enforces global IDs and references; and
   - produces a typed normalized guide only when render-blocking defects are
     absent.
3. Implement canonical serialization with fixed UTF-8/newline behavior and
   lexicographically sorted object keys.
4. Expose a single canonical SHA-256 helper used by every later layer.
5. Implement the deterministic Markdown projection covering every content block.
6. Add focused malformed fixtures as small mutations in tests rather than
   duplicating the full valid course file.

### Contract to freeze

Before merge, publish these stable Python entry points or equivalents:

```text
parse_guide(text) -> parse result with findings
normalize_guide(parsed) -> Guide
canonical_guide_bytes(guide) -> bytes
guide_sha256(guide) -> str
project_guide_markdown(guide) -> str
```

The exact normalized JSON bytes and SHA-256 of the fixture become a checked
test assertion. Agent B builds only against this accepted artifact.

### Gate

```bash
python3 -m pytest tests/test_guide_parse.py tests/test_guide_canonical.py tests/test_guide_projection.py
python3 -m pytest
```

### Merge rule

Merge before parallel Wave 2 begins.

### Chunk 02 relay closeout

After the merge rule and gate pass, update Chunk 02 to `Complete`, record the
canonical fixture hash and accepted public Python entry points, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-03-supervisor.md`, commit
the closeout, and stop. Do not create the Wave 2 worktrees or start validators
or runtime work.

### Chunk 02 completion record

- **Completed:** 2026-07-11
- **Implementation commit:** `6e36dc45520eff5bde9d65af5d456f73f0f011ed`
- **Delivered:** isolated `education_pipeline.guides` typed schema-v1 model;
  authoritative JSON parser with multi-diagnostic structural errors, strict
  fields/types/cardinality, global IDs, references, outcome/module invariants,
  and parsing-owned Markdown/URL safety; immutable normalization; recursive
  canonical JSON serialization and SHA-256; complete “Thinking in Feedback
  Loops” fixture; deterministic Markdown projection; and focused mutation tests
  freezing all six block shapes and the legacy boundary.
- **Accepted public Python signatures:** `parse_guide(text: str | bytes) ->
  ParseResult`; `normalize_guide(parsed: ParseResult | Mapping[str, Any]) ->
  Guide`; `canonical_guide_bytes(guide: Guide) -> bytes`;
  `guide_sha256(guide: Guide) -> str`; and
  `project_guide_markdown(guide: Guide) -> str`, exported from
  `education_pipeline.guides`.
- **Canonical fixture:**
  `tests/fixtures/guides/feedback-loops.guide.json`; normalized SHA-256
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`.
- **Verification:** `git diff --check` passed;
  `python3 -m pytest tests/test_guide_parse.py tests/test_guide_canonical.py
  tests/test_guide_projection.py` passed with `30 passed in 0.13s`; the first
  sandboxed `python3 -m pytest` run failed at the first daemon loopback bind
  with `PermissionError: [Errno 1] Operation not permitted`; rerunning the
  identical command with loopback permission passed with
  `293 passed in 33.26s`.
- **Decisions/deviations:** no packaging or root-package export was needed;
  the accepted API is exposed from the isolated `education_pipeline.guides`
  package. Parse diagnostics remain structural and deliberately do not
  implement Wave 2 report, finding, or waiver types. No legacy renderer,
  pipeline, daemon, provider, CLI, frontend, or packaging file changed.
- **Remaining risks:** None for the Wave 1 contract core. Wave 2 runtime parity
  and validation-report behavior remain governed by their own acceptance gates.

## 7. Wave 2 — Safe parallel foundations

Wave 2 starts only from the accepted Wave 1 commit.

### Lane A — Deterministic validators and waivers

**Owner:** Agent A.

Proposed files:

```text
education_pipeline/guides/validation.py
education_pipeline/guides/reports.py
education_pipeline/guides/waivers.py
tests/test_guide_validation.py
tests/test_guide_waivers.py
```

Work:

- Implement report/finding types, stable IDs, deterministic sort, summary, and
  canonical timestamp-free serialization.
- Implement every milestone rule in explicit groups: parse/schema,
  security/privacy, outcomes/pedagogy, content/sources, runtime/static
  accessibility.
- Keep waiver application separate from report generation. Waivers calculate an
  effective gate; they never remove or mutate findings.
- Derive privacy match inputs from private profile fields without echoing values
  into findings. Establish minimum-length/generic-value exclusions to reduce
  false positives.
- Test guide-hash staleness and non-waivable rejection.

Gate:

```bash
python3 -m pytest tests/test_guide_validation.py tests/test_guide_waivers.py
python3 -m pytest
```

### Lane B — Runtime shell and deterministic document assembler

**Owner:** Agent B.

Proposed boundary:

```text
education_pipeline/guide_runtime/
  __init__.py
  assets/runtime.js
  assets/runtime.css
education_pipeline/guides/document.py
tests/test_guide_document.py
web/e2e/guide-runtime.spec.ts
```

Work:

- Keep the exported runtime browser-native and independent of React.
- Load packaged assets through `importlib.resources`; update setuptools package
  data so wheels contain JavaScript/CSS.
- Build one pure assembler:

  ```text
  normalized guide + exact runtime assets + mode -> full deterministic HTML
  ```

- Implement safe JSON embedding, asset hashes, CSP, static loading/error shell,
  and schema/runtime version checks.
- Implement a safe Markdown/URL renderer for guide v1. Do not reuse the current
  regex link substitution in `education_pipeline/export.py`.
- Start with navigation and static rendering of all six block types; interaction
  state arrives in Wave 3.
- Test closing-script strings, `<`, `>`, `&`, U+2028/U+2029, raw HTML, unsafe
  URLs, CSP hashes, exact assets, and repeated byte determinism.

Asset approach:

- Prefer small, directly maintained browser-native JavaScript and CSS assets.
- If TypeScript/build tooling is introduced, commit the distributable package
  assets and add a CI drift check proving generated output matches source.
- Do not make Node a Python-package installation or runtime dependency.

Gate:

```bash
python3 -m pytest tests/test_guide_document.py
cd web && npm test && npm run build
```

### Supervisor lane — Manifest/content-contract foundation

**Owner:** Supervisor only.

Work:

- Introduce a `ContentContract` value and manifest accessor.
- Interpret absent content contract as `legacy_markdown`.
- Allow explicit immutable `interactive_guide` schema `1.0` on new manifests.
- Add content-type/path maps without changing the default pipeline yet.
- Add source/input hashes needed for future freshness calculations.
- Preserve exact legacy paths and behavior.

The supervisor must not yet insert validation into `_next_action()` or flip new
runs to guide v1. This slice only creates the compatibility foundation.

Gate:

```bash
python3 -m pytest tests/test_runs.py tests/test_cli.py tests/test_e2e.py
python3 -m pytest
```

### Merge order

1. Agent A validators.
2. Agent B runtime shell.
3. Supervisor content-contract foundation.

They should be independently reviewable; resolve any shared package-export
edits in the supervisor worktree.

### Chunk 03 relay closeout

After all three lanes merge and the shared gate passes, update Chunk 03 to
`Complete`, record each lane’s commit and verification, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-04-supervisor.md`, commit
the closeout, and stop. Do not begin prompt or runtime-interaction work.

## 8. Wave 3 — Parallel content and interaction work

### Lane A — Machine-readable prompt contracts

**Owner:** Agent A.

Work in `education_pipeline/prompts.py` and new guide-contract helpers/tests:

- Require exactly one `education-pipeline-contract+json` fenced block in spec
  responses and one `education-pipeline-outline+json` block in outline
  responses.
- Parse and validate those blocks before approval for guide-v1 runs.
- Build immutable `inputs/guide-contract.json` deterministically.
- Change draft prompts to request JSON only and include a concise schema
  reference.
- Include normalized draft and deterministic findings in QA as clearly
  delimited untrusted data.
- Change repair prompts to return complete guide JSON, preserving stable IDs.
- Keep spec/outline/QA Markdown and all legacy prompts unchanged.

Important: the prompt lane exposes helpers but does not wire them into
`RunStore`; the supervisor performs that integration in Wave 4.

Gate:

```bash
python3 -m pytest tests/test_prompts.py tests/test_guide_contract.py
python3 -m pytest
```

### Lane B — Runtime interactions and browser behavior

**Owner:** Agent B.

Work:

- Implement knowledge-check submit/retry/explanation.
- Implement progressive worked reveals and reset/show-all.
- Implement scenario feedback/debrief.
- Implement reflection notes, skip, and reset.
- Implement section/module navigation, fragments, completion, progress, themes,
  reduced motion, responsive layout, and print expansion.
- Make localStorage reads/writes schema-checked and exception-safe.
- Use the canonical JSON fixture for every browser test.
- Exercise runtime from both an HTTP-served fixture document and generated local
  `file:` export.

Add `@axe-core/playwright` for automated scans when implementation is authorized
to update dependencies. Preserve a checked-in manual acceptance template for
keyboard and screen-reader verification.

Gate:

```bash
cd web && npm test
cd web && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts
```

### Chunk 04 relay closeout

After both lanes merge and all Python/runtime gates pass, update Chunk 04 to
`Complete`, record prompt-contract and browser-runtime evidence, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-05-supervisor.md`, commit
the closeout, and stop. Do not edit `runs.py` for Wave 4.

## 9. Wave 4 — Pipeline lifecycle and freshness

### Owner

Supervisor. No sub-agent edits `education_pipeline/runs.py` concurrently.

### Work

1. Make stage artifact paths/content types contract-aware:
   - spec/outline/QA remain Markdown;
   - draft/repair use JSON for guide-v1 runs;
   - legacy paths remain unchanged.
2. Wire machine-contract extraction into spec/outline approval.
3. Write `inputs/guide-contract.json` when the guide-v1 draft prompt is created.
4. Insert deterministic draft validation after draft approval.
5. Require a current parseable draft report before writing QA.
6. Include draft findings in QA and repair prompts.
7. Insert final validation after repair approval.
8. Derive report state (`missing`, `current`, `stale`) from source hashes, not
   file existence.
9. Add `validate` and `resolve_findings` next actions.
10. On reapproval or provider replacement, preserve old files but mark dependent
    approvals/reports/finals/exports stale through hashes.
11. Record the replaced response hash before a forced provider overwrite.
12. Implement guide-v1 finalization as a guarded multi-artifact operation:
    - verify current final report and waivers;
    - write canonical `final/guide.json` atomically;
    - write projected `final/guide.md` atomically;
    - record hashes and only then report finalized.
13. Flip newly created manifests to interactive guide v1 only after the full
    guide lifecycle passes; preserve an explicit legacy creation path for tests
    and recovery.

Do not use file deletion as invalidation. A user should be able to inspect stale
work and understand why it no longer controls the run.

### Required regression scenarios

- Legacy manifest/path/status/finalize/export remains byte-for-byte compatible
  where promised.
- Legacy and guide-v1 runs coexist in one workspace.
- Editing draft invalidates draft report and downstream work.
- Editing repair invalidates final report/final/export.
- Revalidation with identical input is idempotent.
- Waivers become stale when the guide hash changes.
- Non-waivable findings cannot be bypassed.
- A partial finalization failure never reports the run finalized.

### Gate

```bash
python3 -m pytest tests/test_runs.py tests/test_guide_validation.py tests/test_prompts.py
python3 -m pytest
```

### Chunk 05 relay closeout

After lifecycle and freshness regressions pass, update Chunk 05 to `Complete`,
record state-machine decisions and mixed-run evidence, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-06-supervisor.md`, commit
the closeout, and stop. Do not begin API or cockpit work.

## 10. Wave 5 — Export, preview API, and sandboxed preview

### Part A — Backend/API freeze

**Owner:** Supervisor.

Work:

- Add content contract and validation summaries to run status.
- Add stage `content_type`.
- Add validate, findings, and waiver operations.
- Add `POST /v1/guide-preview` using the shared document assembler.
- Map malformed JSON to `400`, safe-but-invalid/unrenderable guide input to
  `422`, stale state to `409`, and missing resources to `404` using the existing
  error envelope.
- Ensure request JSON roots are objects before accessing fields.
- Branch final/download MIME types by content contract.
- Preserve `/v1/preview` and legacy downloads.
- Integrate guide HTML export so it reads only `final/guide.json`, verifies a
  current final report/hash/waivers/runtime assets, and records deterministic
  provenance hashes.

Freeze and document the additive response shapes before frontend work begins.

Gate:

```bash
python3 -m pytest tests/test_write_api.py tests/test_server.py
python3 -m pytest
```

### Part B — Cockpit preview

**Owner:** Agent B after Part A is accepted.

Work:

- Extend API types/client for content contract, content type, validation summary,
  findings, validate, waivers, and guide preview.
- Preserve the existing stale editor-buffer behavior.
- Add JSON syntax feedback without replacing or discarding the buffer.
- Add `GuidePreviewFrame` using a sandboxed `iframe srcDoc` with scripts allowed
  but without same-origin privileges.
- Do not put the executable guide runtime into the current
  `dangerouslySetInnerHTML` preview path; that remains legacy Markdown only.
- Make preview persistence explicitly disposable and exception-safe.

Gate:

```bash
cd web && npm test
cd web && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts
```

### Chunk 06 relay closeout

After backend response shapes are frozen, the sandboxed preview is merged, and
all gates pass, update Chunk 06 to `Complete`, record the accepted API shapes
and preview isolation evidence, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-07-supervisor.md`, commit
the closeout, and stop. Do not begin findings/final-review work.

## 11. Wave 6 — Findings, final review, and acceptance loop

### Ownership

- Supervisor owns run-board action semantics and shared API coordination.
- Agent B may own leaf React components and tests after their props/contracts are
  fixed.

### Work

- Show draft/final validation milestones and current/stale state on the run
  board.
- Add findings summary and filtering by severity/status.
- Navigate from findings to a JSON Pointer or related guide ID.
- Add guarded waiver dialog with required reason and exact guide hash.
- Clearly separate current, waived, and stale findings.
- Disable finalize with a concrete reason when blockers remain.
- Keep finalize and export as separate actions.
- Add explicit provider rerun/replace confirmation and provenance display.
- Add the complete edit → reapprove → revalidate → finalize recovery loop.

### End-to-end scenarios

1. Valid fixture run reaches interactive export.
2. Bad draft findings flow into QA and repair.
3. Final blocker prevents finalization.
4. User edits repair JSON, reapproves, revalidates, and finalizes.
5. A waivable blocker requires a reason and remains visible.
6. A non-waivable blocker rejects waiver creation.
7. HTTP preview and local-file export render matching IDs/content.
8. Runtime interactions work by keyboard and persist locally.
9. Legacy Markdown run still completes and exports.
10. Mixed workspace lists and resumes both run types correctly.

### Chunk 07 relay closeout

After every acceptance-loop scenario passes, update Chunk 07 to `Complete`,
record E2E evidence and unresolved non-blocking risks, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-08-supervisor.md`, commit
the closeout, and stop. Do not begin release-quality closeout.

## 12. Wave 7 — Release-quality milestone closeout

### CI

The current GitHub Actions workflow runs Python only. Before closing this
milestone, add a frontend job that performs:

```bash
cd web
npm ci
npm test
npm run build
```

Add the supported Playwright browser installation and guide-runtime acceptance
suite as a separate job or clearly scoped CI command. Keep the Python 3.11/3.12
matrix and artifact-leak job.

If runtime assets are generated, CI must fail when checked-in package assets do
not match source/build output.

### Packaging

- Build a wheel and inspect it for runtime JavaScript/CSS and schema assets.
- Install the wheel into a clean environment and export the fixture guide.
- Open that export from `file:` and run the smoke scenario.
- Confirm Node is not needed after Python package installation.

### Accessibility acceptance

- Automated axe scan on the full fixture.
- Manual keyboard pass for navigation and every interaction.
- One supported screen-reader smoke pass.
- 320 CSS-pixel reflow, dark theme, reduced motion, and print inspection.
- Store a short dated acceptance record under `docs/testing/`.

### Documentation

- Update README with the guide-v1 workflow and compatibility note.
- Document content contract and artifact layout.
- Document validator findings and waivers.
- Document local progress storage and reset behavior.
- Update the PRD milestone status only after all acceptance gates pass.

### Chunk 08 relay closeout

After CI, packaging, accessibility, documentation, and the milestone definition
of done all pass, update Chunk 08 and the milestone to `Complete`, write
`docs/superpowers/prompts/interactive-guide-v1/chunk-09-post-milestone-supervisor.md`
for an independent audit and next-milestone proposal, commit the closeout, and
stop. Do not implement the next milestone.

## 13. PR and commit sequence

Recommended review units:

1. **docs: interactive guide v1 product, specs, and execution plan**
2. **feat(guide): typed schema, parser, canonical fixture, projection**
3. **feat(guide): deterministic validation reports and waivers**
4. **feat(runtime): packaged guide shell, safe renderer, deterministic assembler**
5. **feat(runtime): interactions, progress, persistence, print, browser tests**
6. **feat(pipeline): content contracts and format-aware artifact metadata**
7. **feat(prompts): machine-readable contracts and guide JSON generation**
8. **feat(pipeline): validation lifecycle, freshness, and guarded finalization**
9. **feat(api): guide export, preview, findings, and waiver endpoints**
10. **feat(web): isolated guide preview and JSON editing feedback**
11. **feat(web): validation findings, waivers, and final review flow**
12. **test: guide-v1 acceptance, accessibility, legacy compatibility, packaging**
13. **docs: interactive-guide milestone closeout**

These may be separate PRs or logical commits on a milestone branch. If using
separate PRs, runtime shell and validation can be open concurrently after guide
core merges. Pipeline lifecycle must wait for validation and prompt contracts;
cockpit work must wait for API response shapes.

## 14. Supervisor checklist at every merge

- Scope matches the assigned slice.
- No unrelated files are staged.
- Shared fixture remains unchanged unless the contract intentionally changed.
- Exact verification commands are recorded.
- Full Python tests pass after backend merges.
- Frontend unit/build tests pass after runtime/cockpit merges.
- Legacy Markdown behavior has explicit regression coverage.
- No private run/profile data entered fixtures, logs, or reports.
- New artifact writes are atomic and no-clobber by default.
- New status derives from content hashes where freshness matters.
- No model-authored HTML/JS enters preview or export.
- Documentation is updated when a contract changes.

## 15. Stop/go checkpoints

### Checkpoint A — Contract core

Stop if Python and runtime cannot agree on exact normalized fixture bytes, IDs,
or hash. Do not paper over parity problems in the renderer.

### Checkpoint B — Runtime safety

Stop if the guide requires raw HTML, arbitrary code, unsafe URLs, or same-origin
cockpit execution to deliver the promised interactions. Redesign the component
contract instead.

### Checkpoint C — Lifecycle integrity

Stop if a changed upstream artifact can appear current because a downstream file
still exists. Hash-based freshness is required before UI integration.

### Checkpoint D — Local-file acceptance

Stop if the exported guide only works over the daemon. Offline `file:` behavior
is a milestone requirement.

### Checkpoint E — Legacy compatibility

Stop if opening the upgraded app mutates or strands an existing Markdown run.
Legacy interpretation must remain explicit and non-destructive.

## 16. Definition of milestone complete

The milestone is complete only when:

- the canonical fixture passes the guide schema and all deterministic gates;
- known-bad fixture mutations trigger stable expected findings;
- new runs default to guide v1 and old manifests remain legacy;
- the full staged pipeline produces canonical guide JSON and projected Markdown;
- finalization is hash-gated by current validation and waivers;
- preview and export use the same isolated runtime;
- exported HTML works offline with all four interactions, navigation, progress,
  persistence, dark theme, and print;
- accessibility and security acceptance passes;
- mixed legacy/v1 workspaces pass CLI, API, cockpit, and E2E tests;
- wheel installation includes all runtime assets without requiring Node; and
- the README and PRD reflect the delivered state.

Until every condition is met, keep the PRD milestone status in progress rather
than “done.”
