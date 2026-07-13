# Autonomous Wave Runner — Design

**Date:** 2026-07-13
**Status:** Approved for planning

## Problem

Wave plans (see `docs/superpowers/wave-plan-playbook.md`) currently require a
human between waves: clear context, paste the kickoff prompt, pick the
manager model/effort, and pace token spend against the 5-hour usage window.
The human adds no judgment at these points as a matter of practice — the plan
prescribes everything. Goal: run an entire plan unattended on the local
machine without losing fresh-context-per-wave, per-wave model/effort control,
or the test gates, and without a mid-plan stall when the usage limit is hit.

## Decisions made during brainstorming

- **Substrate:** local machine (test gates need the local repo, daemon, and
  Playwright).
- **Conductor:** a deterministic script, not a Claude session — zero token
  overhead, fully debuggable, stdlib-only.
- **Budget:** three layers — recovery-on-reset, per-task checkpoints, and a
  pre-task headroom gate (all three approved).
- **Failures:** halt + notify after one retry. Never doom-loop, never skip a
  wave and continue.
- **Not reinventing a built-in:** headless mode, `--resume`, `--model`,
  `--effort`, `--session-id`, `--output-format json`, and `--max-budget-usd`
  are the supported primitives; no built-in feature chains fresh sessions or
  paces the usage window. The Agent SDK is a mechanical migration target if
  the CLI runner ever outgrows subprocess-and-JSON; not needed for v1.

## Components

### 1. `tools/wave_runner.py` (new, stdlib-only)

Input: one or more plan paths (multiple plans run sequentially). Loop per
plan:

1. Parse the plan doc for the first unclosed wave and the current
   model/effort recommendation (fallback when no final-message JSON exists,
   e.g. first wave or crash recovery).
2. **Synthesize the kickoff prompt** from the playbook template (plan path +
   wave number + status-dependent preamble, e.g. "doc shows tasks 1–3
   done"). Under the runner, managers no longer print kickoff prompts —
   the wave-close checklist's print step applies only to human-driven runs.
3. Generate a session UUID and launch from the repo root:

   ```
   claude -p "<kickoff prompt>" --session-id <uuid> --model <m> --effort <e> \
     --output-format stream-json --permission-mode auto \
     --max-budget-usd <cap>
   ```

   **Permission posture:** `auto`, not `bypassPermissions`. In headless mode
   anything `auto` would prompt about is *denied* instead — the safe failure
   direction. The project allowlist in `.claude/settings.json` is the
   pressure valve: the supervised first run doubles as allowlist
   calibration (each denial that blocks a wave gets a rule added).
   `bypassPermissions` remains a documented last-resort override.

4. **Liveness watchdog:** the runner consumes the stream-json output; no
   output for N minutes (default 30, configurable) means the session is
   stalled → kill it and route into the recovery path. Streamed events are
   also appended to a per-wave log file for postmortems.
5. Interpret the outcome (see Control channel) and either advance, recover,
   park, or halt.
6. After the final wave: notify with the milestone summary.

**Pre-flight checks (before wave 1, hard-fail if any miss):** clean working
tree (tracked files only — `--untracked-files=no`; stray untracked files
must not kill an unattended run), expected branch, `claude` authenticated, no stray daemon/Playwright
processes from a previous run, adequate disk space. The runner records the
plan-path HEAD SHA at each wave start for trust-but-verify. The runner is
invoked under `caffeinate -is` (wrapper script or documented invocation) so
the machine cannot sleep mid-run.

State: `wave-runner-status.json` next to the plan (gitignored) records the
current wave, session UUID, attempt count, and last outcome — enough to
resume the runner itself after a machine reboot.

### 2. Control channel: final-message JSON contract

The kickoff prompt template (playbook amendment) requires the manager's
final message to be exactly:

```json
{"wave": N, "status": "closed" | "blocked" | "parked",
 "gate": {"pytest": n, "vitest": n, "e2e": n},
 "next_wave": N+1 | null,
 "next_model": "opus" | "fable" | "sonnet",
 "next_effort": "low" | "medium" | "high" | "xhigh" | "max",
 "notes": "one line for the next manager / the human"}
```

With stream-json output this arrives in the final `result` event — no
markdown parsing for control flow. The plan doc + Wave Log remain
the human-readable handoff and the recovery source of truth when a session
dies before emitting JSON.

### 3. Trust-but-verify wave close

On `"closed"`, the runner cross-checks cheaply before advancing:

- the plan doc was committed since the wave-start SHA recorded by the
  runner (commit-graph comparison, not wall-clock `--since`), and
- the Wave Log row for wave N exists in the doc.

It never re-runs tests (per the playbook, the gate is the manager's job).
Mismatch → anomaly path.

### 4. Budget handling (three layers)

**Layer 1 — recovery on limit-hit.** Detected via the JSON error result or
nonzero exit carrying the limit message; because a limit death may emit no
result event at all, the session supervisor keeps a tail of the last output
lines and limit detection scans both. Parse the reset time if present;
otherwise retry on a capped backoff (every 20 min). Recovery picks the
cheaper of two modes by inspecting the plan doc/git:

- **Fresh relaunch** (preferred) when task commits/checkbox ticks advanced
  since wave start — the wave died *between* tasks, so a new session reading
  only the plan doc ("continue Wave N; doc shows tasks 1–3 done") is far
  cheaper than replaying the transcript.
- **`--resume <uuid>`** only when no checkpoint advanced — the wave died
  mid-task and the manager's in-context state (review findings, partial
  reasoning) is worth the one-time uncached re-read of the transcript.
  Accepted cost: the full transcript is reprocessed as a cache write; still
  ~an order of magnitude cheaper than redoing the work.

**Layer 2 — per-task checkpoints.** Playbook amendment: ticking the task
checkbox and committing after every task is mandatory, not customary. This
is what makes fresh relaunch cheap and correct.

**Park-loop bound:** consecutive parks are capped (default 15, ≈ one full
5-hour window at the 20-minute poll interval). Past the cap the runner
halts + notifies — endless low-headroom churn means something is
mis-measured, and each park cycle burns a session startup.

**Wait visibility:** entering any wait (limit reset, park poll) sends a
notification stating why and until when, so a silent multi-hour sleep is
distinguishable from a hang.

**Layer 3 — pre-task headroom gate.** `tools/headroom.py`: prints remaining
usage-window capacity. The wave protocol adds: before dispatching each task,
the manager runs it; if headroom < ~one task's estimated spend, checkpoint
the doc, emit `"status": "parked"`, and exit cleanly. The runner sleeps
until reset, then relaunches fresh (a park is by construction a clean
boundary). **Open question (spike task in the plan):** measurement source —
the OAuth usage endpoint behind `/usage`, or transcript-based accounting
(ccusage-style). The gate degrades gracefully: if `headroom.py` can't
measure, it reports "unknown" and the manager proceeds (Layer 1 catches the
miss).

`--max-budget-usd` per wave is a generous circuit breaker against runaways,
not a pacer. **Verify at build time:** whether it is meaningful under
subscription auth (headless may report $0.00); if not, the liveness
watchdog plus anomaly halting are the runaway bounds.

### 5. Failure handling

**Progress notifications (success path):** every wave close sends a
notification carrying the gate counts, the manager's `notes` line, and
cumulative usage/cost accumulated from the session results — the runner
replaces the spend-monitoring the human used to do by sitting there.

Anomaly = non-JSON final message, `"blocked"`, failed trust-but-verify,
liveness-watchdog kill after recovery was already attempted, or a second
failure after one recovery attempt. On anomaly the runner:

1. writes diagnosis + exact manual-resume instructions into
   `wave-runner-status.json`,
2. notifies (macOS `osascript` notification + one `curl` to a push channel,
   e.g. ntfy.sh; channel configurable), and
3. halts the whole run. Max one retry per wave; waves are dependent, so no
   skip-and-continue.

## Testing

`tests/test_wave_runner.py` with a fake `claude` executable (stub script
selected via env var) simulating: clean close → advance; limit-hit →
fresh-relaunch recovery; limit-hit → resume recovery; parked → sleep +
relaunch; blocked → halt + notify; malformed JSON → halt; trust-but-verify
mismatch → halt; stalled output → watchdog kill + recovery; pre-flight
failures → refuse to start; multi-plan sequencing. No real tokens in tests. First
real-world run: a low-stakes plan supervised by the human.

## Open-source packaging

The runner ships as a standalone public repo (working name: `wave-runner`)
so practitioners can adopt it without this codebase:

- Developed here under `tools/` with the full TDD harness; the final wave
  **extracts** `tools/waverunner/`, `tools/wave_runner.py`,
  `tools/headroom.py`, `tools/run_waves.sh`, the tests, and the fake-claude
  harness into a self-contained export directory with `pyproject.toml`
  (pytest as the only dev dependency), MIT `LICENSE`, a GitHub Actions
  pytest workflow, and a README documenting the plan-format contract (wave
  headings, Wave Log, manager lines, checkbox discipline, final-message
  JSON) — the contract *is* the product; the runner is useless without it.
- Nothing repo-specific may survive extraction: pre-flight process
  patterns are a parameter (this repo passes its daemon/Playwright
  patterns), and the kickoff template's superpowers-skill references are
  documented in the README as an editable convention.
- **Publishing (creating the public GitHub repo and pushing) is a human
  step**, listed in the plan but never executed by the runner or a wave
  manager autonomously.

## Out of scope (v1)

- Parallel plan execution (needs worktree isolation + budget arbitration).
- Cloud/scheduled execution.
- Agent SDK migration.
- Automatic triage sessions on anomaly (halt + notify chosen instead).

## Scalability

Plan-agnostic by construction: control flow comes from the final-message
JSON contract, not plan-specific parsing, so any playbook-conformant plan of
any wave count works, and plans queue sequentially. The binding constraint
is the usage window, not the runner.
