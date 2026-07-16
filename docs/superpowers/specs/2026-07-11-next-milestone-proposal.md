# Next Milestone Proposal — Finish Model-Plan Configuration in the Cockpit

- **Date:** 2026-07-11
- **Author:** Claude Code supervisor agent (Chunk 09).
- **Status:** Proposal for owner approval. Execution requires a separate
  authorization and its own supervisor prompt; nothing here is implemented.
- **Grounding:** PRD `docs/product-requirements.md` §6.4, §7.4, §10 (the
  unstarted "P0 — Finish model-plan configuration"), §11 release criteria #3,
  and the post-milestone audit
  `docs/superpowers/specs/2026-07-11-interactive-guide-v1-post-milestone-audit.md`.

## 1. Recommendation

Make **"Finish model-plan configuration"** the next milestone. It is the only
remaining **P0** roadmap item that is essentially unstarted in the cockpit, it
directly gates `v0.1` release criterion #3 ("accept recommended model settings
or select a model plan in the UI"), and the backend contract it needs already
exists — so this is primarily a surfacing (API + UI) milestone over a stable
engine, not net-new engine design. That makes it the highest-leverage next
step.

I recommend giving it a **thin, honest home in the cockpit**: a Settings
surface for provider availability + defaults and a per-stage plan editor
reachable from a run, plus the single most acute discoverability fix (a real
"New run" entry point that replaces the raw "paste TOML" empty state and shows
the effective model plan before execution, per PRD §6.3–§6.4). Deeper first-run
onboarding, course-library management, and blueprint pedagogy stay out of scope
and remain their own P1 milestones.

### Why this over the alternatives

- **vs. cockpit discoverability alone.** The empty-board/preview/read-only gaps
  are real (audit §4) but are the *symptoms* the PRD groups under "P1 —
  First-run and course-management experience." Model-plan configuration is a
  standalone **P0**; doing it lets us fix the most acute discoverability gap
  (creating a run and choosing a plan) as a byproduct, without committing to
  the full first-run milestone now.
- **vs. blueprint / course-brief depth.** That is explicitly **P1 —
  Blueprint-driven pedagogy** and depends on prompt/QA contract expansion that
  touches the frozen guide contract. It is larger, riskier, and lower on the
  PRD ladder than finishing an unstarted P0.
- **vs. remediating audit F1 (legacy `javascript:` links).** F1 is a real
  security defect but is scoped to the *legacy Markdown* path and is a small,
  well-understood fix. It should be folded in as a bounded hardening task
  (Wave 0 below) rather than owning a milestone.

## 2. Milestone goal and exit criterion

**Goal.** A user can configure and execute a mixed-provider run entirely from
the cockpit — pick "Use recommended models" or override provider/model/effort
per stage, see availability and warnings, and have the effective configuration
persisted and shown as provenance — while an advanced user can still edit the
underlying local TOML.

**Exit criterion (from PRD §10).** A user configures and executes a
mixed-provider run from the cockpit without editing TOML, and an advanced user
can still edit the underlying local configuration; the effective
provider/model/effort is recorded with the run and displayed.

## 3. Scope

- Read + expose provider availability (which local provider tools are
  detected) and the project model catalog/plan through `/v1`.
- Settings surface: view/edit global default provider/model/effort; "Use
  recommended" reset; show detected vs. unavailable providers with an
  explanation instead of a silent failure.
- Per-stage plan editor on a run: provider/model/effort per model-powered
  stage, "Use recommended" reset per stage, and a warning when a weak
  configuration is chosen for a reasoning-heavy stage (spec/outline/repair).
- Manual operation as a first-class selectable choice for any stage (not an
  error path), consistent with the existing manual copy/paste loop.
- Show the effective command/model/effort before running a stage and persist
  the effective configuration into the run's provenance; display it on the run.
- A "New run" entry point that replaces the empty-board "paste TOML" dead end
  with topic + profile selection and a model-plan review step (PRD §6.3–§6.4),
  keeping raw TOML import available for advanced users.
- Bounded security hardening carried from the audit: URL-scheme allowlist for
  the legacy Markdown renderer and a CSP on the legacy export + cockpit shell
  (audit F1); commit/clean the `.gitignore` drift (audit F2).

## 4. Non-goals

- Full first-run onboarding, workspace picker, and course-library management
  (filter/duplicate/archive/reveal-in-files) — remains PRD "P1 — First-run."
- Blueprint-specific prompt/QA contracts and section-level regeneration —
  remains PRD "P1 — Blueprint-driven pedagogy." No change to the frozen guide
  schema, runtime, validation, prompts, or the canonical fixture.
- Any new provider adapter beyond the existing Claude Code / Codex / manual set.
- Claiming exact model prices; only relative quality/speed/cost guidance.
- Profile creation/editing UI and personalization audit — PRD "P1 — Make
  personalization visible and safe."

## 5. Staged waves

- **Wave 0 — Audit hardening + baseline.** Fix audit F1 (legacy renderer scheme
  allowlist + CSP on legacy export and cockpit shell) and F2 (`.gitignore`),
  each test-first. Establishes a clean `git diff --check` and closes the one
  security defect before feature work. Independent of the rest.
- **Wave 1 — Read API for providers/catalog/plan.** `/v1` endpoints exposing
  provider availability, the model catalog, and the effective plan
  (global + per-stage). Backend + tests only; no engine change.
- **Wave 2 — Settings surface.** Cockpit Settings page: defaults, "Use
  recommended" reset, availability display and explanations. Depends on Wave 1.
- **Wave 3 — Per-stage plan editor + provenance.** Per-stage overrides with
  reset and weak-configuration warnings; write path persists effective
  config and surfaces it as run provenance; effective command/model/effort
  shown pre-run. Depends on Waves 1–2.
- **Wave 4 — New-run entry point.** Replace the empty-board dead end with a
  topic/profile + model-plan-review flow; keep TOML import for advanced users.
  Depends on Wave 3 (reuses the plan editor as the review step).
- **Wave 5 — Acceptance + closeout.** Mixed-provider run driven from the
  cockpit with no TOML editing; advanced-user TOML path still works; docs and
  PRD status updated; independent audit + next proposal.

## 6. Acceptance gates

- `python3 -m pytest`, `npm test`, `npm run build`, and `npm run e2e` all pass
  with recorded counts; no regression to the 404/79/38 baselines beyond
  intended additions.
- New e2e coverage: configure a per-stage override and a weak-config warning in
  the cockpit; drive a mixed-provider run (recommended + one override + one
  manual stage) end to end without editing TOML; confirm the effective plan is
  persisted and displayed as provenance.
- Regression: an advanced user editing the underlying TOML still takes effect
  and round-trips through the UI.
- Wave 0 gate: `render_html_body('[x](javascript:alert(1))')` yields no live
  `javascript:` href; legacy export and cockpit shell carry a CSP; a new test
  asserts each; `git diff --check` is clean.
- Frozen-surface guard: the guide schema, runtime assets, validation rules,
  prompt bytes, canonical fixture, and its normalized SHA-256
  (`99fde906…b07`) are unchanged unless a change is explicitly authorized.
- No private run/profile artifacts committed (CI leak guard stays green).

## 7. Risks

- **Provider availability detection is environment-specific.** Mitigation: test
  availability without sending course content (PRD §7.4); mock provider
  presence in tests; degrade to "unavailable, here's why" rather than error.
- **Scope creep into the full first-run/library milestone.** Mitigation: the
  New-run entry point (Wave 4) is deliberately minimal and reuses the plan
  editor; library management stays a non-goal.
- **Model catalog staleness.** Mitigation: keep the catalog file-driven and
  editable (PRD principle: never hard-code around one model name); the UI reads
  the catalog rather than embedding names.
- **Touching write/provenance paths risks the run contract.** Mitigation: TDD,
  additive provenance fields, and the frozen-surface guard; no change to stage
  ordering or approval gates.
- **Wave 0 CSP on the cockpit could break the same-origin legacy preview.**
  Mitigation: prefer moving legacy preview into a sandboxed iframe (as guide-v1
  already does) over a permissive CSP; covered by a test.

## 8. Sequencing note

Wave 0 is independent and can land first as a small hardening PR. Waves 1→4 are
strictly ordered (each depends on the previous); Wave 5 closes out. This keeps
the one security defect from riding along behind a larger feature and gives the
owner an early, isolated review unit.
