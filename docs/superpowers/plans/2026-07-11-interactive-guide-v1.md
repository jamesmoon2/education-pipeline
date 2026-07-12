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
| 03 | Wave 2 | Validators, runtime shell, content-contract foundation | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-03-supervisor.md` |
| 04 | Wave 3 | Prompt contracts and runtime interactions | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-04-supervisor.md` |
| 05 | Wave 4 | Pipeline lifecycle, freshness, validation, finalization | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-05-supervisor.md` |
| 06 | Wave 5 | Export/preview API and sandboxed cockpit preview | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-06-supervisor.md` |
| 07 | Wave 6 | Findings, waivers, final review, acceptance loop | Complete | `docs/superpowers/prompts/interactive-guide-v1/chunk-07-supervisor.md` |
| 08 | Wave 7 | CI, packaging, accessibility, docs, closeout | Blocked (see §12 status record) | `docs/superpowers/prompts/interactive-guide-v1/chunk-08-supervisor.md` |
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

### Chunk 03 completion record

- **Completed:** 2026-07-11
- **Accepted commits (in merge order):**
  - `236a150` — `feat(runtime): add deterministic guide document shell`
    (Lane B)
  - `a21a6f0` — `feat(guide): add deterministic validation and waivers`
    (Lane A)
  - `42dacb6` — `feat(pipeline): add content contract foundation` and public
    API integration (supervisor lane)
  - `5732ca8` — `test(guide): cover validation rule execution` (Lane A
    coverage completion)
  - `8a6f2bf` — `feat(guide): export ValidationContext from public API`
    (supervisor integration fix)
- **Delivered — Lane A (validators/reports/waivers):**
  `education_pipeline/guides/validation.py`,
  `education_pipeline/guides/reports.py`,
  `education_pipeline/guides/waivers.py`, `tests/test_guide_validation.py`,
  `tests/test_guide_waivers.py`. Immutable `Finding`, `ValidationSummary`,
  and `ValidationReport` types with stable finding/rule IDs, deterministic
  severity/rule/path/ID sort, and canonical timestamp-free JSON bytes via
  `canonical_report_bytes`. Deterministic rule catalog grouped into
  parse/schema, security/privacy, outcomes/pedagogy, content/sources, and
  runtime/static-accessibility checks. Privacy matching accepts private
  denylist inputs but never echoes matched values (SHA-256 fingerprints
  only), with a minimum length of 5 and generic-value exclusions. Separate
  waiver engine keyed to exact guide hash and finding ID with required
  non-empty reason, `waivable=true` enforcement, staleness/orphan handling,
  and effective-gate calculation that never deletes or mutates findings.
- **Delivered — Lane B (runtime shell/document assembler):**
  `education_pipeline/guide_runtime/__init__.py` with `RuntimeAssets` and
  `load_runtime_assets()` via `importlib.resources`; directly maintained
  browser-native `assets/runtime.js` and `assets/runtime.css` included in
  built distributions through `pyproject.toml` package data;
  `education_pipeline/guides/document.py` with a pure deterministic
  `assemble_guide_document(guide, assets, mode)` producing a full HTML
  document with safe embedded JSON escaping (`<`, `>`, `&`, U+2028, U+2029),
  SHA-256 CSP hashes over exact embedded asset bytes, schema/runtime
  compatibility checks, and a nonblank static loading/error shell; and a
  guide-v1 safe Markdown renderer (`render_guide_markdown`) that escapes raw
  HTML, permits only validated `http`/`https`/known-ID fragment links, and
  renders fenced code inertly. Static rendering covers all six accepted
  block types. `tests/test_guide_document.py` and the scoped
  `web/e2e/guide-runtime.spec.ts` static-shell assertion.
- **Delivered — Supervisor lane (manifest/content contract):** immutable
  `ContentContract` dataclass in `education_pipeline/runs.py` with
  `legacy_markdown()` / `interactive_guide_v1()` constructors and
  `to_manifest()`; `RunStore.content_contract()` accessor interpreting
  absent `content_contract` as `legacy_markdown` without on-disk mutation;
  explicit immutable `interactive_guide`/`1.0` creation on `create_run`
  with fail-closed rejection of unsupported kinds/versions; contract-aware
  stage `content_type` mapping (guide-v1 JSON for draft/repair) preserving
  exact legacy paths; and response SHA-256 source-hash events recorded for
  later freshness calculations. `_next_action()`, lifecycle actions, prompt
  contracts, and the legacy default for new runs are unchanged.
- **Accepted public APIs:** from `education_pipeline.guides` —
  `validate_guide(value, *, phase="final", private_values=(), context=ValidationContext()) -> ValidationReport`,
  `ValidationContext`, `Finding`, `ValidationReport`, `ValidationSummary`,
  `canonical_report_bytes(report) -> bytes`,
  `apply_waivers(report, waiver_set) -> WaiverResult`, `Waiver`,
  `WaiverSet`, `WaiverResult`,
  `assemble_guide_document(guide, assets=None, mode="export") -> str`,
  `render_guide_markdown(markdown, known_ids) -> str`, `DocumentMode`, and
  `GuideDocumentError`; from `education_pipeline.guide_runtime` —
  `RuntimeAssets` and `load_runtime_assets()`; from
  `education_pipeline.runs` — `ContentContract` and
  `RunStore.content_contract()`.
- **Canonical fixture:** `tests/fixtures/guides/feedback-loops.guide.json`
  is unchanged; normalized SHA-256 remains
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`
  (reverified at closeout).
- **Verification:** focused integrated Python (`tests/test_guide_validation.py`,
  `tests/test_guide_waivers.py`, `tests/test_guide_document.py`,
  `tests/test_runs.py`, `tests/test_cli.py`, `tests/test_e2e.py`) passed
  with `105 passed`; the shared `python3 -m pytest` gate passed with
  `319 passed in 33.18s` (one benign daemon test-server connection-reset
  log, no failures); `cd web && npm test` passed with `63 passed (63)`;
  `cd web && npm run build` produced a clean production build;
  `cd web && npm run e2e -- guide-runtime.spec.ts` passed with `1 passed`;
  `git diff --check` passed.
- **Decisions/deviations:** closeout was interrupted once by an
  environment account-usage limit after the implementation commits landed;
  the remaining verified two-line `ValidationContext` export was committed
  as `8a6f2bf` when access resumed and all gates were rerun. Rules that
  require a rendered browser release (full interactive accessibility
  acceptance, axe scans, keyboard/screen-reader passes) are deliberately
  deferred to Waves 3 and 7 per the milestone; deterministic static
  counterparts are implemented. No prompt contracts, lifecycle actions,
  API/daemon routes, provider code, legacy renderer behavior, or cockpit
  source changed.
- **Remaining risks:** None for Wave 2. Runtime interaction behavior,
  prompt-contract extraction, and lifecycle/freshness integration remain
  governed by the Wave 3 and Wave 4 acceptance gates.

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

### Chunk 04 completion record

- **Completed:** 2026-07-11
- **Accepted commits (in merge order):**
  - `94c76ba` — `feat(prompts): add machine-readable guide contracts` (Lane A)
  - `eab948d` — `fix(prompts): enforce contract block safety and repair
    constraints` (Lane A review fix)
  - `7627d8b` — `feat(runtime): add guide interactions and local persistence`
    (Lane B)
  - `28220be` — `test(runtime): cover keyboard interaction paths` (Lane B
    review fix)
- **Delivered — Lane A (machine-readable prompt contracts):**
  `education_pipeline/guides/contract.py`, guide-v1 additions to
  `education_pipeline/prompts.py`, `tests/test_guide_contract.py`, and
  guide-v1 additions to `tests/test_prompts.py`. Guide-v1 spec and outline
  prompt variants keep the legacy Markdown response format and additionally
  require exactly one fenced `education-pipeline-contract+json` /
  `education-pipeline-outline+json` block. Pure extraction/validation
  helpers reject zero, multiple, malformed-JSON, schema-invalid, and
  HTML/JavaScript-bearing blocks with stable diagnostics (reusing the
  parser's `RAW_HTML_RE` and `ID_RE`); spec/outline conflicts (version
  mismatch, unknown outcome references) are errors.
  `build_guide_contract(spec, outline, publishable_profile_summary=None)`
  deterministically returns canonical `inputs/guide-contract.json` payload
  bytes with no file I/O. The guide-v1 draft prompt requests one complete
  guide JSON object only (no fences or commentary) with a concise schema
  reference and the embedded binding contract; the QA prompt delimits the
  normalized draft JSON and deterministic findings with explicit
  untrusted-data markers; the repair prompt embeds the guide contract as
  binding constraints and requires complete guide JSON preserving stable
  IDs. Legacy prompt text is proven byte-identical to the accepted base by
  SHA-256 snapshot tests pinned before modification (independently
  reproduced against commit `9ab5b89` during review). Nothing is wired into
  `RunStore` or the run lifecycle.
- **Delivered — Lane B (runtime interactions, persistence, browser
  behavior):** rewritten `education_pipeline/guide_runtime/assets/runtime.js`
  (789-line browser-native strict-mode IIFE, no dependencies) and
  `runtime.css`; additive interactive scaffolding in
  `education_pipeline/guides/document.py`; expanded
  `tests/test_guide_document.py` and `web/e2e/guide-runtime.spec.ts`; manual
  acceptance template at
  `docs/testing/interactive-guide-v1-manual-acceptance.md`;
  `@axe-core/playwright` added as the authorized web devDependency.
  Interactions: knowledge-check select/submit/retry/explanation with native
  radio/checkbox inputs and submit-disabled-until-selection; progressive
  worked-reveal with show-all and reset; scenario choice feedback and
  debrief with quality explanation after submission; reflection notes with
  debounced + on-blur local save, explicit skip, and confirmed reset.
  Navigation: single-visible-section display, prev/next controls, fragment
  routing that resolves nested block IDs to owning sections, unknown
  fragments falling back to the first section with a polite announcement,
  and a mark-complete control with auto-completion when all interactions in
  a section are done. Progress display counts sections and interactions and
  states it tracks progress, not mastery. Persistence: schema-checked,
  exception-safe localStorage wrapper keyed
  `education-pipeline:guide:<courseId>:<contentHash>:v<schemaMajor>`
  (content hash is FNV-1a over the exact embedded JSON text), storing only
  the spec-enumerated state, with a one-time non-blocking notice when
  storage is unavailable and a fresh record on hash change. Themes
  (system/light/dark with persisted preference), reduced-motion support,
  responsive drawer navigation, and print expansion of all educational
  content (reveal steps, choices with correct/incorrect markers,
  explanations, feedback, debriefs) while excluding learner notes.
  Progressive disclosure is gated on a `js-enhanced` root class, so no-JS
  and print contexts retain the full pre-rendered content. Correctness and
  quality are conveyed by text and glyphs, never color alone.
- **Accepted new public APIs:** from `education_pipeline.guides` —
  `ContractError`, `extract_spec_contract(markdown) -> dict`,
  `extract_outline_contract(markdown) -> dict`,
  `validate_spec_contract(data) -> None`,
  `validate_outline_contract(data) -> None`,
  `check_contract_conflict(spec, outline) -> None`, and
  `build_guide_contract(spec, outline, *, publishable_profile_summary=None)
  -> bytes`. From `education_pipeline.prompts` (module-level, not
  re-exported from the package root) — `compile_guide_v1_spec_prompt`,
  `compile_guide_v1_outline_prompt`,
  `compile_guide_v1_draft_prompt(topic, approved_outline, guide_contract,
  profile=None)`, `compile_guide_v1_qa_prompt(topic, *, approved_spec,
  approved_outline, draft_guide_json, draft_findings_json, profile=None)`,
  and `compile_guide_v1_repair_prompt(topic, *, draft_guide_json,
  qa_findings_markdown, draft_findings_json, guide_contract,
  profile=None)`. Every previously frozen signature is unchanged; the
  runtime interaction surface is the data-role/data-interactive markup
  contract between `document.py` and `runtime.js`.
- **Canonical fixture:** `tests/fixtures/guides/feedback-loops.guide.json`
  is unchanged; normalized SHA-256 remains
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`
  (re-verified live at closeout).
- **Verification:** Lane A focused
  `python3 -m pytest tests/test_prompts.py tests/test_guide_contract.py`
  passed with `69 passed`; Lane B focused
  `python3 -m pytest tests/test_guide_document.py` passed with `8 passed`;
  shared `git diff --check` clean; shared `python3 -m pytest` passed with
  `369 passed in 33.64s`; `cd web && npm test` passed with `63 passed (63)`;
  `cd web && npm run build` produced a clean production build;
  `cd web && npm run e2e -- guide-runtime.spec.ts` passed with `32 passed`
  (14 scenarios exercised over both an HTTP-served fixture document and a
  generated local `file:` export, four keyboard-only interaction tests, a
  corrupted-localStorage degradation test, and axe scans with zero
  serious/critical violations on both transports).
- **Decisions/deviations:** two review findings were escalated from the
  binding spec and fixed before acceptance — contract validators now reject
  HTML/JavaScript content (prompt instruction alone was judged insufficient
  at the extraction trust boundary), and the repair prompt embeds the guide
  contract to satisfy spec §6's "approved spec/outline constraints" input.
  Keyboard e2e coverage was extended to all four interaction families plus
  navigation during review. Block headings moved from `h4` to `h3` to fix
  heading order (h1 course → h2 section → h3 block). The runtime content
  hash is FNV-1a over the embedded JSON text rather than SHA-256 (documented
  in source; synchronous and dependency-free — SubtleCrypto is async and
  inconsistent on `file:` origins); it scopes local progress records only.
  No packaging change was needed (`pyproject.toml` package-data already
  ships the exact runtime assets). Known non-blocking notes: sections with
  zero interactive blocks complete only via the explicit mark-complete
  control; the localStorage key joins IDs with unescaped `:`; correctness
  data is present-but-hidden in the DOM pre-submit (inherent to a
  self-contained offline export and required for print/no-JS).
- **Remaining risks:** None for Wave 3. Lifecycle wiring, contract file
  writes, validation gates, freshness, and finalization remain governed by
  the Wave 4 acceptance gates.

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

### Chunk 05 completion record

- **Completed:** 2026-07-11
- **Accepted commits (in merge order):**
  - `c08eb9c` — `feat(pipeline): contract-aware guide-v1 artifacts and prompts`
  - `8811a91` — `feat(pipeline): validation lifecycle, freshness, and guarded
    finalization`
  - `e9b7fad` — `feat(pipeline): default new runs to interactive guide v1`
- **Delivered — contract-aware artifacts and prompts (`c08eb9c`):** guide-v1
  spec/outline approval gated on the frozen `extract_spec_contract` /
  `extract_outline_contract` / `check_contract_conflict` helpers (a missing,
  duplicated, malformed, or conflicting fenced block is an approval-blocking
  `ConfigError` that writes no approved file and no manifest event); guide-v1
  spec/outline/draft prompts compiled through the frozen
  `compile_guide_v1_*` compilers; immutable `inputs/guide-contract.json`
  written atomically (bytes from the frozen `build_guide_contract`, no-clobber
  by default, identical-bytes idempotent, divergent rewrite only with explicit
  overwrite) when the guide-v1 draft prompt is created, with the publishable
  profile summary included only when the attached profile permits publication;
  guide-v1 `prompt_written` events record upstream source hashes
  (`source_spec_file_sha256`, `source_outline_file_sha256`,
  `contract_file_sha256`); and every forced provider response overwrite
  records the replaced response's hash in a `response_replaced` manifest
  event before the atomic write (all run kinds).
- **Delivered — validation lifecycle, freshness, guarded finalization
  (`8811a91`):** `RunStore.validate_run(topic_id, phase)` writes canonical
  timestamp-free reports to `reports/draft-validation.json` /
  `reports/final-validation.json` atomically (idempotent for identical input)
  and records a `validated` manifest event with report/source hashes and
  phase; `RunStore.report_state(topic_id, phase)` derives
  `missing`/`current`/`stale` by recomputing the current approved artifact's
  hash exactly as `validate_guide` records it (normalized guide SHA-256 when
  parseable, raw-bytes SHA-256 otherwise) — never from file existence;
  guide-v1 QA/repair prompts require a current draft report and a parseable
  draft and embed the normalized draft JSON plus the deterministic findings
  as delimited untrusted data through the frozen compilers; `validate` and
  `resolve_findings` next actions per validation-pipeline spec section 8
  (draft report missing/stale → validate draft; unparseable current draft →
  resolve_findings blocking QA; final report missing/stale → validate final;
  gate open → finalize; blockers remaining → resolve_findings, with
  non-waivable findings rejected by the existing waiver engine); waivers
  loaded from `reports/validation-waivers.json` (schema_version 1, exact
  guide hash, per-finding reason) and applied via the frozen `apply_waivers`;
  guarded guide-v1 finalization verifies a current final report and an open
  waiver gate, parses and normalizes the approved repair, writes canonical
  `final/guide.json` and projected `final/guide.md` atomically, and records
  the `finalized` event (source/report/output hashes, `guide_sha256`,
  schema version) only after every write succeeds; `is_finalized` for
  guide-v1 is hash-derived from the finalized event's recorded source hash
  against the current approved repair, so editing/reapproving repair
  un-finalizes without deleting files; `StageStatus` gained an additive
  `stale` flag computed for guide-v1 qa/repair from approval-time upstream
  hashes; `advance` performs `validate` as a machine step and may rebuild a
  stale guide-v1 prompt (machine artifact) with overwrite; guide-v1
  `export_run` is explicitly refused until the Wave 5 export/preview API.
- **Delivered — new-run default flip (`e9b7fad`):** newly created manifests
  record the immutable `interactive_guide`/`1.0` contract by default (flipped
  only after the full lifecycle regressions passed); pre-existing manifests
  without a contract remain legacy and are never mutated (covered by a
  bare-manifest regression test); the explicit legacy creation path is the
  store argument `ContentContract.legacy_markdown()` plus the new CLI command
  `education-pipeline create <topic> [--legacy-markdown]`; a run's contract
  remains immutable after creation.
- **State-machine decisions:** report freshness compares the report's
  recorded `guide_sha256` against a live recomputation from the current
  approved artifact, making freshness purely content-derived; finalized
  state is the manifest `finalized` event hash-matched to the current
  approved repair rather than file existence; a stale approved qa/repair
  stage surfaces `write_prompt` (prompt upstream drifted) or
  `save_response` (prompt current, response/approval predates upstream)
  with rebuild/force/overwrite instructions in the detail — automated
  overwrite is limited to machine-generated prompt files; refinalizing after
  a repair edit requires explicit `overwrite=True` (surfaced for the Wave 6
  recovery loop); spec/outline reapproval staleness for outline/draft stages
  is deferred to the cockpit acceptance wave.
- **Mixed legacy/v1 evidence:**
  `test_mixed_workspace_legacy_and_guide_v1_progress_independently` drives an
  explicit-legacy run to finalized while a default guide-v1 run sits
  mid-lifecycle in the same workspace, with both listed by `list_run_ids`;
  `test_explicit_legacy_creation_is_byte_compatible_and_drives_to_finalize`
  proves the explicit legacy run's spec prompt is byte-identical to the
  legacy compiler output and the legacy flow reaches finalize/export; the
  legacy prompt SHA-256 snapshot pins in `tests/test_prompts.py` are
  unchanged.
- **Canonical fixture:** `tests/fixtures/guides/feedback-loops.guide.json`
  is untouched; normalized SHA-256 re-verified live at closeout:
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`.
- **Verification:** focused
  `python3 -m pytest tests/test_runs.py tests/test_guide_validation.py
  tests/test_prompts.py tests/test_guide_contract.py` passed with
  `161 passed`; shared gate: `git diff --check` clean; `python3 -m pytest`
  passed with `400 passed in 34.69s` (baseline 369 at the Wave 3 head plus
  31 new Wave 4 tests, zero failures); `cd web && npm test` passed with
  `63 passed (63)`; `cd web && npm run build` produced a clean production
  build; `cd web && npm run e2e -- guide-runtime.spec.ts` passed with
  `32 passed`. Scope audit of `d28470f..e9b7fad` confirmed only
  `education_pipeline/runs.py`, `education_pipeline/cli.py`, and nine test
  modules changed — no edits under `education_pipeline/guides/`,
  `guide_runtime/`, `daemon/`, provider code, `prompts.py`, `web/`, or
  fixtures.
- **Intentional test updates (superseded contracts):** after the default
  flip, tests exercising the legacy Markdown flow opt in explicitly via
  `ContentContract.legacy_markdown()` (or the CLI `create --legacy-markdown`)
  in `tests/test_runs.py`, `tests/test_cli.py`, `tests/test_client.py`,
  `tests/test_daemon_serve.py`, `tests/test_e2e.py`,
  `tests/test_job_runner.py`, `tests/test_server.py`, `tests/test_worker.py`,
  and `tests/test_write_api.py`; `test_run_store_creates_run_directories`
  now asserts the guide-v1 default and
  `test_absent_content_contract_is_legacy_without_manifest_mutation` was
  rewritten against a hand-crafted pre-existing bare manifest. No assertion
  was weakened.
- **Decisions/deviations:** guide-v1 spec prompts compile from the topic's
  id/title/brief via `SpecPromptInput` (the frozen guide-v1 spec compiler's
  surface); extending it to full topic sections would need a new prompt
  compiler and is out of Wave 4 scope. The privacy denylist
  (`private_values`) is not yet wired from profile fields into lifecycle
  validation calls — deferred with the findings/waiver UX wave. Per the
  user's direction, implementation was delegated to Grok (grok-4.5)
  sub-agents in three sequential slices with exclusive `runs.py` ownership;
  the supervisor reviewed, gap-filled (a between-writes partial-finalization
  test), verified, and committed each slice.
- **Remaining risks:** `web/e2e/full-run.spec.ts` (and the cockpit write
  flow generally) drives a brand-new run through the legacy Markdown path;
  after the default flip a cockpit-created run is guide-v1, so that
  non-gated spec will fail until the Wave 5/6 cockpit work lands — the
  cockpit currently has no legacy-override or guide-v1 controls. The daemon
  `enqueue` next-stage inference does not yet understand `validate`
  next-actions (Wave 5 API work). No other Wave 4 risks.

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

### Chunk 06 completion record

- **Completed:** 2026-07-11.
- **Accepted commits:** `5e22328` — `feat(api): guide export preview
  findings and waivers`; `eb09e4f` — `feat(web): isolate interactive guide
  preview`.
- **Frozen additive API shapes:** documented in
  `docs/superpowers/specs/2026-07-11-interactive-guide-v1-api-freeze.md`.
  Run status adds `content_contract` and draft/final `validations`; stage
  content adds `content_type`; validate returns `{state, report, status}`;
  findings returns `{state, report}`; waiver creation returns `{waivers,
  state, report}`; guide preview returns `{html, content_sha256, validation}`.
- **Preview isolation:** guide HTML is rendered only by `GuidePreviewFrame`
  using `iframe srcDoc` with `sandbox="allow-scripts"` and no
  `allow-same-origin`. Legacy Markdown alone retains the existing
  `dangerouslySetInnerHTML` preview. Invalid JSON remains in the editor,
  displays syntax feedback, and is not submitted for preview. Opaque-origin
  storage failures remain exception-safe and preview state is disposable with
  the `srcDoc` instance.
- **Export provenance:** guide export reads only canonical
  `final/guide.json`, requires current final validation and an open waiver
  gate, loads the packaged runtime, writes atomically, and records source,
  report, export, runtime asset, schema/runtime version, and non-sensitive
  effective model-stage provenance hashes/aliases in the manifest. Legacy
  export behavior remains unchanged.
- **Fixture:** normalized SHA-256 remains
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`.
- **Verification:** `python3 -m pytest tests/test_write_api.py
  tests/test_server.py` — 77 passed; `python3 -m pytest` — 404 passed;
  `cd web && npm test` — 66 passed; `cd web && npm run build` — passed;
  `cd web && npm run e2e -- guide-runtime.spec.ts` — 32 passed;
  `git diff --check` — clean. Socket-bearing Python/browser gates required
  unrestricted reruns after sandbox `EPERM`; those reruns passed unchanged.
- **Intentional test updates:** legacy stage-content expectations gained the
  additive `content_type`; frontend fixtures gained frozen additive run/status
  fields; the Wave 4 guide-export refusal test was replaced by canonical
  export/provenance acceptance coverage.
- **Decisions/deviations:** guide-v1 export supports HTML only in this wave;
  canonical JSON and projected Markdown remain final artifacts. Wave 6 owns
  findings presentation, waiver dialogs, and final-review/recovery UX.
- **Remaining risks:** the known `web/e2e/full-run.spec.ts` legacy-cockpit
  assumption remains for Wave 6's complete mixed-run acceptance loop. No other
  Wave 5 risks.

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

### Chunk 07 completion record

- **Completed:** 2026-07-11.
- **Accepted commits:** `ed0aa28` — `feat(web): coordinate guide validation
  recovery actions`; `f52fc97` — `feat(web): findings waivers and mixed-run
  acceptance`.
- **Accepted behavior:** run-board draft/final validation milestones;
  severity/status findings filters; current/stale/waived separation with
  persistent hash-bound waiver reads; JSON Pointer and related-ID source
  navigation; exact-hash, required-reason waiver flow preserving input on
  409/422; explicit provider replacement confirmation; provider/model/effort
  provenance; concrete finalize blocking; separate finalize/export actions;
  guide-only HTML export controls and canonical JSON download; downstream
  invalidation explanation and edit → reapprove → revalidate → finalize
  recovery.
- **Ten acceptance scenarios:** valid fixture reached interactive export; bad
  draft findings remain available to QA/repair; final blockers prevent
  finalization; edited repair can be reapproved/revalidated/finalized;
  waivable blockers require reasons and remain visible; non-waivable blockers
  return 422; HTTP/local-file runtime parity remains covered; keyboard and
  persistence runtime checks pass; explicit legacy Markdown flow remains
  byte-compatible; mixed legacy/guide workspace listing and resume passed.
- **API preservation:** all Wave 5 frozen response shapes are unchanged. Wave 6
  adds only `GET /v1/runs/{topic}/validation/{phase}/waivers`, returning the
  waiver set and its current/stale state so waived findings survive reload.
- **Verification:** focused Python — 97 passed; full `python3 -m pytest` — 404
  passed; `cd web && npm test` — 78 passed; `cd web && npm run build` — passed;
  `cd web && npm run e2e` — 37 passed; `git diff --check` — clean. Socket-based
  gates ran unrestricted after sandbox limitations.
- **Fixture:** normalized SHA-256 remains
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`.
- **Intentional test updates:** legacy browser flows now create explicit legacy
  contracts; the full-run suite adds the default guide-v1 fixture and mixed
  workspace; daemon discovery polling waits for a ready record containing a
  port rather than racing the pid-only placeholder.
- **Decisions/deviations:** finding navigation opens the exact source stage and
  displays its JSON Pointer/related guide ID; richer in-iframe selection is
  deferred. No frozen guide/runtime/provider/prompt surface changed.
- **Remaining risks:** None for Wave 6. Release-quality CI, packaging,
  accessibility/manual evidence, and documentation remain Wave 7 work.

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

### Chunk 08 status record — blocked, not complete

- **Recorded:** 2026-07-11. Chunk 08 and the milestone are **not** set to
  `Complete`; two classes of exact blockers remain (below). The chunk-09
  prompt was intentionally not created because its precondition (every Wave 7
  criterion passing) is unmet.
- **Work landed:** CI gains a `web` job (Node 22: `npm ci`, `npm test`,
  `npm run build`) and an `e2e` job (Python 3.12 editable install, cockpit
  build, `npx playwright install --with-deps chromium`, `npm run e2e` full
  37-test acceptance suite); the Python 3.11/3.12 matrix and artifact-leak
  jobs are unchanged. Runtime assets are maintained source, not generated, so
  no drift check is required. README plus new `docs/interactive-guides.md`
  document the guide-v1 workflow, compatibility, contracts/artifacts,
  findings/waivers, preview isolation, progress/reset, and export/privacy
  boundaries. Accessibility evidence recorded in
  `docs/testing/2026-07-11-interactive-guide-v1-acceptance.md`.
- **Verification (2026-07-11, Python 3.12.3, Node v22.14.0, npm 11.4.1):**
  `git diff --check` clean; `python3 -m pytest` — 404 passed;
  `cd web && npm ci && npm test` — 78 passed; `npm run build` — passed;
  `npm run e2e` — 37 passed.
- **Packaging:** `python -m build` (build 1.5.1 in an isolated venv) produced
  `education_pipeline-0.1.0-py3-none-any.whl` (41 files) containing
  `guide_runtime/assets/runtime.js` (27,740 B) and `runtime.css` (7,560 B);
  installed with `pip install --no-index --no-deps` into a clean venv; the
  canonical fixture exported from outside the checkout with no daemon
  (59,693 bytes, all CSS/JS inline, the only external URL a content anchor);
  a Playwright chromium smoke against that export from `file:` passed
  (render, keyboard answer + feedback, progress persisted across reload).
  Node was not used to produce the export. Normalized fixture SHA-256
  re-verified from both wheel and checkout:
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`.
- **Accessibility evidence:** axe-core 4.12.1 (WCAG 2.0/2.1 A+AA tags) on all
  four sections in light and dark themes — 0 violations in all 8 scans;
  320 px reflow — 0 px horizontal overflow in all sections; reduced-motion,
  print-emulation, dark-theme, and focus-visibility checks passed with
  screenshot inspection (details in the dated acceptance record).
- **Blocker 1 (frozen-contract defect):** skip-link activation is a no-op —
  the runtime's document click handler `preventDefault()`s every `#` anchor
  and `goToTarget("guide-main")` returns early because `<main id="guide-main">`
  is not a guide section (measured: hash unchanged, no scroll, focus stays on
  the link). Fixing it requires changing frozen runtime behavior, which
  Chunk 08 prohibits. A related observation: load-time
  `history.replaceState` fragment normalization moves the sequential focus
  starting point into the current section, so first Tab bypasses the skip
  link (still reachable via Shift+Tab).
- **Blocker 2 (human-required):** the manual screen-reader smoke pass, human
  keyboard pass, real print dialog, and real-device reflow checks cannot be
  performed by the supervising agent and were not claimed; see the acceptance
  record's "Human-required items".
- **Deviations:** none beyond the blockers; no frozen source, fixture, prompt
  snapshot, or API surface changed.

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
