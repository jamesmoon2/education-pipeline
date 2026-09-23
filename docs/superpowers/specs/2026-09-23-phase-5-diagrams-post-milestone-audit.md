# Phase 5 Diagram Block — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-23. Opened and closed with the phase.
- **Source of truth:** the thread closeout log in
  [`docs/superpowers/plans/2026-09-23-phase-5-diagrams.md`](../plans/2026-09-23-phase-5-diagrams.md).
- **Design:** [`2026-09-23-diagram-block-design.md`](2026-09-23-diagram-block-design.md).
- **Purpose:** keep a record of the decisions and accepted limitations from
  the seven Phase 5 threads, for a later audit to check independently. This
  ledger is not that audit.

## Closeout disposition

The phase ran as seven map threads (T50–T56) plus one fix-up thread. The
fix-up updated the cockpit e2e fixtures after T52 made 1.2 the default for new
runs.

Every behaviour thread followed strict TDD. One Opus subagent wrote the failing
tests and a different Opus subagent made them pass. The manager reviewed diffs
and made the merge calls.

Parallel work:

- T52 (prompts, engine) and T53 (document assembler, runtime) ran in parallel
  worktrees. T53 merged first, so that a new 1.2 run could export.
- T54 followed T53, because both grow the same renderer module.

Mutations:

- 13 mutations were tried across T51–T55, and all were caught.
- T51: 3 mutations.
- T52 and T53: 2 each.
- T54: 2.
- T55: 1.
- T52's red writer also pinned an 80-SHA byte-identity matrix over every
  guide-v1 prompt at schema 1.0 and 1.1. It passed before and after green.

Two red writers checked their own tests against a throwaway implementation in
scratch before handing off:

- T51: all 314 tests passed against it.
- T53: the check caught two e2e cases that passed with nothing to check, and
  they were tightened.

| Gate | Baseline at open (`2a1aa50`) | At close |
| --- | --- | --- |
| pytest | 2201 passed, 1 skipped | 2619 passed, 1 skipped |
| vitest | 627 | 634 |
| Playwright guide specs | 103 | 130 |
| Playwright full suite | not run at open | see phase closeout |

Code under `education_pipeline/` and `web/src` changed by +1597 / −62
across 22 files, tests included. Sizes:

- `runtime.js` grew from 1991 to 2367 lines (+376, budget 450).
- `runtime.css` grew from 164 to 187 lines (+23, budget 30).
- The new pure module `guides/diagrams.py` is 245 lines.

## Decisions that departed from or refined the plan text

### Kind spelling and the block-type registry (T50)

- Kinds are snake_case (`concept_map`), because `kind` selects a data shape
  and a code path, the way a block `type` does.
- `BLOCK_TYPES` stays at the six v1.0 types, and `diagram` is gated on the
  schema version separately. `contract.py` reuses `BLOCK_TYPES` to check outline
  `interaction_types`, and a diagram is not an interaction.

### Extra limits (T50)

- `title` is limited to 120 characters and `caption` to 240.
- Every diagram string must be a single line (`diagram.multiline_text`).
- The plan's other limits stand as written.

### Goal-annotation prompt lines (plan decision 3, refined at T50)

The plan gated the goal lines on profile presence for every version. The spec
keeps 1.1 gated on version alone. Otherwise, a 1.1 run whose profile was later
detached would produce different prompt bytes, which would break the promise
that 1.1 prompts are byte-identical. Only 1.2 gates the goal lines on profile
presence. The manager confirmed this at T50 close.

### Decision 13: a draft cannot change its run's schema version (added at T50 review)

- **The gap.** Nothing compared a draft's `schema_version` with the run's
  pinned contract. Once 1.2 existed, a 1.0 or 1.1 run could have approved a
  draft full of diagrams.
- **The rule, shipped in T52.** Approving a draft or an unscoped repair is
  refused when the response declares a *supported* version other than the
  run's.
- **What the rule leaves alone.** An unsupported version (for example
  `"2.0"`) or an unparseable response is still left to validation, because
  two existing tests deliberately approve such a repair.
- **Scoped repairs.** Scoped repair fragments carry no version. A diagram in
  one is refused by the splice's strict re-parse against a pre-1.2 base.

### Diagram-local ids (plan decision 6)

- Node, event, item and criterion ids are local to their diagram.
- `canonical._collect_ids` claims only the diagram's own block id. Otherwise,
  per-module assembly would report false collisions between modules that both
  have a node called `start`.
- Schema spec §2 now records the exception.

### The 1.2 default changed 84 existing tests (T52) and 8 e2e flows (fix-up)

- **pytest.** Nearly every change was a spec approval whose pasted contract
  said 1.0 or 1.1. These are fixed by pinning the creation helpers to the old
  contract, as listed in the spec's Migration section.
- **e2e.** Eight cockpit flows failed after the merge; all eight passed at
  `2a1aa50`.
  - **Cause.** The cockpit has no way to pin a run's contract, so each flow's
    new run defaulted to 1.2, and its pasted 1.0/1.1 spec contract was refused.
  - **Fix.** The e2e fixtures now re-declare 1.2 before pasting. The shared
    guide fixtures are unchanged, because pytest uses them too.
- **Consequence for users.** A new run's spec response must declare
  `"guide_schema_version": "1.2"`, and its prompts already say so. A hand-made
  1.0 spec pasted into a new run is refused with the existing contract-mismatch
  message.

### Cockpit bug found and fixed (T55)

- **Bug.** `ResponseEditor` treated only the `version=1.0` guide content type
  as a guide, so 1.1 runs had lost the guide preview before this phase.
- **Fix.** The check is now one generic prefix test on
  `application/vnd.education-pipeline.guide+json;`.

### Static checks (T55)

A heading anywhere inside a `<figure>` fails the existing heading-order check.
The check tracks figure depth. No new finding code was added, as spec §11 says.

## Accepted limitations

- **Edge crossings.** The flow and concept-map layouts do not route around
  nodes. A long flow edge can cross a node box, and the spec's open question 6
  accepts this for this version.
- **Concept map with few ring nodes.** The fixed-size layout leaves empty
  space. The `viewBox` is set by the ring radius formula, so a concept map with
  three ring nodes leaves the lower third of the drawing empty.
- **Edge-label wrapping.** Labels wrap by character count (16 per line, at
  most 2 lines), so a phrase such as "overshoots with a" can split awkwardly.
  Seen in the fixture's concept map during the manager's visual check.
- **Per-engine determinism.** Layout bytes are deterministic per browser
  engine. The e2e pins are Chromium-only.
- **30-second reading time.** Reading time counts 30 s per diagram, which is a
  guess. The example's estimate moved from 8.41 to 9.94 minutes against a
  declared 15, with no warning.
- **"Never" still allows diagrams.** A `diagram_frequency` of "none" or "never"
  maps to the "few diagrams" line rather than forbidding diagrams. No rule
  demands a diagram anywhere.
- **No diagram finding display.** The cockpit has no diagram-specific display
  for `diagram.*` findings. They appear like any other finding at their JSON
  path.
- **No screenshots refreshed.** No script regenerates the docs screenshots from
  the example, and `docs/screenshots` come from a demo workspace.

## Verification by the manager

The manager rendered all four kinds and checked them by eye in light and dark
themes:

- the example's flow (with its feedback loop) and comparison;
- the fixture's concept map and timeline.

This was a headless Chromium check against the committed export and the
assembled fixture. The flow's back edge draws as a dashed right-hand curve with
its label. The comparison is a real table with scoped headers. The timeline
alternates labels above and below the axis.
