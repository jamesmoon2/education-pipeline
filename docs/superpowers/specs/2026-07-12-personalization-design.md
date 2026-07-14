# Personalization Visible and Safe — Design

- **Date:** 2026-07-12
- **Revised:** 2026-07-13 after review against the completed release-gates milestone
- **PRD item:** §10 "P1 — Make personalization visible and safe"
- **Predecessor:** deterministic-release-gates milestone, delivered 2026-07-13
  ([`2026-07-12-deterministic-release-gates-design.md`](2026-07-12-deterministic-release-gates-design.md)).
  This spec consumes the shipped stage-attributed findings, explicit revalidate
  action, sidecar quality report, and attached-profile privacy wiring. All waves
  below design and implement against that delivered baseline.

## Goal

Learner personalization becomes a visible, inspectable contract: profiles are
created and edited in the cockpit without touching files; every profile field
has an application-owned sensitivity classification; publication permission is
enforced independently from that classification; the local final-course record
carries a machine-checkable goal-to-content trace plus a model audit of
tailoring quality; and the cockpit can show "why this course fits you" without
private detail entering the exported guide or its public quality report and
without local personalization annotations entering the exported guide, except
for the one explicitly opted-in publishable summary (PRD §7.2, §6.2, §10 P1).

## Current state (verified after the predecessor landed)

- `profiles.py` defines schema v1: approximately 30 fields in five groups plus
  a `privacy` block (`private_by_default`, `include_in_published_output`,
  `publishable_summary`). The profile is private by default; the summary is the
  only profile-authored content eligible for publication.
- Daemon/cockpit profiles are list/get (raw TOML), import (paste TOML), and
  attach-to-topic only. There is no structured editing or Profiles page.
- Release gates now load the run's attached profile snapshot and pass an
  implementer-selected free-text denylist into draft and final guide
  validation. `privacy.exact_private_value` is therefore active in real runs.
  The selection currently includes `target_learner`, education/experience,
  skill level, sensitive areas, and accessibility constraints, but it is not
  backed by a complete field-classification policy. This milestone replaces
  that selection without regressing the shipped refusal path.
- The guide source schema is exactly `1.0`; it has no goal annotations or local
  personalization trace. `SUPPORTED_STAGES` is
  `("spec", "outline", "draft", "qa", "repair")`.
- Findings support `blocker`, `error`, `warning`, and `info` severity and are
  stage-attributed across the five existing model stages. The export sidecar is
  canonical and timestamp-free for identical inputs.

## Decisions (settled)

- **Privacy has two independent axes:** sensitivity tier explains risk; an
  explicit publication rule decides what may ship. A low tier never silently
  makes a raw profile field publishable.
- **Publication boundary:** the publishable summary is the only profile-authored
  text eligible for export. Generic course properties may reflect low-risk
  mechanical preferences without attributing those properties to the learner.
- **Trace storage:** goal texts and the assembled personalization trace are
  local run artifacts. Guide source may carry opaque goal references needed to
  construct the trace, but the export projection removes every personalization
  field before HTML assembly.
- **Goal identity:** the application assigns stable opaque ids (`goal-001`,
  `goal-002`, ...) from the immutable profile snapshot. Models never invent,
  copy, or rewrite the authoritative goal set.
- **Audit engine:** hybrid. Deterministic validation proves trace integrity and
  goal coverage; a model judges quality across goals and other active profile
  facets. Model findings are nonblocking and never gate finalize or export.
- **Audit lifecycle:** `audit` is an optional model stage over the canonical
  final candidate after final validation. It participates in provider, model
  plan, approval, stale-content, resume, and retry conventions, but not in the
  required-stage `next_action` sequence.
- **Finding vocabulary:** audit projections use existing `warning` and `info`
  severities with `blocking=false` and `waivable=false`; this milestone does not
  introduce an `advisory` severity.
- **Fit view:** cockpit overlay only. It reads local trace and audit artifacts;
  no fit panel, goal text, audit narrative, or personalization annotation is
  added to the exported guide document.
- **Profile UI:** sectioned form covering every schema field, with raw TOML
  import retained as the power-user path.
- **Profile schema:** no profile-schema migration and no per-field publishable
  flags. Guide source schema gains a backward-compatible `1.1` reader/writer
  contract described below.

## Design

### 1. Privacy classification and publication engine (`profiles.py`)

A static leaf-path map classifies every profile field into a sensitivity tier.
The map uses JSON-style paths such as `learning_preferences.attention_constraints`
rather than classifying a nested dataclass as one field.

- **high** — `target_learner`, `professional_experience`, `sensitive_areas`,
  `accessibility_constraints`, `prior_education`, `prior_experience`, and all
  recursive `metadata.*` values;
- **medium** — `id`, `current_skill_level`, `preferred_examples`,
  `examples_to_avoid`, `adjacent_domains`, `learning_goals`,
  `learning_preferences.common_sticking_points`,
  `learning_preferences.attention_constraints`,
  `localization.jurisdiction`, and `localization.locale`;
- **low** — mechanical learning preferences and controls: math/reading level,
  pace, depth, time budget, tone, modalities, practice/feedback/review style,
  assessment styles, units, language register, schema version, and privacy
  control fields. `privacy.publishable_summary` is low-risk only as a
  publication candidate and remains subject to the summary guard below.

New pure functions:

- `profile_field_sensitivity() -> Mapping[str, str]` — the complete immutable
  leaf-path map exposed through the API for per-field UI badges. A test walks
  every dataclass leaf and the `metadata.*` wildcard so a new schema field
  cannot ship unclassified.
- `profile_private_values(profile) -> tuple[str, ...]` — normalized concrete
  string values eligible for exact leak detection. It recursively walks all
  high- and medium-tier fields, including nested metadata, excludes empty,
  generic, and too-short values using the validator's shared normalization
  policy, and never includes `publishable_summary` merely because that summary
  is present. Low-risk categorical/mechanical values are intentionally omitted
  from the exact denylist to avoid blocking ordinary course language such as
  "advanced" or "self-paced"; this omission is not publication permission for
  raw profile records.
- `profile_summary_warnings(profile) -> tuple[ProfileWarning, ...]` — returns
  safe, field-path-based warnings when an enabled publishable summary contains
  an exact high- or medium-tier value. Warning payloads contain field paths and
  fingerprints, never source values.

**Existing wiring becomes the regression baseline:** `finalize_run`,
`export_run`, and `validate_run` continue loading the run's snapshotted profile
and passing `profile_private_values` into validation. Wave 0 replaces the
existing `_private_profile_values` implementation with the shared engine; it
does not re-add a supposedly inert path. Draft and final validation remain
profile-sensitive and hash-bound waivers remain fail-closed.

**Publication enforcement:** an opted-in summary may be supplied to generation
and may appear in the public guide. If it overlaps a protected source value,
the inline profile warning appears before save and the normal
`privacy.exact_private_value` blocker still applies at validation; publication
requires the existing explicit, reason-bearing waiver. No protected value is
silently allowlisted merely because it was copied into the summary.

**Validation boundary:** privacy leak rules inspect the exact public guide
projection that HTML assembly will ship, not local-only goal annotations or
trace artifacts. The checked projection and exported projection are the same
object by construction. Run-aware validation receives explicit
`profile_present: bool`; an empty denylist is not used to infer profile
absence. Standalone `validate_guide` calls omit the run-only
`personalization.no_profile` finding.

Findings, report messages, API warnings, errors, and logs contain only field
paths, safe fixed text, and the existing SHA-256 fingerprint prefix. Private
values never appear in those surfaces.

### 2. Guide source schema 1.1 and the local deterministic trace

Guide **source** schema `1.1` adds optional local-only annotations:

- modules and outcomes gain `serves_goals: [goal_id, ...]`;
- course metadata gains `goal_exclusions: [{goal_id, reason}, ...]`.

Goal texts are not stored in guide source. At prompt-compilation time the
application derives the authoritative ordered mapping from the immutable
profile snapshot (`goal-001` → first goal, and so on) and presents that mapping
as private prompt context. Draft and repair prompts require only the opaque ids
in their guide JSON. Spec and outline prompts carry the private mapping forward
and explicitly address active personalization facets; they do not create a
second authoritative goal list.

After draft/final validation, the application deterministically writes
`reports/personalization-trace.json` with:

- trace schema version, guide SHA-256, and profile-snapshot SHA-256;
- the authoritative ordered `{goal_id, goal_text}` records;
- serving module/outcome ids for each goal;
- valid exclusion records;
- active non-goal facet ids used by the audit (`prior_knowledge`,
  `interests_examples`, `pacing`, `assessment_preferences`, and
  `accessibility` when corresponding profile data exists).

This trace contains private goal text, is local-only, and is never copied beside
an export. The public quality report may record only trace schema version, goal
counts, coverage counts, gate-safe finding ids, and a hash of a safe trace
projection containing opaque goal ids and serving element ids — never the hash
of the private trace bytes, goal texts, or exclusion reasons.

`public_guide_projection(guide)` removes `serves_goals` and `goal_exclusions`
before runtime document assembly. The exported embedded guide data therefore
contains no personalization metadata. Export tests inspect both the HTML and
the sidecar for every planted goal text, exclusion reason, and profile value.

Compatibility contract:

- readers accept source schema `1.0` and `1.1`;
- `1.0` normalizes with empty annotations and remains valid;
- new personalized guide prompts emit `1.1`;
- the runtime accepts both versions, while export always receives the stripped
  public projection;
- no in-place migration rewrites an existing `1.0` run.

New deterministic rules in `guides/validation.py` use category
`personalization.*`:

- `personalization.goal_uncovered` — warning, waivable: an authoritative goal
  has no serving module/outcome and no valid exclusion;
- `personalization.no_annotations` — warning, waivable: a profile declares
  goals but the guide carries no goal references or exclusions;
- `personalization.dangling_goal_ref` — error, blocking, non-waivable: a source
  annotation references a goal id not generated from the snapshot;
- `personalization.duplicate_goal_ref` — error, blocking, non-waivable: one
  annotation or exclusion repeats an id in a structurally ambiguous way;
- `personalization.unexpected_annotations` — warning, waivable: annotations are
  present on a run with no attached profile snapshot;
- `personalization.no_profile` — info, nonblocking, non-waivable: run-aware
  validation has no profile snapshot, so personalization checks are skipped.

All rules are stage-mapped to `draft`. An exclusion clears `goal_uncovered`
only when its id is authoritative and its reason is non-empty. Because the goal
set is application-generated and never model-authored, a model cannot rewrite
or omit the authoritative goals to manufacture complete coverage.

### 3. Optional `audit` model stage

Stage sets become conceptually distinct:

- `REQUIRED_STAGES = ("spec", "outline", "draft", "qa", "repair")`;
- `OPTIONAL_STAGES = ("audit",)`;
- `SUPPORTED_STAGES = REQUIRED_STAGES + OPTIONAL_STAGES` for direct stage,
  provider, and model-plan APIs.

`run_status` exposes audit state (`not_run`, normal stage states, or `stale`),
but the primary `next_action` sequence ignores an unrun or stale audit. Existing
runs therefore remain complete rather than acquiring a required pending step.
The cockpit and CLI expose an explicit **Run personalization audit** action once
final validation is current.

The audit prompt consumes a canonical final candidate built by parsing and
normalizing the approved repair response with the same canonicalizer used by
`finalize_run`; it does not require `final/guide.json` to have been written.
Its input manifest records guide SHA-256, profile-snapshot SHA-256, and trace
SHA-256. It otherwise follows existing prompt-file, response-file,
`StaleContentError`, explicit approval, provider execution, per-stage model-plan,
resume, and retry conventions. `audit` is not added to `REASONING_STAGES`.

An approved audit is current only while all three input hashes match. Editing
or reapproving repair content, replacing the run's profile snapshot, or
regenerating a different trace makes it stale. Audit may run before or after
finalize when the canonical guide hash is identical. Finalize and export never
require audit execution or approval.

**Model response contract:** shape-validated JSON containing:

- per-goal-id verdicts (`served`, `weak`, or `missing`), evidence module/outcome
  ids, and local rationale;
- per-active-facet verdicts for prior knowledge, interests/examples, pacing,
  assessment preferences, and accessibility, with evidence ids;
- generic-section flags with guide element locations and enumerated reason
  codes;
- suspected-private-detail flags with document location, category, and
  confidence — never a value or caller-supplied fingerprint;
- a local overall tailoring summary.

The application, not the model, computes fingerprints from referenced guide
locations. Shape errors and privacy-projection errors use safe diagnostics that
do not echo rejected strings. The raw audit response remains a private local run
artifact. Before projection, every model-authored string is checked against the
profile denylist. Model rationales and summaries are never copied into standard
findings or the public sidecar.

Approved audit results project only safe, deterministic findings: fixed
application messages, rule ids, goal/facet ids, guide element paths, and
application-computed fingerprints. They use existing `warning` or `info`
severity, `blocking=false`, `waivable=false`, and stage `audit`. They appear in
`ValidationFindingsPanel`, per-stage counts, and the export quality report but
can never close the deterministic gate.

The quality-report schema increments and adds an `audit` object containing
`state` (`not_run`, `current`, or `stale`), safe-audit-projection SHA-256 when
current, safe-trace-projection SHA-256, and the safe projected finding ids. Raw
audit-response and private-trace hashes remain in the local manifest only. A
stale audit is not projected as current evidence. The reproducibility invariant
becomes:

> same public guide projection + waivers + current approved audit projection
> (or the same explicit no-current-audit state) + runtime assets ⇒
> byte-identical HTML and sidecar bytes.

Approving or invalidating an audit after export marks the run's export status
stale and prompts re-export; existing files are never silently mutated.

### 4. Profiles API, CLI, and cockpit Profiles page

All structured API and CLI operations share new canonical profile serialization
and atomic `ProfileStore` methods. The serializer accepts only values representable
by the profile's TOML contract, rejects unknown keys at every nesting level,
orders fields deterministically, and hashes the exact canonical UTF-8 bytes
written to disk.

Daemon routes:

- `GET /v1/profiles/{id}` returns `{id, parsed, sensitivity,
  content_sha256, warnings, attached_topic_count}`. `sensitivity` is the
  complete leaf-path map; warnings never include source values. The denylist
  size is omitted because it does not help editing and can reveal profile
  composition.
- `PUT /v1/profiles/{id}` accepts `{profile, base_sha256}`. `profile.id` must
  equal the path id. Create requires the target to be absent and
  `base_sha256: null`; update requires the exact current hash. It returns 201
  for create or 200 for update with the canonical parsed value, fresh hash, and
  safe warnings. Wrong shape/unknown fields are 400; a stale hash is 409 with
  only the fresh hash; an existing target with a create precondition is 409.
- `POST /v1/profiles/{id}/duplicate` accepts `{new_id}`. The source must exist,
  the target must not, and the canonical copy replaces the embedded profile id
  before validation and one atomic write. It returns 201 with the new profile
  payload.

Raw TOML import remains available as the power-user path and delegates to the
same canonical validation/atomic-write engine. CLI gains matching `profile
show`, `profile edit --from-file`, and `profile duplicate` commands rather than
independent serialization logic.

Cockpit **Profiles page** (new nav route): list with snapshot attachment counts,
create, edit, and duplicate. Counts are derived from run profile snapshots whose
embedded profile id matches; editing a source profile never mutates those
snapshots. The editor is a sectioned form — Basics, Background, Goals &
Examples, Learning Preferences, Localization, Privacy & Publication — covering
every schema leaf. Each field, not merely each mixed-sensitivity section, shows
its tier badge and a plain-language note about model and publication boundaries.

The Privacy & Publication section renders side by side: "what models see" (the
actual `render_profile_prompt_context` output) and "what an export may contain"
(the publishable summary, or explicitly *nothing*). Summary warnings appear
inline before save and explain that an overlapping protected value will still
trigger the export gate.

### 5. "Why this course fits you" — preview overlay

A cockpit `PersonalizationPanel` appears alongside the existing guide preview.
It reads only current local artifacts: the profile snapshot, deterministic
personalization trace, and current approved audit projection. Per learner goal
it shows serving modules/outcomes (click scrolls the preview frame to the
element), audit verdict and local evidence, exclusion reasons, generic-section
flags, active-facet verdicts, and unresolved `personalization.*` findings.

When audit has not run or is stale, the panel shows the deterministic trace and
labels audit evidence as unavailable or stale. Missing profile and trace states
are explicit. The panel never writes back into guide source, the public guide
projection, HTML, or the export sidecar.

## Error handling

Existing patterns remain: invalid profile writes raise `ConfigError` (400 at
the API with a safe field path); stale profile writes return 409 with the fresh
hash; malformed audit JSON is a stage error with non-echoing parse diagnostics;
a missing profile snapshot yields `personalization.no_profile` only in
run-aware validation. A missing, malformed, or stale trace for a profiled guide
with goals is a deterministic integrity error and blocks finalize/export. A
missing, malformed, or stale audit fails closed for audit projection but never
turns optional model judgment into an export blocker. Trace integrity errors in
guide source remain deterministic blockers.

Private values may exist in local profile, prompt, trace, and raw audit-response
artifacts by design. They never appear in API errors, warnings, findings, logs,
the public quality report, or exported HTML, except an explicitly opted-in
publishable summary that passes or is deliberately waived through the existing
gate.

## Non-goals

Per-field publishable flags or a profile schema migration; personalization
metadata, goal text, trace artifacts, or audit narrative inside the exported
guide; making the optional audit a release gate; changing the existing `qa`
stage contract; blueprint-specific personalization requirements (P1 blueprint
milestone); interest-graph or diagnostic-preflight features (PRD §14).

## Testing

Strict TDD; each wave gates on the full four-suite run (pytest, vitest,
Playwright e2e, `npm run build`) at wave close, per the wave-plan playbook.

- **pytest:** preserve the shipped planted-private-value refusal path while
  replacing `_private_profile_values`; tier-map completeness across nested
  dataclass leaves; `target_learner` and recursive metadata protection; generic
  low-risk preference false-positive cases; explicit profile-presence context;
  summary-warning redaction; source `1.0`/`1.1` compatibility; public projection
  stripping; goal coverage, dangling/duplicate refs, exclusions, missing-trace
  refusal, and trace hash/content determinism; audit optional lifecycle,
  hash-based staleness,
  valid/malformed/adversarial response ingest, application-computed
  fingerprints, and safe projection; profile JSON↔canonical-TOML round trip,
  atomic create/update/duplicate, stale-write conflicts; quality-report
  reproducibility for no-audit/current-audit/stale-audit states.
- **vitest:** profile form validation and field-level badges, prompt-context and
  export-preview panes, summary warnings, optional audit controls, and
  `PersonalizationPanel` states (trace-only, current audit, stale audit, no
  profile).
- **Playwright e2e:** create a profile in the form → attach → run to export with
  a seeded protected-value leak → export blocked → fix → export succeeds;
  inspect HTML and sidecar to prove planted goal/profile/annotation strings are
  absent; run optional audit and re-export safe projected findings; fit-overlay
  goal click scrolls the preview; axe checks on all new pages and states.

**Rough wave shape** (detail belongs to the implementation plan): W0 rebase and
privacy-policy engine over the shipped wiring → W1 profiles API/CLI/UI → W2
guide-source 1.1 + local trace + public projection → W3 optional audit stage +
safe findings/report projection → W4 overlay + full acceptance. The predecessor
is complete, so no wave carries the former parallel-tail dependency.
