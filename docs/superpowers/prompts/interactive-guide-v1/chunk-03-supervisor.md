# Supervisor Prompt — Interactive Guide v1, Chunk 03

You are the supervisor agent for **Chunk 03: implement and accept the Wave 2
safe parallel foundations** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete only this chunk autonomously, including safe recovery from ordinary
implementation or verification failures. Do not begin Chunk 04. A human
controls the transition between chunks.

## Accepted base and frozen Wave 1 contract

The accepted guide-core implementation is commit:

```text
6e36dc45520eff5bde9d65af5d456f73f0f011ed
```

Confirm it is an ancestor of `HEAD`, inspect the live branch/worktree, and
preserve every unrelated user change. Do not reset, pull, switch branches,
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
`education_pipeline.guides`, are:

```text
parse_guide(text: str | bytes) -> ParseResult
normalize_guide(parsed: ParseResult | Mapping[str, Any]) -> Guide
canonical_guide_bytes(guide: Guide) -> bytes
guide_sha256(guide: Guide) -> str
project_guide_markdown(guide: Guide) -> str
```

Do not change these signatures, normalized fixture bytes, IDs, authored array
order, or hash without stopping at the smallest safe state and reporting the
exact contract blocker.

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
education_pipeline/guides/model.py
education_pipeline/guides/parse.py
education_pipeline/guides/canonical.py
education_pipeline/guides/projection.py
tests/fixtures/guides/feedback-loops.guide.json
tests/test_guide_parse.py
tests/test_guide_canonical.py
tests/test_guide_projection.py
```

Also inspect `pyproject.toml`, package/test conventions, frontend package/test
commands, Git state, and repository-local agent instructions. Trust live code,
not this prompt or a chat summary, when implementation details differ.

## Objective and authorized lanes

Implement, review, verify, and commit only Wave 2. The supervisor may delegate
Lane A to one Agent A and Lane B to one Agent B after confirming clean,
non-overlapping ownership. The supervisor retains the manifest lane and all
integration/review responsibility. Do not start Wave 3 agents or work.

### Lane A — deterministic validators, reports, and waivers

Agent A owns only:

```text
education_pipeline/guides/validation.py
education_pipeline/guides/reports.py
education_pipeline/guides/waivers.py
tests/test_guide_validation.py
tests/test_guide_waivers.py
```

Small edits to `education_pipeline/guides/__init__.py` are allowed only to
publish the accepted new APIs and must be integrated by the supervisor.

Implement:

- immutable report/finding types matching the validation spec;
- stable finding IDs and rule IDs, deterministic severity/rule/path/ID sort,
  summaries, and canonical timestamp-free JSON serialization;
- the complete milestone deterministic rule catalog, grouped into
  parse/schema, security/privacy, outcomes/pedagogy, content/sources, and
  runtime/static-accessibility checks;
- deterministic validation over the accepted normalized fixture plus small bad
  mutations with stable expected findings;
- privacy matching that accepts private denylist inputs but never repeats a
  matched private value in findings, messages, reports, or logs, with explicit
  minimum-length and generic-value exclusions;
- a separate waiver engine keyed to exact guide hash and finding ID; and
- waiver staleness, required non-empty reason, non-waivable rejection, orphaned
  waiver behavior, and effective-gate calculation without deleting or mutating
  findings.

Parsing diagnostics may be converted to findings, but do not duplicate or fork
the accepted authoritative parser. Do not weaken parser safety or teach the
parser about waiver/report lifecycle.

### Lane B — packaged runtime shell, safe renderer, and assembler

Agent B owns only:

```text
education_pipeline/guide_runtime/__init__.py
education_pipeline/guide_runtime/assets/runtime.js
education_pipeline/guide_runtime/assets/runtime.css
education_pipeline/guides/document.py
tests/test_guide_document.py
web/e2e/guide-runtime.spec.ts
```

Required packaging metadata changes are allowed only to include the exact
runtime assets in built distributions. Record every such change. Do not edit
React/cockpit source in this chunk.

Implement:

- small directly maintained browser-native JavaScript and CSS assets loaded
  through `importlib.resources`;
- one pure deterministic document assembler taking a normalized `Guide`, exact
  runtime assets, and mode, and returning a full HTML document;
- schema/runtime compatibility checks and a nonblank static loading/error shell;
- safe embedded JSON escaping for `<`, `>`, `&`, U+2028, and U+2029;
- deterministic SHA-256 CSP hashes over the exact embedded CSS/JavaScript;
- a guide-v1 safe Markdown renderer that escapes raw HTML, constructs only
  validated `http`, `https`, and known-ID fragment links, renders fenced code
  inertly, and never reuses unsafe regex attribute substitution from the legacy
  renderer;
- navigation and static rendering of all six accepted block types, including
  all educational content in print-readable form; and
- focused tests for closing-script input, special-character embedding, unsafe
  URLs, CSP hashes, exact packaged assets, unknown compatibility versions,
  every block type, and repeated byte determinism.

Runtime interactions, persistence, progress state transitions, themes,
responsive interaction behavior, full browser accessibility acceptance, and
cockpit preview integration belong to later chunks. The Wave 2 shell may expose
static semantic controls/markup needed by the next lane, but must not implement
Wave 3 interaction state.

### Supervisor lane — manifest/content-contract compatibility foundation

The supervisor alone owns changes to the manifest/run compatibility seam,
principally `education_pipeline/runs.py` and its focused tests. Implement only:

- an immutable `ContentContract` value and manifest accessor;
- interpretation of absent `content_contract` as `legacy_markdown`;
- explicit creation/reading of immutable `interactive_guide` schema `1.0`
  content contracts without changing the default new-run behavior yet;
- contract-aware content-type and artifact-path maps needed by later work while
  preserving exact legacy paths and behavior; and
- source/input hashes required for later freshness calculations, without yet
  changing lifecycle actions.

Do not insert validation into `_next_action()`, add `validate` or
`resolve_findings` actions, flip new runs to guide v1, change prompt contracts,
or implement guide finalization. Existing manifests and legacy Markdown runs
must remain behaviorally compatible and must not be mutated merely by opening
them.

## Merge order and shared-file discipline

Integrate in this order:

1. Agent A validators/reports/waivers.
2. Agent B runtime shell/renderer/assembler.
3. Supervisor manifest/content-contract foundation.

Review every live diff and test rather than trusting summaries. Resolve shared
`education_pipeline/guides/__init__.py` or packaging edits in the supervisor
worktree after each lane is accepted. Every lane should be a clean logical
commit with exact verification evidence; preserve those commits or integrate
them without rewriting unrelated history.

## Prohibited work

Do not:

- change the frozen fixture, normalized bytes, public Wave 1 signatures, or
  canonical hash;
- implement spec/outline contract extraction or modify model prompts;
- implement knowledge-check/reveal/scenario/reflection runtime state,
  localStorage, progress, themes, or Wave 3 browser interactions;
- add validation lifecycle actions, freshness state, finalization, guide export,
  preview/API routes, findings/waiver endpoints, or cockpit UI;
- flip the new-run default away from legacy Markdown;
- edit provider adapters, CLI behavior, daemon routes, or legacy renderer
  behavior;
- install dependencies or invoke providers/paid APIs;
- execute Chunk 04, create its worktrees, or begin its code; or
- clean, stage, commit, or revert unrelated user changes.

If an acceptance criterion appears to require prohibited work, record the exact
blocker and stop rather than expanding scope.

## Acceptance criteria

### Validators/reports/waivers

1. The valid canonical fixture produces the expected deterministic report with
   no blockers.
2. Small mutations trigger stable IDs for every milestone rule that can be
   exercised before browser integration; explicitly document deferred browser-
   release-only checks.
3. Finding order and canonical report bytes are stable across repeated runs.
4. Findings never echo supplied private values.
5. Waivers require exact current guide hash, exact finding ID, a non-empty
   reason, and `waivable=true`; waived findings remain visible.
6. Stale, orphaned, and non-waivable waivers never open the effective gate.

### Runtime shell/document

1. The accepted fixture statically renders every module, section, block, choice,
   explanation, reveal step, scenario feedback/debrief, reflection prompt,
   glossary entry, and source.
2. Embedded JSON cannot terminate/recontextualize its non-executable script
   element.
3. CSP hashes match exact embedded asset bytes and forbid network, object,
   frame, form, and base behavior as specified.
4. Raw HTML and unsafe link targets cannot become executable DOM or attributes.
5. Repeated assembly from identical inputs returns identical bytes.
6. Package-data tests prove runtime JavaScript/CSS are present through
   `importlib.resources`.

### Manifest/content contract

1. Old manifests without `content_contract` read as `legacy_markdown` without
   an on-disk mutation.
2. Explicit guide-v1 manifests round-trip an immutable
   `interactive_guide`/`1.0` contract.
3. Unsupported contract kinds/versions fail closed and usefully.
4. Legacy stage paths, status, finalize, export, CLI, API, and end-to-end behavior
   remain unchanged.
5. The default run-creation path remains legacy Markdown in this chunk.

## Execution and verification

Start with at least:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 6e36dc45520eff5bde9d65af5d456f73f0f011ed HEAD
git diff --check
rg --files education_pipeline tests web | sort
```

Require lane-focused verification:

```bash
python3 -m pytest tests/test_guide_validation.py tests/test_guide_waivers.py
python3 -m pytest tests/test_guide_document.py
python3 -m pytest tests/test_runs.py tests/test_cli.py tests/test_e2e.py
cd web && npm test && npm run build
```

Run the shared regression gate after integration:

```bash
git diff --check
python3 -m pytest
cd web && npm test && npm run build
```

Run the scoped guide runtime E2E file only if the accepted Wave 2 implementation
contains executable static-shell assertions that do not depend on prohibited
Wave 3 interactions:

```bash
cd web && npm run e2e -- guide-runtime.spec.ts
```

If sandbox policy denies temporary loopback sockets, rerun the identical Python
command with the required permission and classify it as environmental only when
the unrestricted rerun passes. Do not change product code around sandbox
restrictions. Investigate other failures enough to distinguish regressions from
pre-existing environment failures and record exact evidence.

Before closeout, inspect the entire accepted diff and use targeted searches to
prove prompt contracts, lifecycle actions/defaults, API/daemon routes, provider
code, legacy renderer behavior, cockpit source, and Wave 3 interactions were not
changed.

## Commits and recovery

- Fix ordinary defects within the authorized owner boundary.
- Use explicit path lists for staging. Never stage unrelated files.
- Preserve clean lane commits where practical. Suitable messages are
  `feat(guide): add deterministic validation and waivers`,
  `feat(runtime): add deterministic guide document shell`, and
  `feat(pipeline): add content contract foundation`.
- Do not amend the accepted Wave 1 commit.
- Stop for human direction only when specs materially conflict, the frozen
  contract would need to change, or unrelated overlapping changes cannot be
  separated safely.

## Plan update and Chunk 04 prompt

After all three lanes and shared gates pass, reopen the live implementation
plan. Set Chunk 03 to `Complete` and Chunk 04 to `Ready`. Under Wave 2 record:

- completion date;
- every accepted lane/integration commit;
- delivered files and capabilities by lane;
- accepted report/waiver/document/content-contract APIs;
- confirmation that the fixture hash remains
  `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`;
- exact focused, frontend, E2E-if-applicable, and shared verification results;
- deviations/decisions; and
- remaining risks, or `None`.

Then create the complete next supervisor prompt at:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-04-supervisor.md
```

Derive it from the accepted Wave 2 commits and live Wave 3 plan. It must freeze
the fixture hash and accepted APIs; authorize only Agent A machine-readable
spec/outline/draft/QA/repair prompt-contract work and Agent B runtime
interactions/persistence/browser behavior; define ownership and hot-file
boundaries; prohibit Wave 4 `runs.py` lifecycle integration; include recovery,
verification, plan-evidence, and commit rules; require
`chunk-05-supervisor.md` as its final substantive deliverable; and stop without
beginning Chunk 05.

Review the plan update and Chunk 04 prompt against the accepted implementation
commits, then commit only those closeout documentation files in a separate
commit such as:

```text
docs: close interactive guide chunk 03
```

## Human gate and final report

After the Wave 2 implementation commits and closeout commit exist, stop. Do not
invoke the Chunk 04 prompt, begin prompt/runtime-interaction work, or cross the
human checkpoint.

Report:

- Chunk 03 outcome;
- all lane, integration, and closeout commit hashes;
- exact focused/shared/frontend/E2E results;
- unchanged canonical fixture path and SHA-256;
- accepted new public APIs;
- changed-scope summary;
- the path to `chunk-04-supervisor.md`; and
- a direct statement that Chunk 04 has not started.

If the chunk cannot be completed safely, report the exact blocker and preserve
all useful verified work. Do not fabricate the next prompt as though Wave 2 had
been accepted.
