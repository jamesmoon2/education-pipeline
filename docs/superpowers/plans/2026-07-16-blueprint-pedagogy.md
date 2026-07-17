# Blueprint-Driven Pedagogy Implementation Plan

> Executed wave-by-wave on branch `claude/blueprint-pedagogy` with strict TDD.
> Steps use checkbox (`- [ ]`) syntax for tracking. Each wave closes by running
> its focused suites, committing, and updating the Wave Log below; the full
> four-suite gate closes the milestone in Wave 5.

**Goal:** Blueprint becomes user-selected run configuration backed by an
application-owned six-blueprint registry; prompts and the model-QA rubric are
parameterized per blueprint; deterministic time-budget and difficulty
calibration checks warn without blocking; and one weak module can be
regenerated in place through a module-scoped repair variant with a
deterministic splice — all without any guide-schema, runtime-asset, or
spec-contract field change.

**Spec:**
`docs/superpowers/specs/2026-07-16-blueprint-pedagogy-design.md` — its
Out-of-scope list and Decision log are binding.

**Owner decisions on the spec's open questions (2026-07-16):**

1. Time-budget overruns stay warning-only for v1 — no blocking escalation.
2. Module-level granularity is accepted for regeneration v1.
3. Sequencing is moot; this runs in parallel with the first-run milestone.

## Global Constraints

- `education_pipeline/` remains **standard library only at runtime**.
- Strict TDD: write and observe failing focused tests before implementation.
- **Legacy behavior is frozen:** with no configured blueprint, prompt bytes and
  contract parsing are byte/behavior-identical to today. The
  `blueprint is None` byte-identity regression test lands **before** any prompt
  change. Old workspaces are never retroactively invalidated.
- No guide-schema version bump, no new block types, no runtime-asset or
  spec-contract field changes. Topic schema stays `schema_version = 1` with
  additive optional fields only.
- Splice safety: modules outside the regeneration target are byte-identical
  (canonical serialization) after the merge; module-id renames and element-id
  collisions are blocking refusals, never silent fixes.
- Calibration findings never contain profile values — they reference field
  *presence* only and flow through the existing sanitization path.
- Blueprint prompt/rubric lines stay domain-neutral per
  `docs/extraction-manifest.md`.
- The parallel first-run/course-management effort owns the daemon
  error-envelope refactor and New Course wizard restructuring. All daemon and
  wizard additions here follow the current style of the base branch and stay
  self-contained so the eventual merge is mechanical.
- Preserve the `RunStore._manifest_write_lock` contract: non-reentrant; compose
  with `_locked` primitives only.
- Never commit generated runs, real learner profiles, or workspace artifacts.
- The canonical acceptance fixture may be regenerated **exactly once**, under
  `conceptual-foundations`, with the recorded normalized SHA-256 updated in the
  same commit and the diff explained in the Wave Log. (The fixture already
  declares `conceptual-foundations`; if no byte change is required, that is
  recorded instead.)

## Frozen Cross-Wave Contracts

These shapes are settled by this plan so later waves build against them
without reopening design.

### Blueprint registry (`education_pipeline/guides/blueprints.py`)

```python
@dataclass(frozen=True)
class Blueprint:
    id: str
    title: str
    summary: str
    when_to_use: str
    required_interactions: frozenset[str]
    default_difficulty: str
    source_policy: str
    spec_lines: tuple[str, ...]
    outline_lines: tuple[str, ...]
    draft_lines: tuple[str, ...]
    qa_rubric_lines: tuple[str, ...]
    repair_lines: tuple[str, ...]
```

- `get_blueprint(blueprint_id) -> Blueprint` raises `ConfigError` for an
  unregistered id; `list_blueprints() -> tuple[Blueprint, ...]` in stable
  (PRD §7.3) order; `recommend_blueprint(topic) -> tuple[str, str]` is a pure
  deterministic keyword/field heuristic with a pinned keyword table, falling
  back to `conceptual-foundations`.
- Registered ids and minimum interactions (PRD §7.3):
  `conceptual-foundations` {knowledge_check, reflection};
  `procedural-skill` {worked_reveal, knowledge_check};
  `casebook` {scenario, reflection};
  `quantitative-scientific` {worked_reveal, knowledge_check};
  `exam-preparation` {knowledge_check, worked_reveal};
  `project-based` {scenario, reflection}.

### Run configuration and manifest recording

- `Topic` gains optional `blueprint: str | None` (validated as a registered id
  at run-creation time, not topic-parse time) and
  `time_budget_minutes: int | None` (5–10 000, validated at parse);
  `emit_topic_toml` round-trips both; both keys join `_TOP_LEVEL_KEYS`.
- `RunStore.create_run(topic_id, *, content_contract=None, blueprint=None)`
  resolves the effective blueprint for interactive-guide runs when the
  manifest is first created (and may record it later, once, on an existing
  guide manifest that has none): explicit `blueprint` argument → topic
  `blueprint` field → `recommend_blueprint(topic)` when a stored topic exists.
  The manifest gains a single immutable top-level record:
  `"blueprint": {"id": ..., "source": "user" | "topic" | "recommended",
  "rationale": ...}` (`rationale` present for `recommended`). Conflicting
  re-recording raises `ConfigError`. Runs without a stored topic and without
  an explicit choice record nothing (legacy behavior). Legacy Markdown runs
  never record a blueprint.
- `RunStore.blueprint_config(topic_id) -> dict | None` reads the record;
  `RunStore.run_blueprint(topic_id) -> Blueprint | None` resolves it via the
  registry.

### Prompt and contract surface

- Every `compile_guide_v1_*_prompt` gains keyword-only
  `blueprint: Blueprint | None = None`. `None` → byte-identical output to
  today (pinned regression). Present → spec/outline/draft/repair prompts gain
  a `## Blueprint Contract` section placed directly after the header priority
  block (with the authoring contract, above topic requirements); the QA prompt
  gains `## Blueprint Rubric` from `qa_rubric_lines`; the spec prompt's
  contract-block instructions state the configured blueprint id and minimum
  `required_interactions` as required values.
- `extract_spec_contract(markdown_text, *, expected_blueprint=None)`:
  when an expected `Blueprint` is supplied, the parsed contract's `blueprint`
  must equal its id and `required_interactions` must be a superset of its
  minimum set; violations are `ContractError`s. Without the argument, behavior
  is unchanged.

### Calibration (`guides/validation.py`)

```python
@dataclass(frozen=True)
class CalibrationContext:
    configured_blueprint: str | None = None
    time_budget_minutes: int | None = None
    attention_constraints_present: bool = False
    learner_skill_level: str | None = None
```

- `validate_guide(..., calibration_context=None)`; `None` → no new findings
  anywhere (standalone validation and old flows unchanged).
- Rules (id / severity / blocking / waivable / stage):
  `blueprint.unknown` warning/no/no/draft (fires only when
  `configured_blueprint is None` and `course.blueprint` is unregistered);
  `blueprint.contract_mismatch` error/yes/yes/draft;
  `time.budget_exceeded` warning/no/no/outline (estimate > budget by >10 %);
  `time.budget_underrun` info/no/no/outline (estimate < 50 % of budget);
  `time.estimate_implausible` warning/no/no/draft (reading-time model
  disagrees by more than 2× either direction);
  `time.module_overrun` warning/no/no/outline (a module > 45 min while
  `attention_constraints_present`);
  `difficulty.learner_mismatch` warning/no/no/outline (declared difficulty two
  levels from the mapped skill level; never fires without a snapshot; `mixed`
  and unmappable skill text never fire).
- Reading-time and skill-mapping constants live in module-level tables
  (`READING_TIME_WPM`, `READING_TIME_BLOCK_SECONDS`, `_SKILL_LEVEL_MAP`,
  `_DIFFICULTY_LEVELS`) with pinning tests.
- `runs.py` builds the context at gate time from the stored topic (absent
  topic → no topic-derived checks), the manifest blueprint record, and the
  attached profile snapshot (presence flags/values only; messages never echo
  profile content).

### Module-scoped repair

- `guides.canonical.splice_module(base_guide_json, module_id, module_json)
  -> bytes`: parses the response as exactly one module object whose `id`
  equals `module_id` (rename → `SpliceError`), replaces it in place preserving
  module order, re-parses the merged guide strictly (global id uniqueness and
  outcome-reference checks ride the existing parser), and returns canonical
  merged guide bytes. Unknown module id, non-module payloads, id collisions,
  and parse regressions raise `SpliceError` with the exact violation.
- `compile_guide_v1_module_repair_prompt(topic, *, module_id, ...)` embeds the
  guide contract, only the findings inside the target module (deterministic
  findings filtered by `/modules/<index>` path prefix; model-QA finding items
  split from `## Findings` and classified by module id/title mention, with
  unmatchable items listed as out-of-scope context), the single module's
  canonical JSON as the base to revise, and a compact course summary (module
  ids, titles, outcome ids). Output contract: exactly one module object, same
  `id`, JSON-only.
- `RunStore.write_module_repair_prompt(topic_id, module_id, *, overwrite)` is
  valid whenever repair is the active stage; it records `repair_module` and
  `source_draft_file_sha256` on the `prompt_written` event.
- Approval of a scoped repair (latest repair `prompt_written` event carries
  `repair_module`) splices the response fragment into the approved draft and
  writes the **merged whole guide** to `approved/repair.json`; the
  `response_approved` event records the scope. A drifted approved draft
  (hash mismatch with the prompt event) refuses with `StaleContentError`;
  splice violations refuse with `ConfigError` naming the violation. The merged
  guide then flows through the existing final validation, gates, and ledger
  unchanged.
- CLI: `education-pipeline advance <topic> --repair-module <module-id>`
  (usage error outside repair or for an unknown module id, exit 2).
  Daemon: `POST /v1/runs/{topic}/advance` body gains optional
  `repair_module`; `GET /v1/runs/{topic}/repair/modules` lists candidate
  modules with open finding counts and the current scope;
  `GET /v1/runs/{topic}/stages/repair` payload gains `repair_scope`.

### Daemon/CLI/cockpit additions (all additive, current base-branch style)

- `GET /v1/blueprints` → `{blueprints: [{id, title, summary, when_to_use,
  required_interactions, default_difficulty}], recommendation: {id,
  rationale} | null, topic_blueprint: str | null}` (recommendation and
  topic_blueprint populated when `?topic=<id>` names a stored topic).
- `run_status_payload` gains `blueprint: {id, source, rationale} | null`.
- `POST /v1/runs/{topic}/advance` body gains optional `blueprint`
  (recorded as source `user` before the advance step runs).
- `POST /v1/topics` (create body) gains optional `blueprint` and
  `time_budget_minutes`.
- CLI: `education-pipeline blueprints` (read-only registry listing, no
  workspace access) and `education-pipeline create --blueprint <id>`
  (refused for `--legacy-markdown` runs); `create` prints the resolved
  blueprint and rationale.
- Cockpit: New Run wizard gains a blueprint selection step after topic
  creation (recommended blueprint pre-selected with rationale, one-click
  override, optional time-budget input on the describe form); the run board
  header shows the effective blueprint and source; the repair stage view
  gains a "Regenerate one module" control and a scope label on pending
  scoped artifacts.

## File Structure

| Area | Files |
| --- | --- |
| Registry/recommender | `education_pipeline/guides/blueprints.py` (new), `tests/test_guide_blueprints.py` (new) |
| Topic fields | `education_pipeline/topics.py`, `tests/test_topics.py` |
| Run configuration | `education_pipeline/runs.py`, `tests/test_runs.py` |
| Prompts | `education_pipeline/prompts.py`, `tests/test_prompts.py` |
| Contract echo | `education_pipeline/guides/contract.py`, `tests/test_guide_contract.py` |
| Calibration | `education_pipeline/guides/validation.py`, `tests/test_guide_validation.py` |
| Splice | `education_pipeline/guides/canonical.py`, `tests/test_guide_canonical.py` |
| CLI | `education_pipeline/cli.py`, `tests/test_cli.py` |
| Daemon | `education_pipeline/daemon/{read_api,write_api,server}.py`, `tests/{test_write_api,test_server}.py` |
| Cockpit | `web/src/api/{types,client}.ts`, `web/src/pages/{NewRunPage,RunBoardPage,StageViewerPage}.tsx`, new `web/src/components/{BlueprintPicker,ModuleRepairControl}.tsx` and tests |
| Acceptance | `web/e2e/blueprints.spec.ts` (new), `tests/test_release_gate_acceptance.py` |
| Closeout | `docs/product-requirements.md`, `docs/superpowers/specs/2026-07-16-blueprint-pedagogy-post-milestone-audit.md` (new) |

---

# Wave 0 — Blueprint registry, recommender, and topic fields

**Outcome:** the six-blueprint registry and deterministic recommender exist as
pure code with pinned tables; topics carry optional `blueprint` and
`time_budget_minutes`; `RunStore` resolves and immutably records the effective
blueprint on new guide runs.

- [x] RED: `tests/test_guide_blueprints.py` — registry integrity (unique ids
  matching `^[a-z][a-z0-9-]{0,63}$`, six PRD ids present,
  `required_interactions` non-empty subsets of `REQUIRED_INTERACTION_TYPES`,
  valid `default_difficulty`, non-empty prompt-line tuples), `get_blueprint`
  unknown-id `ConfigError`, `list_blueprints` stable order, recommendation
  keyword-table pinning, per-signal recommendation cases, fallback rationale.
- [x] RED: `tests/test_topics.py` — optional field parsing, bounds (5–10 000),
  type rejection, round-trip via `emit_topic_toml`, absent-field defaults.
- [x] RED: `tests/test_runs.py` — resolution precedence (`user` > `topic` >
  `recommended`), manifest record shape/immutability, no record without topic
  or explicit choice, legacy-markdown runs never record, conflicting explicit
  re-record raises, `run_blueprint` round-trip.
- [x] GREEN: implement `blueprints.py`, topic fields, `create_run` blueprint
  resolution + `blueprint_config`/`run_blueprint`.
- [x] Focused suites green; commit
  `feat(blueprints): add registry, recommender, and run configuration`.

# Wave 1 — Prompt contracts and contract echo/superset checks

**Outcome:** blueprint-parameterized prompts for all five stages with the
`blueprint is None` byte-identity regression pinned first; spec-contract echo
and superset enforcement at approval; blueprint threading through `runs.py`;
CLI and daemon read surfaces.

- [x] RED (**lands before any prompt change**): `tests/test_prompts.py` —
  byte-identity of every `compile_guide_v1_*` output with `blueprint=None`
  against captured current bytes; `## Blueprint Contract` sections for
  spec/outline/draft/repair with two contrasting blueprints producing
  different prompts; `## Blueprint Rubric` in QA; spec contract-block
  instructions naming the configured id and minimum interactions.
- [x] RED: `tests/test_guide_contract.py` — echo mismatch, superset violation,
  passing echo+superset, unchanged behavior without `expected_blueprint`.
- [x] RED: `tests/test_runs.py` — spec approval rejects wrong echoed blueprint;
  prompts written by a blueprint-configured run contain the contract section;
  runs without a record produce byte-identical prompts to today.
- [x] RED: `tests/test_cli.py` — `blueprints` listing, `create --blueprint`
  (prints resolution; unknown id exit 1; refused with `--legacy-markdown`).
- [x] RED: `tests/test_server.py`/`tests/test_write_api.py` —
  `GET /v1/blueprints` (+ per-topic recommendation), run status `blueprint`
  payload, advance body `blueprint` recording.
- [x] GREEN: implement prompts, contract echo, `runs.py` threading, CLI,
  daemon routes.
- [x] Focused suites green; commit
  `feat(blueprints): parameterize prompts and enforce the contract echo`.

# Wave 2 — Deterministic calibration rules

**Outcome:** the seven calibration rules fire deterministically behind
`CalibrationContext`, with pinned constant tables, correct stage attribution,
sanitized messages, and sidecar presence; absent context changes nothing.

- [x] RED: `tests/test_guide_validation.py` — trigger and non-trigger cases per
  rule (including boundary values: exactly +10 %, exactly 50 %, exactly 2×,
  exactly 45 min, exactly two-level difficulty distance), no-context and
  no-budget silence, `mixed`/unmappable never fire, constant-table pinning,
  message sanitization (no profile values, presence-only wording), stage
  attribution, waivability/blocking flags.
- [x] RED: `tests/test_runs.py` — gate-time context construction from
  topic/manifest/profile snapshot; findings appear in draft/final reports and
  the sidecar; warning-only rules leave the gate open; missing topic file
  degrades silently.
- [x] GREEN: implement rules + context wiring.
- [x] Focused suites green; commit
  `feat(validation): add blueprint and calibration checks`.

# Wave 3 — Module-scoped repair and deterministic splice

**Outcome:** one weak module can be regenerated in place: scoped prompt,
deterministic splice at approval, byte-identity of untouched modules, stale
protection, event-log scope records, CLI and daemon triggers.

- [x] RED: `tests/test_guide_canonical.py` — `splice_module` success (canonical
  bytes; untouched modules byte-identical), module-id rename, unknown module,
  element-id collision with another module, dangling outcome reference,
  non-module payload, module-order preservation.
- [x] RED: `tests/test_prompts.py` — scoped prompt embeds contract, only
  in-module deterministic findings, QA items split in/out of scope, course
  summary, single-module output contract; blueprint lines compose.
- [x] RED: `tests/test_runs.py` — scoped prompt writing (eligibility, unknown
  module usage error), scoped approval splices and validates, stale draft
  refusal, event scope records, repeated scoped repairs as ordinary retries,
  whole-guide repair unchanged.
- [x] RED: `tests/test_cli.py` — `advance --repair-module` happy path and
  usage errors (exit 2). `tests/test_server.py`/`test_write_api.py` — advance
  `repair_module`, `GET /v1/runs/{t}/repair/modules`, stage payload
  `repair_scope`.
- [x] GREEN: implement splice, scoped prompt compiler, `RunStore` flow, CLI,
  daemon.
- [x] Focused suites green; commit
  `feat(repair): add module-scoped regeneration with deterministic splice`.

# Wave 4 — Cockpit

**Outcome:** blueprint selection in the New Run wizard with visible
recommendation rationale and override; run-header blueprint display; repair
"Regenerate one module" control with finding counts and scope labeling.

- [x] RED (vitest): blueprint step render/override/rationale/time-budget,
  wizard passes the override to advance, run-header blueprint display,
  module-regeneration list with finding counts, scoped-artifact label,
  API client coverage for the new routes.
- [x] GREEN: implement `BlueprintPicker`, `ModuleRepairControl`, wizard step,
  header, stage-view integration in current base-branch style.
- [x] `npm run test -- --run` and `npm run build` green; commit
  `feat(cockpit): add blueprint selection and module regeneration`.

# Wave 5 — Acceptance, fixtures, docs, closeout

**Outcome:** end-to-end evidence, green four-suite gate with recorded counts,
PRD entry moved to Delivered, post-milestone audit ledger.

- [x] Playwright `web/e2e/blueprints.spec.ts`: create a course accepting the
  recommendation and verify the spec prompt carries the blueprint contract;
  override to a second blueprint and verify the prompt differs; drive a
  fixture run to repair, regenerate one module, assert other modules
  unchanged and the run proceeds; verify a time-budget warning surfaces at
  the responsible stage.
- [x] Python acceptance: contrasting `quantitative-scientific` path exercising
  divergent prompt/rubric output (in `tests/test_prompts.py` +
  `tests/test_release_gate_acceptance.py` additions).
- [x] Canonical fixture check: regenerate at most once under
  `conceptual-foundations` (or record that bytes are unchanged) and update the
  pinned SHA in the same commit; explain in the Wave Log.
- [x] Four-suite gate: `python3 -m pytest`; from `web/`: `npm run test --
  --run`, `npm run build`, `npm run e2e`. Record counts below.
- [x] PRD §10 "P1 — Blueprint-driven pedagogy" → Delivered with closeout
  evidence links in the format of the delivered entries above it.
- [x] Write
  `docs/superpowers/specs/2026-07-16-blueprint-pedagogy-post-milestone-audit.md`
  following the 2026-07-13 personalization audit ledger.
- [x] Final commit and push to `claude/blueprint-pedagogy`.

---

## Wave Log

| Wave | Status | Commits | pytest | vitest | e2e | build | Notes for the next wave |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | **recorded** | branch base `28bf6aa` + spec cherry-pick `6e291f5` | 973 (prior gate) | 210 (prior gate) | 53 (prior gate) | clean (prior gate) | Baseline counts are the personalization Wave 4 closeout gate recorded on the same code HEAD (`docs/superpowers/plans/2026-07-13-personalization.md`); the cherry-pick is docs-only. |
| 0 — Registry + topic fields | **complete** | `2808a84` | 1009 | — | — | — | Registry/recommender/topic fields/manifest record frozen as planned. Recommender matches whole words only ("example" never triggers "exam"); scanned fields are title/brief/goals/key_questions/constraints. `create_run` records a blueprint only for interactive-guide manifests and degrades silently on a missing/malformed stored topic; unregistered explicit or topic-declared ids raise at run creation. Existing guide-run test helpers now produce runs recorded as recommended `conceptual-foundations`, matching their spec-contract echoes. |
| 1 — Prompts + echo | **complete** | `f006afc` | 1031 | — | — | — | `blueprint=None` byte-identity pinned first (`_GUIDE_V1_NO_BLUEPRINT_PROMPT_TEXT_SHA256`, hashes captured from pre-change compilers). Blueprint Contract sits between the header priority block and `## Topic`; QA rubric instructs one finding per unmet item. Echo/superset live in `extract_spec_contract(expected_blueprint=...)` and fire at spec approval via `run_blueprint()`. Daemon advance body accepts optional `blueprint` (recorded source `user` before advancing); `GET /v1/blueprints?topic=` 404s for unknown topics. |
| 2 — Calibration | **complete** | `a6fcbea` | 1044 | — | — | — | Seven rules behind `CalibrationContext` (None → reports byte-identical). Constants pinned (200 WPM, per-block seconds, skill keywords, difficulty levels) with `estimated_reading_minutes()` public for tests. Boundaries: exceeded strictly above 1.1×, underrun strictly below 0.5×, implausible strictly beyond 2× either way, overrun strictly above 45 min, difficulty distance ≥ 2, `mixed`/ambiguous never fire. `RunStore._calibration_context` reads topic (silent degrade), manifest record, and profile snapshot; threaded through validate/gate/finalize/export-freshness so sidecar bytes stay reproducible. Note: the canonical fixture legitimately triggers `time.estimate_implausible` (30 declared vs ~9-minute model) — a nonblocking warning that no existing suite pinned against. |
| 3 — Scoped repair | **complete** | `2877c7a` | 1067 | — | — | — | Splice refuses renames/collisions/dangling refs via strict re-parse; untouched modules byte-identical (canonical). Splice runs at approval (covers provider ingest, cockpit paste, and manual file-save uniformly); approved/repair.json holds the merged whole guide while the response file keeps the raw fragment. Scope = latest repair prompt_written event's `repair_module`; whole-guide prompt clears it. Deviation from the frozen contract: none. Note for Wave 4: after a scoped approval the response fragment ≠ approved bytes, so the stage view must not rely on response==approved to derive approval state for scoped repairs — use run status + `repair_scope`. |
| 4 — Cockpit | **complete** | `84aa9a4` | — | 221 | — | clean | `BlueprintPicker` + wizard blueprint step (topic → blueprint → profile → plan); accepted recommendation sends no override so provenance stays `recommended`; registry-fetch failure falls back to the pre-blueprint flow. `RunStatus.blueprint` and `StageContent.repair_scope` typed optional so existing fixtures stay valid. `ModuleRepairControl` hides itself until `GET repair/modules` succeeds. Known cosmetic quirk (accepted): after a scoped approval the response fragment ≠ approved bytes, so the generic Approve button stays visible like an edited response; re-approving re-splices idempotently. `web/e2e/new-run.spec.ts` will need the blueprint-step click — handled in Wave 5. |
| 5 — Acceptance + closeout | **complete** | `3f951e8` | 1068 | 221 | 57 | clean | Four-suite gate green (pytest 1068; vitest 221 across 30 files; Playwright 57 incl. 4 new blueprint specs; build clean). Canonical fixture **not regenerated**: schema/canonicalization untouched, fixture already `conceptual-foundations`, pinned SHA `99fde906…` unchanged — recorded here in lieu of a diff. Contrasting `quantitative-scientific` acceptance covers divergent spec/QA prompts, echo refusal, superset refusal, and the draft-side `blueprint.contract_mismatch` gate. `new-run.spec.ts` updated for the wizard blueprint step. PRD §10 entry moved to Delivered; post-milestone audit ledger added at `docs/superpowers/specs/2026-07-16-blueprint-pedagogy-post-milestone-audit.md`. |

### Post-milestone rebase onto the first-run milestone (2026-07-17)

The branch was rebased onto `main` after the first-run/course-management
milestone merged (PR #11). The daemon-side conflict (`write_api.advance_run`)
was a mechanical union of both signatures. The New Course wizard was
restructured by that milestone, so the blueprint step was re-fitted into the
new `learner → topic → blueprint → plan → confirm` order in a dedicated
commit: because the new wizard creates the topic only at Confirm, the
recommendation now comes from `POST /v1/blueprints/recommend` over the
in-progress fields (describe object or pasted TOML), the daemon's
`create_topic` gained the `blueprint`/`time_budget_minutes` body fields the
wizard sends, and the override still travels via the advance body so an
accepted recommendation keeps `recommended` provenance. Post-rebase gate:
pytest 1186 passed + 1 skipped; vitest 261; Playwright e2e 60; build clean.

Baseline commands: `python3 -m pytest`; `cd web && npm run test -- --run`;
`npm run e2e`; `npm run build`.
