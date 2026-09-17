# Phase 0 — Hygiene and Verified Defects

**Goal:** Remove nine verified sharp edges before the structural work (stage graph, per-module drafting) inherits them. Each thread is independent except T07, which depends on T06.

**Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`), "Build plan · Phase 0". Threads are numbered as there.

**Method:** strict TDD, one subagent writes the failing tests and a different one makes them pass; the manager reviews diffs. Every thread ends on the full pytest suite green, plus `npm run build` and `npm run test` when `web/` changed.

**Baseline at open:** pytest 1528 passed / 1 skipped (33 s); vitest 508; `npm run build` clean.

**Audit ledger:** [`../specs/2026-09-17-phase-0-hygiene-post-milestone-audit.md`](../specs/2026-09-17-phase-0-hygiene-post-milestone-audit.md)

## Threads

| ID | Thread | Exit criteria | Status |
| --- | --- | --- | --- |
| T01 | Cache final validation | Warm status read performs zero parse/validate calls; 20-topic poll under 50 ms; cache invalidates on approve, waive, and on-disk edit. | - [x] |
| T02 | Atomic approved and prompt writes | Approved, prompt, final and export writes go through `atomic_io`; fault-injection tests leave the previous file intact. | - [x] |
| T03 | Cross-process guard for the CLI | Workspace lock file (`fcntl`/`msvcrt`); CLI mutating commands refuse with a catalog error while a job is active or the course is archived. | - [x] |
| T04 | Never lose model output | Audit output is logged; parse failure writes `<stage>.failed.<ts>.txt`; salvage-as-response action; Codex adapter validates shape. | - [x] |
| T05 | Worker safety | PID-reuse guard on reconcile; per-stage timeout from the plan (default 1800 s); socket timeout on request body reads. | - [x] |
| T06 | Cost in the API | `GET /v1/runs/{id}` carries a `cost` object with provenance; workspace total; Codex byte-based estimate labeled as such; CLI `status` prints it. | - [x] |
| T07 | Cost in the cockpit | Cost on run board, stage viewer header, library column; Settings rows show last-observed cost. | - [ ] |
| T08 | Effort: wire it or remove it | Effort reaches the provider CLI where a flag exists; control hidden with a note where none does; decision recorded. | - [x] |
| T09 | Docs truth-up and issue #18 | Shipped plan steps ticked, design status lines updated; preset buttons show "no mapping for this provider" instead of a silent no-op. | - [x] |

## Closeout log

(One line per thread as it lands: what changed, test counts, accepted limitations.)

- **T02** landed: `runs.py:_write_text` delegates to `atomic_io.atomic_write_text`; 7 new tests in `tests/test_atomic_artifact_writes.py`. Suite 1535 passed / 1 skipped. Follow-up noted in the audit: `workspace.py:_write_text` (topic TOML saves) is still a plain write.
- **T06** landed: `cost.py` (estimate + aggregation), `Job.cost_usd`/`cost_source`, `cost` blocks on `/v1/runs/{id}` and `/v1/topics`, CLI status line; 15 new tests. Suite 1543 passed / 1 skipped. Accepted limitation: the price table is a placeholder, not a vendor price sheet.
- **T09** landed: #18 fixed in `SettingsPage.tsx` (disabled preset + visible hint); factcheck plan 29/34 steps ticked, cockpit-usability plan 58/68, remaining are TDD 'verify it fails' steps; both design docs read Shipped; full Playwright run 86 passed. vitest 509.
- **T08** landed: both CLIs support effort (Claude Code `--effort`, Codex `-c model_reasoning_effort=`), so it is wired for both; `supports_effort` capability on every runner and in `/v1/config/providers`; Settings hides the control for providers without it; help copy corrected; decision recorded in the model-plan audit. pytest 1536, vitest 510.
- **T03** landed: `workspace_lock.py` (fcntl/msvcrt, non-blocking poll, reentrant per process) held inside `RunStore`'s manifest lock; CLI advance/audit/approve/finalize/export/waive/unwaive refuse with `job_conflict`/`archived_course`; new `workspace_locked` catalog code. 9 new tests. Accepted limitation: a lock timeout inside the daemon surfaces as HTTP 400 `invalid_request`, not a `workspace_locked` envelope.
- **T05** landed: `Job.pid_identity` from `/proc/<pid>/stat` start time gates reconcile kills (Linux; other platforms keep pid-only behaviour, accepted); `timeout_seconds` per stage in the model plan, validated, round-tripped through the API and the cockpit Save, default 1800 s; 30 s socket timeout on request reads. 14 new tests. pytest 1540, vitest 510 in-thread.
- **T04** landed: parse/ingest failures salvage raw stdout to `<stage>.failed.<ts>.txt`; `failed_outputs` per stage in run status; `POST .../stages/{stage}/salvage` (409 without overwrite, manifest event, never approves); Codex rejects empty output. Decision: the plan's "log audit output" line was rejected because the personalization spec forbids private values in logs; the salvage file preserves audit output as a private raw artifact instead. 11 new tests.
- **T01** landed: validated-final-report memo (per RunStore, keyed by source digest + validation inputs, bounded 64) on the poll path; request-scoped per-thread manifest read scope opened by `run_status`/`next_action`/`run_status_payload`, discarded on write; `content_contract` no longer stats the manifest twice. Warm status read: zero validation calls; 20-topic poll 41 ms (was 228). 15 new tests. Timing test asserts the fastest of five passes, budget ×4 under `CI`.
