# Blueprint-Driven Pedagogy — Design

- **Date:** 2026-07-16
- **Status:** Proposed design, pending owner approval and implementation plan
- **PRD item:** §10 "P1 — Blueprint-driven pedagogy" (also §6.3, §7.3, §7.5,
  §7.7, and open question 6 in §15)
- **Predecessor:** personalization milestone, delivered 2026-07-16
  ([`2026-07-12-personalization-design.md`](2026-07-12-personalization-design.md)).
  This spec consumes the shipped stage-attributed findings, the export sidecar
  quality report, the run's attached profile snapshot in release gates, and the
  guide source `1.0`/`1.1` reader/writer contracts.

## Goal

Blueprint stops being a decorative string and becomes an application-owned
pedagogical contract: the user selects (or accepts a recommended) blueprint
before generation; that choice measurably changes every stage prompt and the
model-QA rubric; deterministic gates enforce blueprint-required interactions,
time-budget fit, and difficulty calibration; and a single weak module can be
regenerated in place without discarding the approved rest of the draft
(PRD §10 P1 bullets, §7.3).

**Exit criterion.** For the same topic and profile, two different blueprints
produce visibly different spec/outline/draft/QA prompts and different
deterministic requirements; a run whose draft omits a blueprint-required
interaction or blows the stated time budget surfaces findings at the
responsible stage; and a QA-flagged module is repaired via section-level
regeneration while every other module's bytes are preserved.

## Current state (verified 2026-07-16)

- `blueprint` is a free-text non-empty string in the spec contract
  (`guides/contract.py`, `_SPEC_CONTRACT_FIELDS`) and in guide course metadata
  (`guides/model.py`, `guides/parse.py`). No registry, no known-id validation,
  no behavior attached. The model invents the value in the spec-stage contract
  block; the user never chooses it.
- `Topic` (`topics.py`, schema v1) has no `blueprint` and no time-budget
  field; the cockpit has no blueprint UI at all (zero matches in `web/src`).
- Stage prompts (`prompts.py`) are blueprint-agnostic: one fixed set of
  header/output/quality lines per stage.
- `required_interactions` is a model-chosen non-empty subset of
  `REQUIRED_INTERACTION_TYPES = {knowledge_check, worked_reveal, scenario,
  reflection}`; presence is enforced downstream by the existing
  `interaction.missing_required_type` and `module.no_interaction` rules.
- Time checks: only `time.module_total_mismatch` (module minutes must sum to
  the course estimate). Nothing compares the estimate to what the learner or
  brief asked for.
- Difficulty: `course.difficulty` is validated as one of `introductory`,
  `intermediate`, `advanced`, `mixed` and otherwise unused. The profile
  snapshot (already loaded by release gates) carries `current_skill_level`,
  `time_budget`, and `attention_constraints`.
- Repair is whole-guide only: the repair prompt embeds the full draft and the
  model must return one complete guide JSON. `SUPPORTED_STAGES` is
  `("spec", "outline", "draft", "qa", "repair")` plus the optional `audit`
  stage outside the required sequence.
- Findings infrastructure: `Rule(severity, blocking, waivable, remediation,
  stage)` table in `guides/validation.py`, stage-attributed findings, waiver
  ledger, canonical export sidecar.

## Decisions (settled by this spec, subject to owner review)

- **The application owns the blueprint set.** Six registered blueprints ship
  in maintained source code (not user-editable config): the PRD §7.3 list.
  Blueprint selection is configuration, not a forked runtime — one engine,
  one schema, one runtime, parameterized prompts and gates.
- **The user picks the blueprint; the model echoes it.** Blueprint moves from
  a model-invented contract value to run configuration chosen at course
  creation (recommended default, user-overridable). The spec-stage contract
  must echo the configured blueprint exactly; a mismatch is a contract error,
  same as a bad `guide_schema_version`.
- **No guide-schema bump and no spec-contract field changes.** The guide
  `course.blueprint` field and the contract's existing fields are sufficient.
  Time budget and difficulty calibration read from the run's topic and
  attached profile snapshot at validation time; nothing new enters exported
  guide JSON. The frozen guide schema, runtime assets, and block vocabulary
  are untouched.
- **Blueprint minimums flow through the existing interaction machinery.** A
  blueprint declares a minimum `required_interactions` set; contract parsing
  rejects a spec contract whose `required_interactions` is not a superset of
  it. Downstream enforcement then rides the existing
  `interaction.missing_required_type` rule unchanged.
- **Calibration findings warn, they do not block.** Time-budget and
  difficulty findings are `warning`/`info`, nonblocking and non-waivable,
  because they are heuristics over declared intent, not structural defects.
  Blueprint-required interaction gaps stay blocking-but-waivable exactly as
  the existing rule behaves today.
- **Section-level regeneration is a scoped variant of the repair stage,** not
  a new stage. `SUPPORTED_STAGES`, approval gates, resume semantics, and
  stale-content protection are unchanged; the scope is recorded with the
  repair artifact. v1 scope granularity is one module ("one weak lesson"),
  not individual sections or blocks.
- **Source expectations vary by blueprint** (PRD open question 6): each
  blueprint carries a default `source_policy` sentence embedded in the spec
  prompt (casebook and quantitative/scientific require sources for
  non-common-knowledge claims; exam preparation requires sources for rules
  being tested; the others recommend but do not require). The existing
  `source.missing_for_required_claim` check is the enforcement point; this
  milestone changes only the default policy text per blueprint.
- **Recommendation is deterministic and explainable.** A pure function over
  topic fields returns `(blueprint_id, rationale)`; no model call. The user
  always sees the rationale and can override. When nothing matches, the
  default is `conceptual-foundations`.

## Design

### 1. Blueprint registry (`education_pipeline/guides/blueprints.py`)

A new module defining a frozen dataclass and an immutable registry keyed by
id:

```python
@dataclass(frozen=True)
class Blueprint:
    id: str                      # e.g. "procedural-skill"
    title: str                   # "Procedural skill"
    summary: str                 # one-sentence description
    when_to_use: str             # selection guidance shown in UI/CLI
    required_interactions: frozenset[str]   # minimum contract set
    default_difficulty: str      # one of the four schema values
    source_policy: str           # default source-expectation sentence
    spec_lines: tuple[str, ...]      # appended to the spec prompt
    outline_lines: tuple[str, ...]   # appended to the outline prompt
    draft_lines: tuple[str, ...]     # appended to the draft prompt
    qa_rubric_lines: tuple[str, ...] # appended to the QA prompt
    repair_lines: tuple[str, ...]    # appended to the repair prompt
```

Registered ids (PRD §7.3):

| id | required interactions (minimum) |
| --- | --- |
| `conceptual-foundations` | `knowledge_check`, `reflection` |
| `procedural-skill` | `worked_reveal`, `knowledge_check` |
| `casebook` | `scenario`, `reflection` |
| `quantitative-scientific` | `worked_reveal`, `knowledge_check` |
| `exam-preparation` | `knowledge_check`, `worked_reveal` |
| `project-based` | `scenario`, `reflection` |

All prompt-line content stays domain-neutral per the extraction manifest:
lines describe pedagogy ("every procedure must be presented as a complete,
numbered worked sequence the learner can replay"), never subject matter.

Pure functions:

- `get_blueprint(blueprint_id) -> Blueprint` — raises `ConfigError` for an
  unregistered id.
- `list_blueprints() -> tuple[Blueprint, ...]` — stable order for UI/CLI.
- `recommend_blueprint(topic) -> tuple[str, str]` — deterministic keyword and
  field heuristics over `title`, `brief`, `goals`, `key_questions`, and
  `constraints` (e.g. exam/certification vocabulary → `exam-preparation`;
  compute/derive/units vocabulary → `quantitative-scientific`; build/ship
  vocabulary → `project-based`); returns the id and a one-sentence rationale.
  Falls back to `conceptual-foundations` with a "general conceptual topic"
  rationale. A test pins the full keyword table so recommendations only
  change deliberately.

A registry-integrity test asserts: ids are unique and match
`^[a-z][a-z0-9-]{0,63}$`; every `required_interactions` set is a non-empty
subset of `REQUIRED_INTERACTION_TYPES`; every `default_difficulty` is a valid
schema value; every prompt-line tuple is non-empty; and the six PRD
blueprints are all present.

### 2. Blueprint as run configuration

- **Topic schema (additive).** `topics.py` gains two optional fields, keeping
  `schema_version = 1`: `blueprint` (string; when present must be a
  registered id at run-creation time) and `time_budget_minutes` (int,
  5–10 000). `emit_topic_toml` round-trips both. Existing topic files remain
  valid; both keys join `_TOP_LEVEL_KEYS`.
- **Resolution at run creation.** `create` (CLI `--blueprint` flag, daemon
  write API, cockpit wizard) resolves the effective blueprint:
  explicit choice → topic field → `recommend_blueprint(topic)`. The effective
  blueprint id, the selection source (`user`, `topic`, `recommended`), and
  the recommendation rationale are recorded in the run manifest next to the
  effective model plan, and surfaced by `status` and the run-detail API.
  Legacy Markdown runs (`--legacy`) ignore blueprints entirely.
- **Contract echo.** `guides/contract.py` gains: when the run supplies an
  expected blueprint, `blueprint` in the parsed spec contract must equal it
  and `required_interactions` must be a superset of the blueprint's minimum
  set; violations are `ContractError`s reported at the spec stage exactly
  like today's contract failures. Contract parsing without an expected
  blueprint (old workspaces, direct library use) keeps today's
  free-text-string behavior — no retroactive invalidation of existing runs.

### 3. Blueprint-specific prompt and QA contracts (`prompts.py`)

Each `compile_guide_v1_*_prompt` function accepts an optional
`blueprint: Blueprint | None` (threaded from the run manifest by `runs.py`).
When present:

- spec/outline/draft/repair prompts gain a `## Blueprint Contract` section:
  the blueprint title, its stage lines, its minimum required interactions
  (stated as binding), and its default source policy. Priority order places
  it with the authoring contract — above topic requirements and learner
  profile context.
- the QA prompt gains a `## Blueprint Rubric` section from `qa_rubric_lines`
  and instructs QA to record a finding for each unmet rubric item. Examples
  of rubric intent per blueprint: casebook — fact patterns are realistic and
  decision points have defensible distractors; quantitative-scientific —
  every computation is worked step-by-step with units carried;
  exam-preparation — practice items match the assessment format and every
  answer has a rationale; procedural-skill — procedures are complete,
  ordered, and replayable; project-based — modules advance a concrete
  deliverable with checkable milestones.
- the spec prompt's contract-block instructions state the configured
  blueprint id as the required `blueprint` value and the minimum
  `required_interactions`, instead of leaving both to the model's judgment.

When `blueprint is None` (legacy runs, direct calls) prompt bytes are
unchanged from today, byte-for-byte — a regression test asserts this so the
frozen prompt surface only changes where explicitly authorized. The canonical
acceptance fixture is regenerated once under `conceptual-foundations` and its
recorded normalized SHA-256 updated in the same change, with the diff
reviewed as part of the wave gate.

### 4. Deterministic calibration checks (`guides/validation.py`)

New rules, all parameterized by inputs `runs.py` already has at gate time
(topic, blueprint, profile snapshot):

| Rule id | Severity | Blocking | Waivable | Trigger |
| --- | --- | --- | --- | --- |
| `blueprint.unknown` | warning | no | no | `course.blueprint` is not a registered id (informational for old/manual guides) |
| `blueprint.contract_mismatch` | error | yes | yes | `course.blueprint` differs from the run's configured blueprint |
| `time.budget_exceeded` | warning | no | no | `course.estimated_minutes` exceeds the topic `time_budget_minutes` (when set) by more than 10 % |
| `time.budget_underrun` | info | no | no | estimate is under 50 % of the stated budget |
| `time.estimate_implausible` | warning | no | no | deterministic reading-time model (words-per-minute over markdown text plus fixed per-interaction constants) disagrees with `course.estimated_minutes` by more than a factor of two, in either direction |
| `time.module_overrun` | warning | no | no | a single module exceeds 45 minutes while the profile snapshot declares `attention_constraints` |
| `difficulty.learner_mismatch` | warning | no | no | declared `course.difficulty` is two levels away from a mechanical mapping of the profile's `current_skill_level` (e.g. `introductory` course for an advanced learner); never fires without a snapshot |

Constants of the reading-time model (words per minute, per-block-type
seconds) live in one table in the module with a pinning test, so calibration
only changes deliberately. All new findings flow through the existing
sanitization path (no private profile values in messages — findings reference
field *presence*, never content), appear in the sidecar quality report, and
are attributed to `outline` (time/difficulty shape) or `draft`
(estimate-vs-content) so the responsible stage shows them.

Blueprint-required interaction coverage needs **no new rule**: the contract
superset check (§2) guarantees the blueprint minimums are in
`required_interactions`, and the existing `interaction.missing_required_type`
rule enforces them against the guide.

### 5. Section-level regeneration (`runs.py`, providers, daemon, CLI)

A scoped variant of the existing repair stage:

- **Trigger surface.** Whenever repair is the run's active stage (after QA
  approval, or on re-entry after a failed final validation), the user may
  request a scoped repair for exactly one module id present in the approved
  draft. CLI: `education-pipeline advance <topic> --repair-module <module-id>`
  (invalid outside repair; unknown module id is a usage error). Daemon: the
  existing repair-prep write route accepts an optional `repair_module` field.
- **Scoped prompt.** A new `compile_guide_v1_module_repair_prompt` embeds the
  guide contract, only the findings whose location falls inside the target
  module (deterministic findings filtered by path prefix; model-QA findings
  filtered by the location line naming the module, with unmatchable findings
  listed as out-of-scope context), the single module's JSON as the base to
  revise, and a compact summary of the rest of the course (module ids,
  titles, outcome ids only) so cross-references stay coherent. Output
  contract: exactly one module object (same `id`), same JSON-only rules as
  whole-guide repair.
- **Deterministic splice.** New pure function
  `guides.canonical.splice_module(base_guide_json, module_id, module_json)`:
  parses the response as one module; requires the module `id` to be
  unchanged; requires every new element id introduced inside the module to be
  globally unique across the merged guide; requires `outcome_ids` references
  to stay within the contract's outcomes; replaces the module in place
  preserving module order; returns the merged guide. Any violation is a
  blocking, stage-attributed repair finding — the splice never silently
  drops or renames content.
- **Same gates, same ledger.** The merged whole guide — not the fragment —
  goes through full draft validation, approval, stale-content protection
  (`response_sha256` keys the scoped response to the exact base draft it
  patches, so a concurrent edit of the draft invalidates the pending scoped
  repair), and the append-only event log, which records the scope. Repeated
  scoped repairs before approval are ordinary repair retries. Byte-identity
  test: modules outside the target are byte-identical after the splice.
- **Provider flow unchanged.** Providers execute the scoped prompt exactly
  like any repair prompt; manual copy/paste works identically.

### 6. Cockpit

- **New Course flow.** The wizard's existing simple blueprint field becomes a
  selection step: the six blueprints with title, summary, `when_to_use`
  guidance, and the recommended one pre-selected with its rationale ("we
  recommend Exam preparation because your brief mentions a certification
  deadline"). An override is one click; the confirm step shows the effective
  blueprint. An optional time-budget input writes `time_budget_minutes`.
- **Run board / stage workspace.** The run header shows the effective
  blueprint and selection source. The stage prompt view already displays
  compiled prompts, so blueprint contract sections are visible with no new
  UI. Calibration findings render through the existing findings components.
- **Module regeneration.** On the repair stage, a "Regenerate one module"
  control lists the draft's modules with their open finding counts; choosing
  one prepares the scoped prompt through the normal prep/run/paste flow. The
  response panel labels the pending artifact as scoped to that module.

### 7. CLI and API summary

- `education-pipeline create --blueprint <id>` and topic TOML `blueprint` /
  `time_budget_minutes`; `create` prints the resolved blueprint + rationale.
- `education-pipeline blueprints` — list ids, titles, and when-to-use
  guidance (read-only, no workspace needed).
- `education-pipeline advance <topic> --repair-module <module-id>`.
- Daemon: `GET /v1/blueprints` (registry + per-topic recommendation via query
  param); run-detail payload gains `blueprint {id, source, rationale}`;
  repair-prep route gains optional `repair_module`. All additive.

## Testing

- **Python (pytest):** registry integrity and recommendation-table pinning;
  topic round-trip with the new optional fields; blueprint resolution
  precedence (`user` > `topic` > `recommended`) and manifest recording;
  contract echo and superset rejection, plus unchanged behavior with no
  expected blueprint; per-blueprint prompt sections and the
  `blueprint is None` byte-identity regression; each new validation rule's
  trigger and non-trigger cases, including sanitization (no profile values in
  messages) and sidecar presence; `splice_module` success, id-collision,
  id-rename, unknown-module, and out-of-contract-reference failures;
  byte-identity of untouched modules; scoped-repair stale-content
  invalidation and event-log scope records; CLI `blueprints`, `--blueprint`,
  and `--repair-module` including usage-error exit codes.
- **Web (vitest):** blueprint selection step render/override/rationale;
  module-regeneration list and finding counts; run-header blueprint display.
- **E2E (Playwright):** create a course accepting the recommendation, verify
  the spec prompt contains the blueprint contract; override to a second
  blueprint and verify the prompt differs; drive a fixture run to repair and
  regenerate one module, asserting the other modules' content is unchanged
  and the run proceeds to approval; verify a time-budget warning appears at
  the responsible stage for a fixture that exceeds its budget.
- **Fixture:** the canonical acceptance fixture is regenerated once under
  `conceptual-foundations`; a second small fixture under a contrasting
  blueprint (`quantitative-scientific`) exercises the divergent prompt and
  rubric paths.

TDD throughout, per repo convention.

## Out of scope

- New interaction block types or any guide-schema change (PRD §7.8 admission
  criteria; casebook/quantitative/exam needs are expressible with the
  existing six block types).
- Blueprint-specific visual themes or runtime behavior (content/runtime
  separation, PRD §4 principle 7).
- User-defined or file-configurable blueprints ("optional guide packs" is a
  §14 future opportunity).
- Section- or block-granular regeneration below module level, and targeted
  regeneration of spec/outline fragments.
- Model-driven blueprint recommendation.
- Difficulty *progression* analysis across modules (only declared-difficulty
  calibration ships here).
- First-run/course-management deliverables (separate approved design,
  [`2026-07-12-first-run-course-management-design.md`](2026-07-12-first-run-course-management-design.md)).

## Open questions for the owner

1. Should `time.budget_exceeded` escalate to a waivable blocking `error` when
   the overrun is extreme (say, more than 2× the stated budget), or is
   warning-only right for v1?
2. Is module-level granularity acceptable for regeneration v1, or is
   section-level required to meet the "one weak lesson" bar? (Module-level is
   substantially simpler and matches how outlines are structured today.)
3. Sequencing: this milestone and the approved first-run milestone are
   independent (different files, different surfaces). Build order preference?

## Decision log

| Decision | Choice |
| --- | --- |
| Blueprint ownership | Application-owned registry in source; six PRD blueprints; no user config files |
| Who chooses | User at creation (recommended default); model must echo; mismatch is a contract error |
| Schema impact | None to guide schema or spec-contract fields; additive optional topic fields only |
| Interaction enforcement | Blueprint minimums via contract superset check + existing rules |
| Calibration severity | Warnings/info, nonblocking, non-waivable |
| Regeneration shape | Scoped variant of the repair stage, module granularity, deterministic splice, full-guide revalidation |
| Recommendation | Deterministic keyword/field heuristic with pinned table and visible rationale |
| Source policy by blueprint | Per-blueprint default policy sentence; enforcement via existing citation checks |
| Legacy behavior | No expected blueprint → prompts and contracts byte-identical to today |
