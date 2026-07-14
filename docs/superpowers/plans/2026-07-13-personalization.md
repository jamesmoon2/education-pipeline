# Personalization Visible and Safe Implementation Plan

> **For Codex managers:** Implement this plan wave-by-wave using Codex subagents.
> Steps use checkbox (`- [ ]`) syntax for tracking. Each wave runs in a **fresh
> Codex task** with a **fresh manager**; the human starts the new task with the
> model named in the manager table and pastes the kickoff prompt returned by the
> previous wave's manager.

**Goal:** Make learner personalization visible, inspectable, and safe across
profile editing, deterministic goal tracing, optional model audit, cockpit
preview, and export without placing private profile details or local
personalization annotations in the public guide.

**Architecture:** Build five layers in dependency order: (1) one canonical
profile privacy/serialization/store engine, (2) API/CLI/cockpit profile surfaces
over that engine, (3) backward-compatible guide-source 1.1 annotations plus a
private hash-bound trace and a stripped public projection, (4) an optional audit
stage with safe deterministic projection into the public report, and (5) a
cockpit-only fit panel with end-to-end acceptance. Deterministic validation and
export remain model-free; audit remains optional and nonblocking.

**Tech Stack:** Python 3.11+ standard library only, pytest; React 18 +
TypeScript, Vite, vitest, Playwright; file-backed local workspace artifacts.

**Spec:**
`docs/superpowers/specs/2026-07-12-personalization-design.md`

## Global Constraints

- `education_pipeline/` remains **standard library only at runtime**. Do not add
  a dependency without prior issue-level approval.
- Strict TDD in every task: write and observe a failing focused test before
  implementation, then drive it green.
- Preserve the shipped real-run privacy refusal path while replacing its
  implementer-derived field selection. `target_learner` and recursive
  `metadata.*` remain protected.
- Sensitivity, publication permission, and exact leak detection are separate
  policies. Never infer that a low sensitivity tier makes raw profile data
  publishable.
- Private profile values may exist only in local profile, prompt, trace, and raw
  audit-response artifacts. They never appear in API errors/warnings, findings,
  logs, exported HTML, or the public quality report, except the explicitly
  opted-in publishable summary after the existing gate/waiver flow.
- The public guide is built from `public_guide_projection(guide)`. Privacy/static
  validation and export assemble the same projected object; source-only
  annotations must not reach the embedded guide JSON even as empty keys.
- Existing guide-source 1.0 canonical fixture bytes and hashes are frozen.
  Readers accept 1.0 and 1.1; existing manifests are never rewritten in place.
- Deterministic steps (validation, trace construction, finalize, export, report
  projection) never call a model.
- `audit` is optional: never add it to required `next_action`, never make it a
  prerequisite for finalize/export, and never let projected audit findings
  affect `effective_blocking` or waivers.
- All new writes are canonical and atomic (temp file in the target directory +
  `os.replace`). Compare-and-swap checks and the write occur under the same
  per-artifact lock.
- Preserve the `RunStore._manifest_write_lock` contract: it is non-reentrant;
  take it once and call only `_locked` primitives inside it. Never nest a public
  lock-taking wrapper.
- Never commit generated runs, real profiles, private prompts/traces/audit
  responses, tuned prompt libraries, Playwright output, or local workspace
  records. Fixtures use conspicuously synthetic planted values only.
- `web/`: `npm run build` is the type/lint gate; there is no eslint/prettier.
- Loopback daemon and Playwright suites may require execution outside the
  filesystem/network sandbox. `EPERM` on `127.0.0.1` is an environment failure;
  rerun with the approved narrow test command rather than changing product code.
- Do not touch unrelated dirty or untracked files. Stage and commit only the
  current task's reviewed files.

## Parallel Sub-Agent Protocol

- Each numbered task gets a fresh implementer sub-agent, then a fresh spec
  reviewer and code-quality reviewer. The implementer resolves review findings
  before the task is committed.
- Dispatch tasks concurrently only when the wave's **Dispatch** paragraph says
  they are parallel-safe. Maximum: three active implementers plus the manager.
- Freeze interfaces named in the wave before parallel dispatch. Downstream
  agents implement against the frozen contract and do not redesign it locally.
- Hot files have one owner per wave: `education_pipeline/runs.py`,
  `education_pipeline/daemon/server.py`, `web/src/api/types.ts`,
  `web/src/api/client.ts`, `web/src/pages/RunBoardPage.tsx`, and
  `web/src/styles.css`. No two active agents edit the same production or test
  file.
- Pure-core agents land before lifecycle/integration agents. The manager owns
  package exports and resolves cross-task integration after each parallel
  barrier.
- No concurrent git mutations. Agents may work concurrently on disjoint files,
  but the manager stages and lands reviewed commits serially, one scoped task at
  a time.
- Every implementer reports: RED command/result, GREEN command/result, files
  changed, interface deviations, and commit recommendation.

---

## Wave Protocol (manager instructions — read first, every wave)

This plan executes as **five waves (0–4)**. Each wave is one independent Codex
task driven by a manager that explicitly uses Codex subagents: a fresh
implementer per task followed by fresh spec and code-quality reviewers.

### Trust the Wave Log — do not retest prior waves

- A wave **closes** by running the full four-suite gate (`python3 -m pytest`,
  `cd web && npm run test -- --run`, `npm run e2e`, `npm run build`) and
  recording the results in the Wave Log below.
- A wave **opens** by reading this plan and the Wave Log **and nothing else**.
  The recorded gate of the previous wave is canonical truth. **Do NOT re-run any
  test suite, re-verify prior waves' work, or re-read prior waves' diffs at
  session start.** Start dispatching the first task immediately. Individual
  tasks still run their own narrow test files during TDD.
- If HEAD or the working tree does not match the last Wave Log handoff, stop and
  reconcile the unexpected state before dispatching. Do not silently absorb
  unrelated changes.

### Wave-close checklist (the manager does this personally, in order)

1. Run the four-suite gate once; all suites green. Fix or dispatch fixes until
   green.
2. **Update this plan document itself:** tick every completed checkbox, fill in
   this wave's Wave Log row (commits, suite counts, deviations, and anything the
   next wave must know), and correct later-wave instructions invalidated by the
   implementation. The Wave Log is the handoff artifact.
3. Commit the plan-document update.
4. **Return in the final response, for the human:**
   - the recommended **Codex manager model for the next wave** (GPT-5.6 Sol or
     GPT-5.6 Terra) and **reasoning effort**, with a one-sentence rationale tied
     to that wave; and
   - the **verbatim kickoff prompt** below with the next wave number.
5. Stop. Do not begin the next wave in the same session.

### Kickoff prompt template

```text
Act as the Codex manager for Wave N of the personalization milestone. Read
docs/superpowers/plans/2026-07-13-personalization.md and execute only Wave N.

Use Codex subagents exactly as the plan specifies: fresh implementers for
bounded tasks, followed by fresh spec and code-quality reviewers. Parallelize
only tasks that the wave marks parallel-safe, respect hot-file ownership, and
keep all git staging and commits serialized through the manager.

The Wave Log records all prior waves' gates. Treat it as canonical truth: do not
re-run or re-verify prior waves before starting. Begin with the first eligible
Wave N task, require RED then GREEN evidence from every implementer, resolve all
review findings, and land only reviewed task-scoped commits.

At wave close, personally run the four-suite gate, update and commit the plan
and Wave Log, then stop. In your final response, give the next wave's recommended
Codex model and reasoning effort plus this complete kickoff prompt updated to
the next wave number. Do not begin the next wave.
```

The final wave returns a milestone summary and a post-milestone-audit
recommendation instead of another kickoff prompt.

### Manager model recommendations

| Wave | Manager | Why |
| --- | --- | --- |
| 0 | GPT-5.6 Sol — High | Privacy normalization, recursive metadata, canonical serialization, and CAS storage establish security-critical invariants. |
| 1 | GPT-5.6 Terra — High | Terra is the pragmatic Codex workhorse for broad but concrete API/CLI/form delivery; parallel ownership and stale-edit UX are the main risks. |
| 2 | GPT-5.6 Sol — High | Schema compatibility, canonical hashes, private trace freshness, and export stripping have subtle cross-system failure modes. |
| 3 | GPT-5.6 Sol — High | Optional-stage state, hostile model output, and deterministic report projection require careful adversarial reasoning. |
| 4 | GPT-5.6 Sol — High | Preview-frame messaging, multi-state UI, privacy acceptance, and final audit need a strong cross-surface manager. |

### Wave Log

| Wave | Status | Commits | pytest | vitest | e2e | build | Notes for the next wave |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | **complete** | code HEAD `929cc8cd` | 600 | 127 | 42 | clean | Fresh gate run 2026-07-13. Planning/spec edits are docs-only; unrelated pre-existing untracked files are outside scope. |
| 0 — Privacy + profile store | **complete** | planning `eb44004`; code `dc75c54`, `9124a7b`, `e5b0f17` | 666 | 127 | 42 | clean | Privacy/codec, atomic store, and run integration are frozen. Task 0.3 expanded internally to NFC normalization and shared validation hashing with no public signature/schema change. Unrelated concurrent docs commit `7e67007` was preserved; see closeout notes. |
| 1 — Profile product surface | pending | — | — | — | — | — | — |
| 2 — Guide 1.1 + trace | pending | — | — | — | — | — | — |
| 3 — Optional audit + report | pending | — | — | — | — | — | — |
| 4 — Fit panel + acceptance | pending | — | — | — | — | — | — |

Baseline commands: `python3 -m pytest` → 600; `cd web && npm run test --
--run` → 127; `npm run e2e` → 42; `npm run build` → clean.

### Initial Wave 0 planning bootstrap

The recorded code baseline intentionally precedes the revised spec and this
new plan. At the start of Wave 0, before dispatching Task 0.1, the manager must:

1. Review and commit only
   `docs/superpowers/specs/2026-07-12-personalization-design.md` and
   `docs/superpowers/plans/2026-07-13-personalization.md` as the scoped planning
   baseline.
2. Preserve every unrelated modified or untracked file exactly as found.
3. Record the planning commit in the Wave 0 notes. This bootstrap does not
   rerun the four-suite gate because the recorded code baseline is already
   green and the bootstrap is documentation-only.

**Wave 0 kickoff:** GPT-5.6 Sol with High reasoning. Use the kickoff template
with `N = 0`.

---

## Frozen Cross-Wave Contracts

These shapes are implementation details settled by this plan so parallel agents
can work without reopening design.

### Profile records

- `ProfileRecord(profile, canonical_bytes, content_sha256)` is the store/API
  value. The SHA is over the exact canonical UTF-8 TOML bytes.
- Structured metadata accepts only the recursive JSON/TOML intersection:
  string, Boolean, integer, finite float, list, and string-keyed mapping. Reject
  nulls, dates/times, bytes, non-finite floats, and unsupported objects with a
  safe field path.
- GET never rewrites a legacy noncanonical profile. Create, update, import, and
  duplicate write canonical bytes. Attaching a profile snapshots its current
  exact source bytes, so historical runs remain immutable.

### Profile HTTP API

```text
GET  /v1/profiles
GET  /v1/profiles/{id}
POST /v1/profiles/preview
PUT  /v1/profiles/{id}
POST /v1/profiles/{id}/duplicate
```

- List payload: `{"profiles": [{"id", "attached_topic_count"}, ...]}`.
- Detail payload: `{id, parsed, sensitivity, content_sha256, warnings,
  attached_topic_count}`.
- Preview body: `{profile}`. Response: `{parsed, prompt_context,
  publishable_summary, sensitivity, warnings}`. It performs no write and lets
  the UI show the actual Python renderers without duplicating policy in TS.
- PUT body: `{profile, base_sha256}`. `profile.id` equals the path id. Create
  requires absent target + `base_sha256: null` and returns 201. Update requires
  the exact current SHA and returns 200. Stale/existing conflicts are 409 and
  expose only the fresh hash in structured details.
- Duplicate body: `{new_id}`. Source exists, target is absent, embedded id is
  replaced, then the canonical target is atomically created; return 201.
- Raw TOML import remains supported and delegates to the same canonical store.

### Guide source and public projection

- Source 1.1 adds `Outcome.serves_goals`, `Module.serves_goals`, and
  `Course.goal_exclusions` with `{goal_id, reason}`. Goal texts never enter
  guide source.
- New personalized runs created before the spec prompt use content contract
  1.1. Existing 1.0 manifests never migrate; later profile attachment yields
  the intended no-annotation warning rather than a hidden contract rewrite.
- Empty annotation fields are omitted canonically. The frozen 1.0 fixture bytes
  and hash do not change.
- `public_guide_projection` removes all annotations but retains the declared
  source schema version. Document assembly defensively projects before embedding
  JSON. Python and JS runtimes accept 1.0 and stripped 1.1; unknown versions
  still fail.

### Personalization trace and cockpit payload

- Local `reports/personalization-trace.json` contains private goal text and is
  bound to canonical source-guide SHA, exact profile-snapshot SHA, and trace
  schema version. Draft validation may write this path for inspection; final
  validation replaces it with the canonical final-candidate trace. Only the
  final validation/release state is freshness-bound to this single current
  trace, so that replacement never regresses draft validation or `next_action`.
  It never ships beside an export.
- Duplicate goal text remains distinct by position. Repeating one goal id within
  a single module/outcome or in multiple exclusion records is blocking; serving
  the same goal from different modules/outcomes is valid. A served goal may also
  retain an exclusion record; service already covers it and the trace preserves
  both facts without inventing another rule.
- Public reports receive only the safe trace projection/hash: opaque goal ids,
  serving element ids, counts, and safe finding ids — no private trace-byte hash,
  goal text, or exclusion reason.
- Public sidecars never expose a canonical **source** guide hash because source
  1.1 includes private exclusion reasons. Local validation and waiver artifacts
  retain source hashes; public report fields use the public-guide-projection SHA
  or omit the hash. Changing only an exclusion reason must not change any
  public source-hash field.
- `GET /v1/runs/{topic}/personalization` is the authenticated local cockpit
  aggregate. It returns profile/trace/audit/export states plus local goals,
  facets, exclusions, evidence, generic flags, and safe findings. The browser
  never parses workspace artifacts itself.

### Optional audit controls

```text
POST /v1/runs/{topic}/audit                 # prepare/rebuild prompt explicitly
GET  /v1/runs/{topic}/stages/audit          # existing generic stage read
POST /v1/runs/{topic}/stages/audit/response # existing generic ingest
POST /v1/runs/{topic}/stages/audit/approve  # existing generic approval
POST /v1/jobs {topic_id, stage: "audit"}    # existing provider job route
```

`advance` and primary `next_action` never prepare or require audit. The CLI
equivalent is `education-pipeline audit TOPIC`, which prepares or rebuilds the
prompt and prints the normal manual/provider next step.

Audit preparation requires a current final validation, an attached profile
snapshot, and a current personalization trace. A no-profile run stays valid and
exportable but reports audit as unavailable with fixed safe text. Fixed local
paths are:

```text
prompts/audit.prompt.md
responses/audit.response.json
approved/audit.json
reports/personalization-audit-projection.json
```

Audit response/approved artifacts use `application/json`, never the guide MIME
type. Audit staleness takes precedence over ordinary file-derived stage state.
Explicit provider enqueue for `stage=audit` refuses a missing or stale prompt.
An audit is current only when one approval event binds the three current input
hashes, the exact approved-response bytes, and the exact safe-projection bytes;
all must match on read. Writes are ordered so a failure between approved and
projection files yields stale, never partially current, state.

### Finding and export-state integration

- Keep `final-validation.json` deterministic and audit-free. One shared
  combined-findings accessor augments it with the current safe audit projection
  for daemon presentation, CLI `findings`/`report`, and public sidecar assembly.
- Preserve existing `findings_by_stage` blocker/error semantics. Audit warnings
  surface through additive `audit.finding_count` and the aggregate
  personalization payload; do not silently redefine the old field.
- Audit findings carry `stage="audit"` plus `source_stage="repair"` for evidence
  navigation. The cockpit opens guide evidence, not a guide JSON pointer inside
  the audit response.
- `export_state() -> missing | current | stale` compares a canonical export-input
  digest over public guide projection, canonical final-validation report bytes,
  validator/report schema versions, waiver result, explicit audit state, current
  safe audit projection, safe trace projection, `QUALITY_REPORT_SCHEMA_VERSION`,
  and runtime asset hashes. Audit approval/invalidation after export changes
  state only; it never mutates existing HTML or sidecar bytes.
- Existing schema-v1 sidecars are stale-for-re-export but do not change
  `next_action == done`.
- Public audit state maps as follows: no successful approval event is `not_run`,
  a fully bound matching approval/projection is `current`, and any previously
  approved audit whose bindings no longer match is `stale`. Merely preparing a
  prompt or ingesting an unapproved response does not change public audit state
  or stale an export. Re-preparing identical inputs does not invalidate an
  already-current approval.

---

## File Structure

| Area | Files |
| --- | --- |
| Profile policy/codec | `education_pipeline/privacy.py` (new), `education_pipeline/profiles.py` |
| Profile store | `education_pipeline/workspace.py` |
| Profile API/CLI | `education_pipeline/daemon/{read_api,write_api,server}.py`, `education_pipeline/cli.py` |
| Profiles cockpit | `web/src/pages/{ProfilesPage,ProfileEditorPage}.tsx` (new), `web/src/components/{ProfileForm,SensitivityBadge,ProfilePrivacyPreview}.tsx` (new), API types/client, `App.tsx` |
| Guide source 1.1 | `education_pipeline/guides/{model,parse,canonical,contract}.py`, `education_pipeline/prompts.py`, `education_pipeline/runs.py` |
| Trace/public boundary | `education_pipeline/guides/personalization.py` (new), `guides/{projection,document,static_checks,validation,reports}.py`, runtime Python/JS |
| Audit | `education_pipeline/guides/audit.py` (new), `config.py`, `prompts.py`, `runs.py`, daemon/CLI adapters |
| Public report | `education_pipeline/guides/quality_report.py`, export path in `runs.py` |
| Cockpit fit/audit | `AuditControls.tsx`, `PersonalizationPanel.tsx` (new), `GuidePreviewFrame.tsx`, `RunBoardPage.tsx`, runtime message bridge |
| Acceptance | `tests/test_personalization_acceptance.py` (new), `web/e2e/personalization.spec.ts` (new) |

---

# Wave 0 — Privacy policy and canonical profile store

**Outcome:** one tested engine owns profile classification, structured mapping,
canonical TOML, protected-value extraction, warnings, atomic CRUD, hashes, and
the existing run-validation denylist.

**Inherited debt absorbed:** the predecessor milestone deliberately shipped an
implementer-derived `_private_profile_values` field list and scheduled its policy
definition here. No unrelated predecessor cleanup enters this wave.

**Dispatch:** Task 0.1 is the interface freeze. After it lands, Tasks 0.2 and
0.3 are parallel-safe: 0.2 owns `workspace.py`; 0.3 owns `runs.py`. They must not
share test files.

### Task 0.1: Profile privacy policy and canonical codec

**Files:**

- Create: `education_pipeline/privacy.py`
- Modify: `education_pipeline/profiles.py`
- Test: `tests/test_profiles.py`

**Produces:** `SensitivityTier`, `ProfileWarning`, shared private-value
normalization/fingerprinting, `profile_field_sensitivity`,
`profile_private_values`, `profile_summary_warnings`, `profile_to_dict`,
`canonical_profile_toml_bytes`, and canonical SHA helper.

- [x] Write RED tests for all dataclass leaf paths plus `metadata.*`, recursive
  metadata traversal, `target_learner`/goal protection, normalization and
  deduplication, low-risk generic exclusions, safe summary warnings, JSON/TOML
  metadata restrictions, and deterministic mapping→TOML→mapping round trip.
- [x] Run `python3 -m pytest tests/test_profiles.py -v` and record the intended
  failures.
- [x] Implement the pure policy/codec. Warning payloads contain only `code`,
  field path, and 12-character fingerprint. Preserve first-field order while
  deduplicating normalized protected values.
- [x] Run the focused suite green and add one independent canonical-byte test
  using differently ordered equivalent input mappings.
- [x] Fresh spec review, privacy/adversarial review, code-quality review; resolve
  findings; manager lands `feat(profiles): add canonical privacy policy and codec`.

### Task 0.2: Atomic canonical ProfileStore

**Files:**

- Modify: `education_pipeline/workspace.py`
- Test: `tests/test_workspace.py`

**Produces:** `ProfileRecord`, safe write-conflict value, record read,
create/update/duplicate/import adapters, attachment counts, atomic canonical
writes, and immutable raw-byte snapshot attachment.

- [x] Write RED tests for canonical create, compare-and-swap update, stale hash,
  duplicate id replacement/collision, write failure preserving old bytes,
  attachment counts, legacy GET without rewrite, and snapshot independence.
- [x] Run `python3 -m pytest tests/test_workspace.py -v` and capture RED.
- [x] Implement a per-profile lock and temp-file/`os.replace` writer. Keep hash
  comparison and replacement in one critical section. Convert existing import
  and save entry points into adapters over the canonical engine.
- [x] Run the focused suite green; include a small concurrent stale-writer test.
- [x] Fresh spec/code review; manager lands
  `feat(profiles): add atomic canonical profile storage`.

### Task 0.3: Real-run privacy integration and regression record

**Files:**

- Modify: `education_pipeline/runs.py`
- Modify: `education_pipeline/guides/validation.py`
- Test: new `tests/test_personalization_privacy.py`
- Test: focused additions in `tests/test_release_gate_acceptance.py` only if the
  existing acceptance helper is required

**Produces:** existing `_private_profile_values` becomes a compatibility wrapper
over `profile_private_values`; run-aware validation passes explicit profile
presence; standalone validation does not manufacture `no_profile`.

This task freezes and creates
`PersonalizationValidationContext(profile_present, authoritative_goal_ids=())`.
Wave 2 extends use of the frozen shape with authoritative goal ids; it does not
replace the interface.

- [x] Write RED tests proving planted `target_learner`, learning-goal, and nested
  metadata leaks block draft/final export; generic low-risk terms do not; and no
  private input appears in diagnostics, report bytes, or logs.
- [x] Run the new focused test plus the existing release-gate privacy acceptance
  test and observe the new RED cases.
- [x] Rewire the shared engine with minimal `runs.py` churn. Do not change waiver
  semantics or duplicate normalization in `validation.py`.
- [x] Run `python3 -m pytest tests/test_personalization_privacy.py
  tests/test_release_gate_acceptance.py tests/test_guide_validation.py -v` green.
- [x] Fresh spec/privacy/code review; manager lands
  `refactor(privacy): centralize attached-profile leak policy`.

### Wave 0 close

- [x] Complete the Wave 0 row using the Wave Protocol and stop.
- Suggested next manager: **GPT-5.6 Terra with High reasoning** for parallel
  API/CLI/cockpit delivery over the now-frozen profile engine.

### Wave 0 closeout notes

- **Planning bootstrap:** `eb44004` committed only this plan and
  `docs/superpowers/specs/2026-07-12-personalization-design.md`. The review also
  corrected two stale Wave 1–5 references to Wave 0–4. Per the bootstrap
  instruction, no baseline suite was rerun for that documentation-only commit.
- **Implementation:** `dc75c54` froze the privacy policy and canonical codec;
  `9124a7b` added the atomic canonical `ProfileStore`; `e5b0f17` centralized
  attached-profile leak policy and explicit run-aware profile presence.
- **TDD/review evidence:** Task 0.1 closed at 47 focused profile tests; Task 0.2
  closed at 21 focused workspace tests; Task 0.3 closed at 84 focused
  profile/privacy/release/validation tests. Every task received fresh spec and
  code-quality review; the plan-required privacy/adversarial reviews for Tasks
  0.1 and 0.3 also approved. All reported findings were regression-tested and
  resolved before commit.
- **Four-suite gate:** `python3 -m pytest` → 666 passed; `cd web && npm run
  test -- --run` → 127 passed; `npm run e2e` → 42 passed; `npm run build`
  → clean. The first sandboxed pytest attempt hit the documented loopback
  `EPERM`; the exact full command was rerun with loopback permission and passed.
- **Deviations:** Task 0.3 was deliberately expanded to
  `education_pipeline/privacy.py` and `tests/test_profiles.py` after adversarial
  review found canonical-Unicode equivalence belonged in the shared policy.
  Normalization is now NFC → whitespace collapse → casefold, and the internal
  `validation_guide_sha256` helper keeps validation and run report-state hashes
  identical for valid and invalid-scalar inputs. No public function signature,
  persisted schema, waiver contract, or frozen
  `PersonalizationValidationContext(profile_present,
  authoritative_goal_ids=())` shape changed. No findings are deferred.
- **Concurrent unrelated state:** docs-only commit `7e67007` landed between the
  planning and Task 0.1 commits and was preserved without modification. The
  pre-existing untracked `docs/design-demos/`, `docs/design-system.md`, and
  `docs/superpowers/wave-runner-paper-draft.md` remain untouched.
- **Wave 1 handoff:** use `profile_field_sensitivity`,
  `profile_summary_warnings`, `profile_to_dict`, and canonical codec helpers
  directly from `education_pipeline.privacy`. The frozen store surface is
  `read_profile_record`, `create_profile`, `update_profile`,
  `duplicate_profile`, and `profile_attachment_count`; stale/existing writes
  raise value-free `ProfileWriteConflict(current_sha256)`. Legacy GET remains
  non-mutating, new writes are canonical/atomic, attachments retain exact source
  bytes, metadata is deeply immutable, and warnings use the safe `metadata.*`
  path. Wave 1 has not started.

---

# Wave 1 — Structured profile API, CLI, and Profiles cockpit

**Outcome:** users can create, inspect, edit, duplicate, preview, and attach
profiles without editing files; all surfaces share Wave 0's engine and preserve
run snapshots.

**Dispatch:** Tasks 1.1 and 1.2 are parallel-safe after the manager confirms the
Wave 0 store interface. Task 1.3 starts after 1.1 freezes HTTP payloads. Task 1.4
starts after 1.3 and owns the wave's Playwright file.

### Task 1.1: Structured daemon profile API

**Files:**

- Modify: `education_pipeline/daemon/read_api.py`
- Modify: `education_pipeline/daemon/write_api.py`
- Modify: `education_pipeline/daemon/server.py`
- Test: `tests/test_write_api.py`, `tests/test_server.py`

**Produces:** every route and payload under **Profile HTTP API**, including the
non-mutating preview route and list-summary migration.

- [ ] Write RED pure-adapter and HTTP tests for success/status shapes, path/body
  id mismatch, wrong nested types, unknown keys, create/update preconditions,
  stale hash redaction, duplicate collisions, preview non-mutation, canonical
  raw import, and attached counts.
- [ ] Run focused daemon tests and observe RED.
- [ ] Implement thin adapters over `ProfileStore`; do not add serializer or
  warning-policy copies. Route unexpected exceptions through existing safe
  envelopes.
- [ ] Run `python3 -m pytest tests/test_write_api.py tests/test_server.py -v`
  green.
- [ ] Fresh spec/API/security/code review; manager lands
  `feat(api): add structured profile management`.

### Task 1.2: Profile CLI parity

**Files:**

- Modify: `education_pipeline/cli.py`
- Test: `tests/test_cli.py`

**Produces:** `profile show`, `profile edit --from-file`, and `profile
duplicate`, retaining existing list/import/attach commands.

- [ ] Write RED CLI tests for output, canonical edit, duplicate, stale/conflict
  exit 2, missing source, and zero private values in errors.
- [ ] Run `python3 -m pytest tests/test_cli.py -k profile -v` and observe RED.
- [ ] Implement commands only over the canonical store API.
- [ ] Run focused profile CLI tests green.
- [ ] Fresh spec/code review; manager lands
  `feat(cli): add structured profile commands`.

### Task 1.3: Profiles pages and structured editor

**Files:**

- Modify: `web/src/api/types.ts`, `web/src/api/client.ts`,
  `web/src/api/client.test.ts`
- Modify: `web/src/App.tsx`, `web/src/styles.css`
- Create: `web/src/pages/ProfilesPage.tsx`, `ProfileEditorPage.tsx` and tests
- Create: `web/src/components/ProfileForm.tsx`, `SensitivityBadge.tsx`,
  `ProfilePrivacyPreview.tsx` and tests
- Modify consumers: `TopicListPage.tsx`, `NewRunPage.tsx`,
  `AttachProfileControl.tsx` and tests

**Produces:** `/profiles`, `/profiles/new`, `/profiles/:profileId`; every schema
leaf in six sections; recursive metadata editor; field-level tiers; actual server
prompt/export preview; canonical save/duplicate; stale-edit recovery that keeps
unsaved input.

- [ ] Write RED API-client, component, and page tests for all six sections,
  arrays/nested preferences/metadata, safe warnings, preview debounce/loading,
  create/edit/duplicate, dirty-form navigation, 409 reload choice, and migrated
  summary-object consumers.
- [ ] Run `cd web && npm run test -- --run` and capture focused RED failures.
- [ ] Implement against the frozen HTTP shapes. Type every field explicitly;
  do not reproduce Python validation or prompt rendering in TypeScript.
- [ ] Run vitest and `npm run build` green.
- [ ] Fresh accessibility/spec/code review; manager lands
  `feat(cockpit): add structured profiles workspace`.

### Task 1.4: Profiles cockpit acceptance

**Files:**

- Create: `web/e2e/profiles.spec.ts`
- Modify: `web/e2e/helpers/daemon.ts` only for genuinely reusable setup

- [ ] Write RED Playwright flows for create→edit→duplicate→attach, prompt/export
  preview, warning rendering, snapshot immutability, stale conflict, and axe scans
  of list/new/edit/warning/conflict states.
- [ ] Run `cd web && npx playwright test e2e/profiles.spec.ts` and observe RED.
- [ ] Fix only product gaps within Wave 1 scope; do not start trace/audit work.
- [ ] Run the focused e2e green and independently inspect saved profile/snapshot
  bytes in the fixture workspace.
- [ ] Fresh acceptance review; manager lands
  `test(cockpit): cover structured profile workflow`.

### Wave 1 close

- [ ] Complete the Wave 1 row using the Wave Protocol and stop.
- Suggested next manager: **GPT-5.6 Sol with High reasoning** for the
  guide-version, canonical-hash, private-trace, and public-projection boundary.

---

# Wave 2 — Guide source 1.1, deterministic trace, and public projection

**Outcome:** new profiled guide runs use source 1.1 with opaque goal references;
local trace artifacts bind goals to content; invalid/missing traces fail closed;
exported HTML and sidecars contain no local annotations, goal text, or exclusion
reason.

**Dispatch:** Task 2.1 freezes guide dataclasses/parser/canonical behavior. After
it lands, Tasks 2.2 and 2.4 run in parallel. As soon as 2.2 freezes the goal/trace
API, Task 2.3 joins while 2.4 continues. Task 2.5 is the sole
`runs.py`/validation integrator after all three land.

### Task 2.1: Backward-compatible guide source 1.1

**Files:**

- Modify: `education_pipeline/guides/model.py`, `parse.py`, `canonical.py`
- Test: `tests/test_guide_parse.py`, `tests/test_guide_canonical.py`
- Create: synthetic `tests/fixtures/guides/feedback-loops.personalized.guide.json`

**Produces:** `GoalExclusion`, optional module/outcome `serves_goals`, course
`goal_exclusions`, strict 1.0/1.1 readers, authored-version preservation, and
version-aware omission of empty annotations.

- [ ] Write RED tests: frozen 1.0 canonical hash unchanged; 1.0 rejects authored
  annotation keys; 1.1 round trip; unknown versions fail; invalid goal-id/reason
  shapes fail; duplicate/dangling ids survive parsing for personalization rules.
- [ ] Run focused parse/canonical tests and observe RED.
- [ ] Implement without changing existing fixture bytes.
- [ ] Run focused suites green and print the unchanged 1.0 fixture SHA in the
  task report.
- [ ] Fresh compatibility/spec/code review; manager lands
  `feat(guides): add source schema 1.1 annotations`.

### Task 2.2: Deterministic personalization trace core

**Files:**

- Create: `education_pipeline/guides/personalization.py`
- Create: `tests/test_guide_personalization.py`

**Produces:** positional authoritative goals, facet activation, annotation
indexing, private trace model/parser/canonical bytes, safe trace projection/hash,
and freshness comparison helpers.

- [ ] Write RED tests for duplicate goal text retaining separate positional ids,
  exact facet activation, legal multi-module service, duplicate-within-field,
  exclusions, deterministic bytes across mapping/order variations, trace parser
  rejection, and absence of goal text/reasons/private hashes from safe projection.
- [ ] Run the new test file and observe RED.
- [ ] Implement pure functions only; no filesystem or `RunStore` calls.
- [ ] Run focused tests green, including independent-workspace byte equality.
- [ ] Fresh privacy/spec/code review; manager lands
  `feat(personalization): add deterministic local trace model`.

### Task 2.3: Versioned prompt and guide-contract propagation

**Files:**

- Modify: `education_pipeline/prompts.py`
- Modify: `education_pipeline/guides/contract.py`
- Test: `tests/test_prompts.py`, `tests/test_guide_contract.py`

**Produces:** private prompt mapping `goal-001 → text`, active facet instructions,
opaque-id-only draft/repair output contracts, and 1.0/1.1 contract preservation.

- [ ] Write RED tests that personalized spec/outline/draft/repair prompts carry
  the authoritative mapping but demand only ids in guide JSON; unprofiled/default
  paths remain 1.0; contracts accept/preserve both versions.
- [ ] Run focused prompt/contract tests and observe RED.
- [ ] Implement `guide_schema_version` propagation with a 1.0-compatible default.
  Do not change the QA contract.
- [ ] Run focused tests green and inspect prompt snapshots for private/public
  instruction separation.
- [ ] Fresh prompt/spec/code review; manager lands
  `feat(prompts): carry opaque personalization goals`.

### Task 2.4: Public guide projection and runtime compatibility

**Files:**

- Modify: `education_pipeline/guides/projection.py`, `document.py`,
  `static_checks.py`
- Modify: `education_pipeline/guide_runtime/__init__.py`,
  `guide_runtime/assets/runtime.js`
- Test: `tests/test_guide_projection.py`, `test_guide_document.py`,
  new `test_guide_static_checks.py`; focused cases in
  `web/e2e/guide-runtime.spec.ts`

**Produces:** `public_guide_projection`, defensive projection in document
assembly, `guide_to_dict` payload serialization, and strict runtime acceptance of
1.0/1.1 only.

- [ ] Write RED tests proving source retains annotations while projected and
  embedded JSON omit annotation keys/reasons; static checks inspect the exact
  projected document; both versions load; unknown versions fail.
- [ ] Run focused Python/runtime tests and observe RED.
- [ ] Implement using `dataclasses.replace`; never add `allow-same-origin` or
  weaken runtime version checks.
- [ ] Run focused Python tests plus relevant `guide-runtime.spec.ts` cases green.
- [ ] Fresh privacy/runtime/code review; manager lands
  `feat(export): strip local personalization metadata`.

### Task 2.5: Validation, trace persistence, and RunStore integration

**Files:**

- Modify: `education_pipeline/guides/validation.py`, `reports.py`
- Modify: `education_pipeline/runs.py`
- Test: `tests/test_guide_validation.py`, `tests/test_runs.py`,
  `tests/test_export.py`, `tests/test_quality_report.py`

**Produces:** use of Wave 0's `PersonalizationValidationContext` with
authoritative goal ids, named trace rules/severities, complete content-contract
1.1 selection for new profiled runs, trace path/write/state, profile-aware
report freshness, conditional missing/stale-trace refusal, and validation over
the same public projection export writes.

- [ ] Write RED tests for every named rule and exact duplicate semantics; new
  profiled versus existing 1.0 run selection; trace writes on draft/final
  validation; profile snapshot replacement staling report/trace; malformed or
  stale trace refusing finalize/export when learning goals are nonempty; no-goal
  profiles retaining facet trace observability without trace-gating release;
  final validation replacing the draft trace without regressing draft status or
  `next_action`; malformed annotations producing a retrievable current report
  and `next_action=resolve_findings` rather than a validation loop; canonical
  final source retaining opaque annotations while public outputs omit them.
- [ ] Run focused validation/run/export tests and observe RED.
- [ ] Add `ContentContract.interactive_guide_v1_1`, update
  `_validate_content_contract`, derive draft/repair MIME types from the manifest
  contract in `stage_paths`, and preserve `GUIDE_V1_CONTENT_TYPE` as the 1.0
  compatibility constant. Test existing 1.0 manifests, new profiled 1.1
  manifests, and response content types end to end.
- [ ] Implement one shared validation-artifact computation. Write a trace for
  every attached profile so facets stay inspectable. Draft may write the shared
  path, but final validation replaces it; only final release freshness depends
  on that current trace, never draft report status. A final report requires a
  current trace to release only when `learning_goals` is nonempty; no-goal
  profile snapshot freshness remains bound separately as a local validation
  input. A report remains current for its guide/profile validation inputs even
  when trace construction fails; trace integrity closes the gate through the
  report's blocking finding rather than making the report itself perpetually
  stale. Keep prior malformed-source trace artifacts stale rather than silently
  deleting evidence.
- [ ] Run focused suites green and re-run the existing checked-document/export
  identity test and release-gate acceptance.
- [ ] Fresh adversarial/spec/code review of all Wave 2 diffs; manager lands
  `feat(runs): persist and enforce personalization traces`.

### Wave 2 close

- [ ] Complete the Wave 2 row using the Wave Protocol and stop.
- Suggested next manager: **GPT-5.6 Sol with High reasoning** for optional-stage
  state, hostile model output, and safe public report projection.

---

# Wave 3 — Optional audit lifecycle and safe quality-report projection

**Outcome:** users may explicitly run a hash-bound personalization audit before
or after finalize; hostile model narratives remain local; safe fixed findings
can appear in cockpit/reporting without changing the deterministic gate.

**Dispatch:** Tasks 3.1 and 3.2 are parallel-safe: 3.1 owns stage/config
topology; 3.2 owns the new pure audit module. Task 3.3 integrates after both.
Tasks 3.4 and 3.5 then run sequentially because both consume lifecycle state.

### Task 3.1: Optional-stage and model-plan topology

**Files:**

- Modify: `education_pipeline/config.py`, `education_pipeline/runs.py`
- Modify: `config/model-plan.example.toml`
- Modify as required: daemon plan payloads/jobs and Settings stage assumptions
- Test: `tests/test_config.py`, `tests/test_runs.py`, job/provider tests, focused
  PlanStageRow/Settings tests

**Produces:** `REQUIRED_STAGES`, `OPTIONAL_STAGES`, `SUPPORTED_STAGES`; audit in
direct/model-plan/provider APIs but not `REASONING_STAGES` or required
`next_action`; existing complete runs remain complete.

- [ ] Write RED tests for config parsing/overrides, direct audit stage support,
  no-audit status, unchanged required next action, existing-run compatibility,
  and Settings rendering audit as model-powered.
- [ ] Run focused Python/vitest tests and observe RED.
- [ ] Implement the topology without prompt/lifecycle behavior yet.
- [ ] Run focused suites green; verify every tuple/set consumer deliberately uses
  required, optional, or supported stages. Audit uses JSON response content type,
  and stale state takes precedence over `approved`/`response_ingested`.
- [ ] Fresh state-machine/spec/code review; manager lands
  `feat(stages): register optional audit stage`.

### Task 3.2: Strict audit response and safe projection core

**Files:**

- Create: `education_pipeline/guides/audit.py`
- Modify: `education_pipeline/guides/reports.py`
- Create: `tests/test_guide_audit.py`
- Test: focused backward-compatibility additions in `tests/test_guide_reports.py`

**Produces:** backward-compatible `Finding` serialization with `audit` stage and
optional `source_stage`; strict response parser, evidence-reference validation,
private string screening, application-owned location fingerprints,
fixed-message finding projection, and safe audit projection/hash. Increment
`ValidationReport.report_schema_version` for the extended finding shape while
retaining a reader path for the existing version.

- [ ] Write RED compatibility tests proving legacy findings round-trip unchanged
  while audit findings accept `source_stage="repair"`, then valid/malformed/
  adversarial cases for every response field,
  unknown keys, invalid goal/facet/evidence ids, model-supplied fingerprint/value,
  private strings in every narrative slot, non-echoing diagnostics, deterministic
  safe findings, and safe projection excluding narratives/private hashes.
- [ ] Run the new test file and observe RED.
- [ ] Implement pure parse/project functions. Free-form rationale/summary remains
  local and never becomes a standard finding message.
- [ ] Run focused tests green and independently scan serialized safe projection
  for every planted secret.
- [ ] Fresh adversarial privacy/spec/code review; manager lands
  `feat(audit): add safe personalization audit projection`.

### Task 3.3: Audit prompt, approval, and hash-derived lifecycle

**Files:**

- Modify: `education_pipeline/prompts.py`, `education_pipeline/runs.py`
- Test: `tests/test_prompts.py`, `tests/test_runs.py`

**Produces:** fixed audit paths, prompt compiler/writer, explicit preparation,
shape-validation on ingest/approval, approved safe projection, state/freshness,
and before-or-after-finalize operation over the canonical final candidate.

- [ ] Write RED tests for eligibility only with current final validation,
  attached profile, and current trace; safe no-profile unavailability;
  prompt input hashes; manual ingest/approval; provider-ready paths; no-audit
  finalize/export; before/after-finalize equivalence; repair/profile/trace
  invalidation; stale rebuild; explicit enqueue refusal for missing/stale audit
  prompt; failure between approved-response and projection writes; and existing
  complete run staying `done`.
- [ ] Run focused prompt/run tests and observe RED.
- [ ] Implement `prepare_personalization_audit`. Bind state to canonical candidate
  guide SHA + exact snapshot SHA + private trace SHA in one approval event, plus
  hashes of the exact approved-response and safe-projection bytes. Current state
  requires every binding to match; rebuilding a prompt cannot make an old
  approval appear current. Never put private artifact hashes into the public
  projection.
- [ ] Run focused tests green, including `StaleContentError` cases.
- [ ] Fresh state-machine/privacy/spec/code review; manager lands
  `feat(runs): add optional personalization audit lifecycle`.

### Task 3.4: Sidecar schema, safe findings, and export staleness

**Files:**

- Modify: `education_pipeline/guides/quality_report.py`
- Modify: export/report state in `education_pipeline/runs.py`
- Test: `tests/test_quality_report.py`, `tests/test_runs.py`,
  `tests/test_release_gate_acceptance.py`

**Produces:** incremented quality-report schema; explicit audit state;
safe-trace/safe-audit projection hashes and findings; no merge into the on-disk
deterministic gate report; canonical export-input digest/state; schema-v1
sidecars stale-for-re-export; export state invalidated by later audit changes;
public-guide-projection hashes replace or omit validation/waiver source hashes
that could be derived from private exclusion reasons; one shared
combined-findings accessor for sidecar/API/CLI consumers.

- [ ] Write RED canonical-byte tests for not-run/current/stale audit; safe
  projection inclusion; raw narrative/private-hash absence; unchanged gate and
  waiver result; old sidecar staleness without changing `next_action`; later
  approval leaving old files byte-unchanged; re-export restoring current state;
  and changing only a private exclusion reason never changing a public
  source-hash field. Pin the public mapping: prompt/response without any approval
  is `not_run`; a mismatched prior approval is `stale`; preparing or ingesting
  identical inputs does not stale a current export. Changing canonical final
  report bytes, validator/report schema versions, or
  `QUALITY_REPORT_SCHEMA_VERSION` stales export state.
- [ ] Run focused report/run tests and observe RED.
- [ ] Implement sidecar augmentation at export time from the current safe audit
  projection. UI/API validation presentation may combine lists, but persisted
  deterministic gate findings remain separate.
- [ ] Run focused suites green and prove independent-run byte equality in all
  three audit states.
- [ ] Fresh reproducibility/privacy/spec/code review; manager lands
  `feat(report): add safe audit provenance`.

### Task 3.5: Audit daemon and CLI controls

**Files:**

- Modify: `education_pipeline/daemon/read_api.py`, `write_api.py`, `server.py`
- Modify: `education_pipeline/cli.py`
- Test: `tests/test_write_api.py`, `tests/test_server.py`, `tests/test_cli.py`

**Produces:** explicit prompt-preparation POST, generic audit stage route reuse,
API/CLI use of Task 3.4's combined-findings accessor, additive audit finding
count, safe audit status/presentation, `audit TOPIC` CLI, and no impact on
`advance`.

- [ ] Write RED route/CLI tests for eligibility, prepare/rebuild, manual/provider
  next step, response/approval reuse, not-run/current/stale status, private-safe
  errors, `source_stage="repair"` evidence navigation, additive audit counts,
  deterministic-gate counts unchanged, and attempts to waive audit findings
  receiving the existing non-waivable refusal through both HTTP and CLI.
- [ ] Run focused daemon/CLI tests and observe RED.
- [ ] Implement thin adapters over `RunStore`; do not add a second audit state
  machine in API code.
- [ ] Run focused suites green and one daemon-level fake-provider audit flow.
- [ ] Fresh API/privacy/code review; manager lands
  `feat(api): expose optional personalization audit`.

### Wave 3 close

- [ ] Complete the Wave 3 row using the Wave Protocol and stop.
- Suggested next manager: **GPT-5.6 Sol with High reasoning** for cross-frame
  cockpit behavior, multi-state acceptance, and final milestone review.

---

# Wave 4 — Audit controls, fit panel, acceptance, and closeout

**Outcome:** the cockpit exposes profile fit and optional audit without changing
exported guide content; evidence links operate in the sandboxed preview; full
Python and browser acceptance prove privacy, trace, audit, recovery, and
reproducibility; docs close the milestone.

**Dispatch:** Task 4.1 freezes the aggregate payload and TS types. After it
lands, Tasks 4.2, 4.3, and 4.4 are parallel-safe. Their agents create/test
components and acceptance without touching the shared `RunBoardPage.tsx` or
`styles.css`; the manager alone performs the integration barrier below. Task
4.4 is test-only during this batch and queues any product fix for the manager
after the barrier. Task 4.5 starts after fixes and integration. Task 4.6 is
manager-led closeout.

### Task 4.1: Cockpit personalization aggregate contract

**Files:**

- Modify: `education_pipeline/daemon/read_api.py`, `server.py`
- Modify: `web/src/api/types.ts`, `client.ts`, `client.test.ts`
- Test: `tests/test_server.py`

**Produces:** `GET /v1/runs/{topic}/personalization` with explicit
profile/trace/audit/export states and local cockpit goals/facets/evidence,
without exposing artifact paths or unvalidated audit strings. Audit evidence
includes its repair-source navigation target rather than an audit-response JSON
pointer. This task also owns typed client adapters/results for the explicit
`POST /v1/runs/{topic}/audit` preparation action and the existing audit
response/approve/provider-job routes consumed by Wave 4 UI.

- [ ] Write RED Python and TS contract tests for no-profile, trace-only, current
  audit, stale audit, invalid trace, and stale export states.
- [ ] Run focused server/client tests and observe RED.
- [ ] Implement one server-side aggregate; the browser never reads raw trace or
  audit artifacts.
- [ ] Run focused Python/vitest tests and build green.
- [ ] Fresh API/privacy/spec/code review; manager lands
  `feat(api): expose cockpit personalization state`.

### Task 4.2: Optional audit cockpit controls

**Files:**

- Create: `web/src/components/AuditControls.tsx` and test
- Modify: `web/src/components/ValidationFindingsPanel.tsx` and test
- Modify: `web/src/pages/StageViewerPage.tsx`
- Focused non-regression: `PrimaryAction.test.tsx`

**Produces:** separate optional UI for prepare, provider run, manual paste,
review, approval, rerun, stale state, and re-export prompt. It never replaces or
blocks `PrimaryAction`.

- [ ] Write RED component/page tests for every optional state and action.
- [ ] Add RED finding-navigation coverage proving an audit finding renders in
  the shared panel and opens `source_stage ?? stage`, so audit evidence targets
  the repair guide rather than the private audit response.
- [ ] Run focused vitest and observe RED.
- [ ] Implement using generic stage viewer/job controls where possible; do not
  fork response editing.
- [ ] Run focused tests and build green.
- [ ] Fresh accessibility/state-machine/code review; manager lands
  `feat(cockpit): add optional audit controls`.

### Task 4.3: PersonalizationPanel and sandboxed preview bridge

**Files:**

- Create: `web/src/components/PersonalizationPanel.tsx` and test
- Modify: `web/src/components/GuidePreviewFrame.tsx`
- Create: canonical repair/final preview wrapper component and test
- Modify: `education_pipeline/guide_runtime/assets/runtime.js` and focused
  runtime tests

**Produces:** fit panel beside a durable repair/final preview; trace-only,
current/stale audit, no-profile/invalid states; goal/facet/exclusion/evidence
display; click-to-reveal/scroll/focus through a preview-only semantic evidence
resolver.

- [ ] Write RED vitest/runtime tests for rendering states and the exact
  `postMessage` contract. Parent messages include only a fixed type, evidence
  kind (`module` or `outcome`), and validated id. Runtime listens only when the
  document has `data-guide-mode="preview"`, requires
  `event.source === window.parent`, rejects malformed/unknown ids, resolves
  module evidence to the first section with matching `data-module-id`, resolves
  outcome evidence by DOM id, reveals the owning section, scrolls, and focuses
  the target. Test both evidence kinds and prove export-mode documents ignore
  messages.
- [ ] Run focused vitest/runtime tests and observe RED.
- [ ] Implement with an imperative iframe ref and `postMessage`. Keep the iframe
  opaque; **do not add `allow-same-origin`**.
- [ ] Run focused vitest, runtime Playwright cases, and build green.
- [ ] Fresh security/accessibility/spec/code review; manager lands
  `feat(cockpit): add personalization fit panel`.

### Task 4.4: Python milestone acceptance

**Files:**

- Create: `tests/test_personalization_acceptance.py`

Reuse existing guide-run helpers rather than creating a second pipeline harness.

- [ ] Write acceptance tests for structured CRUD and snapshot immutability;
  planted high/medium leak refusal; 1.1 trace construction; dangling/missing/
  stale trace refusal; stripped public outputs; optional audit before/after
  finalize; hostile narrative projection; export staleness; and reproducible
  not-run/current/stale sidecars.
- [ ] Run the new file and observe RED only for any still-missing integration.
- [ ] During parallel dispatch, modify only this new test file. Report product
  gaps with their owning modules to the manager; do not collide with active
  UI/runtime/API agents, weaken tests, or duplicate core logic.
- [ ] After the parallel barrier, the manager dispatches or applies queued fixes
  serially through the owning modules, then runs this file and the existing
  release-gate acceptance green.
- [ ] Fresh adversarial acceptance review after fixes; manager lands
  `test(personalization): add end-to-end engine acceptance`.

### Wave 4 integration barrier (manager-owned hot files)

- [ ] Integrate `AuditControls`, the canonical repair/final preview wrapper, and
  `PersonalizationPanel` in `web/src/pages/RunBoardPage.tsx`; add scoped rules in
  `web/src/styles.css`. No sub-agent edits these two files during the parallel
  batch.
- [ ] Add/update `RunBoardPage.test.tsx` for trace-only, current/stale audit,
  re-export prompt, and no-profile states; run focused vitest and build green.
- [ ] Land the integration as `feat(cockpit): integrate personalization workspace`.

### Task 4.5: Browser milestone acceptance

**Files:**

- Create: `web/e2e/personalization.spec.ts`
- Modify: `web/e2e/helpers/daemon.ts` only for reusable setup

One scenario must cover: structured profile create and previews; attach; full
guide run; planted leak refusal; repair/revalidate/finalize/export; raw HTML and
sidecar absence checks for profile value, goal text, exclusion reason, and
annotation keys; optional audit run/approval/re-export; safe projected findings;
goal evidence click changing current/focused preview target; axe scans for
Profiles, trace-only, current-audit, stale-audit, and no-profile states.

- [ ] Write the scenario and observe focused RED.
- [ ] Fix only genuine integration/accessibility gaps, preserving privacy and
  optional-stage invariants.
- [ ] Run `cd web && npx playwright test e2e/personalization.spec.ts` green.
- [ ] Sabotage-check the absence assertions and click bridge so the test fails
  when stripping or messaging is bypassed.
- [ ] Fresh acceptance review; manager lands
  `test(cockpit): cover personalization milestone`.

### Task 4.6: Final review and durable closeout

**Files:**

- Modify: `README.md`, `docs/product-requirements.md`, this plan
- Create: `docs/superpowers/specs/2026-07-13-personalization-post-milestone-audit.md`
  if the fresh review finds accepted/deferred items

- [ ] Dispatch an independent fresh-eyes whole-milestone review covering privacy
  boundary, source/public projection, trace freshness, optional audit state,
  report reproducibility, API stale writes, cockpit recovery, accessibility, and
  generated-artifact hygiene.
- [ ] Fix all Critical/Important findings with RED tests. Explicitly adjudicate
  lesser findings into fix-now, accepted, or next-milestone buckets.
- [ ] Update README usage/privacy guidance and mark PRD P1 status/exit evidence
  with exact test paths and delivered commits.
- [ ] Record any deferred items in the post-milestone audit artifact; do not hide
  them only in chat or a commit message.
- [ ] Run the final Wave 4 close checklist and commit the completed plan/log.

### Wave 4 close

- [ ] Record the final four-suite gate, milestone commit range, acceptance test
  paths, and review verdict in the Wave Log.
- [ ] Return a milestone summary and recommend a fresh post-milestone audit
  task. Stop; do not begin the next PRD milestone.
