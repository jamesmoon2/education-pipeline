# Phase 3 Headless Run-to-Judgment — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-18 (opened with the phase; closed 2026-09-19 with T32)
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-18-phase-3-headless.md`](../plans/2026-09-18-phase-3-headless.md)
- **Purpose:** preserve the decisions and accepted limitations from the
  three Phase 3 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

Three threads, each merged into the phase branch only after the full pytest
suite was green on the merged result (plus `npm run build`, vitest and
`approve-continue.spec.ts` for T32, the one thread that changed `web/`).
Every thread was strict TDD with a Sonnet test writer and a separate
implementer (Opus for T30 and T31, Sonnet for T32 after an Opus rate limit;
the manager reviewed every engine and daemon diff), and every implementer ran
a three-mutation pass: of nine mutations tried, seven were caught by the red
set and two survived and were pinned before the thread merged (T31: the
`running` mark written to disk before a course is driven; a batch with one
failed module is not a success). Baseline at open was pytest 2032 passed /
1 skipped, vitest 602, Playwright 74; at close 2156 / 1, 592, 74 on
Python 3.11.

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

### Decision 3: stall guard

Not in the map. A waited job that succeeds without changing the next action
would otherwise re-enqueue until the cap; the loop stops with `failed` and
the message "the job finished but no response was saved".

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

## Open for the owner

- Whether `run --until` should grow a second target (for example `--until
  finalize`, which would let the loop finalize and export a run whose gates
  are all approved). The loop deliberately treats `finalize` and `done` as
  stops today.
- Whether the queue should be visible in the cockpit (a "queued courses"
  panel over the same file) or stay CLI-only.
