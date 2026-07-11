# Supervisor Prompt — Interactive Guide v1, Chunk 04

You are the supervisor agent for **Chunk 04: implement and accept the Wave 3
parallel content and interaction work** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete only this chunk autonomously, including safe recovery from ordinary
implementation or verification failures. Do not begin Chunk 05. A human
controls the transition between chunks.

## Accepted base and frozen contracts

The accepted Wave 2 integration head is commit:

```text
8a6f2bffd456d4f675e7ce35b2523b7c70ffcc91
```

The accepted Wave 2 lane commits, in merge order, are:

```text
236a150d3c4780c908fa48bf12e2c13522993aa9  feat(runtime): add deterministic guide document shell
a21a6f01045baa37951ecc2da55a75447c736c28  feat(guide): add deterministic validation and waivers
42dacb6f23e34b939aced7c7df6bce726db6ecf2  feat(pipeline): add content contract foundation
5732ca85cb108d809483718655776d455a1fc7d5  test(guide): cover validation rule execution
8a6f2bffd456d4f675e7ce35b2523b7c70ffcc91  feat(guide): export ValidationContext from public API
```

Confirm `8a6f2bf` is an ancestor of `HEAD`, inspect the live branch/worktree,
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
```

Also frozen: `education_pipeline.guide_runtime.load_runtime_assets()` /
`RuntimeAssets`, and `education_pipeline.runs.ContentContract` with
`RunStore.content_contract()`. Do not change these signatures, the normalized
fixture bytes, IDs, authored array order, or the hash without stopping at the
smallest safe state and reporting the exact contract blocker. Additive,
backward-compatible extension of the document assembler and runtime assets is
authorized only inside Lane B's ownership below.

## Authoritative files to reopen completely

Before implementation, read:

```text
docs/product-requirements.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-schema.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md
docs/superpowers/plans/2026-07-11-interactive-guide-v1.md
education_pipeline/guides/__init__.py
education_pipeline/guides/document.py
education_pipeline/guides/validation.py
education_pipeline/guide_runtime/__init__.py
education_pipeline/guide_runtime/assets/runtime.js
education_pipeline/guide_runtime/assets/runtime.css
education_pipeline/prompts.py
tests/fixtures/guides/feedback-loops.guide.json
tests/test_prompts.py
tests/test_guide_document.py
web/e2e/guide-runtime.spec.ts
web/package.json
```

Also inspect `pyproject.toml`, package/test conventions, frontend package/test
commands, Git state, and repository-local agent instructions. Trust live code,
not this prompt or a chat summary, when implementation details differ.

## Objective and authorized lanes

Implement, review, verify, and commit only Wave 3. The supervisor may delegate
Lane A to one Agent A and Lane B to one Agent B after confirming clean,
non-overlapping ownership. The supervisor retains all integration and review
responsibility. Do not start Wave 4 agents or work.

### Lane A — machine-readable prompt contracts

Agent A owns only:

```text
education_pipeline/prompts.py
education_pipeline/guides/contract.py        (or an equivalently named new helper module under education_pipeline/guides/)
tests/test_prompts.py
tests/test_guide_contract.py
```

Small edits to `education_pipeline/guides/__init__.py` are allowed only to
publish accepted new contract-helper APIs and must be integrated by the
supervisor.

Implement:

- exactly one required `education-pipeline-contract+json` fenced block in
  guide-v1 spec responses and exactly one `education-pipeline-outline+json`
  fenced block in guide-v1 outline responses, with parsing and validation
  helpers that reject zero or multiple blocks, malformed JSON, and
  schema-invalid content with useful diagnostics;
- deterministic construction of an immutable `inputs/guide-contract.json`
  payload from validated spec/outline contract blocks (helper only — no file
  writes into run directories from this lane);
- guide-v1 draft prompt text that requests complete guide JSON only, with a
  concise schema reference;
- guide-v1 QA prompt construction that includes the normalized draft and
  deterministic validation findings as clearly delimited untrusted data; and
- guide-v1 repair prompt construction that requires complete guide JSON output
  preserving stable IDs.

Keep spec/outline/QA Markdown response formats and every legacy prompt exactly
unchanged. The prompt lane exposes helpers but must not wire them into
`RunStore` or the run lifecycle; the supervisor performs that integration in
Wave 4 (Chunk 05).

### Lane B — runtime interactions, persistence, and browser behavior

Agent B owns only:

```text
education_pipeline/guide_runtime/__init__.py
education_pipeline/guide_runtime/assets/runtime.js
education_pipeline/guide_runtime/assets/runtime.css
education_pipeline/guides/document.py
tests/test_guide_document.py
web/e2e/guide-runtime.spec.ts
docs/testing/                                 (manual acceptance template only)
```

Required packaging metadata changes are allowed only to keep the exact runtime
assets in built distributions. Record every such change. Do not edit
React/cockpit source in this chunk, and do not make Node a Python-package
installation or runtime dependency.

Implement:

- knowledge-check selection, submit, retry, and explanation reveal;
- progressive worked-example reveals with reset and show-all;
- scenario choice feedback and debrief;
- reflection notes, skip, and reset;
- section/module navigation, fragment links, completion, and progress display;
- dark/light theme handling, reduced motion, responsive layout, and print
  expansion of all interactive content;
- schema-checked, exception-safe localStorage reads/writes — corrupted or
  unavailable storage must degrade gracefully, never crash the runtime; and
- browser tests driven by the canonical JSON fixture, exercising the runtime
  from both an HTTP-served fixture document and a generated local `file:`
  export.

The runtime must remain browser-native JavaScript/CSS with no framework
dependency, must preserve deterministic assembly bytes for identical inputs,
and must keep the Wave 2 safety properties: safe JSON embedding, CSP hashes
over exact asset bytes, escaped raw HTML, and validated link targets.

Adding `@axe-core/playwright` as a web devDependency is authorized if it does
not require network access beyond the standard install flow already available
in the environment; if installation is unavailable, record the deferral and
keep a checked-in manual acceptance template under `docs/testing/` for
keyboard and screen-reader verification.

### Supervisor lane

The supervisor owns integration, review, shared `__init__.py`/packaging
resolution, and the closeout documentation. The supervisor writes no new
product features in this chunk.

## Merge order and shared-file discipline

Integrate in this order:

1. Agent A prompt contracts.
2. Agent B runtime interactions.

Review every live diff and test rather than trusting summaries. Resolve shared
`education_pipeline/guides/__init__.py` or packaging edits in the supervisor
worktree after each lane is accepted. Every lane should be a clean logical
commit with exact verification evidence; preserve those commits or integrate
them without rewriting unrelated history.

## Prohibited work

Do not:

- change the frozen fixture, normalized bytes, frozen public signatures, or
  canonical hash;
- wire prompt-contract extraction, guide-contract file writes, or validation
  into `education_pipeline/runs.py`, `_next_action()`, or any lifecycle
  action — all `runs.py` lifecycle integration is Wave 4 (Chunk 05);
- add `validate` or `resolve_findings` actions, freshness state, finalization,
  guide export, preview/API routes, findings/waiver endpoints, or cockpit UI;
- flip the new-run default away from legacy Markdown;
- change legacy prompts, legacy renderer behavior, provider adapters, CLI
  behavior, or daemon routes;
- weaken any Wave 2 safety property (CSP, escaping, link validation,
  deterministic bytes);
- install dependencies beyond the explicitly authorized
  `@axe-core/playwright` devDependency, or invoke providers/paid APIs;
- execute Chunk 05, create its worktrees, or begin its code; or
- clean, stage, commit, or revert unrelated user changes.

If an acceptance criterion appears to require prohibited work, record the
exact blocker and stop rather than expanding scope.

## Acceptance criteria

### Prompt contracts

1. Guide-v1 spec/outline prompt text instructs exactly one typed fenced JSON
   contract block, and extraction accepts exactly one well-formed block while
   rejecting zero, multiple, malformed, and schema-invalid blocks with stable
   diagnostics.
2. `inputs/guide-contract.json` construction is deterministic: identical
   validated inputs produce identical canonical bytes.
3. Guide-v1 draft prompts request JSON only; QA prompts delimit the normalized
   draft and findings as untrusted data; repair prompts require complete guide
   JSON preserving stable IDs.
4. Legacy prompt text is byte-identical to the accepted base for every legacy
   path, proven by tests.
5. No `runs.py` or lifecycle file changed in this lane.

### Runtime interactions

1. All four interaction families (knowledge check, worked reveal, scenario,
   reflection) work in the browser from the canonical fixture, by mouse and by
   keyboard.
2. Progress and interaction state persist across reload via schema-checked
   localStorage and degrade safely when storage is corrupted or unavailable.
3. Navigation, fragments, completion, themes, reduced motion, responsive
   layout, and print expansion behave per the runtime-export spec.
4. The exported document works from a local `file:` URL with no network access.
5. Repeated assembly from identical inputs still returns identical bytes, and
   CSP hashes still match the exact embedded asset bytes.
6. All Wave 2 escaping/link-safety tests still pass unchanged in substance.

## Execution and verification

Start with at least:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 8a6f2bffd456d4f675e7ce35b2523b7c70ffcc91 HEAD
git diff --check
rg --files education_pipeline tests web | sort
```

Require lane-focused verification:

```bash
python3 -m pytest tests/test_prompts.py tests/test_guide_contract.py
python3 -m pytest tests/test_guide_document.py
cd web && npm test && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts
```

Run the shared regression gate after integration:

```bash
git diff --check
python3 -m pytest
cd web && npm test && npm run build
cd web && npm run e2e -- guide-runtime.spec.ts
```

If sandbox policy denies temporary loopback sockets, rerun the identical
command with the required permission and classify it as environmental only
when the unrestricted rerun passes. Do not change product code around sandbox
restrictions. Investigate other failures enough to distinguish regressions
from pre-existing environment failures and record exact evidence.

Before closeout, inspect the entire accepted diff and use targeted searches to
prove `runs.py`, lifecycle actions/defaults, API/daemon routes, provider code,
legacy prompts, legacy renderer behavior, and cockpit source were not changed.

## Commits and recovery

- Fix ordinary defects within the authorized owner boundary.
- Use explicit path lists for staging. Never stage unrelated files.
- Preserve clean lane commits where practical. Suitable messages are
  `feat(prompts): add machine-readable guide contracts` and
  `feat(runtime): add guide interactions and local persistence`.
- Do not amend accepted Wave 1 or Wave 2 commits.
- Stop for human direction only when specs materially conflict, a frozen
  contract would need to change, or unrelated overlapping changes cannot be
  separated safely.

## Plan update and Chunk 05 prompt

After both lanes and shared gates pass, reopen the live implementation plan.
Set Chunk 04 to `Complete` and Chunk 05 to `Ready`. Under Wave 3 record:

- completion date;
- every accepted lane/integration commit;
- delivered files and capabilities by lane;
- accepted prompt-contract helper APIs and runtime interaction surface;
- confirmation that the fixture hash remains
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`;
- exact focused, frontend, E2E, and shared verification results;
- deviations/decisions; and
- remaining risks, or `None`.

Then create the complete next supervisor prompt at:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-05-supervisor.md
```

Derive it from the accepted Wave 3 commits and the live Wave 4 plan section.
It must freeze the fixture hash and all accepted APIs; authorize only the
supervisor-owned Wave 4 pipeline lifecycle work (contract-aware artifact
paths, machine-contract extraction wiring, `inputs/guide-contract.json`
writes, draft/final validation insertion, hash-based freshness, `validate` /
`resolve_findings` actions, guarded guide-v1 finalization, and the gated
default flip with an explicit legacy creation path); prohibit Wave 5 API,
export, preview, and cockpit work; define ownership and hot-file boundaries
(no sub-agent edits `education_pipeline/runs.py` concurrently); include
recovery, verification, plan-evidence, and commit rules; require
`chunk-06-supervisor.md` as its final substantive deliverable; and stop
without beginning Chunk 06.

Review the plan update and Chunk 05 prompt against the accepted
implementation commits, then commit only those closeout documentation files in
a separate commit such as:

```text
docs: close interactive guide chunk 04
```

## Human gate and final report

After the Wave 3 implementation commits and closeout commit exist, stop. Do
not invoke the Chunk 05 prompt, begin lifecycle-integration work, or cross the
human checkpoint.

Report:

- Chunk 04 outcome;
- all lane, integration, and closeout commit hashes;
- exact focused/shared/frontend/E2E results;
- unchanged canonical fixture path and SHA-256;
- accepted new public APIs;
- changed-scope summary;
- the path to `chunk-05-supervisor.md`; and
- a direct statement that Chunk 05 has not started.

If the chunk cannot be completed safely, report the exact blocker and preserve
all useful verified work. Do not fabricate the next prompt as though Wave 3
had been accepted.
