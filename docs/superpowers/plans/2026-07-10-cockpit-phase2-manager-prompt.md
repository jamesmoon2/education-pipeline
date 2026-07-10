# Manager prompt — Cockpit Phase 2 (Write Actions)

You (Claude, in this Claude Code session) are the supervising manager for implementing the Cockpit Phase 2 plan in this repo. You do not write feature code yourself — you dispatch fresh subagents per task, review their work between tasks, and keep durable on-disk state current so the effort survives any interruption. You are starting with a fresh context: everything you need is in the three inputs below plus git history — read them before dispatching anything, and do not assume any knowledge from prior sessions.

## Inputs (read all three before dispatching anything)

- Plan (authoritative task list): `docs/superpowers/plans/2026-07-10-cockpit-phase2-write-actions.md`
- Spec (authoritative behavior): `docs/superpowers/specs/2026-07-10-cockpit-phase2-write-actions.md`
- Prior-phase ledger (precedents you must honor): `.superpowers/sdd/progress.md` — but first check whether it (or a Phase 2 ledger) already records Phase 2 progress: **if a Phase 2 ledger exists, you are resuming, not starting — skip setup and continue from the "To resume" pointer.**

## Process

Use the superpowers:subagent-driven-development skill. Concretely:

1. **Branch setup.** If `feat/cockpit-phase1` has merged to `main`, create `feat/cockpit-phase2` off `main`. If it has NOT merged, stack `feat/cockpit-phase2` on top of `feat/cockpit-phase1` and record that in the ledger. Commit the spec and plan files as the first commit if they are untracked.
2. **Ledger setup.** Archive the Phase 1 ledger to `.superpowers/sdd/progress-cockpit-phase1.md` and start a fresh `.superpowers/sdd/progress.md` headed with: plan path, branch, base commit, model assignments (implementers: Sonnet; reviewers: Sonnet; final whole-branch review: you, the manager).
3. **Per task (1 through 16, in order — later tasks consume earlier tasks' interfaces):**
   - Dispatch a fresh Sonnet implementer subagent. Its brief is that task's full text from the plan (verbatim, including code blocks) plus the plan's **Global Constraints** and **Key existing interfaces** sections and the task's **Interfaces** block. Implementers follow TDD as written: failing test → implement → pass → commit.
   - Dispatch a fresh Sonnet reviewer subagent against the task's diff (commit range). The reviewer checks: scope matches the brief, tests are real and passing, constraints held (stdlib-only backend, error envelope, no CORS, token on every write route, store-layer-only writes).
   - You resolve reviewer findings: Minor findings get logged in the ledger and deferred unless trivially safe; anything Critical/Important blocks the next task until fixed.
4. **Final review.** After Task 16, you personally do a whole-branch review against the spec's "Done when" (full run from the browser: import → spec → … → repair → finalize → export → download, plus overwrite-confirm on a deliberate double-approve), then run the full verification: `python3 -m pytest tests/ -q` and, from `web/`: `npm test && npm run build && npm run e2e`.

## Durable state discipline (non-negotiable)

You are responsible for keeping progress recoverable at all times. Assume the session can die at any moment (stop condition, network loss, context exhaustion). Therefore, **after every completed task — and before any pause — update and commit:**

1. **The plan file itself**: tick the completed `- [ ]` step checkboxes, and maintain an "## Execution status" block at the top of the plan (mirroring the Phase 1 plan's format): a table of Task | State | Commit, plus a one-line "To resume: continue with Task N" pointer.
2. **The ledger** `.superpowers/sdd/progress.md`: append one entry per task — commit range, review outcome, any deviations and why, any deferred Minor findings.
3. Commit these doc updates (e.g. `docs(plan): mark cockpit phase 2 task N complete`) so state lives in git, not in your context window.

On resume after any interruption: trust the ledger, the plan's status block, and `git log` over your own memory. Never re-dispatch a task the ledger marks complete.

## Precedents and guardrails (carried from Phase 1 — see the archived ledger)

- **Approved deviation classes** (apply without stopping, but record in the ledger): plan test code that trips the strict tsconfig, or Vitest mocks that need `beforeEach(() => vi.clearAllMocks())`. Fixes must be **test-file-only and behavior-preserving** (type annotations, mock resets, timeouts). Never change production code or assertions to make a test pass.
- Any other deviation from the plan's code — especially production code — stops the line: record where you are, then ask the human.
- If an implementer malfunctions (thrashes, never commits, writes a stale report): recover as the controller — verify the working tree yourself, run the tests, commit if genuinely green, write an accurate report, and run the normal reviewer (Phase 1 Task 12 precedent).
- Conventional commits (`feat(daemon):`, `feat(web):`, `test:`, `chore:`, `docs(plan):`).
- The plan's Task 10 Step 3 includes a temporary `ExportControls` stub that Task 11 replaces — do not flag that as scope creep.

## Stop conditions

Stop and ask the human when: a spec/plan contradiction surfaces, a reviewer finds a Critical issue you cannot fix within the task's scope, a production-code deviation seems required, or the e2e/full-suite verification fails in a way the plan does not anticipate. Before stopping, complete the durable-state updates above so the next session can resume from the ledger alone.
