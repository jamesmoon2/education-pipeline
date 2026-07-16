# Wave-Plan Playbook

How implementation plans in this repo are structured and executed. Every plan
generated from a spec in `docs/superpowers/specs/` follows this pattern; the
reference example is
[`plans/2026-07-12-deterministic-release-gates.md`](plans/2026-07-12-deterministic-release-gates.md).

## Shape of a plan

1. Standard header (goal, architecture, tech stack, **Global Constraints**).
2. A **Wave Protocol** section containing the manager instructions below,
   verbatim, plus a **Wave Log** table (one row per wave: status, commits,
   per-suite counts, notes for the next wave) seeded with the baseline suite
   counts at plan time.
3. Tasks grouped into waves (0..N). Wave 0 absorbs the previous milestone
   audit's scheduled debt. The final wave is acceptance + docs closeout.
4. Each wave ends with a "Wave N close" checkbox pointing at the wave-close
   checklist, plus a *suggested* next-wave manager recommendation the closing
   manager may override with judgment.

## Execution model

- Each wave is **one independent session** with a **fresh manager agent**
  running `superpowers:subagent-driven-development` (fresh implementer
  subagent per task, per-task review). The human clears the context window
  between waves and pastes the kickoff prompt printed by the previous wave.
- **Trust the Wave Log; never retest closed waves.** A wave closes on a full
  test gate (all suites) recorded in the Wave Log; the next wave treats that
  record as canonical truth and starts dispatching immediately — no
  opening-ceremony suite runs, no re-verification of prior diffs. Tasks still
  run their own narrow test files during TDD.
- **The manager maintains the plan document itself** (token spend lives in
  the doc, not in re-derived context): tick checkboxes as tasks complete,
  fill the Wave Log row at close, and fix any later-wave instruction the
  current wave invalidated.

## Wave-close checklist (manager, personally, in order)

1. Run the full test gate once; drive to green.
2. Update the plan document (checkboxes, Wave Log row, downstream
   corrections). The Wave Log row is the only handoff artifact — write it so
   the next manager needs nothing else.
3. Commit the plan-document update.
4. **Print to the terminal for the human:**
   - the recommended **manager model for the next wave** (Opus or Fable) and
     **effort level**, with a one-sentence rationale tied to that wave's
     difficulty;
   - the **verbatim kickoff prompt** for the next wave.
5. Stop. Never start the next wave in the same session.

## Kickoff prompt template

```
Read <plan path> and execute Wave N using superpowers:subagent-driven-development.
The Wave Log records all prior waves' gates — treat it as canonical truth and do
NOT re-run or re-verify prior waves' tests before starting. Dispatch Wave N's
tasks per the plan, then run the wave-close checklist in the Wave Protocol
section (test gate, update the plan doc, commit, print the next wave's manager
recommendation and kickoff prompt).
```

The final wave prints a milestone summary and a post-milestone-audit
recommendation instead of a kickoff prompt.
