# Personalization Visible and Safe — Design

- **Date:** 2026-07-12
- **PRD item:** §10 "P1 — Make personalization visible and safe"
- **Predecessor:** deterministic-release-gates milestone
  ([`2026-07-12-deterministic-release-gates-design.md`](2026-07-12-deterministic-release-gates-design.md)).
  This spec targets the codebase after that milestone lands: it consumes
  stage-attributed findings, the explicit revalidate action, and the
  sidecar quality report. Waves 1–2 below depend only on today's main and
  may start in parallel with the gates milestone's tail; Wave 3 onward
  requires gates Wave 2 (stage attribution + sidecar report) to be closed.

## Goal

Learner personalization becomes a visible, inspectable contract: profiles
are created and edited in the cockpit without touching files, every
profile field has a known privacy classification that is actually
enforced at export, the final course carries a machine-checkable
goal-to-content trace plus a model audit of tailoring quality, and the
cockpit preview can show "why this course fits you" without any private
detail ever entering the exported guide (PRD §7.2, §6.2, §10 P1).

## Current state (verified at design time)

- `profiles.py` defines schema v1: ~30 fields in 5 groups plus a
  `privacy` block (`private_by_default`, `include_in_published_output`,
  `publishable_summary`). Whole-profile-private with one opt-in
  publishable string.
- Daemon/cockpit: profiles are list/get (raw TOML), import (paste TOML),
  and attach-to-topic only. No structured editing, no Profiles page.
- `guides/validation.py` has two privacy rules —
  `privacy.exact_private_value` (blocker) and
  `privacy.possible_identifier` (warning) — **but the `private_values`
  denylist is never supplied by any pipeline caller**; the blocker is
  inert in real runs. Closing that gap is in scope here.
- No personalization metadata exists in the guide schema; no audit
  stage; `SUPPORTED_STAGES = ("spec", "outline", "draft", "qa",
  "repair")`.

## Decisions (settled in brainstorming)

- **Sequencing:** design against the post-release-gates codebase.
- **Audit engine:** hybrid. Deterministic goal→content trace from
  required draft annotations; a model-powered audit judges quality.
  Model findings are advisory and never gate export.
- **Privacy model:** static application-owned sensitivity tiers, no
  profile schema migration. The single `publishable_summary` remains the
  only publishable profile content.
- **Fit view:** cockpit overlay only; nothing personalization-related is
  added to the exported guide document.
- **Profile UI:** sectioned form covering every schema field, with raw
  TOML import retained as the power-user path.
- **Audit placement:** new first-class `audit` stage appended after
  `repair`.

## Design

### 1. Privacy classification engine (`profiles.py`)

A static map classifies every profile field into a sensitivity tier:

- **high** — `professional_experience`, `sensitive_areas`,
  `accessibility_constraints`, `prior_education`, `prior_experience`,
  `metadata` values;
- **medium** — `preferred_examples`, `examples_to_avoid`,
  `adjacent_domains`, `learning_goals`,
  `learning_preferences.common_sticking_points`,
  `learning_preferences.attention_constraints`,
  `localization.jurisdiction`, `localization.locale`;
- **low** — everything else (pace, depth, tone, modalities, and other
  mechanical preferences).

New pure functions:

- `profile_field_sensitivity() -> Mapping[str, str]` — the full map,
  exposed via the API for UI badges. A test enumerates the dataclass
  fields against the map so a new schema field cannot ship
  unclassified.
- `profile_private_values(profile) -> tuple[str, ...]` — concrete
  string values of all medium- and high-tier fields; this is the
  denylist.

**Denylist wiring (fixes the inert blocker):** `finalize_run`,
`export_run`, and `validate_run` load the run's snapshotted profile and
pass `profile_private_values` into `validate_guide`, activating
`privacy.exact_private_value` and `privacy.possible_identifier` for
real runs. Findings carry only the existing SHA-256 fingerprint prefix;
private values never appear in findings, reports, or logs.

**Publishable-summary guard:** a deterministic check that
`publishable_summary` contains no high-tier field value. Surfaced (a) at
profile save time as an API warning the UI shows inline, and (b) as a
validation finding (`privacy.summary_contains_private_value`, warning,
waivable) whenever the summary would be included in an export.

### 2. Guide schema: goal annotations (deterministic trace)

Minor guide-schema version bump; all new fields optional so existing
guides remain valid.

- Course metadata gains `learner_goals`: the ordered goal texts
  snapshotted from the profile at spec time, so the trace stays stable
  if the profile later changes.
- Modules and outcomes gain optional `serves_goals`: references (by
  index) into `learner_goals`.
- Course metadata gains `goal_exclusions`: `{goal, reason}` records for
  goals deliberately out of scope.
- The draft and repair prompt contracts require the model to emit these
  annotations; the spec/outline contracts carry the goals forward so
  drafting has them.

New deterministic rules in `guides/validation.py` (category
`personalization.*`, **warning severity, waivable**, stage-mapped to
`draft` under the gates rule→stage map):

- `personalization.goal_uncovered` — a learner goal with no serving
  module/outcome and no exclusion record;
- `personalization.dangling_goal_ref` — `serves_goals` references a
  nonexistent goal;
- `personalization.no_annotations` — the profile declares goals but the
  guide carries no personalization metadata at all;
- `personalization.no_profile` — info-level: the run has no profile
  snapshot, personalization checks skipped (never a crash, and the leak
  check trivially passes because there is nothing to leak).

### 3. New `audit` pipeline stage

`SUPPORTED_STAGES` becomes
`("spec", "outline", "draft", "qa", "repair", "audit")`. The stage
follows every existing stage convention with no special cases: prompt
artifact on disk (profile prompt context + final guide + deterministic
trace), response saved to a known path, `StaleContentError` protection,
explicit approval, provider execution, per-stage model-plan
configuration, resume and retry. `audit` is *not* added to
`REASONING_STAGES`; recommended-plan guidance may assign a faster
model. Existing runs simply show `audit` as pending.

**Gate relationship:** finalize and export do **not** require audit
approval. The audit is advisory by design — model judgment never closes
the deterministic gate. A suspected private detail that is real is
independently caught by the deterministic denylist blocker.

**Response contract:** structured JSON, shape-validated
deterministically on ingest (same pattern as guide parsing): per-goal
verdicts (`served` with evidence references / `weak` / `missing` with
rationale), generic-section flags with document locations,
suspected-private-detail entries (fingerprints only, never values), and
an overall tailoring summary. A shape failure is a visible stage error
(edit or retry), never silent acceptance.

Approved audit findings are projected into the standard findings model
at **advisory** severity — they appear in `ValidationFindingsPanel`,
the sidecar quality report, and per-stage counts, but can never block
export and need no waivers.

### 4. Profiles API and cockpit Profiles page

Daemon routes (CLI gains matching subcommands — `profile show/edit
--from-file/duplicate` — sharing the same engine paths):

- `GET /v1/profiles/{id}` — extended with `parsed` (structured JSON of
  the validated profile), per-field sensitivity tiers, and the denylist
  *size* (never values).
- `PUT /v1/profiles/{id}` — create or update from structured JSON. The
  server renders canonical TOML, validates through
  `parse_learner_profile`, and writes atomically. Updates require the
  current content hash (stale-write protection matching response
  editing); the conflict response returns the fresh hash.
- `POST /v1/profiles/{id}/duplicate` — copy under a new id.

Cockpit **Profiles page** (new nav route): list with attached-topic
counts, create, edit, duplicate. The editor is a sectioned form —
Basics, Background, Goals & Examples, Learning Preferences,
Localization, Privacy & Publication — covering every schema field; raw
TOML import remains available. Each section shows its sensitivity badge
with a plain-language note on where the values travel (local prompts
only vs. may appear in export). The Privacy & Publication section
renders side by side: "what models see" (the actual
`render_profile_prompt_context` output) and "what an export may
contain" (the publishable summary, or explicitly *nothing*), with the
summary-leak warning inline before save.

### 5. "Why this course fits you" — preview overlay

A cockpit `PersonalizationPanel` alongside the existing guide preview,
rendered entirely from run artifacts (guide annotations + approved
audit response) — nothing is written into the guide document, so the
export cannot leak it by construction. Per learner goal it shows: the
serving modules/outcomes (click scrolls the preview frame to the
element), the audit verdict with evidence, exclusion reasons,
generic-section flags, and any unresolved `personalization.*`
findings. When the audit stage has not run, the panel shows the
deterministic trace only, labeled as such.

## Error handling

Existing patterns throughout: invalid profile writes raise
`ConfigError` (400 at the API, message names the field); stale profile
writes return 409 with the current hash; malformed audit JSON is a
stage error with the parse diagnostics; a missing profile snapshot
yields the `personalization.no_profile` info finding rather than a
crash or a silent pass. Private values never appear in errors, findings,
reports, or logs — fingerprints only.

## Non-goals

Per-field publishable flags or a profile schema migration; any
personalization content inside the exported guide (including a "course
fit" section); changes to the qa stage contract; blueprint-specific
personalization requirements (P1 blueprint milestone); interest-graph
or diagnostic-preflight features (PRD §14).

## Testing

Strict TDD; each wave gates on the full four-suite run (pytest, vitest,
Playwright e2e, `npm run build`) at wave close, per the wave-plan
playbook.

- **pytest:** end-to-end denylist wiring (a planted private value in a
  guide blocks export); tier-map completeness against the dataclass
  fields; goal-coverage and dangling-ref rules; exclusion records
  clearing `goal_uncovered`; audit response shape validation (valid,
  malformed, adversarial); profile JSON↔TOML round-trip
  canonicalization; stale-write conflicts; summary-leak guard; `audit`
  stage lifecycle (prompt, ingest, approve, resume).
- **vitest:** profile form validation and section rendering,
  sensitivity badges, prompt-context/export preview panes,
  `PersonalizationPanel` states (trace-only, with audit, no profile).
- **Playwright e2e:** create a profile in the form → attach → run to
  export with a seeded leak → export blocked → fix → export succeeds;
  fit-overlay goal click scrolls the preview; axe checks on the new
  pages.

**Rough wave shape** (detail belongs to the implementation plan):
W1 privacy engine + denylist wiring → W2 profiles API/UI → W3 schema
annotations + deterministic rules → W4 audit stage → W5 overlay +
acceptance. W1–W2 may start before the gates milestone closes; W3+
require gates Wave 2.
