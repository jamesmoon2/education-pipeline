# Phase 3 Headless Run-to-Judgment — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-18 (opened with the phase; closed 2026-09-19 with T32)
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-18-phase-3-headless.md`](../plans/2026-09-18-phase-3-headless.md)
- **Purpose:** preserve the decisions and accepted limitations from the
  three Phase 3 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

Five threads (T30–T32 from the opportunity map, T33–T34 added after the
owner asked for the cockpit to behave exactly like `run --until approval`),
each merged into the phase branch only after the full pytest suite was green
on the merged result (plus `npm run build`, vitest and the relevant
Playwright specs whenever `web/` changed). Every thread was strict TDD with a
Sonnet test writer and a separate implementer (Opus for T30, T31 and T33,
Sonnet for T32 and T34; the manager reviewed every engine and daemon diff),
and every implementer ran a three-mutation pass: of fifteen mutations tried,
thirteen were caught by the red set and two survived and were pinned before
the thread merged (T31: the `running` mark written to disk before a course is
driven; a batch with one failed module is not a success). Baseline at open
was pytest 2032 passed / 1 skipped, vitest 602, Playwright 74; at close 2184
/ 1, 624, 76 on Python 3.11.

Two red-set corrections by the manager: T34's e2e expectation double-named a
stage the stop already names (the brief's fault; corrected to the deduped
phrase the approve flow already uses), and T33's red writer pinned a stall
that was in fact a T30 bug (below), which was fixed rather than pinned.

No thread exceeded the ~800-changed-line guideline once tests are set aside
(T31 is +1431 over six files, 1,000 of them tests and docs).

## Decisions that departed from the plan text

### Decision 1: the engine loop does not run providers

The opportunity map described the orchestrator as "loops advance → provider
job → validate". The engine never spawns provider processes (the daemon's
worker owns every subprocess, a Phase 0 invariant), so the loop is generic
over an injected `run_job` that reports whether it waited. The CLI's runner
enqueues through the daemon and blocks until the job or batch is terminal;
the daemon's runner enqueues and returns, so the route answers `started`
exactly as the cockpit chain did. One loop, two runners, no HTTP request
that blocks on a model.

### Decision 3: stall guard (revised in T33)

Not in the map. A waited job that succeeds without changing the next action
would otherwise re-enqueue until the cap; the loop stops with `failed` and
the message "the job finished but no response was saved". T30 compared only
action and stage; T33's red set showed that this misreads the skeleton job of
an interactive-guide run (its ingest writes the module prompts, so the next
action is `save_response`/`draft` again, for the batch) and therefore broke
`run --until approval` on every non-legacy course. The guard now requires the
whole `NextAction` (action, stage, detail) to be identical; the four draft
`save_response` arms carry distinct details, and a response that fails ingest
fails the job. A CLI test on a guide-v1 run pins the fix.

### Decision 9: the daemon carries the chain across job completions

Added after T32 at the owner's request. A job started by the continue route
is marked `chain`; when it, or its whole batch, reaches a terminal status the
worker's completion hook runs the same `continue_run` with `after_job` and
enqueues the next job with `chain` set again, recording each outcome on the
finishing job and in `run_status_payload.continuation`. `POST /v1/jobs`
never chains. The cockpit's one click therefore reaches the same stop the
CLI reaches, through the same loop.

### Decision 7: the queue is a workspace file

`queue add/list/remove/run` operate on `<workspace>/queue/courses.json`
(already gitignored). Nothing in the engine, manifest or daemon knows about
the queue; `queue run` is `run --until approval` in a loop with the file
rewritten before and after each course so an interrupted pass resumes.

### T32: stage derived by the daemon, not passed by the loop

Both runners call enqueue without a stage so the daemon derives it from the
same next action the loop just read and keeps its own "next action must be
save_response" check. The loop's stage is used only for labels and the
provider lookup.

## Accepted limitations

- **T30:** a waited job that fails without a message reads "the job did not
  succeed" (unpinned). `StoreSteps.validate` is unit-tested through a patched
  `validate_and_gate`; the real gate is exercised by T31's live-daemon test.
- **T31:** the module fan-out path is pinned at the runner level over a fake
  batch client, not through a live interactive-guide batch. A `queue run`
  whose entries are all `stopped` prints "queue: nothing pending" (unpinned).
  A daemon error mid-queue leaves that course `running` and aborts the pass;
  the next `queue run` resumes it.
- **T32:** the continue route holds no lock across the loop (decision 8);
  each step takes the guard it takes today, so steps interleave with other
  clients exactly as the cockpit's five-call chain did. vitest dropped from
  602 to 592 because the old loop's branch cases were replaced by the
  thin-client set; the phrase tests are unchanged.

- **T33:** the completion hook holds the context lock across the whole
  continuation, so chains of different topics serialize (the pool only
  overlaps jobs of one batch anyway). `continuation` picks the latest record
  by `at`, not job id. Crash recovery (`reconcile`) does not fire the hook, so
  a chain interrupted by a daemon restart shows no record until the user
  continues again.
- **T34:** no chained Playwright case (T33's live-server tests own the
  chain); the continuation line stays until the next job replaces it.

## Open for the owner

- Whether `run --until` should grow a second target (for example `--until
  finalize`, which would let the loop finalize and export a run whose gates
  are all approved). The loop deliberately treats `finalize` and `done` as
  stops today.
- Whether the queue should be visible in the cockpit (a "queued courses"
  panel over the same file) or stay CLI-only.
