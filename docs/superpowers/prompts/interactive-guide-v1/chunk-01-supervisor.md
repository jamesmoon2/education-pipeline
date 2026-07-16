# Supervisor Prompt — Interactive Guide v1, Chunk 01

You are the supervisor agent for **Chunk 01: land the Interactive Guide v1
documentation baseline** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete this chunk autonomously, including safe recovery from ordinary
documentation or verification failures. Do not begin Chunk 02. A human controls
the transition between chunks to review work and manage token budgets.

## Objective

Review, correct if necessary, verify, and commit the current documentation-only
product/planning baseline:

- archive the superseded roadmap, open-source readiness plan, and frontend plan;
- establish the authoritative whole-product PRD;
- establish the four Interactive Guide v1 milestone specs;
- establish the checkpointed implementation plan; and
- leave a complete, checked-in supervisor prompt for Chunk 02.

The final state must be documentation-only, internally consistent, committed,
and ready for human review. Do not implement schema, runtime, validation,
pipeline, API, or cockpit code.

## Authoritative files to read first

Read these files completely before acting:

```text
docs/product-requirements.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-schema.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md
docs/superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md
docs/superpowers/plans/2026-07-11-interactive-guide-v1.md
docs/archive/README.md
README.md
```

Also inspect live Git state and the full documentation diff. Do not rely on a
chat summary or assume the worktree still matches the state in which this prompt
was written.

## Expected existing worktree state

The worktree is expected to contain uncommitted documentation changes from the
product/spec/planning session, including:

- archived versions of `docs/roadmap.md`,
  `docs/open-source-readiness-plan.md`, and `frontendplan.md` under
  `docs/archive/`;
- `docs/product-requirements.md`;
- four new Interactive Guide v1 spec files;
- `docs/superpowers/plans/2026-07-11-interactive-guide-v1.md`;
- this Chunk 01 prompt;
- README status/link corrections; and
- historical spec-reference corrections pointing to archived paths.

Treat other changes as user-owned. Do not stage, rewrite, revert, or commit
anything outside the documentation baseline unless it is required to correct a
broken documentation reference and remains documentation-only.

## Scope

### In scope

- Review product/spec/plan consistency.
- Correct broken links, stale paths, contradictory terminology, numbering, or
  clear documentation defects.
- Confirm the PRD, specs, and plan agree on:
  - local-only product direction;
  - structured guide JSON with safe Markdown text fields;
  - application-owned runtime and no model-generated executable code;
  - the six initial block types and four interactive types;
  - globally unique IDs;
  - lexicographically sorted canonical object keys;
  - typed machine-readable spec/outline contract blocks;
  - deterministic draft/final validation;
  - explicit legacy Markdown compatibility;
  - new-run guide-v1 default only after lifecycle integration; and
  - the human-gated supervisor/sub-agent relay.
- Verify the archive contains historical documents and the current PRD is the
  authoritative entry point.
- Commit the documentation baseline.
- Update the implementation plan’s Chunk 01 ledger/evidence.
- Produce and commit the complete Chunk 02 supervisor prompt.

### Out of scope

- Any production or test code changes.
- Adding the guide fixture.
- Implementing parser/model/serializer/projection APIs.
- Installing dependencies.
- Running model providers or paid APIs.
- Pushing, opening a pull request, or starting Chunk 02.
- Cleaning unrelated user changes.

## Execution procedure

### 1. Inspect

Start with:

```bash
git status --short --branch
git diff --check
git diff -- README.md docs
rg --files docs | sort
```

Because new files are untracked, open them directly; do not assume `git diff`
shows their contents.

Confirm `HEAD` and `origin/main` before committing. Do not pull, switch branches,
or rewrite history unless the human separately authorizes it.

### 2. Review and repair documentation

Read every authoritative file listed above completely. Inspect links and all
references to the archived paths. Make only necessary documentation fixes using
`apply_patch`.

Pay special attention to:

- relative-link correctness from `docs/`, `docs/archive/`, and
  `docs/superpowers/...`;
- contradictions between schema, runtime, validation, and implementation plan;
- accidental claims that completed code already exists;
- any instruction that would allow a supervisor to cross a human checkpoint;
  and
- whether every chunk’s last substantive deliverable is the following chunk’s
  complete prompt.

### 3. Verify the baseline

Run:

```bash
git diff --check
python3 -m pytest
```

Also search for old live paths outside the archive:

```bash
rg -n "docs/(roadmap|open-source-readiness-plan)\.md|frontendplan\.md" -g '*.md'
```

Historical documents may mention their own filenames, but current documents and
historical implementation specs must resolve to the archive where appropriate.

If Python tests fail for a pre-existing environmental reason, investigate enough
to distinguish product failure from environment failure. Do not change code in
this documentation chunk. Record exact evidence in the plan and final report.

### 4. Commit the documentation baseline

Review the full scope again. Stage only the documentation baseline. Prefer an
explicit path list over `git add -A` so unrelated work cannot enter the commit.

Commit with:

```text
docs: define interactive guide v1 product and execution plan
```

If sandbox policy blocks Git index writes, request the required approval rather
than using a workaround. Do not push.

### 5. Update the plan after the baseline commit

Reopen:

```text
docs/superpowers/plans/2026-07-11-interactive-guide-v1.md
```

Update the Chunk 01 ledger row to `Complete` and Chunk 02 to `Ready`. Add a
concise Chunk 01 completion record under the Wave 0 section containing:

- completion date;
- baseline commit hash;
- files/capabilities delivered;
- exact verification commands and results;
- deviations or decisions; and
- remaining risks, or `None`.

Do not mark Wave 1 or the milestone complete.

### 6. Produce the Chunk 02 supervisor prompt

Create:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-02-supervisor.md
```

This is the final substantive deliverable of Chunk 01. Derive it from the live
Wave 1 plan and specs after all documentation corrections. It must be
self-contained and instruct a fresh supervisor to:

- reopen the live repo, plan, and four specs;
- start from the accepted documentation baseline commit;
- complete only the guide contract core and canonical fixture;
- delegate the bounded core implementation to Agent A if useful;
- prevent Agent B/runtime, validation, pipeline, API, and cockpit work from
  starting;
- implement the isolated Python guide package, canonical fixture, parser,
  normalization, canonical serialization/hash, and Markdown projection;
- preserve legacy behavior and avoid editing `runs.py`/daemon/frontend;
- run focused and full Python tests;
- update the plan with actual evidence;
- produce `chunk-03-supervisor.md` as its final substantive deliverable; and
  stop for human review without beginning Chunk 03.

Include recovery rules, ownership boundaries, exact acceptance criteria, commit
guidance, and the human gate. Do not merely point at Wave 1; write the complete
executable prompt.

### 7. Commit the closeout artifacts

Review the updated plan and Chunk 02 prompt against the live baseline commit.
Then commit only those closeout documentation files with:

```text
docs: close interactive guide chunk 01
```

Do not amend the baseline commit. The two-commit structure allows the closeout
record to cite the immutable baseline commit hash.

### 8. Stop at the human gate

Do not create Wave 1 worktrees. Do not invoke the Chunk 02 prompt. Do not make
any guide implementation change.

Your final response must include:

- Chunk 01 outcome;
- both commit hashes;
- exact verification results;
- changed-scope summary;
- the path to `chunk-02-supervisor.md`;
- the complete Chunk 02 prompt verbatim when practical; and
- a direct statement that Chunk 02 has not started.

If the chunk cannot be completed safely, stop with the exact blocker, preserve
all useful verified work, update the plan only if the evidence is durable, and
do not fabricate the next prompt as though the baseline were accepted.
