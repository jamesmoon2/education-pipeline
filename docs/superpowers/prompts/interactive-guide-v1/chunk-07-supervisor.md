# Supervisor Prompt — Interactive Guide v1, Chunk 07

You are the supervisor agent for **Chunk 07: implement and accept the Wave 6
findings, waivers, final-review, and recovery loop** in:

```text
/Users/jmooney/Documents/education-pipeline
```

Complete only this chunk autonomously. Do not begin Chunk 08; a human controls
the transition between chunks.

## Accepted base and frozen contracts

The accepted Wave 5 integration head and commits are:

```text
eb09e4f  feat(web): isolate interactive guide preview
5e22328  feat(api): guide export preview findings and waivers
e9b7fad  feat(pipeline): default new runs to interactive guide v1
```

Confirm `eb09e4f` is an ancestor of `HEAD`, inspect live Git/worktree state,
and preserve unrelated changes. Do not reset, pull, switch branches, rewrite
history, push, or open a pull request without separate human authorization.

The canonical fixture is
`tests/fixtures/guides/feedback-loops.guide.json`; its normalized SHA-256 is
frozen as:

```text
99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07
```

Freeze all public Python guide surfaces, runtime assets/data-role contracts,
guide-v1 and legacy prompt compilers, Wave 4 lifecycle/freshness/finalization
behavior, and Wave 5 export/preview behavior. The additive API response shapes
in `docs/superpowers/specs/2026-07-11-interactive-guide-v1-api-freeze.md` are
accepted and frozen. In particular:

- run status adds `content_contract` and draft/final `validations`;
- stage content adds `content_type`;
- validate returns `{state, report, status}`;
- findings returns `{state, report}`;
- waiver creation returns `{waivers, state, report}`; and
- guide preview returns `{html, content_sha256, validation}`.

The accepted cockpit isolation contract is also frozen: executable guide HTML
enters only `GuidePreviewFrame` via `iframe srcDoc` with
`sandbox="allow-scripts"` and no same-origin privilege; legacy Markdown alone
uses the existing safe `dangerouslySetInnerHTML` path; invalid JSON never
replaces the editor buffer or triggers preview.

Do not change any frozen signature/shape/behavior, fixture bytes or authored
order, or hash. Stop at the smallest safe state and report an exact blocker if
Wave 6 appears to require such a change.

## Authoritative files to reopen completely

Before implementation read the PRD; the milestone, runtime/export, and
validation-pipeline specs (especially sections 8–11); implementation plan
section 11 and the Chunk 06 completion record; the Wave 5 API-freeze note;
`runs.py`; daemon read/write/server routes and job semantics; current web API
types/client; run board, primary action, stage workspace/editor, export
controls, and their tests; and all relevant E2E specs including
`full-run.spec.ts` and `guide-runtime.spec.ts`. Also inspect `pyproject.toml`,
package/test conventions, Git state, and repository-local instructions. Trust
live code over this prompt when details differ.

## Objective and authorized scope

Implement, review, verify, and commit only Wave 6 (plan section 11):

1. Show draft/final validation milestones and current/stale state on the run
   board, plus findings summaries filterable by severity/status.
2. Navigate a selected finding to its JSON Pointer or closest `related_ids`
   guide target in source/preview.
3. Add a guarded waiver dialog requiring a non-empty reason and the exact
   current guide hash. Keep current, waived, and stale findings visibly
   distinct; surface 409 stale and 422 non-waivable refusals without losing
   user input.
4. Make primary actions correctly handle `validate` and `resolve_findings`.
   Disable finalization with concrete reasons while blockers, stale reports,
   or invalid waivers remain. Keep finalize and export separate.
5. Add explicit provider rerun/response-replace confirmation and show
   non-sensitive provenance. Preserve the manifest's
   `response_replaced` evidence and no-clobber defaults.
6. Complete the edit → reapprove → revalidate → finalize recovery loop,
   including clear downstream-invalidation explanations and overwrite
   confirmation.
7. Make mixed legacy/guide workspaces list, resume, preview, finalize, and
   export correctly. Resolve the known `web/e2e/full-run.spec.ts` assumption
   within this acceptance-loop scope; do not delete or silently skip it.

### Ownership and hot-file boundaries

The supervisor owns `education_pipeline/runs.py`, daemon routes/jobs, run-board
action semantics, shared API coordination, and integration tests. These are hot
files and must not be edited concurrently by sub-agents.

Only after shared props/contracts are fixed may Agent B own leaf React
components and their tests. Agent B must not edit `education_pipeline/`, daemon
routes, shared Python code, or supervisor-owned run-board/API coordination.
Commit supervisor/shared changes before starting overlapping frontend work.

## Required acceptance scenarios

1. A valid fixture run reaches interactive export.
2. Bad draft findings flow into QA and repair.
3. A final blocker prevents finalization with a concrete reason.
4. Editing repair JSON, reapproving, revalidating, and finalizing succeeds.
5. A waivable blocker requires a reason and remains visible after waiver.
6. A non-waivable blocker is rejected with 422.
7. HTTP preview and local-file export render matching IDs/content.
8. Runtime interactions work by keyboard and persist locally.
9. A legacy Markdown run still completes and exports byte-compatibly.
10. A mixed workspace lists and resumes both contracts correctly.

Add deterministic unit/integration/E2E coverage for every implemented branch.
Do not invoke providers or paid APIs.

## Prohibited work

Do not change the fixture, normalized bytes/hash, guide/runtime frozen modules,
prompt bytes, accepted response shapes, preview sandbox boundary, legacy
preview/download/export behavior, or public signatures. Do not add arbitrary
model HTML/JS execution, delete files as invalidation, redesign provider
adapters beyond the rerun/replace flow, install Python dependencies, or begin
Wave 7 CI, packaging, accessibility closeout, release documentation, or
milestone closeout.

## Verification and recovery

Begin with Git/base checks, `git diff --check`, and `python3 -m pytest`. During
work run focused Python/API tests and frontend unit/build gates. Before
acceptance run:

```bash
git diff --check
python3 -m pytest
cd web && npm test
cd web && npm run build
cd web && npm run e2e
```

The full E2E gate must include both guide-runtime and full-run/mixed-run
acceptance. If sandbox policy denies loopback sockets, rerun the identical
command with required permission and classify it as environmental only when the
unrestricted run passes. Fix ordinary in-scope defects autonomously. Stop only
for a material spec conflict, a required frozen-contract change, or inseparable
unrelated edits.

Before closeout inspect the entire accepted diff and prove with targeted
searches that guide/runtime frozen modules, provider adapters beyond authorized
coordination, legacy prompt bytes/preview/downloads, and the fixture were not
changed. Recompute the normalized fixture hash.

## Commits and plan evidence

Use explicit path lists for staging and preserve unrelated work. Prefer clean
logical commits; do not amend Wave 1–5 history. After all gates pass, update the
live plan: set Chunk 07 to `Complete` and Chunk 08 to `Ready`; record completion
date, every accepted commit, all ten scenario results, exact verification
counts, response-shape preservation, recovery/provenance behavior,
fixture-hash confirmation, intentional test updates, deviations, and remaining
risks or `None`.

Then create the complete next supervisor prompt at:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-08-supervisor.md
```

Derive it from accepted Wave 6 commits and live plan section 12. It must freeze
all accepted guide, lifecycle, API, preview, findings/waiver, provenance, and
recovery behavior; authorize only Wave 7 CI, wheel/package-data verification,
clean-environment fixture export, accessibility/manual acceptance evidence,
documentation, and milestone closeout; define ownership/hot files, recovery,
verification, evidence, and commit rules; require
`chunk-09-post-milestone-supervisor.md` as its final substantive deliverable;
and stop without beginning post-milestone work.
