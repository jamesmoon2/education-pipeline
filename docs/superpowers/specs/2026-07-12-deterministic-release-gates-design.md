# Deterministic Release Gates — Design

- **Date:** 2026-07-12
- **PRD item:** §10 "P0 — Establish deterministic release gates"
- **Predecessor:** model-plan-configuration milestone (delivered 2026-07-12);
  Wave-0 debt items inherited from
  [`2026-07-12-model-plan-configuration-post-milestone-audit.md`](2026-07-12-model-plan-configuration-post-milestone-audit.md) §7.

## Goal

Export provides a clear, reproducible quality report and cannot silently
package structurally invalid or privacy-leaking content (PRD §10 exit
criterion; PRD §11 release criterion #6).

## Current state (verified against `runs.py` / `guides/` at design time)

Most of the validator machinery exists: `guides/validation.py` defines ~45
structured rules with severity/blocking/waivable flags across schema,
privacy, link, outcome-coverage, interaction, and a11y categories;
`runs.py` validates at finalize and export, refuses export with unwaived
blocking findings, and writes draft/final report files; waivers are
hash-bound (`guides/waivers.py`) with a `POST
/v1/runs/{topic}/validation/{phase}/waivers` route and a cockpit
`ValidationFindingsPanel`.

The genuine gaps:

1. **Audit debt (scheduled into this milestone):** non-dict PUT bodies
   return 500 not 400; misspelled stage-override keys persist silently as a
   200 no-op; `_write_manifest` is a plain unserialized `write_text` with
   two writer classes (HTTP ingest thread, worker) and this milestone adds
   a third.
2. **Static/runtime checks are stubs:** `ValidationContext`
   (`render_succeeded`, `assets_match`, `controls_have_labels`,
   `heading_order_valid`) defaults every field to `True` and no caller
   computes them — the PRD's "browser-runtime checks" bullet is
   unimplemented.
3. **Findings are not attributed to the responsible stage**, and there is
   no explicit rerun-after-repair (revalidate) affordance.
4. **No quality-report artifact ships with the export**, and no
   reproducibility guarantee is tested.
5. **The CLI — the supported power-user surface — has no validation,
   waiver, or report commands.**

## Decisions (settled in brainstorming)

- **Runtime verification depth:** deterministic static checks only, stdlib
  only. No browser in the gate; the existing Playwright e2e suite remains
  the real-browser smoke layer.
- **Where checks compute:** against the assembled export document in
  memory. Export writes the exact string it checked, so the checked
  artifact and the shipped artifact are identical by construction.
- **Report deliverable:** a canonical, timestamp-free sidecar
  `<name>.report.json` next to the exported HTML, with its hash recorded
  in a manifest event.
- **CLI parity:** full — validate, list findings, waive/unwaive, print
  report; exit codes reflect gate state.

## Design

### Wave 0 — Hardening debt

1. **API hygiene:** non-dict JSON bodies on PUT/POST builders return 400,
   not 500, across the daemon. Unknown keys inside stage-override dicts are
   rejected with 400 (strict).
2. **Manifest write safety:** `_write_manifest` becomes atomic (temp file +
   `os.replace`, matching every other write in the repo) and serialized via
   a per-topic in-process lock in `RunStore`. All current and planned
   manifest writers are threads of the one daemon process; cross-process
   CLI concurrency remains out of scope and is documented as such.

### Wave 1 — Real static checks (engine)

New stdlib-only `guides/static_checks.py`:
`compute_static_checks(guide, assets)` assembles the export HTML in memory
(the same `assemble_guide_document` call export uses), parses it with
`html.parser`, and returns a computed `ValidationContext` plus the
assembled document:

- `render_succeeded` — assembly completes and structural markers are
  present;
- `assets_match` — SHA-256 of packaged `runtime.js`/`runtime.css` matches
  the contract's expected hashes;
- `controls_have_labels` — no interactive control without an accessible
  name;
- `heading_order_valid` — no skipped heading levels in rendered order.

`finalize_run` and `export_run` call `validate_guide` with the computed
context; export writes the assembled string it checked.

### Wave 2 — Stage attribution, rerun, sidecar report

- `Finding` gains a `stage` field from a static rule→stage map
  (schema/content/link → draft, outcome coverage → outline, privacy →
  draft, runtime/a11y → repair). The run status payload carries per-stage
  finding counts; the cockpit shows findings at the responsible stage and
  `ValidationFindingsPanel` links follow the map instead of the current
  draft/repair hardcode.
- **Rerun after repair:** expose revalidation (`validate_run`) as an
  explicit action in the API and cockpit so a repaired guide gets a fresh
  report without re-running finalize blind.
- **Sidecar quality report:** `export_run` writes a canonical,
  timestamp-free `<name>.report.json` next to the HTML — report version,
  guide SHA, runtime asset hashes, all findings, waiver result, gate
  decision — and records its SHA-256 in a manifest event. Reproducibility
  is a test: same guide + waivers ⇒ byte-identical report.

### Wave 3 — CLI parity

`validate`, `findings` (list/filter), `waive <finding-id> --reason`,
`unwaive`, and `report` subcommands, sharing the engine paths the daemon
uses. Exit codes reflect gate state (0 = gate open) so scripts can gate on
export.

### Wave 4 — Acceptance

- Playwright e2e: injected validation failure → finding shown at the
  responsible stage → repair → rerun → waive a residual waivable finding →
  export succeeds with the report.
- pytest: export refuses an unwaived blocker (structural and privacy
  fixtures); byte-identical report reproducibility; stale-waiver (hash
  mismatch) closes the gate.

## Error handling

Gate failures are explicit `ConfigError`s carrying the finding summary
(existing pattern). Waiver files whose `guide_sha256` no longer matches are
stale and never silently applied (existing behavior, newly tested at
export). Malformed waiver/report files fail loudly, never as an open gate.

## Non-goals

Browser-in-the-gate checks; model-based QA changes; personalization audit
(P1); re-opening the audit's remaining ACCEPT items.

## Testing

Strict TDD per repo convention. Each wave gates on the full four-suite run
(pytest, vitest, Playwright e2e, `npm run build`) **at wave close only**;
subsequent waves trust the recorded gate rather than re-running prior
suites at session start (see the implementation plan's handoff protocol).
