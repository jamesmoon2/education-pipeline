# Phase 0 Hygiene — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-17
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-17-phase-0-hygiene.md`](../plans/2026-09-17-phase-0-hygiene.md)
- **Purpose:** preserve the decisions and accepted limitations from the nine
  Phase 0 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

Every thread landed test-first: one subagent wrote the failing tests, a
different one made them pass, and the manager reviewed diffs. Each thread
merged only after the full pytest suite was green on the merged branch, plus
`npm run build` and `npm run test` where `web/` changed. Baseline at open was
pytest 1528 passed / 1 skipped and vitest 508.

## Decisions that departed from the plan text

### T04: audit output is still kept out of the job log

The plan said "log audit output like every other stage; redaction stays on
the ingest path." That contradicts the personalization design
(`2026-07-12-personalization-design.md`, "Private values ... never appear in
API errors, warnings, findings, logs ..."), and two existing tests pinned the
suppression on purpose. The suppression stays and the code comment now cites
the spec. The gap the plan was pointing at ("if the audit response fails to
parse, the model's output exists nowhere on disk") is closed instead by the
salvage path: raw output is written to `responses/<stage>.failed.<ts>.txt`,
which the same spec classifies as a raw audit-response artifact that may hold
private values and stays in the workspace.

### T08: effort is wired for both providers, not removed

The plan expected Claude Code to lack an effort option. Verified against
current docs on 2026-09-17, both CLIs accept one (Claude Code `--effort`,
Codex `-c model_reasoning_effort="..."`), so the control was wired rather
than hidden. Values beyond low/medium/high are deliberately not exposed; see
the 2026-09-17 follow-up in the model-plan post-milestone audit.

### T01: the memo sits at the status call site, not inside `_validated_final`

Memoizing inside `_validated_final` made `validate_run` re-warm the cache
and broke the invalidation tests; the memo wraps only the poll-path caller,
so `gate_result`, `validate_run` and export still compute fresh as their
docstrings promise. The waiver invalidation test needed no change.

## Accepted limitations

- **T02 (closed at closeout):** `workspace.py:_write_text` (topic TOML
  saves) was the last plain `Path.write_text` in the package; it now goes
  through `atomic_io` as well, with the same fault-injection and structural
  tests as the run artifacts. No plain artifact write remains in
  `education_pipeline/`.
- **T03 (closed):** a `workspace_locked` timeout raised inside the daemon now
  surfaces as HTTP 409 `workspace_locked` on every verb, not as a generic 400
  `invalid_request` (`WorkspaceLockedError` is a `ConfigError` subclass, so
  its arm sits above the generic one in `daemon/server.py`). Closed alongside
  the admission fix: job admission (`DaemonContext.enqueue_stage`,
  `JobStore.create`, and the queued -> running transition) now takes the same
  workspace lock the CLI holds across its check-and-mutate, so a job can no
  longer be admitted in the gap between the CLI's guard and its mutation.
- **T03:** the four lock tests that spawn a child interpreter import the
  installed package, so they require the editable install to point at the
  checkout under test (true on the main checkout and in CI).
- **T04:** no CLI `salvage` subcommand; the action exists on the API
  (`POST /v1/runs/{topic}/stages/{stage}/salvage`) and the cockpit button is
  a later thread. `failed_outputs` reaches the cockpit types in T07.
- **T05:** process identity comes from `/proc/<pid>/stat` and is Linux-only;
  macOS and Windows keep the pid-only reconcile behaviour. No `ps` shell-out
  by decision.
- **T05:** there is no per-model timeout layer in the plan today;
  `effective_timeout_seconds(plan, stage, model)` accepts `model` for a future
  layer and ignores it.
- **T05:** the 30 s socket timeout also closes idle HTTP/1.1 keep-alive
  connections. The cockpit polls every 5–10 s and Chromium retries a request
  whose reused socket closed before any response bytes, so no e2e change was
  needed; the full Playwright suite was re-run at closeout.
- **T05:** "Reset to default" and preset buttons still replace the whole
  stage entry and therefore drop a hand-set `timeout_seconds`, the same as
  they drop `effort`; both are explicit user resets.
- **T06:** `education_pipeline/cost.py:PRICE_TABLE` is a placeholder (USD
  per million tokens, blended), not a vendor price sheet. Estimates are
  labelled `estimate` everywhere they appear. Provider-reported cost exists
  only for Claude Code.
- **T09:** TDD "run to verify it fails" steps in the factcheck and
  cockpit-usability plans stay unticked: tests and implementation landed in
  the same commits, so the pre-implementation red state cannot be reproduced.

- **T01:** inside an open manifest read scope, `read_manifest` returns a
  dict shared by every reader in that request; read-modify-write callers
  must use `_read_manifest_for_update` (all five in-tree callers do). Copying
  measured slower than a fresh parse, so sharing was chosen and the contract
  is documented on both functions.
- **T01:** the 20-topic timing test measures the fastest of five warm passes
  against 50 ms locally and 200 ms when `CI` is set, because the hosted
  Windows and macOS runners are slower and noisier than a workstation.

- **T07:** "last observed cost per stage" on Settings is workspace-wide
  (newest costed job for that stage in any topic), fetched once on mount
  from `/v1/topics`; it is an observation, not a forecast, and a failed fetch
  never blocks the plan editor.
- **T07:** one test-writer assertion was rescoped: it matched the row's
  always-present "Provider for <stage>" label, so it passed with no
  implementation and threw on multiple matches once the feature rendered; it
  now asserts the "last observed" line's own text.
- **T07:** 14 implementation files, over the 12-file guideline; accepted so
  the API half of the Settings path did not land unused.

- **Closeout e2e:** three full Playwright runs on the merged branch: 86/86,
  86/86, then 85/86 with one failure in
  `guide-progress.spec.ts` ("the offer works the same way from a file://
  URL": resumed progress read back as 0 of 4 sections). No Phase 0 thread
  touched `guide_runtime/`, `export.py`, `guides/` or that spec, and the spec
  passed 18/18 on two immediate re-runs, so it is recorded as a pre-existing
  flake in the file:// resume path, not a Phase 0 regression. Worth a look
  when the runtime is next in scope (Phase 4).

## Owner decisions still not recorded (carried from the opportunity map)

- PyPI vs GitHub-release-only distribution.
- Unknown keys in stage overrides: reject or ignore.
- When to delete the stage-less-finding shims.
- The v0.1 release checklist is human sign-off, not thread work.
