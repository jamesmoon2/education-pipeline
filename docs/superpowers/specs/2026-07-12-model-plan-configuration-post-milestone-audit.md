# Model-Plan Configuration — Post-Milestone Audit & Next-Milestone Proposal

- **Date:** 2026-07-12
- **Auditor:** Wave-5 final review (Fable), recorded here per the plan's
  closeout task; independent of the individual task implementers.
- **Base:** `HEAD` at the milestone gate commit `0d5f9f8` (Wave 5 code
  commit); Wave Log rows 0–5 in
  `docs/superpowers/plans/2026-07-11-model-plan-configuration.md`.
- **Mandate:** confirm the milestone's exit criterion against live code and
  the recorded gates, state every accepted limitation explicitly, and propose
  one coherent next milestone grounded in the PRD. This audit fixes nothing;
  findings are recorded, not repaired.

## 1. Verdict

The milestone is **closed and sound**. The spec's exit criterion — *a user
configures and executes a mixed-provider run entirely from the cockpit
(recommended defaults or per-stage provider/model/effort overrides, with
availability display, weak-configuration warnings, and manual operation as a
first-class choice) without editing TOML, while an advanced user can still
hand-edit the local TOML and have it take effect, with the effective
provider/model/effort recorded and displayed as run provenance* — is met and
proven by the Wave-5 acceptance e2e (`web/e2e/model-plan.spec.ts`, a
mixed-provider flow with recommended defaults, one per-stage override, one
manual stage, and exact provenance assertions, never touching TOML in the
UI path) plus TOML hand-edit round-trip regression tests over a real
`WorkspaceConfigSource`.

Every wave (0–5) was reviewed; **zero Critical or Important findings remain
open**. Three Criticals were found and fixed mid-milestone by task reviews
(§3.1), and the one recorded Wave-3 MUST-FIX was resolved in Wave 5 (§3.2).
The frozen-surface guard passed: no changes to `guides/` or
`guide_runtime/` since the Wave-0 gate, and the canonical fixture's
normalized SHA-256 is untouched.

## 2. Final gate (recorded results)

| Suite | Milestone start | Final gate (commit `0d5f9f8`) |
| --- | --- | --- |
| pytest | 404 | **478** |
| vitest | 79 | **114** |
| Playwright e2e | 38 | **41** |
| `npm run build` | clean | clean |

All waves gated on the full four-suite run before recording; no baseline
regression occurred at any gate. PRD §10 "P0 — Finish model-plan
configuration" is marked delivered with the Wave Log as closeout evidence.

## 3. What shipped

- **Wave 0 — audit hardening:** URL-scheme allowlist in the legacy Markdown
  renderer, CSP on the legacy HTML export and the cockpit shell, `.gitignore`
  drift cleaned (resolving F1/F2 of the previous milestone's audit).
- **Wave 1 — read API:** catalog-driven weak-config warnings in `config.py`;
  `ConfigSource` abstraction so the daemon re-reads catalog/plan from disk
  per request; `GET /v1/config/{providers,catalog,plan}` and
  `GET /v1/runs/{topic}/plan` with per-stage command preview.
- **Wave 2 — global writes + Settings:** `emit_model_plan_toml` (narrow,
  round-trip-tested emitter), atomic SHA-guarded `PUT /v1/config/plan`, the
  Settings page, and the shared `PlanStageRow` editor component.
- **Wave 3 — per-run overrides + provenance:** sparse per-run override file
  with validated overlay, fresh resolution at enqueue *and* execution,
  append-only `stage_provenance` in the run manifest,
  `PUT /v1/runs/{topic}/plan`, and the `RunPlanPanel` run-plan editor with
  command preview and provenance display.
- **Wave 4 — new-run entry point:** structured topic creation
  (`emit_topic_toml` + `POST /v1/topics` without raw TOML) and the New-run
  wizard replacing the paste-TOML empty state, reusing `RunPlanPanel`
  unmodified.
- **Wave 5 — acceptance + closeout:** the mixed-provider acceptance e2e with
  PATH-stubbed provider CLIs, TOML hand-edit regression tests, the MUST-FIX
  resolution (§3.2), a final-review fix batch, README cockpit docs, and the
  PRD §10 status update.

### 3.1 Criticals found and fixed mid-milestone

Recorded because they characterize where this design bites:

1. **Task 2.4 — Settings full-replace data loss.** SettingsPage seeded its
   override state from a field the global plan payload does not carry, so
   the full-replace Save silently wiped persisted overrides on untouched
   stages. Fixed (Settings seeds every non-local stage and transmits the
   complete plan) with a regression test.
2. **Task 3.2 — execution-time re-resolution inert.** `JobRunner.execute`
   read frozen Job fields and provider adapters ignore the stage-plan
   argument, so the designed queued-then-edited re-resolution did nothing.
   Fixed by re-stamping job provider/model/effort from the re-resolved plan
   at execution start, proven by a live-daemon integration test.
3. **Task 4.2 — RunPlanPanel mount race.** The wizard mounted the plan panel
   before run initialization completed; caught and fixed by e2e.

### 3.2 The Wave-3 MUST-FIX and its resolution

Editing global defaults could invalidate an existing run's stored overrides,
after which `GET /v1/runs/{topic}/plan` returned 400 and the run-plan UI
rendered only a load error with no in-UI recovery. Wave 5 resolved it with
`apply_overrides_lenient` (`config.py`): the run-plan GET never 400s on
stored-override content; the broken stage degrades per-stage, carrying
`override_error` (rendered `role="alert"` in `PlanStageRow`) with
`command: null`; enqueue/execution fail explicitly for that stage only; and
`PUT` rejects only the stages a request touches, so the per-row "Use
recommended" reset is the in-UI recovery.

## 4. Design decisions recorded (for future executors)

- **Invalidated stored overrides degrade, never silently fall back.** The
  displayed plan degrades to defaults with `override_error` and
  `command: null`, but enqueue/execution of that stage fails explicitly
  rather than silently running the fallback configuration. If a future
  milestone adds a "run anyway with defaults" affordance, revisit the
  command-preview semantics at the same time.
- **MUST-FIX recovery is proven by composition, not one e2e.** The recovery
  loop is covered by a server clear-while-broken test, a vitest alert-render
  test, and the existing reset-affordance test; no single e2e drives the full
  break→alert→reset→recovered loop end to end.
- **`source` vocabularies differ by surface.** The run-plan payload's
  `source` is `default | override`, while provenance records
  `default | override | manual`. Any future `source` value must change
  `read_api.py`, `web/src/api/types.ts`, and the provenance formatter
  together.

## 5. Accepted limitations (ACCEPT verdicts from final-review triage)

None of these block the milestone; each was explicitly triaged and accepted.

**Behavioral:**

- Task 1.1: an unknown catalog `quality` string ranks as `strong`
  (plan-mandated ordering; a typo in a hand-edited catalog masks a warning).
- Task 1.3: a broad `except ConfigError` around `get_runner` in the
  availability/command-preview paths.
- Custom per-stage `recommendation` hand-edits are not preserved across a
  Settings Save, and `PUT` run-plan replaces a stage's override wholesale
  rather than key-merging (both documented intent; cockpit-only users never
  have a custom recommendation to lose).
- A non-dict `PUT` body yields 500 rather than 400 (matches the existing
  PUT-builder pattern repo-wide; see §7 candidate).
- Emitter U+007F/DEL escaping is absent (unreachable for the ids-only
  schema).
- SHA TOCTOU between `load()` and `plan_sha256()` (benign for the loopback
  single-user daemon; the guard is advisory, not compare-and-swap).
- `emit_topic_toml`'s nested-`metadata` branch would emit invalid TOML
  (unreachable — `create_topic` never sets `metadata`; fix if metadata ever
  gains nesting).
- `create_topic` body-validation helpers duplicate `topics.py` internals.
- Wave-5 MUST-FIX message wording diverges between `read_api` and enqueue;
  a row can legitimately render dual `role="alert"` nodes (weak-config
  warning + `override_error`).
- `LOCAL_ONLY_STAGES` constant duplicated in `PlanStageRow` and
  `RunPlanPanel`.

**Test hygiene:**

- The e2e daemon-discovery poll is duplicated across specs (extract a shared
  fixture module when a third spec appears); `test_server` boot-helper
  duplication; one assertion-duplicative vitest case in
  `PlanStageRow.test.tsx`.

## 6. Surfaces confirmed clean

- **Frozen surfaces.** No commits touch `education_pipeline/guides/` or
  `education_pipeline/guide_runtime/` since the Wave-0 gate commit; the
  canonical fixture's normalized SHA-256 is unchanged.
- **Read/write discipline.** Wave 1 landed strictly read-only (verified in
  its wave review: `write_plan` stubbed to `NotImplementedError`, no PUT
  routes); all writes are atomic (temp file + `os.replace`) and the global
  write is SHA-guarded.
- **Import parity.** Structured topic creation converges on the same
  `save_topic_toml` → artifact-id validation → 409-on-conflict path as raw
  TOML import; the structured path bypasses no validation.
- **No new runtime dependencies**; the emitter is hand-written stdlib.

## 7. Next-milestone proposal

**Proposed milestone: "P0 — Establish deterministic release gates"** (PRD
§10), with a small Wave-0 hardening batch drawn from this audit's
NEXT-MILESTONE triage — mirroring how this milestone's Wave 0 absorbed the
previous audit's findings.

**Why this one.** With model-plan configuration delivered, two P0s remain
before the P1 tier opens, and release gates is the one this milestone's
output feeds directly: runs now carry provenance and an effective-plan
record, but export still cannot produce a reproducible quality report or
refuse to package invalid or privacy-leaking content. It is also the last
remaining engineering-gate blocker for PRD §11 (release criterion #6:
deterministic and model-based quality findings with actionable repair paths;
plus the "cannot silently package structurally invalid or privacy-leaking
content" gate). The alternative P1 candidates (first-run experience,
personalization UI, blueprint pedagogy) all sit behind the P0 tier by the
PRD's own ordering, and the validation subsystem already exists in
`guides/` with a waiver mechanism — this milestone is about surfacing and
enforcing it, not inventing it.

**Scope sketch:**

1. **Wave 0 — hardening from this audit's triage:**
   - *API hygiene batch:* non-dict PUT bodies → 400 across the PUT builders;
     decide and enforce strictness for unknown keys inside stage-override
     dicts (today a misspelled key persists silently and returns 200 as a
     no-op).
   - *Manifest write concurrency:* `_write_manifest` is a plain
     `write_text` with no lock and now has two writer classes (the HTTP
     ingest thread and the worker). Provenance made this real; release-gate
     findings will add a third writer. Make manifest writes atomic and
     serialized before layering findings onto the manifest. (Triage judged
     this milestone-scale work, which is exactly why it belongs at the front
     of the milestone that adds more manifest writers.)
2. **Core:** structured validator results with severities, surfaced at the
   responsible stage via the run status payload; rerun-after-repair;
   recorded waivers for remaining blockers (extending the existing guides
   waiver mechanism); export refuses to package content with unwaived
   blocking findings.
3. **Acceptance:** an e2e that drives a run with an injected validation
   failure through finding → repair → rerun → export, plus a
   deterministic-report reproducibility check.

**Exit criterion (from PRD §10):** export provides a clear, reproducible
quality report and cannot silently package structurally invalid or
privacy-leaking content.

Deferred with rationale: the remaining ACCEPT items in §5 stay accepted (all
are unreachable, loopback-benign, or documented intent); they should be
re-triaged only if their preconditions change (e.g. `metadata` nesting, a
multi-user daemon).
