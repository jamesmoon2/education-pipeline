# Deterministic Release Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan wave-by-wave. Steps use checkbox (`- [ ]`) syntax for tracking. Each wave runs in a **fresh session** with a **fresh manager**; the human clears context between waves and pastes the kickoff prompt printed by the previous wave's manager.

**Goal:** Export produces a clear, reproducible quality report and cannot silently package structurally invalid or privacy-leaking content (PRD §10 "P0 — Establish deterministic release gates").

**Architecture:** The validator/waiver engine in `guides/` already exists. This milestone (a) pays down two scheduled debt items (manifest write safety, API body hygiene), (b) makes the stubbed `ValidationContext` static checks real by computing them from the assembled export document, (c) attributes findings to their responsible stage and ships a canonical sidecar quality report with every export, (d) gives the CLI full gate parity, and (e) proves the loop with an acceptance e2e.

**Tech Stack:** Python 3.11+ stdlib only (`html.parser`, `hashlib`, `threading`), pytest; React 18 + TypeScript, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-07-12-deterministic-release-gates-design.md`

## Global Constraints

- `education_pipeline/` is **standard library only at runtime**; `pytest` is the sole dev dependency. No new runtime dependencies.
- Strict TDD: the failing test is written and observed to fail before implementation, in every task.
- Deterministic steps (finalize, export, validation) never call a model.
- All new file writes are atomic (`_write_bytes_atomic` pattern: temp file + `os.replace`).
- Reports and the sidecar quality report are canonical and timestamp-free: same inputs ⇒ byte-identical bytes.
- Never commit generated runs, real learner profiles, or tuned prompt libraries.
- `web/`: `npm run build` (tsc) is the only type/lint gate; no eslint/prettier exists.
- Commit after every green test cycle; commit messages follow the repo's `type(scope): summary` convention.

---

## Wave Protocol (manager instructions — read first, every wave)

This plan executes as **five waves (0–4)**. Each wave is one independent session driven by a manager agent using `superpowers:subagent-driven-development` (fresh implementer subagent per task, spec review + code review per task).

### Trust the Wave Log — do not retest prior waves

- A wave **closes** by running the full four-suite gate (`python3 -m pytest`, `cd web && npm run test`, `npm run e2e`, `npm run build`) and recording the results in the Wave Log below.
- A wave **opens** by reading this plan and the Wave Log **and nothing else**. The recorded gate of the previous wave is canonical truth. **Do NOT re-run any test suite, re-verify prior waves' work, or re-read prior waves' diffs at session start.** Start dispatching your first task immediately. (Individual tasks still run their own narrow test files during TDD; that is normal. The prohibition is on opening-ceremony full-suite runs and re-verification of closed waves.)

### Wave-close checklist (the manager does this personally, in order)

1. Run the four-suite gate once; all suites green (fix or dispatch fixes until green).
2. **Update this plan document itself:** tick every completed checkbox, fill in this wave's Wave Log row (commits, suite counts, deviations, anything the next wave must know), and correct any later-wave instruction this wave invalidated. The Wave Log entry is the *only* handoff artifact — write it so the next manager needs nothing else.
3. Commit the plan-document update.
4. **Print to the terminal, for the human:**
   - a recommendation for the **next wave's manager model** (Opus or Fable) **and effort level**, with a one-sentence rationale tied to the next wave's difficulty;
   - the **verbatim kickoff prompt** for the next wave (template below), so the human can clear context and paste it.
5. Stop. Do not begin the next wave in this session.

### Kickoff prompt template

```
Read docs/superpowers/plans/2026-07-12-deterministic-release-gates.md and execute Wave N
using superpowers:subagent-driven-development. The Wave Log records all prior waves'
gates — treat it as canonical truth and do NOT re-run or re-verify prior waves' tests
before starting. Dispatch Wave N's tasks per the plan, then run the wave-close checklist
in the Wave Protocol section (four-suite gate, update the plan doc, commit, print the
next wave's manager recommendation and kickoff prompt).
```

### Wave Log

| Wave | Status | Commits | pytest | vitest | e2e | build | Notes for the next wave |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 — Hardening | **complete** | `5f03d56..d492ccc` (10) | 543 | 114 | 41 | clean | See "Wave 0 outcome" below. **Read the manifest-lock composition contract before touching `RunStore`.** |
| 1 — Static checks | **complete** | `3103042..b0e5fd3` (5) | 557 | 114 | 41 | clean | See "Wave 1 outcome" below. The `assets_match`-on-assembly-failure semantics are settled — do not re-litigate. |
| 2 — Attribution + report | **complete** | `ee3ceac..d0a291f` (7) | 565 | 123 | 41 | clean | See "Wave 2 outcome" below. `_validated_final` now returns a 3-tuple; sidecar + `export_report_path` shipped for Task 3.1's `report` command. |
| 3 — CLI parity | **complete** | `c03bb24..f4e4f39` (10) | 592 | 127 | 41 | clean | See "Wave 3 outcome" below. Task 3.1b (waiver-aware badges) was folded in by owner decision. **Read the waivers-file existence contract before touching `remove_waiver` or `read_api`.** |
| 4 — Acceptance + closeout | not started | | | | | | |

Baseline at plan time: pytest 478, vitest 114, e2e 41, build clean (commit `57f715e`).

### Wave 0 outcome (read before Wave 1 or Wave 2)

**Gate:** pytest 543, vitest 114, e2e 41/41, build clean at `d492ccc`. Whole-wave review: READY TO MERGE.

**⚠️ The manifest-lock composition contract — Task 2.3 as written below will DEADLOCK.**

`RunStore._manifest_lock` from Task 0.1 is now named **`_manifest_write_lock`** and is a plain, **non-reentrant** `threading.Lock`. It serializes the manifest *and* the waivers file per topic. The rule is **one read-modify-write cycle per critical section**:

- To compose two writes: take the lock **once** and call the **unlocked `_locked` primitives** (`_append_manifest_event_locked`, `_record_stage_provenance_locked`).
- **Never** call a public wrapper (`append_manifest_event`, `record_stage_provenance`, `_append_event`, `record_waiver`, `create_run`) from inside the lock — it deadlocks *by design*. That is deliberate: an earlier fix used an `RLock` to make nesting "work", and it silently **lost updates** instead (the inner call writes, the outer then overwrites from its stale snapshot). Fail-loud was chosen over silent corruption.
- **Never** call a `_locked` primitive *without* holding the lock — that silently loses updates and nothing will stop you (contract is documented, not enforced).

Task 2.3 says the sidecar write and the exported-event append "sit inside the Task 0.1 manifest lock where the event is recorded." The `exported` event is recorded by **`_append_event`**, which is a *lock-taking wrapper* and was **not** split into a primitive. **Wave 2 must first extract `_append_event_locked`** (same pattern as the other two), then compose against it. There is no pytest timeout configured, so a nesting mistake surfaces as a **CI hang**, not a crisp failure.

**Other Wave 0 outcomes the later waves depend on:**

- **The plan's Task 0.2 premise was largely false, and this is verified.** `update_global_plan`, `update_run_plan`, and `create_topic` already converted every nested wrong-shape body to `ConfigError` (114 adversarial probes, zero crashes). No shared `_require_json_string` was needed there. The real bugs were elsewhere and are fixed: `create_waiver` crashed on element-level corruption of `validation-waivers.json` and **dropped the HTTP connection** with no status line; its guard diverged from the loader so the endpoint could return 200 while persisting a file its own loader rejects (bricking the run); `read_api.waivers_payload` held a third schema copy returning `200 {"state":"current"}` on files every other reader rejected; and `create_waiver`'s unserialized read-modify-write with a fixed temp name lost 30/30 concurrent waivers and crashed 15/60 calls.
- **`RunStore.load_waiver_set(topic_id)` is now the single source of truth** for the waivers-file schema, and **`RunStore.record_waiver`** is its sole writer (locked + atomic). **Task 3.2 must build `record_waiver`/`remove_waiver` on these** — do not add a fourth shape check.
- **Scope addition (not in the plan, owner-approved):** `server.py`'s `do_GET`/`do_POST`/`do_PUT` now wrap their entire body in a last-resort handler returning a 500 envelope + stderr traceback, so no unguarded exception can drop the socket. The 422 arms (`UnprocessableError`, `GuideDocumentError`, `ContractError`, `GuideParseError`) are pinned by tests on every verb — **Wave 1 adds new failure modes to the finalize/export path, and they must map to 422, not 500.**
- **Owner decision (Task 0.3 follow-up):** unknown stage keys are **strict at write, lenient on disk** — `PUT /v1/config/plan` with a misspelled key now 400s (`parse_model_plan(..., strict_keys=True)`), but an existing hand-edited `model-plan.toml` with a stray key still loads.

**Residual Minors for milestone final triage:** `_locked` primitives' "caller holds the lock" contract is documented, not enforced (a `lock.locked()` heuristic assert would catch the dev-time error); the lock's name still says "manifest" though it also guards waivers; no pytest timeout, so a lock-nesting regression hangs CI; loader-accepted extra keys in `waivers.json` are now dropped from the GET payload rather than echoed; a truncated request body (`Content-Length` > bytes sent) hangs a handler thread forever (**pre-existing**, reproduces at `d46406a`, post-auth + loopback only).

**Wave 0 manager recommendation (initial):** Opus, medium effort — mechanical hardening with well-scoped tests; Fable is not needed until the cross-surface design work in Waves 1–2.

### Wave 1 outcome (read before Wave 2)

**Gate:** pytest 557, vitest 114, e2e 41/41, build clean at `b0e5fd3`. Whole-wave review (Fable): READY TO RECORD after one Important fix (see below). Three docs-only commits from a parallel session (`5c6ad44`, `6f71bbc`, `7b8c123`) are interleaved in the range and are not part of this wave.

**Settled adjudication — do not re-litigate in Wave 2:** the Task 1.1 prose "on assembly failure every other check reports True" conflicts with the task's own reference code; ruled in favor of the code. `assets_match` is input-derived and stays *computed* when assembly fails (forcing True would mask real tampering); only the document-derived checks (`controls_have_labels`, `heading_order_valid`) default True. Pinned by `test_render_failure_keeps_assets_match_computed`. The whole-wave reviewer independently endorsed the ruling.

**Interfaces Wave 2 builds on (as shipped):**

- `compute_static_checks(guide, assets=None) -> StaticCheckResult` and `StaticCheckResult(context, document)` exported from `education_pipeline.guides`; `runs.py` imports `compute_static_checks` into its own namespace (tests monkeypatch `runs_mod.compute_static_checks`).
- `RunStore._validated_final(topic_id, source_text) -> (ValidationReport, str | None)` — `document` is `None` in **three** cases: source does not parse, assembly failed, or the source exceeds `MAX_GUIDE_SOURCE_BYTES` (its docstring still lists only the first two — touch it up when Task 2.3 edits the function). The oversized case falls back to the raw `validate_guide` path *before parsing*, restoring the `schema.size_limit` blocker and the raw-sha digest (an Important found by the whole-wave review: parsing first had silently dropped the size gate and livelocked `report_state` at "stale").
- `MAX_GUIDE_SOURCE_BYTES` (2,000,000) now lives in `guides/validation.py` and is the single constant behind all three cap sites (`validate_guide`, `_guide_source_sha`, `_validated_final`). Do not reintroduce the literal.
- `_export_guide_v1` writes exactly `_validated_final`'s document and *re-parses the source a second time* only for event provenance (schema_version, assets). When Task 2.3 rewires the exported-event append, prefer surfacing the guide/assets from `_validated_final` instead of keeping the duplicate parse.
- `controls_have_labels` requires the wrapping `<label>` to have non-empty text (deferred verdict at `</label>`); any descendant text counts, per the plan's wording.

**Residual items for milestone final triage (accepted this wave, not blockers):**

- Heading-order rule is as the plan specified — "no more than one level deeper than the *deepest seen so far*" — which passes `h1,h2,h3` then `h2→h4`, and a document whose first heading is `h4`. Plan-level weakness, not an implementation bug; if real WCAG-style skip detection is wanted, track the *previous* heading instead. Owner call at closeout.
- Status polling (`_next_action_guide_v1`) now assembles the full export document per status call (~1.4 ms on the canonical fixture; deterministic; plan-mandated). Perf note only.
- New GET-path surface: a corrupted install (missing runtime assets) makes `load_runtime_assets()` raise `OSError` during status polling → last-resort 500. Finalize/export POST paths already had this exposure pre-wave; a `try/except OSError → ConfigError` or caching would close it.
- Analyzer latent shell-coupling: `<input type="hidden">` would be treated as needing a label, and script/style CDATA inside a label counts as label text. Unreachable through today's assembler output; add a hidden-input exemption whenever `static_checks.py` is next touched.
- Unclosed `<label>` at EOF escapes the label check (assembled documents cannot produce one).

### Wave 2 outcome (read before Wave 3)

**Gate:** pytest 565, vitest 123, e2e 41/41, build clean at `d0a291f`. Whole-wave review (Fable): READY TO RECORD after one Important fix (see below). The Wave 0 deadlock trap was fully defused — the reviewer independently re-audited every `_append_event`/`_append_event_locked`/`_manifest_write_lock` call site and the one-RMW-per-critical-section contract holds throughout.

**Interfaces Wave 3 builds on (as shipped):**

- `RunStore._validated_final(topic_id, source_text)` now returns a **3-tuple** `(ValidationReport, str | None, Guide | None)` — the guide is surfaced so `_export_guide_v1` no longer re-parses for event provenance. Any code unpacking the old 2-tuple is stale. Docstring lists all three `None`-document cases.
- `_append_event_locked` is the unlocked primitive; `_append_event` remains the lock-taking wrapper. Same composition contract as Wave 0 — one read-modify-write per critical section, primitives only under the lock.
- `quality_report_bytes(report, waiver_result, waiver_set, *, export_sha256, runtime_css_sha256, runtime_js_sha256, runtime_version) -> bytes` and `QUALITY_REPORT_SCHEMA_VERSION = 1` exported from `education_pipeline.guides`; `RunStore.export_report_path(topic_id)` maps `guide.html → guide.report.json` (same directory). Task 3.1's `report` command consumes these as planned.
- Findings carry `stage` (report schema v2, 45 rules: 34 draft / 6 outline / 5 repair); the daemon's validation summaries carry `findings_by_stage` (blocking-or-error only, missing stage defaults `"draft"`); TS `ValidationFinding.stage` is **optional** with a phase-derived fallback in `findingHref` (pre-v2 reports on disk have no stage — the Important the whole-wave review caught: required TS field + direct interpolation produced `/stages/undefined` links; fixed in `d0a291f`).
- RunBoard badges count only reports whose `state === "current"` (stale counts were inflating the actionable-work signal — Important found by Task 2.2's review, fixed `58f422f`). "Re-run validation" button lives in `ValidationFindingsPanel` (its sole render site), via the pre-existing `postValidate` helper — the plan's `/validation/{phase}` route spelling was wrong; the real route is `POST /v1/runs/{topic}/validate` with phase in the body.

**Endorsed deviation (recorded, not a defect):** the sidecar `_write_bytes_atomic` sits immediately *before* the lock-held critical section, not inside it as the task prose said. The manifest RMW invariant fully holds; sidecar bytes are deterministic so concurrent re-export cannot desync the event's two sha fields; shorter lock hold.

**Wave-3 candidate (reviewer recommendation, not yet scoped):** badges and the re-run affordance are waiver-blind — a run whose blockers are all waived (gate open) still shows badges and an un-clearable re-run button. Task 3.1's planned `RunStore.gate_result` is the natural vehicle: surface `effective_blocking` into `_validation_summary` while wiring it. Owner may fold this into 3.1 or defer to closeout.

**Residual items for milestone final triage (accepted this wave, not blockers):**

- `role="status"` on the always-present findings badge is a live region; with 5 s polling, count changes re-announce to screen readers. Plain `span` + `aria-label` (or visually-hidden text) is more appropriate.
- `report_state` ignores `report_schema_version` — a v1 report against unchanged content stays "current" forever. Policy question for the owner: treating `< 2` as stale would self-heal legacy workspaces via one re-validation prompt.
- Sidecar write `OSError` after the HTML write lands on the last-resort 500 (same exposure class as the pre-existing HTML write; pairs with Wave 1's `load_runtime_assets` OSError item).
- `_validation_summary`'s flat `"draft"` default for stage-less findings vs `findingHref`'s phase-derived fallback — legacy-only, self-healing, accepted.
- `ValidationFindingsPanel.test.tsx` fixture says `report_schema_version: 1` while its findings carry `stage` (a hybrid that doesn't exist); the exported event carries redundant-but-equal `quality_report_file_sha256` + `quality_report_sha256`; `_finalize_guide_v1` still does its own parse (fold into closeout cleanup).

### Wave 3 outcome (read before Wave 4)

**Gate:** pytest 592, vitest 127, e2e 41/41, build clean at `f4e4f39`. Whole-wave review (Opus): READY TO RECORD after two Important fixes (below). The reviewer independently re-derived the `_manifest_write_lock` audit (7 lock sites, 8 `_locked` primitive calls, every one inside a lock, zero outside) and re-verified the fixes' RED evidence in an isolated worktree rather than trusting the report.

**Scope addition (owner-approved, not in the original plan): Task 3.1b.** Wave 2's reviewer flagged the cockpit's badges and re-run affordance as waiver-blind; the owner folded the fix into this wave rather than deferring it. The daemon's `_validation_summary` now reports a post-waiver `effective_blocking`, and the RunBoard badges + `ValidationFindingsPanel`'s re-run button key off it, so a fully-waived (gate-open) run no longer shows a red badge or an un-clearable re-run button. `findings_by_stage` is netted post-waiver **server-side**.

**⚠️ The waivers-file existence contract — three components are now coupled through it.**

`read_api._validation_summary` skips an expensive per-poll `gate_result` recompute (full parse + normalize + static checks; plus a runtime render + a11y pass for `final`) **only when `load_waiver_set(topic_id) is None`** — i.e. only when the waivers file *does not exist*. Two consequences that bit twice in this wave:

- **No writer may leave an empty waivers file behind.** `remove_waiver` originally wrote `{"waivers": []}` unconditionally, so `unwaive` of a typo'd id — and later, of the *last* real waiver — created a file that was semantically identical to "no waivers" but permanently defeated the short-circuit for that topic, with nothing to heal it. Both paths are now closed: a no-op removal writes nothing, and removing the last waiver `unlink`s the file. `_write_waiver_set_locked` is the **sole** writer of `waivers_path`; keep it that way.
- **`load_waiver_set` RAISES `ConfigError` on a malformed file and returns `None` only for "no file".** Conflating the two produced the wave's nastiest bug: a `load_waiver_set` call placed *outside* a `ConfigError` handler turned a graceful degrade into an **HTTP 400 on `GET /v1/runs/{topic}`** — the endpoint the cockpit polls every 5 seconds — and because `read_api.py:49` builds the topic-list payload by calling `run_status_payload` for *every* topic, **one** corrupt waivers file on **one** run 400'd the entire `/v1/topics` list. Every read-path call site is now guarded (`_validation_summary`, `_next_action_guide_v1`); the remaining raising sites (`_export_guide_v1`, `_finalize_guide_v1`) are fail-closed **write** paths where raising is correct, and `waivers_payload` raises by documented contract.

**Two notions of "the report" now coexist — do not pair them.** The on-disk report JSON, and the report freshly recomputed by `_compute_phase_report`. Pairing a *stale* on-disk body with a *fresh* recomputed gate makes a surface disagree with itself, and this bug was found independently in **both** `_cmd_report` and `_validation_summary`. The rule: only trust a recomputed gate when `report_state` is `"current"`; otherwise fall back to the raw counts and let the stale banner do its job. Waivers are hash-bound, so the recompute is fail-safe in the other direction — a waiver set recorded against different content is dropped and the gate **closes**; it can never silently open one.

**Interfaces Wave 4 builds on (as shipped):**

- `RunStore.gate_result(topic_id, phase) -> WaiverResult`, `RunStore.validate_and_gate(...)`, and the shared private `RunStore._compute_phase_report(...)`. `gate_result` **recomputes** from the approved source (there is no `ValidationReport.from_dict()`, and adding one would be new untested schema surface for zero gain — the reviewer adjudicated the recompute sound and fail-safe).
- `RunStore.record_waiver(topic_id, phase, finding_id, reason) -> WaiverResult` and `RunStore.remove_waiver(topic_id, phase, finding_id) -> WaiverResult`. Both hash-bound, atomic, single-critical-section. `write_api.create_waiver` builds its response payload from the `WaiverSet` written **inside** the lock (via the private `_record_waiver`), not from an unlocked re-read — the re-read was racy and dereferenced an unchecked Optional.
- CLI: `education-pipeline validate | findings | report | waive | unwaive`. **Exit codes: 0 = gate open/success, 1 = gate blocked, 2 = usage error.** `waive`/`unwaive` catch `ConfigError` locally → 2; `validate`/`findings`/`report` let it reach `main()` → 1 (see carry-forward #2 — the surfaces disagree about what 1 means).
- `_warn_if_report_stale` (`cli.py`) — read commands print the on-disk body but warn on stderr when it is stale, keeping stdout pipeable while the exit code carries current truth. Gate/write paths still fail closed.
- Daemon: `_validation_summary` carries `effective_blocking` (post-waiver). TS `effective_blocking` is **optional** with a raw-count fallback (the `d0a291f` precedent — an absent field must never silently read as 0 and hide a blocker).

**Test-quality note for Wave 4 (this wave's recurring defect).** Every review in this wave caught tests that would pass against unfixed code — including, at the extreme, a regression test that could never reach the path named in its own docstring (its fixture was draft-only and the guarded line required a finalize-ready run), and an existing test that had **encoded the old buggy behavior** and would have actively defended the bug. Wave 4 is the acceptance suite; for every test, verify it is genuinely RED against the unfixed code before believing it.

**Residual items for milestone final triage (accepted this wave, not blockers):**

- No `DELETE` waiver route: the cockpit can create waivers but cannot remove them, though the store now supports it. CLI/cockpit parity gap this wave opened.
- CLI exit-code convention is not uniform: `ConfigError` → 2 in `waive`/`unwaive`, but → 1 (via `main`) in `validate`/`findings`/`report`, colliding with "gate blocked". `education-pipeline validate typo-topic` exits 1, so `validate "$t" || echo blocked` mislabels a nonexistent run as a blocked gate.
- `write_api.py` reaches into the private `runs._record_waiver` (deliberate and documented — it needs the locked-write `WaiverSet` without a racy re-read — but the layering is wrong; promote a public method returning both).
- `read_api._validation_summary` still defaults stage-less findings to a flat `"draft"` while the CLI and the web both derive it from the phase. Legacy-only and self-healing, but it is now the last surface out of three.
- `report` reflects **export-time** gate state (the frozen sidecar) while `validate` reflects **current** state; now warned about on stderr, still worth a docs line in Task 4.3.
- Carried from earlier waves: `role="status"` live region on the findings badge; `report_state` ignores `report_schema_version` (a v1 report against unchanged content stays "current" forever); `_finalize_guide_v1` still does its own parse; the heading-order rule tracks the deepest heading seen rather than the previous one.

---

# Wave 0 — Hardening debt

Two scheduled debt items from the model-plan post-milestone audit §7. No behavior of the gate itself changes in this wave.

### Task 0.1: Atomic, serialized manifest writes

**Files:**
- Modify: `education_pipeline/runs.py` (`_write_manifest` ~line 1607; `RunStore.__init__` ~line 190; `append_manifest_event` ~line 728; `record_stage_provenance` ~line 739; `create_run` manifest write ~line 305; `_append_event` ~line 1574)
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: existing `_write_bytes_atomic(path, data)` in `runs.py`.
- Produces: `RunStore._manifest_lock(topic_id: str) -> threading.Lock` (private); `_write_manifest` unchanged signature, now atomic. Later waves' findings writer (Task 2.3 manifest events) relies on every manifest read-modify-write being wrapped in the per-topic lock.

> **As shipped:** the lock is named **`_manifest_write_lock`**, is non-reentrant, and also guards the waivers file. Composition is via unlocked `_locked` primitives, never by nesting public wrappers. See "Wave 0 outcome" in the Wave Log.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_runs.py
import concurrent.futures
import json


def test_manifest_write_is_atomic_no_partial_file(tmp_path, monkeypatch):
    """_write_manifest must go through the temp-file + os.replace path."""
    from education_pipeline import runs as runs_mod

    calls = []
    original = runs_mod._write_bytes_atomic

    def spy(path, data):
        calls.append(path.name)
        return original(path, data)

    monkeypatch.setattr(runs_mod, "_write_bytes_atomic", spy)
    store = runs_mod.RunStore(tmp_path)
    store.create_run("atomic-topic")
    assert "manifest.json" in calls


def test_concurrent_manifest_events_are_all_recorded(tmp_path):
    """Two writer threads appending events must not lose either event."""
    from education_pipeline.runs import RunStore

    store = RunStore(tmp_path)
    store.create_run("locked-topic")

    def append(n: int) -> None:
        store.append_manifest_event("locked-topic", {"action": f"evt-{n}"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(50)))

    manifest = store.read_manifest("locked-topic")
    actions = [e["action"] for e in manifest["events"] if e.get("action", "").startswith("evt-")]
    assert sorted(actions) == sorted(f"evt-{n}" for n in range(50))
    # File must still be valid JSON (no torn write)
    json.loads(store.manifest_path("locked-topic").read_text(encoding="utf-8"))
```

Adjust the event-shape assertions to match how `append_manifest_event` actually stores events (read the method first; it may namespace under a key other than `events`).

- [x] **Step 2: Run tests, verify the concurrency test fails (lost updates) or is flaky**

Run: `python3 -m pytest tests/test_runs.py -k "manifest_write_is_atomic or concurrent_manifest" -v`
Expected: FAIL — `_write_bytes_atomic` spy not called for manifest, and/or fewer than 50 events recorded.

- [x] **Step 3: Implement**

In `runs.py`:

```python
def _write_manifest(path: Path, manifest: dict) -> None:
    _write_bytes_atomic(path, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
```

In `RunStore.__init__`, add per-topic locks:

```python
import threading  # top of file

self._manifest_locks: dict[str, threading.Lock] = {}
self._manifest_locks_guard = threading.Lock()
```

```python
def _manifest_lock(self, topic_id: str) -> threading.Lock:
    with self._manifest_locks_guard:
        return self._manifest_locks.setdefault(topic_id, threading.Lock())
```

Wrap **every** manifest read-modify-write cycle (`append_manifest_event`, `record_stage_provenance`, `_append_event`, and the `create_run` manifest mutation) in `with self._manifest_lock(safe_id):` so the read→mutate→write sequence is a critical section. Find all four call sites of `_write_manifest` and confirm no read-modify-write escapes the lock.

Add a short comment at `_manifest_lock` stating the boundary: serialization is in-process only (daemon threads); cross-process CLI concurrency is out of scope.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_runs.py -v`
Expected: PASS (all existing + 2 new).

- [x] **Step 5: Commit**

```bash
git add tests/test_runs.py education_pipeline/runs.py
git commit -m "fix(runs): make manifest writes atomic and serialize writers per topic"
```

### Task 0.2: Non-dict and wrong-shape PUT/POST bodies return 400

**Files:**
- Modify: `education_pipeline/daemon/write_api.py` (`update_global_plan` ~line 363, `update_run_plan` ~line 380, `create_topic` ~line 326, `create_waiver` ~line 92)
- Test: `tests/test_write_api.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `ConfigError` (→ HTTP 400 in `server.py`), existing builder signatures.
- Produces: every builder raises `ConfigError` (never `TypeError`/`AttributeError`/`KeyError`) for any body whose nested values have the wrong JSON type.

- [x] **Step 1: Write the failing tests**

The daemon's `_read_body` already rejects a non-dict *root*. The audit's gap is nested shapes. For each builder, feed a body with wrong-typed nested values and assert `ConfigError` (not a crash). Representative cases (add one test per builder):

```python
# tests/test_write_api.py
import pytest
from education_pipeline.config import ConfigError
from education_pipeline.daemon import write_api


@pytest.mark.parametrize("body", [
    {"stages": "draft"},                       # stages not a dict
    {"stages": {"draft": "opus"}},             # stage override not a dict
    {"stages": {"draft": {"model": 5}}},       # value not a string
    {"plan_sha256": {}},                       # guard not a string
])
def test_update_run_plan_rejects_wrong_shapes_with_config_error(run_env, body):
    runs, config = run_env  # reuse/adapt this module's existing fixture for a live topic
    with pytest.raises(ConfigError):
        write_api.update_run_plan(runs, config, "topic-a", body)
```

Mirror the same parametrized pattern for `update_global_plan` and `create_topic` (e.g. `{"title": 5}`, `{"metadata": []}`), and `create_waiver` (e.g. `{"finding_id": 7}`, `{"reason": []}`). Read each builder first and derive the wrong-shape cases from the keys it actually touches. Then add one HTTP-level test in `tests/test_server.py` proving a nested-wrong-shape `PUT /v1/runs/{topic}/plan` returns status 400 with the standard error envelope, not 500 (use this module's existing daemon boot helper).

- [x] **Step 2: Run tests, verify failures**

Run: `python3 -m pytest tests/test_write_api.py tests/test_server.py -k "wrong_shape or rejects" -v`
Expected: FAIL — `TypeError`/`AttributeError` raised instead of `ConfigError`, and HTTP 500 instead of 400.

- [x] **Step 3: Implement**

Add a small shared shape guard in `write_api.py` and call it at the top of each builder for the keys that builder reads:

```python
def _require_json_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a JSON object")
    return value


def _require_json_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string")
    return value
```

Use them where each builder currently indexes into the body unchecked (e.g. `_require_json_object(body.get("stages", {}), "'stages'")`, and per-stage `_require_json_object(stage_override, f"override for stage {name!r}")`). Keep the existing `_require_body_string`/`_optional_body_string` helpers where already used; do not duplicate them.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_write_api.py tests/test_server.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add tests/test_write_api.py tests/test_server.py education_pipeline/daemon/write_api.py
git commit -m "fix(daemon): return 400 for wrong-shape PUT/POST bodies across write builders"
```

### Task 0.3: Reject unknown keys in stage-override dicts

**Files:**
- Modify: `education_pipeline/config.py` (`apply_overrides` ~line 231)
- Test: `tests/test_config.py`, `tests/test_write_api.py`

**Interfaces:**
- Consumes: `apply_overrides(plan, overrides, catalog)` and `apply_overrides_lenient` (which delegates per stage).
- Produces: `apply_overrides` raises `ConfigError` naming the unknown key(s); `apply_overrides_lenient` converts that into the stage's `override_error` (existing degrade behavior, unchanged).

- [x] **Step 1: Write the failing tests**

```python
# tests/test_config.py
def test_apply_overrides_rejects_unknown_stage_override_keys():
    plan = parse_model_plan({"provider": "claude-code", "stages": {}})
    with pytest.raises(ConfigError, match="unknown stage-override key"):
        apply_overrides(plan, {"stages": {"draft": {"modle": "opus"}}})


def test_apply_overrides_lenient_degrades_unknown_key_to_stage_error():
    plan = parse_model_plan({"provider": "claude-code", "stages": {}})
    effective, errors = apply_overrides_lenient(plan, {"stages": {"draft": {"modle": "opus"}}})
    assert "draft" in errors and "modle" in errors["draft"]
```

Match this module's existing fixture style for building a plan/catalog (reuse its helpers rather than raw dicts if helpers exist). Add one `tests/test_write_api.py` test: `update_run_plan` with a misspelled key raises `ConfigError` (→ 400) instead of persisting a silent no-op.

- [x] **Step 2: Run tests, verify failures**

Run: `python3 -m pytest tests/test_config.py tests/test_write_api.py -k "unknown" -v`
Expected: FAIL — the misspelled key merges silently and validation passes.

- [x] **Step 3: Implement**

In `apply_overrides`, before merging each stage override:

```python
_STAGE_OVERRIDE_KEYS = frozenset({"provider", "model", "effort", "recommendation"})
```

```python
unknown = sorted(set(stage_override) - _STAGE_OVERRIDE_KEYS)
if unknown:
    keys = ", ".join(repr(k) for k in unknown)
    allowed = ", ".join(sorted(_STAGE_OVERRIDE_KEYS))
    raise ConfigError(
        f"unknown stage-override key(s) {keys} for stage {stage_name!r}; allowed: {allowed}"
    )
```

`apply_overrides_lenient` needs no change — it already catches `ConfigError` per stage.

- [x] **Step 4: Run tests, verify pass; check for existing tests that legitimately used extra keys**

Run: `python3 -m pytest tests/test_config.py tests/test_write_api.py tests/test_server.py -v`
Expected: PASS. If an existing test relied on tolerated unknown keys, that test encoded the bug — update it and say so in the commit message.

- [x] **Step 5: Commit**

```bash
git add tests/test_config.py tests/test_write_api.py education_pipeline/config.py
git commit -m "fix(config): reject unknown stage-override keys instead of silently ignoring them"
```

### Wave 0 close

- [x] Run the wave-close checklist in the Wave Protocol section (four-suite gate → update this plan doc + Wave Log → commit → print next-wave manager recommendation and kickoff prompt → stop).
- Suggested next-wave recommendation to print (override with judgment): **Fable, high effort** for Wave 1 — the static-check semantics (accessible-name rules, heading order over the assembled document) reward careful reading of `document.py`.

---

# Wave 1 — Real static checks (engine)

`ValidationContext` (`guides/validation.py:24-32`) defaults every check to `True` and nothing computes it. This wave computes it from the assembled export document, so the checked artifact is the shipped artifact.

### Task 1.1: `guides/static_checks.py` — compute `ValidationContext` from the assembled document

**Files:**
- Create: `education_pipeline/guides/static_checks.py`
- Modify: `education_pipeline/guides/__init__.py` (export the new names)
- Test: `tests/test_guide_static_checks.py` (new)

**Interfaces:**
- Consumes: `Guide` (`guides/model.py`), `assemble_guide_document(guide, assets, mode)` (`guides/document.py:244`), `GuideDocumentError`, `RuntimeAssets` / `load_runtime_assets()` (`guide_runtime/__init__.py`), `ValidationContext` (`guides/validation.py`).
- Produces (Task 1.2 and Wave 2 depend on these exact names):

```python
@dataclass(frozen=True)
class StaticCheckResult:
    context: ValidationContext
    document: str | None   # the assembled export HTML; None when assembly failed


def compute_static_checks(guide: Guide, assets: RuntimeAssets | None = None) -> StaticCheckResult: ...
```

Check semantics:

- `render_succeeded` — `assemble_guide_document(guide, assets, mode="export")` completes without `GuideDocumentError` and the document contains the structural markers `data-guide-shell`, `id="guide-data"`, and `class="skip-link"`. On assembly failure every other check reports `True` (they are unknowable; the render failure is the finding) and `document` is `None`.
- `assets_match` — the SHA-256 of `assets.css` and `assets.javascript` used for assembly equal the SHA-256 of the currently packaged `load_runtime_assets()` content, and `assets.version == RUNTIME_VERSION`. (Guards a caller assembling with stale/tampered assets.)
- `controls_have_labels` — parse the document with `html.parser.HTMLParser`; every `<button>` has non-empty text content or a non-empty `aria-label`; every `<select>`, `<input>`, `<textarea>` has a non-empty `aria-label`/`aria-labelledby` or is a descendant of a `<label>` element with text.
- `heading_order_valid` — collecting `h1..h6` in document order, no heading is more than one level deeper than the deepest heading seen so far (h2 → h4 is a skip; h4 → h2 is fine).

- [x] **Step 1: Write the failing tests**

```python
# tests/test_guide_static_checks.py
"""Static checks computed from the assembled export document (stdlib only)."""
import dataclasses
import json
from pathlib import Path

import pytest

from education_pipeline.guide_runtime import RuntimeAssets, load_runtime_assets
from education_pipeline.guides import compute_static_checks
from education_pipeline.guides.parse import normalize_guide, parse_guide

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


@pytest.fixture()
def guide():
    parsed = parse_guide(FIXTURE.read_text(encoding="utf-8"))
    assert parsed.ok
    return normalize_guide(parsed)


def test_canonical_fixture_passes_every_static_check(guide):
    result = compute_static_checks(guide)
    ctx = result.context
    assert (ctx.render_succeeded, ctx.assets_match, ctx.controls_have_labels,
            ctx.heading_order_valid) == (True, True, True, True)
    assert result.document is not None and "data-guide-shell" in result.document


def test_static_checks_are_deterministic(guide):
    assert compute_static_checks(guide).document == compute_static_checks(guide).document


def test_tampered_assets_fail_assets_match(guide):
    packaged = load_runtime_assets()
    tampered = RuntimeAssets(css=packaged.css + "/*x*/", javascript=packaged.javascript)
    result = compute_static_checks(guide, assets=tampered)
    assert result.context.assets_match is False
    assert result.context.render_succeeded is True


def test_render_failure_is_reported_and_document_is_none(guide, monkeypatch):
    from education_pipeline.guides import static_checks as mod
    from education_pipeline.guides.document import GuideDocumentError

    def boom(*args, **kwargs):
        raise GuideDocumentError("forced")

    monkeypatch.setattr(mod, "assemble_guide_document", boom)
    result = compute_static_checks(guide)
    assert result.context.render_succeeded is False
    assert result.document is None


def test_unlabeled_button_fails_controls_check(guide):
    # Exercise the HTML analyzer directly: the assembled document is trusted
    # input, so the analyzer is what needs adversarial coverage.
    from education_pipeline.guides.static_checks import _analyze_document

    ok_doc = "<html><body><button>Go</button><h2>a</h2></body></html>"
    bad_doc = "<html><body><button></button><h2>a</h2></body></html>"
    assert _analyze_document(ok_doc).controls_have_labels is True
    assert _analyze_document(bad_doc).controls_have_labels is False


def test_skipped_heading_level_fails_heading_order():
    from education_pipeline.guides.static_checks import _analyze_document

    assert _analyze_document("<h1>a</h1><h2>b</h2><h3>c</h3>").heading_order_valid is True
    assert _analyze_document("<h1>a</h1><h4>b</h4>").heading_order_valid is False


def test_aria_labeled_and_label_wrapped_controls_pass():
    from education_pipeline.guides.static_checks import _analyze_document

    doc = ('<select aria-label="Theme"><option>x</option></select>'
           '<label>Name<input type="text"></label>'
           '<button aria-label="Close"></button><h2>a</h2>')
    assert _analyze_document(doc).controls_have_labels is True
```

- [x] **Step 2: Run tests, verify import failure**

Run: `python3 -m pytest tests/test_guide_static_checks.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_static_checks'`.

- [x] **Step 3: Implement `static_checks.py`**

```python
"""Deterministic static checks computed from the assembled export document.

Stdlib only. These checks make ``ValidationContext`` real: instead of callers
asserting the runtime invariants, the invariants are derived from the exact
HTML string export will ship.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser

from ..guide_runtime import RUNTIME_VERSION, RuntimeAssets, load_runtime_assets
from .document import GuideDocumentError, assemble_guide_document
from .model import Guide
from .validation import ValidationContext

_STRUCTURAL_MARKERS = ("data-guide-shell", 'id="guide-data"', "skip-link")
_LABELABLE = {"select", "input", "textarea"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


@dataclass(frozen=True)
class StaticCheckResult:
    context: ValidationContext
    document: str | None


@dataclass(frozen=True)
class _DocumentFacts:
    controls_have_labels: bool
    heading_order_valid: bool


class _Analyzer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.controls_ok = True
        self.heading_ok = True
        self._deepest_heading = 0
        self._label_depth = 0
        self._open_buttons: list[dict[str, bool]] = []  # {"named": bool}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "label":
            self._label_depth += 1
        if tag in _HEADINGS:
            level = _HEADINGS[tag]
            if self._deepest_heading and level > self._deepest_heading + 1:
                self.heading_ok = False
            self._deepest_heading = max(self._deepest_heading, level)
        if tag == "button":
            self._open_buttons.append({"named": bool((attributes.get("aria-label") or "").strip())})
        if tag in _LABELABLE:
            named = bool((attributes.get("aria-label") or "").strip()) or bool(
                (attributes.get("aria-labelledby") or "").strip()
            )
            if not named and self._label_depth == 0:
                self.controls_ok = False

    def handle_data(self, data):
        if data.strip() and self._open_buttons:
            self._open_buttons[-1]["named"] = True

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth:
            self._label_depth -= 1
        if tag == "button" and self._open_buttons:
            if not self._open_buttons.pop()["named"]:
                self.controls_ok = False


def _analyze_document(document: str) -> _DocumentFacts:
    analyzer = _Analyzer()
    analyzer.feed(document)
    analyzer.close()
    return _DocumentFacts(analyzer.controls_ok, analyzer.heading_ok)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_static_checks(guide: Guide, assets: RuntimeAssets | None = None) -> StaticCheckResult:
    assets = assets or load_runtime_assets()
    packaged = load_runtime_assets()
    assets_match = (
        assets.version == RUNTIME_VERSION
        and _sha(assets.css) == _sha(packaged.css)
        and _sha(assets.javascript) == _sha(packaged.javascript)
    )
    try:
        document = assemble_guide_document(guide, assets=assets, mode="export")
    except GuideDocumentError:
        return StaticCheckResult(
            ValidationContext(render_succeeded=False, assets_match=assets_match), None
        )
    render_succeeded = all(marker in document for marker in _STRUCTURAL_MARKERS)
    facts = _analyze_document(document)
    return StaticCheckResult(
        ValidationContext(
            render_succeeded=render_succeeded,
            assets_match=assets_match,
            controls_have_labels=facts.controls_have_labels,
            heading_order_valid=facts.heading_order_valid,
        ),
        document,
    )
```

Note `ValidationContext` also has `sources_required`; it is a policy input, not a computed check — leave it at its default here (callers merge it, see Task 1.2). Export `compute_static_checks` and `StaticCheckResult` from `guides/__init__.py` following its existing `__all__` style.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_guide_static_checks.py tests/test_guide_validation.py -v`
Expected: PASS (new file green; validation suite untouched).

- [x] **Step 5: Commit**

```bash
git add education_pipeline/guides/static_checks.py education_pipeline/guides/__init__.py tests/test_guide_static_checks.py
git commit -m "feat(guides): compute ValidationContext static checks from the assembled export document"
```

### Task 1.2: Wire computed checks into validate/finalize/export; export ships the checked string

**Files:**
- Modify: `education_pipeline/runs.py` (`validate_run` ~line 1091, `_finalize_guide_v1` ~line 994, `_export_guide_v1` ~line 839, `_next_action_guide_v1` gate re-check ~line 507)
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `compute_static_checks(guide, assets) -> StaticCheckResult` (Task 1.1); `validate_guide(value, *, phase, private_values, context)`.
- Produces: a private helper in `runs.py` that every final-phase validation call goes through:

```python
def _validated_final(self, topic_id: str, source_text: str) -> tuple[ValidationReport, str | None]:
    """Validate final-phase content with computed static checks.

    Returns (report, assembled_document). document is None when the source
    does not parse (schema blockers already in the report) or assembly failed.
    """
```

Behavior: parse the source; if it parses, `normalize_guide` → `compute_static_checks` → `validate_guide(guide, phase="final", context=result.context)`; if it does not parse, fall back to `validate_guide(source_text, phase="final")` exactly as today. `_export_guide_v1` writes `result.document` (the checked string) instead of calling `assemble_guide_document` itself.

- [x] **Step 1: Write the failing tests**

Build on this module's existing guide-v1 run helpers (there are existing finalize/export tests — reuse their fixture-driven run setup):

```python
# tests/test_runs.py
def test_final_validation_report_includes_computed_static_checks(guide_v1_run):
    """A healthy run's final report has no runtime.* findings; the context was computed."""
    store, topic_id = guide_v1_run  # adapt to the existing helper's return shape
    report_path = store.validate_run(topic_id, "final")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert not [f for f in report["findings"] if f["rule_id"].startswith("runtime.")]


def test_export_refuses_when_render_fails(guide_v1_run, monkeypatch):
    store, topic_id = guide_v1_run
    from education_pipeline import runs as runs_mod
    from education_pipeline.guides.static_checks import StaticCheckResult
    from education_pipeline.guides.validation import ValidationContext

    def broken(guide, assets=None):
        return StaticCheckResult(ValidationContext(render_succeeded=False), None)

    monkeypatch.setattr(runs_mod, "compute_static_checks", broken)
    store.validate_run(topic_id, "final")
    with pytest.raises(runs_mod.ConfigError, match="blocking finding"):
        store.finalize_run(topic_id, overwrite=True)


def test_export_writes_exactly_the_checked_document(guide_v1_run):
    store, topic_id = guide_v1_run
    store.validate_run(topic_id, "final")
    store.finalize_run(topic_id, overwrite=True)
    export_path = store.export_run(topic_id, format="html", overwrite=True)
    from education_pipeline.guides import compute_static_checks
    from education_pipeline.guides.parse import normalize_guide, parse_guide

    source = store.read_approved(topic_id, "repair")
    guide = normalize_guide(parse_guide(source))
    assert export_path.read_text(encoding="utf-8") == compute_static_checks(guide).document
```

Match the actual fixture/helper names in `tests/test_runs.py` (read its existing `finalize`/`export` tests first); the bodies above are the required behavior, not the required fixture plumbing.

- [x] **Step 2: Run tests, verify failures**

Run: `python3 -m pytest tests/test_runs.py -k "static_checks or checked_document or render_fails" -v`
Expected: FAIL — `runs.py` has no `compute_static_checks` import; reports carry no computed context; export assembles independently.

- [x] **Step 3: Implement**

- Import `compute_static_checks` in `runs.py`.
- Add `_validated_final` per the interface block. Use it in `validate_run` (final phase only; draft keeps plain `validate_guide`), `_finalize_guide_v1`, `_export_guide_v1`, and the `_next_action_guide_v1` re-check at ~line 507.
- In `_export_guide_v1`, replace the direct `assemble_guide_document` call: take `report, document = self._validated_final(...)`; after the waiver gate opens, `document` must be non-`None` (a `None` document implies blocking findings, which the gate already refused) — write `document` via `_write_text_atomic`.
- Keep the existing "final validation is missing or stale" precondition checks unchanged.

- [x] **Step 4: Run the affected suites**

Run: `python3 -m pytest tests/test_runs.py tests/test_guide_static_checks.py tests/test_write_api.py tests/test_server.py -v`
Expected: PASS. (Daemon validate route flows through `validate_run`, so server tests exercise the wiring.)

- [x] **Step 5: Commit**

```bash
git add education_pipeline/runs.py tests/test_runs.py
git commit -m "feat(runs): gate finalize/export on computed static checks; export ships the checked document"
```

### Wave 1 close

- [x] Run the wave-close checklist in the Wave Protocol section.
- Suggested next-wave recommendation to print: **Fable, high effort** for Wave 2 — it spans validator schema, daemon payloads, and three cockpit surfaces in one wave.

---

# Wave 2 — Stage attribution, rerun affordance, sidecar report

### Task 2.1: `Finding.stage` from a rule→stage map

**Files:**
- Modify: `education_pipeline/guides/reports.py` (`Finding` dataclass), `education_pipeline/guides/validation.py` (`RULES` / `_finding`)
- Test: `tests/test_guide_validation.py`

**Interfaces:**
- Consumes: `Rule` dataclass (`validation.py:16`), `Finding` (`reports.py:13`).
- Produces: `Rule` gains a `stage: str` field (one of `"spec" | "outline" | "draft" | "qa" | "repair"`); `Finding` gains `stage: str` (default `"draft"` for backward construction compatibility) serialized in `to_dict()`; `ValidationReport.report_schema_version` bumps `1 → 2`. Attribution map (the stage whose rework fixes the finding):
  - `outcome.*`, `interaction.missing_required_type`, `module.no_interaction`, `time.module_total_mismatch` → `outline`
  - `runtime.*`, `a11y.*` → `repair`
  - everything else (`json.*`, `schema.*`, `content.*`, `link.*`, `privacy.*`, `source.*`, `markdown.*`, `knowledge_check.*`, `scenario.*`, `worked_reveal.*`, `personalization.*`) → `draft`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_guide_validation.py
def test_every_rule_declares_a_responsible_stage():
    from education_pipeline.guides.validation import RULES

    assert all(rule.stage in {"spec", "outline", "draft", "qa", "repair"} for rule in RULES.values())
    assert RULES["outcome.untaught"].stage == "outline"
    assert RULES["a11y.heading_order"].stage == "repair"
    assert RULES["privacy.exact_private_value"].stage == "draft"


def test_findings_carry_stage_and_report_schema_bumped():
    report = validate_guide('{"schema_version": "1.0"}', phase="draft")
    payload = report.to_dict()
    assert payload["report_schema_version"] == 2
    assert all("stage" in f for f in payload["findings"])
```

Adapt to this module's existing imports/helpers.

- [x] **Step 2: Run tests, verify failures**

Run: `python3 -m pytest tests/test_guide_validation.py -v`
Expected: FAIL — `Rule` has no `stage`, findings have no `stage`, schema version is 1.

- [x] **Step 3: Implement**

- Add `stage: str` to `Rule` and to every entry in `RULES` per the attribution map above (44 one-line edits).
- Add `stage: str = "draft"` to `Finding`; include `"stage"` in `to_dict()`; extend `__post_init__` to validate the stage value.
- Pass `rule.stage` through `_finding`.
- Bump `ValidationReport.report_schema_version` default to `2`.
- Grep for consumers of `report_schema_version` and finding dict keys (`read_api.py`, `web/src/api/types.ts` is Task 2.2's problem — Python-side only here).

- [x] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_guide_validation.py tests/test_guide_waivers.py tests/test_runs.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/guides/reports.py education_pipeline/guides/validation.py tests/test_guide_validation.py
git commit -m "feat(guides): attribute every finding to its responsible stage (report schema v2)"
```

### Task 2.2: Surface per-stage findings in the run status payload and cockpit

**Files:**
- Modify: `education_pipeline/daemon/read_api.py` (`_validation_summary` ~line 139, `run_status_payload` ~line 78)
- Modify: `web/src/api/types.ts`, `web/src/components/ValidationFindingsPanel.tsx`, `web/src/pages/RunBoardPage.tsx`
- Test: `tests/test_server.py` (or the read-api test module if one exists — check), `web/src/components/ValidationFindingsPanel.test.tsx`, new assertions in the RunBoard test file

**Interfaces:**
- Consumes: `Finding.stage` (Task 2.1), existing `validations` block in `run_status_payload`.
- Produces: `_validation_summary` adds `"findings_by_stage": {stage: count}` (blocking-or-error findings only, so badges signal actionable work); `ValidationFinding` TS type gains `stage: string`; `ValidationFindingsPanel`'s stage link (currently hardcoded `phase === "draft" ? "draft" : "repair"` at line 20) uses `finding.stage`; `RunBoardPage` renders a per-stage findings-count badge from `findings_by_stage`.

- [x] **Step 1: Write the failing Python test**

```python
# tests/test_server.py (follow this module's daemon-boot helper conventions)
def test_run_status_reports_findings_by_stage(daemon_env_with_validated_guide_run):
    status = get_json(f"/v1/runs/{topic_id}")  # adapt helper names
    summary = status["validations"]["draft"]
    assert "findings_by_stage" in summary
    assert all(isinstance(v, int) for v in summary["findings_by_stage"].values())
```

- [x] **Step 2: Run, verify failure; implement `_validation_summary`**

Run: `python3 -m pytest tests/test_server.py -k findings_by_stage -v` → FAIL.

In `_validation_summary`, after loading the report dict, add:

```python
by_stage: dict[str, int] = {}
for finding in report.get("findings", []):
    if finding.get("blocking") or finding.get("severity") == "error":
        stage = finding.get("stage", "draft")
        by_stage[stage] = by_stage.get(stage, 0) + 1
summary["findings_by_stage"] = by_stage
```

(Adapt to the function's actual local names; it currently builds the summary from the report file on disk.) Re-run → PASS. Commit:

```bash
git add education_pipeline/daemon/read_api.py tests/test_server.py
git commit -m "feat(daemon): report findings-by-stage counts in run status validations"
```

- [x] **Step 3: Write the failing web tests**

In `ValidationFindingsPanel.test.tsx`: a finding with `stage: "outline"` renders a link to `/topics/{id}/stages/outline` (today it would link to draft/repair). In the RunBoard test file: a stage row whose `findings_by_stage` count is ≥1 shows a badge with the count and an accessible name like `"2 findings"`. Follow the files' existing render/msw-or-stub patterns exactly.

Run: `cd web && npm run test` → new tests FAIL.

- [x] **Step 4: Implement the web side**

- `types.ts`: add `stage: string` to `ValidationFinding`; add `findings_by_stage: Record<string, number>` to the validation-summary type.
- `ValidationFindingsPanel.tsx`: replace the line-20 hardcode with `finding.stage` when building each finding's stage link (the panel-level phase link may keep its current target).
- `RunBoardPage.tsx`: render the badge on each stage row using the summary from the run-status payload it already fetches.

Run: `cd web && npm run test && npm run build` → PASS, clean.

- [x] **Step 5: Commit**

```bash
git add web/src/api/types.ts web/src/components/ValidationFindingsPanel.tsx web/src/pages/RunBoardPage.tsx web/src
git commit -m "feat(web): show findings at the responsible stage with per-stage badges"
```

### Task 2.3: Sidecar quality report at export

**Files:**
- Create: `education_pipeline/guides/quality_report.py`
- Modify: `education_pipeline/runs.py` (`_export_guide_v1`, new path helper), `education_pipeline/guides/__init__.py`
- Test: `tests/test_guide_reports.py` additions or new `tests/test_quality_report.py`; `tests/test_runs.py`

**Interfaces:**
- Consumes: `ValidationReport.to_dict()`, `WaiverResult` (`guides/waivers.py:23`), `RuntimeAssets`, `canonical_report_bytes` style.
- Produces:

```python
# guides/quality_report.py
QUALITY_REPORT_SCHEMA_VERSION = 1


def quality_report_bytes(
    report: ValidationReport,
    waiver_result: WaiverResult,
    waiver_set: WaiverSet | None,
    *,
    export_sha256: str,
    runtime_css_sha256: str,
    runtime_js_sha256: str,
    runtime_version: str,
) -> bytes: ...
```

Returns canonical bytes (`json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True) + "\n"`, UTF-8) of an object with keys: `quality_report_schema_version`, `gate` (`{"open": bool, "effective_blocking": int}`), `report` (full `to_dict()`), `waivers` (`{"guide_sha256", "applied": [...], "rejected": [...], "orphaned": [...], "stale": bool}`), `export` (`{"file_sha256", "runtime_version", "runtime_css_sha256", "runtime_js_sha256"}`). **No timestamps anywhere.**

`RunStore` gains `export_report_path(topic_id) -> Path` (the export HTML path with a `.report.json` suffix appended to its stem, in the same directory).

- [x] **Step 1: Write the failing tests**

```python
# tests/test_quality_report.py
def test_quality_report_bytes_are_canonical_and_timestamp_free(sample_report_and_waivers):
    a = quality_report_bytes(...)
    b = quality_report_bytes(...)
    assert a == b
    payload = json.loads(a)
    assert payload["quality_report_schema_version"] == 1
    assert "gate" in payload and "report" in payload and "export" in payload
    flat = a.decode("utf-8")
    assert "recorded_at" not in flat and "timestamp" not in flat
```

```python
# tests/test_runs.py
def test_export_writes_sidecar_quality_report_and_manifest_event(guide_v1_run):
    store, topic_id = guide_v1_run
    store.validate_run(topic_id, "final")
    store.finalize_run(topic_id, overwrite=True)
    export_path = store.export_run(topic_id, format="html", overwrite=True)
    sidecar = store.export_report_path(topic_id)
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["gate"]["open"] is True
    assert payload["export"]["file_sha256"] == hashlib.sha256(export_path.read_bytes()).hexdigest()
    manifest = store.read_manifest(topic_id)
    exported = [e for e in manifest["events"] if e.get("action") == "exported"][-1]
    assert exported["quality_report_sha256"] == hashlib.sha256(sidecar.read_bytes()).hexdigest()


def test_reexport_produces_byte_identical_quality_report(guide_v1_run):
    store, topic_id = guide_v1_run
    store.validate_run(topic_id, "final")
    store.finalize_run(topic_id, overwrite=True)
    store.export_run(topic_id, format="html", overwrite=True)
    first = store.export_report_path(topic_id).read_bytes()
    store.export_run(topic_id, format="html", overwrite=True)
    assert store.export_report_path(topic_id).read_bytes() == first
```

(Adapt manifest-event access to the real event shape, as in Task 0.1.)

- [x] **Step 2: Run, verify failures**

Run: `python3 -m pytest tests/test_quality_report.py tests/test_runs.py -k quality -v`
Expected: FAIL — module and path helper don't exist.

- [x] **Step 3: Implement**

- Write `quality_report.py` per the interface block; export from `guides/__init__.py`.
- Add `export_report_path` to `RunStore`.
- In `_export_guide_v1`, after writing the export HTML: compute `export_sha256` over the written bytes, build the sidecar bytes, `_write_bytes_atomic` it, and add `quality_report_file` to the exported event's `files` plus `quality_report_sha256` to its extras. Both writes and the event append sit inside the Task 0.1 manifest lock where the event is recorded.

> **⚠️ CORRECTION (Wave 0 shipped a different shape — following the line above verbatim deadlocks).** The lock is `_manifest_write_lock`, **non-reentrant**. The `exported` event is recorded by `_append_event`, which is a *lock-taking wrapper*. Taking the lock and then calling it re-enters the same lock and **hangs the daemon thread forever** (there is no pytest timeout, so this surfaces as a CI hang). **First extract `_append_event_locked`** — the unlocked primitive, following the existing `_append_manifest_event_locked` / `_record_stage_provenance_locked` pattern — then take the lock once and call *that* from inside the critical section. One read-modify-write cycle per critical section. Full contract in "Wave 0 outcome" in the Wave Log.

- [x] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_quality_report.py tests/test_runs.py tests/test_server.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/guides/quality_report.py education_pipeline/guides/__init__.py education_pipeline/runs.py tests/test_quality_report.py tests/test_runs.py
git commit -m "feat(export): ship a canonical sidecar quality report with every export"
```

### Task 2.4: Rerun-after-repair affordance in the cockpit

**Files:**
- Modify: `web/src/pages/RunBoardPage.tsx` (or the stage viewer if that's where validation state renders — read both first), `web/src/api/client.ts` if the POST helper is missing
- Test: the page's existing test file

**Interfaces:**
- Consumes: existing `POST /v1/runs/{topic}/validation/{phase}` route (`write_api.validate_run`, already implemented) and whatever client helper wraps it (check `client.ts` for an existing `postValidation`/`validateRun`; add one if absent).
- Produces: a visible "Re-run validation" button wherever a validation summary shows state `stale` or blocking findings, which calls the POST and refreshes the status payload.

- [x] **Step 1: Write the failing test** — clicking "Re-run validation" issues the POST and re-renders updated summary counts (stub the client per the file's existing pattern).

Run: `cd web && npm run test` → FAIL.

- [x] **Step 2: Implement** the button + client helper; loading/disabled state while in flight; surface `ApiRequestError` message per the panel's existing error pattern.

Run: `cd web && npm run test && npm run build` → PASS.

- [x] **Step 3: Commit**

```bash
git add web/src
git commit -m "feat(web): re-run validation affordance for the repair loop"
```

### Wave 2 close

- [x] Run the wave-close checklist in the Wave Protocol section.
- Suggested next-wave recommendation to print: **Opus, medium effort** for Wave 3 — CLI subcommands over existing engine paths, well-trodden patterns in `cli.py`.

---

# Wave 3 — CLI parity

### Task 3.1: `validate`, `findings`, `report` subcommands

**Files:**
- Modify: `education_pipeline/cli.py` (`_build_parser` ~line 48, new `_cmd_*` functions)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `RunStore.validate_run(topic_id, phase)`, `report_state`, report files via `draft_report_path`/`final_report_path`, `apply_waivers` + `RunStore.load_waiver_set` — add a public `RunStore.gate_result(topic_id, phase) -> WaiverResult` wrapper so the CLI never touches privates.

> **As shipped:** `load_waiver_set` was already **public** (Wave 0), not `_load_waiver_set` as this line originally said. `gate_result` **recomputes** the report from the approved source via the shared `_compute_phase_report` rather than deserializing the on-disk JSON — there is no `ValidationReport.from_dict()`, and the recompute is fail-safe because waivers are hash-bound. `validate_and_gate` was added so `validate` does not compute the same report twice.
- Produces:
  - `education-pipeline validate <topic> [--phase draft|final]` (default `final`) — runs validation, prints the summary line, exit 0 if the gate is open, exit 1 if blocking findings remain.
  - `education-pipeline findings <topic> [--phase] [--blocking]` — prints one line per finding: `severity  rule_id  stage  path  message` (tab-separated), exit 0 always (listing is not a gate).
  - `education-pipeline report <topic>` — prints the export sidecar quality report (`export_report_path`) verbatim if present, else the final validation report; exit 0/1 by `gate.open`.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_cli.py (follow the module's existing main([...]) invocation + capsys pattern)
def test_validate_command_exit_codes_track_the_gate(guide_v1_workspace, capsys):
    root, topic_id = guide_v1_workspace
    assert main(["--root", str(root), "validate", topic_id, "--phase", "final"]) == 0

def test_findings_command_lists_stage_attributed_findings(workspace_with_blockers, capsys):
    root, topic_id = workspace_with_blockers
    assert main(["--root", str(root), "findings", topic_id, "--phase", "draft"]) == 0
    out = capsys.readouterr().out
    assert "\tdraft\t" in out  # stage column present

def test_report_command_prints_sidecar_after_export(exported_guide_workspace, capsys):
    root, topic_id = exported_guide_workspace
    assert main(["--root", str(root), "report", topic_id]) == 0
    assert '"quality_report_schema_version"' in capsys.readouterr().out
```

Match `test_cli.py`'s real invocation helper and root-flag spelling (read the module's existing `_cmd_status` tests first). Build fixtures from the existing guide-v1 run helpers used by `tests/test_runs.py`.

- [x] **Step 2: Run, verify failures** — `python3 -m pytest tests/test_cli.py -k "validate_command or findings_command or report_command" -v` → FAIL (unknown command).

- [x] **Step 3: Implement** the three parsers + `_cmd_validate`, `_cmd_findings`, `_cmd_report`, and `RunStore.gate_result`. Follow the existing `_cmd_finalize`/`_cmd_status` structure (`_root(args)`, print, return int). No new output frameworks — plain `print`.

- [x] **Step 4: Run** `python3 -m pytest tests/test_cli.py tests/test_runs.py -v` → PASS. Also run the CI smoke: `education-pipeline --help` exits 0.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/cli.py education_pipeline/runs.py tests/test_cli.py
git commit -m "feat(cli): validate, findings, and report commands with gate exit codes"
```

### Task 3.1b: Waiver-aware badges and re-run affordance (added mid-wave, owner-approved)

Not in the original plan. Wave 2's whole-wave reviewer flagged that the cockpit's per-stage findings badges and "Re-run validation" button were **waiver-blind** — a run whose blockers were all waived (gate open, ready to export) still showed a red badge and an un-clearable re-run button, telling the user there was actionable work when there was none. Task 3.1 builds `RunStore.gate_result` anyway, which is the natural vehicle, so the owner folded the fix into this wave rather than deferring it to closeout.

**Files:** `education_pipeline/daemon/read_api.py` (`_validation_summary`); `web/src/api/types.ts`, `web/src/pages/RunBoardPage.tsx`, `web/src/components/ValidationFindingsPanel.tsx`; tests in `tests/test_server.py`, `web/src/components/ValidationFindingsPanel.test.tsx`, `web/src/pages/RunBoardPage.test.tsx`.

**As shipped:** `_validation_summary` reports `effective_blocking` (blocking findings remaining *after* waivers), and nets `findings_by_stage` post-waiver server-side. The badge and the re-run button key off it; waived findings still **list** in the panel (they are not hidden — only the badge and button change). A stale report still offers re-run regardless of waivers, and badges still count only reports whose `state === "current"` (`58f422f`). TS `effective_blocking` is optional with a raw-count fallback.

Two traps this task had to avoid, both of which it hit first and fixed — see the Wave 3 outcome block for the full contract:

- the recompute must not run on every 5-second status poll (short-circuited: no waivers file ⇒ `effective_blocking` *is* the raw count, so skip it) — but the short-circuit's `load_waiver_set` call must sit **inside** the `ConfigError` handler, or a malformed waivers file 400s the cockpit's hot endpoint;
- a stale on-disk report body must never be paired with a freshly recomputed gate.

- [x] Complete. Commits `e8ee4f8..18804c0`.

### Task 3.2: `waive` / `unwaive` subcommands

**Files:**
- Modify: `education_pipeline/cli.py`, `education_pipeline/runs.py` (new `RunStore.record_waiver` / `RunStore.remove_waiver`), `education_pipeline/daemon/write_api.py` (`create_waiver` delegates to the new store methods)
- Test: `tests/test_cli.py`, `tests/test_runs.py`, `tests/test_write_api.py`

**Interfaces:**
- Consumes: the waiver-file read/merge/write logic currently inlined in `write_api.create_waiver` (~lines 92–133).

> **⚠️ CORRECTION — Wave 0 already did most of this.** `RunStore.record_waiver` exists (locked via `_manifest_write_lock`, atomic, add-or-replace by `finding_id`), `RunStore.load_waiver_set` is the single source of truth for the waivers schema, and `write_api.create_waiver` is already a thin adapter over them. This task shrinks to: add `remove_waiver`, return `WaiverResult` from both, and add the CLI. **Reuse `record_waiver`/`load_waiver_set` — do not re-add them and do not introduce a fourth shape check.**

- Produces: that logic moves into the store so CLI and daemon share one implementation:

```python
def record_waiver(self, topic_id: str, phase: str, finding_id: str, reason: str) -> WaiverResult: ...
def remove_waiver(self, topic_id: str, phase: str, finding_id: str) -> WaiverResult: ...
```

Both are hash-bound to the current report's `guide_sha256`, write atomically, and return the fresh `apply_waivers` result. `write_api.create_waiver` becomes a thin adapter (its HTTP payload shape unchanged — existing server tests are the regression harness). CLI:
- `education-pipeline waive <topic> <finding-id> --reason "..." [--phase]` — exit 0 on success; refuses empty reasons and non-waivable findings with the engine's `ConfigError` message, exit 2 (argparse-style usage errors stay distinct from gate exit 1).
- `education-pipeline unwaive <topic> <finding-id> [--phase]`.

- [x] **Step 1: Write the failing tests** — store-level: `record_waiver` waives a waivable blocker and `gate_result` flips open; rejects empty reason and non-waivable ids with `ConfigError`; `remove_waiver` restores the closed gate. CLI-level: `waive` then `validate` exits 0; `waive` with empty reason exits 2. Write-api-level: existing `create_waiver` tests keep passing unchanged (that *is* the refactor test).

- [x] **Step 2: Run, verify failures** — `python3 -m pytest tests/test_runs.py tests/test_cli.py -k waive -v` → FAIL.

- [x] **Step 3: Implement** store methods (move, don't duplicate, the merge logic), rewire `write_api.create_waiver`, add CLI parsers/commands.

- [x] **Step 4: Run** `python3 -m pytest tests/test_runs.py tests/test_cli.py tests/test_write_api.py tests/test_server.py -v` → PASS.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/cli.py education_pipeline/runs.py education_pipeline/daemon/write_api.py tests/
git commit -m "feat(cli): waive/unwaive commands backed by shared store waiver methods"
```

### Wave 3 close

- [x] Run the wave-close checklist in the Wave Protocol section.
- Suggested next-wave recommendation to print: **Fable, high effort** for Wave 4 — the acceptance e2e choreographs daemon, fixtures, and UI timing, historically where this repo's subtle bugs surface.

---

# Wave 4 — Acceptance + closeout

### Task 4.1: Gate acceptance tests (pytest)

**Files:**
- Create: `tests/test_release_gate_acceptance.py`
- Possibly create: a deliberately-broken fixture `tests/fixtures/guides/feedback-loops.privacy-leak.guide.json` (the canonical fixture with one rich-text block containing a supplied private value)

**Interfaces:**
- Consumes: everything shipped in Waves 1–3; the canonical fixture `tests/fixtures/guides/feedback-loops.guide.json`.
- Produces: the milestone's executable exit criterion. Four tests:

1. **Structural refusal:** a guide-v1 run whose repair content has a schema blocker → `export_run` raises `ConfigError` and no export HTML or sidecar file exists afterward.
2. **Privacy refusal:** validation runs with `private_values` supplied (thread through however `validate_run` receives them today — if it doesn't, wire `private_values` from the attached profile snapshot as part of this task and test that path) → `privacy.exact_private_value` blocks export until the content is fixed; a waiver with a recorded reason opens the gate (it is waivable by the rule table).
3. **Reproducibility:** full validate→finalize→export twice on the same content ⇒ export HTML and sidecar report both byte-identical.
4. **Stale waivers never open the gate:** mutate the repair content after waiving ⇒ `apply_waivers` reports `stale` and export refuses.

- [ ] **Step 1: Write all four tests, run, and triage** — some may pass immediately (earlier waves built the behavior); that is fine, they are the acceptance record. Any failure is a real gap: fix it in this task with its own red-green cycle.

- [ ] **Step 2: Run** `python3 -m pytest tests/test_release_gate_acceptance.py -v` → PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_release_gate_acceptance.py tests/fixtures/guides/
git commit -m "test: release-gate acceptance — refusal, privacy, reproducibility, stale waivers"
```

### Task 4.2: Acceptance e2e (Playwright)

**Files:**
- Create: `web/e2e/release-gates.spec.ts`

**Interfaces:**
- Consumes: the cockpit surfaces from Wave 2 (per-stage badges, findings panel, waive dialog, re-run validation button, export action) and the e2e suite's existing daemon-boot + fixture-run scaffolding (reuse the scaffolding from `web/e2e/model-plan.spec.ts` and the existing validation-panel specs; the audit notes the daemon-discovery poll is duplicated — if this is the third duplication, extract the shared fixture module as the audit prescribed).
- Produces: one spec driving the full loop in the UI:

seed a guide-v1 run whose draft content contains a placeholder blocker → run board shows a findings badge on the **draft** stage → open findings panel, confirm the blocker links to the draft stage → repair the content via the editor → click "Re-run validation" → blocker cleared; a remaining waivable finding is waived with a reason through the panel → export from the UI succeeds → assert the exported HTML and `*.report.json` sidecar exist in the workspace and the report's `gate.open` is `true`.

Include the suite's standard `@axe-core` accessibility check on the findings panel and badge states.

- [ ] **Step 1: Write the spec, run it, iterate to green** — `cd web && npx playwright test e2e/release-gates.spec.ts` → PASS.

- [ ] **Step 2: Commit**

```bash
git add web/e2e/
git commit -m "test(e2e): finding -> repair -> rerun -> waive -> export acceptance loop"
```

### Task 4.3: Docs + PRD closeout

**Files:**
- Modify: `README.md` (document the CLI gate commands and the sidecar quality report), `docs/product-requirements.md` (§10 mark "P0 — Establish deterministic release gates" delivered with evidence links, same pattern as the model-plan closeout at line 485)
- Modify: this plan document (final Wave Log row)

- [ ] **Step 1: Update README** — a short "Release gates" subsection: what blocks export, how to read the sidecar report, the five CLI commands, waiver semantics (hash-bound, reason required). Keep it domain-neutral.
- [ ] **Step 2: Update the PRD** §10 status line linking this plan and spec.
- [ ] **Step 3: Commit**

```bash
git add README.md docs/product-requirements.md docs/superpowers/plans/2026-07-12-deterministic-release-gates.md
git commit -m "docs: close deterministic-release-gates milestone"
```

### Wave 4 close

- [ ] Run the wave-close checklist. This is the final wave: instead of a next-wave kickoff prompt, print a milestone summary (exit criterion met? evidence: which tests) and a recommendation for whether a post-milestone audit session (Opus or Fable, and effort) is warranted, mirroring `docs/superpowers/specs/2026-07-12-model-plan-configuration-post-milestone-audit.md`.
