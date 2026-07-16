# Running Multi-Hour AI Coding Plans Unattended: A Deterministic Conductor for Wave-Based Agent Workflows

*Draft for X / LinkedIn. Placeholder to fill before posting: [FIRST-RUN STATS].*

---

## Abstract

I develop software with a wave-based agent workflow: a frontier model writes a spec, then an implementation plan structured as sequential "waves" of TDD tasks, and each wave executes in a fresh agent session with a model and reasoning-effort level prescribed per wave. It works — but it kept me chained to my desk, because a human (me) had to sit between waves: clear the context window, paste the next kickoff prompt, pick the model, and watch token spend against a 5-hour usage window. This post describes wave-runner, a ~600-line dependency-free Python conductor that removes the human from that loop without removing the structure. The interesting parts aren't the loop — they're the handoff contract between sessions, and a three-layer strategy for surviving usage-limit exhaustion mid-plan without burning tokens on redone work.

## The problem

Long agentic coding sessions degrade. Context windows fill with stale exploration, attention gets diluted, and cost compounds because every turn re-reads everything before it. My mitigation has been architectural rather than heroic: plans are divided into waves, each wave runs in a brand-new session with a "manager" agent that dispatches fresh implementer subagents per task, and the only thing that crosses the wave boundary is a Wave Log — a table in the plan document recording what closed, what the test gate said, and what the next manager must know. No session ever inherits another session's context. The plan document is the memory.

This design had one dependency I'd been ignoring: me. Between every wave, I performed four mechanical actions — clear context, paste a kickoff prompt (printed by the previous wave's manager), select the prescribed model and effort level, and eyeball my remaining usage budget. None of these required judgment. All of them required presence. A five-wave plan meant five interventions spread across a workday, which meant the workday was mine to lose.

There's a second, sneakier problem: subscription usage limits reset on a rolling 5-hour window. An unattended run that hits the limit mid-wave doesn't just pause — a naive retry re-derives everything the dead session knew, and a 250k-token session that died one task from done becomes 250k tokens of pure waste.

## What exists, and what doesn't

The primitives are all supported: headless mode (`claude -p`), `--resume` by session ID, per-session `--model` and `--effort`, machine-readable `--output-format stream-json`. What doesn't exist is the chaining: nothing sequences fresh sessions through an artifact, and nothing handles limit exhaustion in headless mode — a session that hits the wall simply fails. The gap is small enough that the right answer is a script, not a framework. Notably, I chose a *deterministic* conductor over an "orchestrator agent": the thing launching sessions costs zero tokens, cannot hallucinate, and is trivially debuggable. Judgment lives inside the waves, where it belongs.

## Design

**The handoff contract.** Each wave manager's final message must be exactly one JSON object: wave number, status (`closed` / `blocked` / `parked`), test-gate counts, and the recommended model + effort for the next wave. With stream-json output, that lands in the conductor's stdout as a structured event — no parsing of prose, no scraping of markdown for control flow. The plan document and its Wave Log stay exactly what they were: the human-readable record, and the recovery source of truth if a session dies before it can emit the JSON.

**Trust, but verify.** The conductor doesn't believe `"closed"` on its word. It cheaply cross-checks that the plan document was actually committed during the wave and that the Wave Log row exists. It never re-runs tests — gates are the manager's job — but a manager that *says* it closed without leaving the paper trail is treated as an anomaly, and the run halts.

**Three-layer budget survival.** This is the part I'd argue is genuinely reusable thinking:

1. *Cheap-recovery selection.* When a session dies at the limit, the conductor inspects git. If task commits or checkbox ticks advanced since wave start, the wave died *between* tasks — relaunch fresh, and the new session needs only the plan document, not the dead session's transcript. Only when zero progress was checkpointed does it pay for `--resume`, re-ingesting the transcript once (a cache write) to preserve mid-task reasoning. The principle: re-reading is roughly an order of magnitude cheaper than re-doing, and often you don't even need to re-read.
2. *Mandatory checkpointing.* Every task ends with a commit and a ticked checkbox in the plan document. This isn't hygiene — it's what makes layer 1's "fresh relaunch" both cheap and correct. The plan document is a write-ahead log.
3. *A pre-task headroom gate.* Before dispatching each task, the manager asks a tiny script how much of the usage window remains. If the answer is "less than about one task," it checkpoints, emits `parked`, and exits at a clean boundary — so the expensive recovery paths rarely fire at all. The gate fails open: if headroom can't be measured, work proceeds and layer 1 catches the miss.

**Unattended-hardening.** The boring failures are the ones that actually kill an 8-hour run, so: a liveness watchdog kills any session silent for 30 minutes; pre-flight checks refuse to start on a dirty tree, wrong branch, or leftover test processes; the whole thing runs under `caffeinate`; every wave close pushes a phone notification with gate counts and cumulative spend; and any anomaly — a blocked wave, a malformed final message, a second failure after one recovery — halts the entire run rather than improvising. One retry, then stop and tell the human. An autonomous system's most important feature is a crisp definition of when it gives up.

**Permissions.** The sessions run with auto-approval for low-risk actions only; in headless mode, anything riskier is denied rather than silently allowed, and the project allowlist is calibrated during one supervised first run. Failing closed is the correct default for a robot with commit access.

## Results

[FIRST-RUN STATS: plan name, wave count, wall-clock, sessions launched, limit hits survived, cost/usage, human interventions = 0.]

## Takeaways

1. **Make the artifact the memory.** Fresh context per phase beats one long session, but only if the handoff artifact is disciplined enough that a cold session can resume from it alone.
2. **Structured final messages are an API.** One JSON object per session turns "AI workflow" into "process you can supervise with 600 lines of stdlib Python."
3. **Budget for the limit, don't pray around it.** Checkpoint at task granularity, choose the cheapest recovery mode from evidence, and park before you crash.
4. **Determinism at the boundary, intelligence inside.** The conductor is dumb on purpose. Every token it doesn't spend is a token the actual work gets.

Everything is TDD'd against a fake `claude` executable — the test suite simulates limit hits, stalls, parks, and malformed handoffs without spending a token. Code, plan-format contract, and operator guide: https://github.com/jamesmoon2/education-pipeline.
