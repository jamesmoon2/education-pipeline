# Supervisor Prompt — Interactive Guide v1, Chunk 02

You are the supervisor agent for **Chunk 02: implement and accept the guide
contract core and canonical fixture** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete only this chunk autonomously, including safe recovery from ordinary
implementation or verification failures. Do not begin Chunk 03. A human
controls the transition between chunks to review work and manage token budgets.

## Accepted base and objective

The accepted documentation baseline is commit:

```text
e35f9c82a620e89e27dcb846a240a09bb73cdf10
```

Start by confirming that this commit is an ancestor of `HEAD`, inspecting the
live branch/worktree, and preserving all unrelated user changes. Do not reset,
pull, switch branches, rewrite history, push, or open a pull request unless the
human separately authorizes it.

Implement, review, verify, and commit only Wave 1 of the Interactive Guide v1
plan:

- an isolated Python guide package;
- the complete canonical “Thinking in Feedback Loops” guide JSON fixture;
- typed guide data and parsing/normalization;
- canonical JSON bytes and SHA-256;
- deterministic Markdown projection; and
- focused tests that freeze the accepted contract.

The final state must preserve all existing legacy behavior, pass focused and
full Python tests, update the implementation plan with actual evidence, contain
a complete checked-in Chunk 03 supervisor prompt, and stop at the human gate.

## Authoritative files to reopen completely

Read these files before implementation:

```text
docs/product-requirements.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-schema.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md
docs/superpowers/plans/2026-07-11-interactive-guide-v1.md
```

Also inspect live package/test conventions, `pyproject.toml`, Git state, and
any repository-local agent instructions. Do not rely on this prompt or a chat
summary when live code supplies the answer.

## Scope and ownership

### In scope

The intended boundary is:

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

Names may change when live repository conventions justify it, but keep the new
package isolated from the legacy renderer and pipeline. Small packaging/export
surface edits are allowed only when necessary to expose the accepted guide-core
API; record any such deviation in the plan.

You may delegate the bounded guide-core implementation and focused tests to one
Agent A if useful. Give that agent this exact ownership boundary and require a
commit plus verification evidence. The supervisor remains responsible for
reading the specs, reviewing every line and test, repairing defects, integrating
the work, running the complete gates, updating the plan, and producing the next
prompt. Do not start Agent B.

### Prohibited work

Do not:

- implement validators, validation reports, findings, or waivers;
- create runtime JavaScript/CSS, HTML assembly, browser tests, preview, or
  export integration;
- edit `education_pipeline/runs.py`, daemon/server/API code, provider code, CLI
  behavior, React/cockpit code, or existing legacy export behavior;
- implement typed spec/outline contract extraction or prompt changes;
- add lifecycle/content-contract defaults, validation transitions, or new API
  shapes;
- install dependencies or run model providers/paid APIs;
- begin Wave 2 or create Wave 2 worktrees; or
- clean, stage, commit, or revert unrelated user changes.

If fulfilling an acceptance criterion appears to require prohibited work, stop
and record the exact blocker rather than expanding scope.

## Contract requirements

### Canonical fixture

Check in the complete synthetic course from the milestone acceptance scenario:
“Thinking in Feedback Loops,” for a project manager who enjoys gardening
examples, wants a 30-minute conceptual course, and prefers scenario practice.

It must contain:

- three explicit learning outcomes;
- two modules with at least two sections each;
- all six v1 block types: `rich_text`, `callout`, `knowledge_check`,
  `worked_reveal`, `scenario`, and `reflection`;
- two knowledge checks with explanations;
- one multi-step worked reveal;
- one gardening decision scenario;
- one reflection prompt;
- a glossary and at least one source record; and
- no private profile details.

Every outcome must be assigned, taught, and assessed/practiced. Each module must
contain an interactive block. All IDs, including choices and reveal steps, must
be valid and globally unique.

### Parser and normalization

Implement the v1 schema as typed Python data with a single authoritative parse
path. The parser must:

- accept UTF-8 JSON with a root object and exact schema version `1.0`;
- reject malformed JSON, unsupported versions, unknown fields, invalid types,
  invalid/duplicate IDs, unknown references, and unknown block types;
- enforce collection/cardinality and per-field constraints from the schema;
- enforce global ID uniqueness and cross-object references/invariants;
- enforce the safe Markdown text/URL boundary to the extent owned by parsing,
  while leaving the later full validation rule catalog to Chunk 03;
- report multiple structural problems when practical; and
- produce a typed normalized guide only when render-blocking structural defects
  are absent.

Do not prematurely implement the Wave 2 report/waiver system. If a lightweight
parse diagnostic type is needed, keep it explicitly structural and convertible
to later findings.

### Canonical serialization and hash

Canonical bytes must use:

- UTF-8 without ASCII escaping;
- two-space indentation;
- lexicographically sorted keys at every object level;
- authorial array order; and
- exactly one final newline.

Expose one SHA-256 helper over those canonical bytes. Freeze the fixture's exact
canonical bytes/hash with checked assertions so later Python/runtime layers
cannot drift independently.

### Markdown projection

Produce a deterministic, readable projection that includes every educational
field defined by the schema: course metadata and description, outcomes, modules
and sections, all block content, answer choices and explanations, expanded
worked steps, scenario feedback/debrief, reflection prompts without learner
notes, glossary, and sources. Preserve authorial ordering. The projection is
lossy only with respect to future interactive state.

### Public contract to freeze

Publish these entry points or close equivalents:

```text
parse_guide(text) -> parse result with structural diagnostics
normalize_guide(parsed) -> Guide
canonical_guide_bytes(guide) -> bytes
guide_sha256(guide) -> str
project_guide_markdown(guide) -> str
```

If the exact API differs, keep one obvious path for each operation and record
the accepted signatures in the plan. Agent B in Chunk 03 must be able to build
only against the accepted normalized fixture and public contract.

## Test and acceptance criteria

Focused tests must prove at least:

1. The complete fixture parses and normalizes successfully.
2. Exact normalized bytes and SHA-256 are stable.
3. Non-ASCII content is preserved and only one trailing newline is emitted.
4. Object keys sort recursively while arrays retain authored order.
5. Unknown root/nested/block fields and block types are rejected.
6. Unsupported versions and malformed JSON are rejected usefully.
7. Every `id` field is checked globally, including choice and reveal-step IDs.
8. Invalid references and required collection/cardinality rules are rejected.
9. Small mutation-based bad cases exercise each of the six block shapes without
   duplicating the full fixture.
10. Markdown projection contains all educational content and is deterministic.
11. Existing tests and legacy Markdown behavior remain unchanged.

Prefer fixture mutations inside tests for malformed cases. Do not create a
large collection of near-duplicate fixture files.

## Execution procedure

### 1. Inspect and establish the live base

Run at least:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor e35f9c82a620e89e27dcb846a240a09bb73cdf10 HEAD
git diff --check
rg --files education_pipeline tests | sort
```

Identify and preserve unrelated changes. Confirm no production/test change from
another task overlaps the proposed boundary before delegation or editing.

### 2. Implement and review the isolated core

If Agent A is used, review its live diff and commit rather than trusting its
summary. Trace every schema invariant against the fixture and focused tests.
Repair within the authorized files when needed. Do not accept an API or fixture
that merely satisfies happy-path tests while contradicting the specs.

### 3. Verify

Run:

```bash
git diff --check
python3 -m pytest tests/test_guide_parse.py tests/test_guide_canonical.py tests/test_guide_projection.py
python3 -m pytest
```

If sandbox policy denies temporary loopback sockets, rerun the identical full
test command with the required permission. Treat `PermissionError: [Errno 1]
Operation not permitted` from socket binding as environmental only after
confirming the unrestricted rerun passes. Do not change product code to work
around sandbox restrictions.

Also inspect the final diff and run targeted searches proving prohibited hot
files and runtime/frontend areas were untouched.

### 4. Commit the implementation

Stage only the guide-core package, canonical fixture, and focused tests. Use an
explicit path list. A suitable commit message is:

```text
feat(guide): add v1 contract core and canonical fixture
```

If Agent A already made a clean logical commit, review and retain or integrate
it without rewriting unrelated history. Do not push.

### 5. Update the plan with actual evidence

Reopen the live implementation plan. Set Chunk 02 to `Complete` and Chunk 03 to
`Ready`. Under Wave 1 add a concise completion record containing:

- completion date;
- implementation commit hash(es);
- delivered files/capabilities;
- accepted public Python signatures;
- exact canonical fixture SHA-256;
- exact focused and full verification commands/results;
- deviations/decisions; and
- remaining risks, or `None`.

Do not mark Wave 2 or the milestone complete.

### 6. Produce the complete Chunk 03 supervisor prompt

Create:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-03-supervisor.md
```

Derive it from the accepted Wave 1 implementation and the live Wave 2 plan. It
must be a self-contained executable prompt that starts from the accepted core
commit and authorizes only:

- Agent A deterministic validators/reports/waivers;
- Agent B packaged runtime shell, safe renderer, deterministic document
  assembler, static rendering of all six block types, and its focused tests;
- the supervisor's manifest/content-contract compatibility foundation; and
- the Wave 2 merge order and shared regression gates.

It must freeze the exact fixture hash/public API, define ownership and hot-file
boundaries, prohibit Wave 3 prompt contracts/runtime interactions, include
recovery rules and exact acceptance criteria, require actual plan evidence,
require `chunk-04-supervisor.md` as the final substantive deliverable, and stop
without beginning Chunk 04.

### 7. Commit closeout artifacts

Review the plan update and Chunk 03 prompt against the accepted implementation
commit. Commit only those closeout documentation files with a suitable message,
for example:

```text
docs: close interactive guide chunk 02
```

Do not amend the implementation commit. This lets the closeout record cite its
immutable hash.

## Recovery and stop rules

- Fix ordinary guide-core defects and focused-test failures inside scope.
- Investigate full-suite failures enough to separate regressions from sandbox or
  pre-existing environment failures; record exact evidence.
- If unrelated user changes overlap an owned file, preserve them and integrate
  carefully. Stop for human direction only when safe separation is impossible.
- If the specs conflict materially, do not invent a contract. Record the exact
  passages and stop at the smallest safe state.
- Never relax schema safety, canonical determinism, or global-ID rules merely to
  make the fixture pass.
- Never cross the human checkpoint, even when all Chunk 02 gates pass.

## Human gate and final report

After the implementation commit and closeout commit exist, stop. Do not invoke
the Chunk 03 prompt, start Agent A/Agent B for Wave 2, create Wave 2 worktrees,
or make validator/runtime/pipeline/API/cockpit changes.

Your final response must include:

- Chunk 02 outcome;
- all implementation and closeout commit hashes;
- exact focused and full verification results;
- canonical fixture path and SHA-256;
- accepted public Python entry points;
- changed-scope summary;
- the path to `chunk-03-supervisor.md`; and
- a direct statement that Chunk 03 has not started.

If the chunk cannot be completed safely, report the exact blocker and preserve
all useful verified work. Do not fabricate the next prompt as though the core
contract had been accepted.
