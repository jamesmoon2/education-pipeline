# Release-Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (fresh implementer subagent per task, spec review + code review per task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three owner decisions and the one user-facing gap left open by the deterministic-release-gates milestone.

**Architecture:** Six independent hardening tasks over the shipped gate. Two of them change gate behavior and must land together (Task 3); one is pure test infrastructure and lands first because it is the safety net for everything after it (Task 1). Nothing here invents new subsystems — every task modifies a surface the release-gates milestone already shipped.

**Tech Stack:** Python 3.11+ stdlib only at runtime (`pytest` + `pytest-timeout` as dev dependencies); React 18 + TypeScript, vitest, Playwright.

**Spec of record:** [`docs/superpowers/specs/2026-07-13-deterministic-release-gates-post-milestone-audit.md`](../specs/2026-07-13-deterministic-release-gates-post-milestone-audit.md) §7 (owner decisions, carried triage). The owner ruled on all three §7 decisions on 2026-07-13; this plan implements those rulings. **§8 is superseded — see "Scheduling" below.**

## Scheduling (revised 2026-07-13, after personalization Wave 0 landed)

This plan was written to run *before* the personalization milestone. Personalization **Wave 0 has since landed** (`dc75c54`, `9124a7b`, `e5b0f17`; gate pytest **666**, vitest 127, e2e 42, build clean). This batch now runs **between personalization Wave 0 and Wave 1**, and it still runs first, for the same two reasons:

- Task 2 (report staleness) must land **before the report schema is extended again**. Personalization Waves 2–3 extend guide source to 1.1 and project the quality report; landing the staleness ruling after them means shipping a second generation of compatibility shims.
- Task 3 tightens a **blocking** gate. It wants to be absorbed in isolation, not discovered mid-milestone.

Nothing in Wave 0 collides with Tasks 1–6: it left `report_state`, `guides/reports.py`, `guides/static_checks.py`, `guides/document.py`, `daemon/`, and every waiver method untouched (verified). It **did** rewrite the field-selection policy that §8 of the audit documented — see the Wave-close checklist, step 4.

## Global Constraints

- `education_pipeline/` is **standard library only at runtime**. Task 1 adds `pytest-timeout` as a **dev** dependency — an explicit owner ruling overriding the "one dev dependency" convention, on the grounds that it does not touch the runtime install. No other dependency may be added.
- Strict TDD: the failing test is written and **observed to fail** before implementation, in every task.
- **This milestone's hard-won standard: verify every test is genuinely RED against the unfixed code.** Waves 3 and 4 of the predecessor each caught tests that would have passed against unfixed code — including one that could never reach the line named in its own docstring. A test that does not fail before the fix has proven nothing.
- Deterministic steps (finalize, export, validation) never call a model.
- All new file writes are atomic (`_write_bytes_atomic`: temp file + `os.replace`).
- Reports and the sidecar quality report are canonical and timestamp-free: same inputs ⇒ byte-identical bytes.
- **The manifest-lock composition contract holds:** `_manifest_write_lock` is a non-reentrant per-topic `threading.Lock` guarding the manifest *and* the waivers file. One read-modify-write cycle per critical section. Compose by taking the lock once and calling the unlocked `_locked` primitives; **never** nest a public wrapper inside the lock (it deadlocks by design). Never call a `_locked` primitive without the lock.
- **The waivers-file existence contract holds:** `read_api._validation_summary` skips its expensive per-poll gate recompute **only when the waivers file does not exist**. No writer may leave an empty waivers file behind. `_write_waiver_set_locked` is the sole writer of `waivers_path`.
- `web/`: `npm run build` (tsc) is the only type/lint gate; no eslint/prettier exists.
- Commit after every green test cycle; commit messages follow `type(scope): summary`.

## Preconditions (the human does this before Task 1)

The tracked tree is clean as of personalization Wave 0's close; the only untracked files are unrelated docs (`docs/design-demos/`, `docs/design-system.md`, `docs/superpowers/wave-runner-paper-draft.md`). **Leave them exactly as found** — the personalization plan's bootstrap made the same commitment. Do not start with modified tracked files: Task 2 changes report freshness and Task 3 changes rendered output, and both need an unambiguous baseline.

---

## Wave Protocol

This is a **single-wave** plan. The manager runs Tasks 1–6 in order, then executes the wave-close checklist personally.

### Wave-close checklist (the manager does this personally, in order)

1. Run the four-suite gate once: `python3 -m pytest`, `cd web && npm run test`, `npm run e2e`, `npm run build`. All suites green (fix or dispatch fixes until green).
2. **Update this plan document:** tick every completed checkbox and fill in the Wave Log row (commits, suite counts, deviations).
3. **Correct the audit document** (`docs/superpowers/specs/2026-07-13-deterministic-release-gates-post-milestone-audit.md`):
   - §7.1 over-claims that adopting the staleness rule makes the three stage-less-finding shims dead code. **It does not.** A stale report is still *displayed* (CLI prints it with a stderr warning; the cockpit shows it under a stale banner), so a v1 report on disk is still read and rendered and the shims still fire. What the rule actually buys is a **sunset**: the report is re-derived at v2 on the next validation instead of sitting "current" forever. Deleting the shims stays a separate future cleanup, gated on being willing to assert no v1 reports exist. Rewrite §7.1's "blast radius if declined" paragraph accordingly.
   - Record the owner's three rulings (§7.1 adopt; §7.2 adopt, with the markdown-offset fix; §7.3 add the dependency) and mark items #1, #2, #4, #5, #7, #12 of the §7 table as resolved by this plan.
4. **Mark the audit's §8 paragraph SUPERSEDED — do not copy it anywhere.** This step was originally "land §8 in the design spec". Personalization Wave 0 (`e5b0f17`) has since **replaced** the field selection it documented, so copying it would enshrine a policy that no longer exists. Instead:
   - Rewrite audit §8 to state that the policy of record is now `education_pipeline/privacy.py` (`_PROFILE_FIELD_SENSITIVITY`, `SensitivityTier`, `profile_private_values`), and that carried-triage item #10 is **resolved by personalization Wave 0**, not by this batch.
   - **Record the divergence, prominently.** The new policy screens **HIGH *and* MEDIUM** tier fields, and MEDIUM includes `learning_goals`, `preferred_examples`, `examples_to_avoid`, and `adjacent_domains`. §8 had deliberately **excluded** exactly those, on the stated grounds that they are pedagogical inputs the guide is *supposed to act on* — a course built for a learner whose goal is "ship a Rust CLI" should contain that phrase, and denylisting it makes the gate refuse personalization that is working correctly. Verified against the shipped code: a profile with `learning_goals=("ship a Rust CLI tool",)` yields a denylist containing `'ship a rust cli tool'`, and `privacy.exact_private_value` is a **blocking** finding. No test pairs a goal-bearing profile with a guide that quotes it, so this is latent — it fires on real runs, not in the suite.
   - This is an **owner policy question, not a defect to fix in this batch.** Record it; do not "correct" the tier map here. If the owner has already ruled, note the ruling and move on.
5. Commit the plan-document update and the audit corrections (§7.1 and §8).
6. **Print to the terminal, for the human:** the four-suite counts, and the verbatim kickoff prompt for personalization **Wave 1** ("Profile product surface") from `docs/superpowers/plans/2026-07-13-personalization.md` — its Wave 0 is already closed, and that plan's model table recommends **GPT-5.6 Terra, High** for Wave 1. Use that plan's own kickoff template with `N = 1`.
7. Stop.

### Wave Log

| Wave | Status | Commits | pytest | vitest | e2e | build | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 — Release-gate hardening | **closed 2026-07-13** | dd4b58e (T1), 64293c5 (T2), b6e53cd (T3), f9f19ba (T4), bf7f8b1 (T5), 1c86ffa (T6) | 684 | 130 | 43 | clean | Six tasks, all spec ✅ / quality Approved per-task; whole-branch review READY, no findings. Implementers/reviewers: Sonnet subagents (grok blocked by permission classifier; owner redirected). Deviations from plan text, all reviewer-adjudicated: **T1** `timeout = 60` ini key can't satisfy the plan's own `getoption` test on pytest-timeout 2.4.0 — landed as `addopts = "-q --timeout=60"`, identical per-test enforcement. **T3** plan's `Block(...)` constructor is a non-constructible TypeAlias — tests use `RichText`; known-ids arg follows module convention `{"known"}`. **T4** plan's `WaiverResult.report` attribute doesn't exist (guide_sha256 read from the report file instead); plan's boom-monkeypatch test was unimplementable (public method legitimately delegates to `_record_waiver`) — replaced with a spy on the public method; `waiver_env`/`_report_sha` did not pre-exist in test_write_api.py and were created under those names. **T6** existing e2e badge assertions migrated from `role="status"` queries to `.findings-badge` + aria-label (required fallout of the badge fix; one assertion strengthened). Deferred-and-accepted Minors: T4 spy test can't catch a future direct-`_record_waiver` reversion; T5 `do_DELETE` omits `do_PUT`'s inline taxonomy comment. Canonical fixture bytes/SHA verified unchanged (T3 premise held). |

**Baseline: pytest 666, vitest 127, e2e 42, build clean** — the personalization Wave 0 close (`e5b0f17`), *not* the release-gates gate of 600. Wave 0 added `tests/test_personalization_privacy.py` (+66 tests) between this plan's authoring and its execution. If a task's suite run shows fewer than 666 passing before your change, stop: something else regressed and it is not yours.

---

## Task 1: `pytest-timeout` — make a lock-nesting regression fail instead of hang

Lands first: it is the safety net for every task after it. The manifest-lock contract deadlocks **on purpose** (fail-loud was chosen over the silent lost-updates an `RLock` produced), so a nesting regression today does not fail CI — it *hangs* CI, burning the wall-clock budget and reporting a timeout with no failing test to point at. Tasks 4 and 5 add a new caller to exactly that locked path.

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies]` ~line 33; `[tool.pytest.ini_options]` ~line 44)
- Test: `tests/test_packaging.py` (create)

**Interfaces:**
- Produces: a global per-test timeout, active for every pytest run including CI. Later tasks rely on nothing from this task at the code level; they rely on it operationally.

- [x] **Step 1: Write the failing test**

```python
# tests/test_packaging.py
"""Dev-tooling guarantees the suite itself depends on."""


def test_pytest_timeout_is_active_with_a_global_timeout(pytestconfig):
    """A lock-nesting regression must fail a test, not hang the run.

    The manifest-lock contract deadlocks by design (see runs.py). Without a
    timeout that surfaces as a CI hang with no failing test; with one it is a
    crisp per-test failure naming the offending test.
    """

    assert pytestconfig.pluginmanager.hasplugin("timeout")
    assert pytestconfig.getoption("timeout") == 60
```

- [x] **Step 2: Run the test, verify it fails**

Run: `python3 -m pytest tests/test_packaging.py -v`
Expected: FAIL — the `timeout` plugin is not installed, so `hasplugin("timeout")` is `False` (and `getoption("timeout")` raises `ValueError: no option named 'timeout'`).

- [x] **Step 3: Implement**

In `pyproject.toml`, extend the dev extra:

```toml
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-timeout"]
```

and add the global timeout to the pytest config:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
timeout = 60
```

Then install it: `python3 -m pip install -e ".[dev]"`.

Note for the implementer: 60 seconds is a deliberately generous per-test ceiling — the slowest existing tests boot a live daemon and finish in low single-digit seconds. The timeout exists to catch a *hang*, not to police slowness. Do not tune it downward to make tests "fast"; that converts a diagnostic into a flake source.

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_packaging.py -v && python3 -m pytest`
Expected: PASS — new test green, and the full suite still green (no existing test exceeds 60 s).

- [x] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "test: add pytest-timeout so a lock-nesting deadlock fails instead of hanging CI"
```

---

## Task 2: `report_state` treats a pre-v2 report as stale

Owner decision §7.1, adopted. `report_state` derives freshness purely from content and never looks at `report_schema_version`, so a **v1 report** (pre-stage-attribution) against unchanged content reports `"current"` **forever** and nothing will ever prompt a revalidation.

**Read this before implementing:** marking v1 stale does **not** make the stage-less-finding fallbacks unreachable. A stale report is still *displayed* (the CLI prints the on-disk body with a stderr warning; the cockpit renders it under a stale banner), so those fallbacks still fire until the user revalidates. This task buys a **sunset**, not a deletion. **Do not remove** `read_api.py`'s `finding.get("stage", "draft")` defaults or the TS phase-derived fallback in this task.

**Files:**
- Modify: `education_pipeline/guides/reports.py` (add the module constant; `report_schema_version` field ~line 84)
- Modify: `education_pipeline/guides/__init__.py` (export the constant)
- Modify: `education_pipeline/runs.py` (`report_state` ~line 1223; the import block that already pulls from `.guides`)
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `RunStore.report_state(topic_id, phase) -> str` (`"missing" | "current" | "stale"`), unchanged signature.
- Produces: `REPORT_SCHEMA_VERSION = 2` exported from `education_pipeline.guides` — the single constant behind both the emitted report and the freshness check. Task 3 does not depend on it.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_runs.py
def test_pre_v2_report_is_stale_even_when_content_is_unchanged(tmp_path):
    """A v1 report predates stage attribution. Against unchanged content it
    must NOT sit "current" forever -- it must read stale so the existing
    re-run affordance re-derives it at v2."""

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)
    assert runs.report_state(tid, "final") == "current"

    report_path = runs.final_report_path(tid)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["report_schema_version"] == 2
    report["report_schema_version"] = 1
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    assert runs.report_state(tid, "final") == "stale"


def test_report_missing_schema_version_is_stale(tmp_path):
    """A report with no version key at all is older still -- also stale."""

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)

    report_path = runs.final_report_path(tid)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["report_schema_version"]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    assert runs.report_state(tid, "final") == "stale"


def test_current_v2_report_stays_current(tmp_path):
    """Regression guard: the version check must not make a healthy v2 report
    stale (which would livelock every run at 'stale')."""

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)
    assert runs.report_state(tid, "final") == "current"
    assert runs.report_state(tid, "final") == "current"
```

Reuse this module's existing helpers `_create_guide_run` and `_drive_guide_to_finalize_ready` (they are the same helpers `tests/test_release_gate_acceptance.py` imports); `json` is already imported in `tests/test_runs.py`.

- [x] **Step 2: Run the tests, verify they fail**

Run: `python3 -m pytest tests/test_runs.py -k "pre_v2_report or missing_schema_version or stays_current" -v`
Expected: FAIL on the first two — `report_state` returns `"current"` for the downgraded report because it never inspects `report_schema_version`. The third passes already (it is the regression guard, and it must keep passing after Step 3).

- [x] **Step 3: Implement**

In `education_pipeline/guides/reports.py`, hoist the version into a module constant and use it as the field default:

```python
REPORT_SCHEMA_VERSION = 2
```

```python
    report_schema_version: int = REPORT_SCHEMA_VERSION
```

Export it from `education_pipeline/guides/__init__.py`, following that module's existing import/`__all__` style (add `REPORT_SCHEMA_VERSION` to the `from .reports import ...` line and to `__all__`).

In `education_pipeline/runs.py`, add `REPORT_SCHEMA_VERSION` to the existing `from .guides import ...` block, then in `report_state`, immediately after the existing phase check and before the `guide_sha256` comparison:

```python
        if not isinstance(report, dict) or report.get("phase") != phase:
            return "stale"
        schema_version = report.get("report_schema_version")
        if not isinstance(schema_version, int) or schema_version < REPORT_SCHEMA_VERSION:
            # A pre-v2 report predates stage attribution. Its findings are
            # still displayed (under the stale banner), but it must not sit
            # "current" forever against unchanged content: reading it stale
            # routes the run through the re-run affordance that already
            # exists, which re-derives the report at the current schema.
            return "stale"
        recorded = report.get("guide_sha256")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_runs.py tests/test_guide_validation.py tests/test_server.py tests/test_cli.py -v`
Expected: PASS. If an existing test wrote a hand-rolled report fixture without `report_schema_version` and asserted `"current"`, that fixture encoded the old behavior — update it to emit the current schema version and say so in the commit message.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/guides/reports.py education_pipeline/guides/__init__.py education_pipeline/runs.py tests/test_runs.py
git commit -m "fix(runs): treat a pre-v2 validation report as stale so legacy workspaces self-heal"
```

---

## Task 3: Heading order tracks the previous heading — and markdown headings stop skipping a level

Owner decision §7.2, adopted. **Both halves land in this one task; neither is safe alone.**

The analyzer's rule ("no more than one level deeper than the *deepest* heading seen so far") is not a skipped-heading check: once any `h3` appears anywhere, a later `h2 → h4` is waved through. Tracking the **previous** heading fixes it.

But tightening the rule alone creates a **trap**, and this is the crux of the task. The assembled document's headings are shell-owned: `h1` course title → `h2` section titles → `h3` block prompts. A `rich_text` block renders **bare markdown with no `h3` title**. Learner markdown is rendered with a **`+2` offset** (`document.py:101`), and a separate blocking rule (`markdown.invalid_heading_level`) **bans `#`** — so the shallowest heading an author may legally write is `##`, which renders as **`h4`**. A section whose first block is a `rich_text` opening with `## Foo` therefore renders `h2 → h4`: a real skip, and an entirely ordinary way to write a lesson. Under the tightened rule that blocks the export, and the finding's natural remediation ("use one level shallower") is **forbidden by the other blocking rule**. A blocking finding whose fix is banned by a second blocking finding is not shippable.

The fix is to change the offset to `+1`, so `##` renders as `h3` and slots directly under the section's `h2`. The model keeps writing exactly what it writes today; we stop dropping it a rung too far.

**Verified before planning:** the canonical fixture's assembled heading sequence is `1,2,2,2,3,2,3,3,2,3,3,2,3,3,2,2,2` — zero skips under the tightened rule — and it contains **zero** markdown headings, so the offset change leaves its bytes (and its export SHA) untouched.

**Files:**
- Modify: `education_pipeline/guides/static_checks.py` (`_Analyzer.__init__` ~line 37; `_Analyzer.handle_starttag` heading branch ~lines 50-54)
- Modify: `education_pipeline/guides/document.py` (`render_guide_markdown` heading branch, lines 100-102)
- Test: `tests/test_guide_static_checks.py`, `tests/test_guide_document.py`

**Interfaces:**
- Consumes: `_analyze_document(document: str) -> _DocumentFacts` and `compute_static_checks(guide, assets=None) -> StaticCheckResult` (both unchanged signatures).
- Produces: no new names. `heading_order_valid` becomes strictly more sensitive; `render_guide_markdown` emits `h3..h6` instead of `h3..h6` shifted one deeper.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_guide_static_checks.py
def test_previous_heading_skip_is_detected_even_after_a_deeper_heading():
    """The rule the deepest-seen implementation missed: h1,h2,h3 establishes
    depth 3, so a later h2 -> h4 was waved through even though it skips h3."""
    from education_pipeline.guides.static_checks import _analyze_document

    doc = "<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2><h4>e</h4>"
    assert _analyze_document(doc).heading_order_valid is False


def test_returning_to_a_shallower_heading_is_never_a_skip():
    from education_pipeline.guides.static_checks import _analyze_document

    doc = "<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2><h3>e</h3>"
    assert _analyze_document(doc).heading_order_valid is True


def test_document_whose_first_heading_is_below_h1_is_a_skip():
    """Unreachable through the assembler (the shell always emits <h1> first),
    but the analyzer is a general-purpose checker and must not pass a document
    that opens four levels deep."""
    from education_pipeline.guides.static_checks import _analyze_document

    assert _analyze_document("<h4>a</h4>").heading_order_valid is False
    assert _analyze_document("<h1>a</h1><h2>b</h2>").heading_order_valid is True
```

```python
# tests/test_guide_static_checks.py  (the integration test that proves the trap is gone)
def test_rich_text_section_opening_with_a_markdown_heading_passes(guide):
    """A section whose first block is rich_text opening with '##' must not
    skip a heading level: the shell emits <h2> for the section title, so the
    markdown heading must render as <h3>, not <h4>.

    This is the ordinary shape of a written lesson and the exact case the
    tightened rule would otherwise block with no legal remediation ('#' is
    banned by markdown.invalid_heading_level).
    """
    import dataclasses

    from education_pipeline.guides.model import Block

    section = guide.modules[0].sections[0]
    heading_block = Block(
        id="blk-md-heading",
        type="rich_text",
        markdown="## Why loops compound\n\nA short explanation.",
    )
    patched_section = dataclasses.replace(section, blocks=(heading_block, *section.blocks))
    patched_module = dataclasses.replace(
        guide.modules[0], sections=(patched_section, *guide.modules[0].sections[1:])
    )
    patched = dataclasses.replace(guide, modules=(patched_module, *guide.modules[1:]))

    result = compute_static_checks(patched)
    assert result.document is not None
    assert "<h3>Why loops compound</h3>" in result.document
    assert result.context.heading_order_valid is True
```

The implementer must read `guides/model.py` first and match `Block`'s **actual** required fields and the `Guide`/`Module`/`Section` attribute names; the body above states the required behavior, not the required constructor plumbing. If `Block` requires fields not shown, supply them from the canonical fixture's existing `rich_text` block.

```python
# tests/test_guide_document.py
def test_markdown_headings_nest_one_level_under_the_section_heading():
    """The shell owns <h1> (course title) and <h2> (section title). '##' is the
    shallowest heading a learner-Markdown author may write (markdown.invalid_
    heading_level bans '#'), so it must render as <h3> -- directly under the
    section heading, skipping nothing."""
    from education_pipeline.guides.document import render_guide_markdown

    assert render_guide_markdown("## Foo", []) == "<h3>Foo</h3>"
    assert render_guide_markdown("### Bar", []) == "<h4>Bar</h4>"
    assert render_guide_markdown("###### Deep", []) == "<h6>Deep</h6>"
```

Match this module's existing call convention for `render_guide_markdown` (read a neighbouring test first — the second argument is the known-ids iterable) and its assertion style; if the renderer wraps output in a container, assert containment rather than equality.

- [x] **Step 2: Run the tests, verify they fail**

Run: `python3 -m pytest tests/test_guide_static_checks.py tests/test_guide_document.py -k "previous_heading or shallower or first_heading or rich_text_section or markdown_headings_nest" -v`
Expected: FAIL —
- `test_previous_heading_skip_is_detected_even_after_a_deeper_heading`: returns `True` (deepest-seen waves it through).
- `test_document_whose_first_heading_is_below_h1_is_a_skip`: returns `True` (the `if self._deepest_heading and ...` guard short-circuits on the first heading).
- `test_rich_text_section_opening_with_a_markdown_heading_passes`: the document contains `<h4>Why loops compound</h4>`, not `<h3>`.
- `test_markdown_headings_nest_one_level_under_the_section_heading`: `## Foo` renders `<h4>Foo</h4>`.
- `test_returning_to_a_shallower_heading_is_never_a_skip` passes already — it is the regression guard.

- [x] **Step 3: Implement**

In `education_pipeline/guides/static_checks.py`, rename the tracked state and change the comparison. In `_Analyzer.__init__`:

```python
        self.heading_ok = True
        self._previous_heading = 0
```

and in `handle_starttag`, replace the heading branch:

```python
        if tag in _HEADINGS:
            level = _HEADINGS[tag]
            # Skip detection is relative to the *previous* heading, not the
            # deepest seen so far: after h1,h2,h3, a later h2 -> h4 skips h3
            # even though an h3 appeared earlier in the document. A document
            # whose first heading is deeper than h1 has skipped the levels
            # above it. Going shallower is never a skip.
            allowed = self._previous_heading + 1 if self._previous_heading else 1
            if level > allowed:
                self.heading_ok = False
            self._previous_heading = level
```

In `education_pipeline/guides/document.py`, change the markdown heading offset from `+2` to `+1` (lines 100-102):

```python
        elif match := re.match(r"^(#{1,6})\s+(.+)$", line):
            # Learner Markdown nests *under* the shell's structure: the shell
            # owns <h1> (course title) and <h2> (section titles), and
            # markdown.invalid_heading_level bans a level-one Markdown
            # heading -- so the shallowest heading an author may write, '##',
            # must render as <h3>, one level below the section heading it sits
            # under. A +2 offset put it at <h4>, skipping a level in any
            # section whose first block is a heading-leading rich_text block.
            flush(); level = min(6, len(match.group(1)) + 1)
            rendered.append(f"<h{level}>{_inline(match.group(2), ids)}</h{level}>")
```

- [x] **Step 4: Run the affected suites**

Run: `python3 -m pytest tests/test_guide_static_checks.py tests/test_guide_document.py tests/test_guide_canonical.py tests/test_guide_validation.py tests/test_runs.py tests/test_release_gate_acceptance.py -v`
Expected: PASS. The canonical fixture has no markdown headings, so `test_guide_canonical.py` (which pins the fixture's normalized SHA and assembled bytes) must be **unchanged** — if it fails, the offset change altered the canonical document and the plan's premise is wrong: **stop and report**, do not update the golden.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/guides/static_checks.py education_pipeline/guides/document.py tests/test_guide_static_checks.py tests/test_guide_document.py
git commit -m "fix(guides): detect heading skips against the previous heading and nest markdown headings one level under the section"
```

---

## Task 4: Promote the waiver store's public tuple methods; stop `write_api` reaching into privates

Carried triage item #2. `write_api.create_waiver` calls the **private** `runs._record_waiver` because it needs the `WaiverSet` written *inside* the locked critical section (an unlocked re-read afterward is racy and dereferences an unchecked Optional). The need is legitimate; the layering is not. Promote it — and make removal symmetric, because Task 5's DELETE route needs exactly the same thing.

**Files:**
- Modify: `education_pipeline/runs.py` (`record_waiver` ~line 1797; `_record_waiver` ~line 1811; `remove_waiver` ~line 1869)
- Modify: `education_pipeline/daemon/write_api.py` (`create_waiver` ~line 145)
- Test: `tests/test_runs.py`, `tests/test_write_api.py`

**Interfaces:**
- Consumes: the existing private `_record_waiver(topic_id, phase, finding_id, reason) -> tuple[WaiverResult, WaiverSet]`, and `remove_waiver`'s existing locked body (which already builds `new_set` inside the lock — it simply discards it).
- Produces (Task 5 depends on these exact names):

```python
def record_waiver_with_set(
    self, topic_id: str, phase: str, finding_id: str, reason: str
) -> tuple[WaiverResult, WaiverSet]: ...


def remove_waiver_with_set(
    self, topic_id: str, phase: str, finding_id: str
) -> tuple[WaiverResult, WaiverSet]: ...
```

Both return the `WaiverSet` as it stands **after** the write, built inside the critical section. On the removal path that unlinks the file (last waiver removed), the returned set is the empty set for the current `guide_sha256` — the file's absence and an empty set are the same state to every reader, and returning it lets the caller build a response without a second read.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_runs.py
def test_record_waiver_with_set_returns_the_written_set(tmp_path):
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)
    finding_id = _first_waivable_blocking_finding_id(runs, tid, "final")

    result, waiver_set = runs.record_waiver_with_set(tid, "final", finding_id, "reviewed")

    assert result.gate_open is True
    assert [w.finding_id for w in waiver_set.waivers] == [finding_id]
    assert waiver_set.guide_sha256 == runs.gate_result(tid, "final").report.guide_sha256


def test_remove_waiver_with_set_returns_the_empty_set_and_leaves_no_file(tmp_path):
    """Removing the last waiver must unlink the file, not write an empty one:
    read_api skips its per-poll gate recompute only when the file is ABSENT,
    so an empty file would permanently defeat that optimization for this topic."""
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)
    finding_id = _first_waivable_blocking_finding_id(runs, tid, "final")
    runs.record_waiver(tid, "final", finding_id, "reviewed")
    assert runs.waivers_path(tid).exists()

    result, waiver_set = runs.remove_waiver_with_set(tid, "final", finding_id)

    assert result.gate_open is False
    assert waiver_set.waivers == ()
    assert not runs.waivers_path(tid).exists()
    assert runs.load_waiver_set(tid) is None


def test_remove_waiver_with_set_no_op_writes_nothing(tmp_path):
    """Removing an id that was never waived must not create the file."""
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)

    result, waiver_set = runs.remove_waiver_with_set(tid, "final", "never.waived:/root")

    assert waiver_set.waivers == ()
    assert not runs.waivers_path(tid).exists()
    assert result.gate_open is False
```

`_prompt_leak_guide_json` already exists in `tests/test_runs.py` (the acceptance suite imports it). Add the small local helper `_first_waivable_blocking_finding_id(runs, tid, phase)` if this module does not already have an equivalent — read the module first and reuse its helper if one exists:

```python
def _first_waivable_blocking_finding_id(runs, topic_id: str, phase: str) -> str:
    report = json.loads(runs.final_report_path(topic_id).read_text(encoding="utf-8"))
    for finding in report["findings"]:
        if finding["blocking"] and finding["waivable"]:
            return finding["id"]
    raise AssertionError("fixture produced no waivable blocking finding")
```

```python
# tests/test_write_api.py
def test_create_waiver_does_not_reach_into_private_store_methods(monkeypatch, waiver_env):
    """write_api must consume the public tuple method, not runs._record_waiver.

    The daemon genuinely needs the WaiverSet written *inside* the lock, but it
    must get it through a public contract rather than a private attribute.
    """
    from education_pipeline import runs as runs_mod

    runs, topic_id, finding_id = waiver_env

    def boom(*args, **kwargs):
        raise AssertionError("write_api must not call the private _record_waiver")

    monkeypatch.setattr(runs_mod.RunStore, "_record_waiver", boom)

    payload = write_api.create_waiver(
        runs, topic_id, "final", finding_id, _report_sha(runs, topic_id), "reviewed"
    )

    assert [w["finding_id"] for w in payload["waivers"]["waivers"]] == [finding_id]
```

`waiver_env` / `_report_sha` are this module's existing fixture and hash helper (see Task 5's note); read them first and use their real names. The assertion — that the private method is never called, and the endpoint still works — is the requirement.

- [x] **Step 2: Run the tests, verify they fail**

Run: `python3 -m pytest tests/test_runs.py tests/test_write_api.py -k "with_set or private_store" -v`
Expected: FAIL — `AttributeError: 'RunStore' object has no attribute 'record_waiver_with_set'` / `'remove_waiver_with_set'`, and the `write_api` test fails via the `boom` assertion (it calls `_record_waiver` today).

- [x] **Step 3: Implement**

In `education_pipeline/runs.py`, add the public wrapper next to `record_waiver`:

```python
    def record_waiver_with_set(
        self, topic_id: str, phase: str, finding_id: str, reason: str
    ) -> tuple[WaiverResult, WaiverSet]:
        """Waive one finding and return both the gate and the written set.

        Public form of :meth:`_record_waiver`, for callers (the daemon) that
        must render the persisted waiver set in their response. The set is the
        one built *inside* the locked critical section: a second, unlocked
        ``load_waiver_set`` afterward would be racy (a concurrent writer bound
        to a different ``guide_sha256`` could land between the two calls and
        silently drop the waiver just recorded) and would dereference an
        unchecked Optional.
        """

        return self._record_waiver(topic_id, phase, finding_id, reason)
```

Refactor `remove_waiver` so its locked body is reusable, preserving every existing invariant (no-op writes nothing; last-waiver removal unlinks; `_write_waiver_set_locked` stays the sole writer):

```python
    def remove_waiver(self, topic_id: str, phase: str, finding_id: str) -> WaiverResult:
        """Remove one finding's waiver for ``phase`` and return the resulting gate.

        [keep the existing docstring body verbatim -- it documents the
        no-op-writes-nothing and unlink-on-last-removal invariants that the
        daemon's per-poll short-circuit depends on]
        """

        result, _ = self._remove_waiver(topic_id, phase, finding_id)
        return result

    def remove_waiver_with_set(
        self, topic_id: str, phase: str, finding_id: str
    ) -> tuple[WaiverResult, WaiverSet]:
        """Removal's counterpart to :meth:`record_waiver_with_set`.

        The returned set is the state after the write. When the last waiver is
        removed the file is unlinked and the set is empty for the current
        ``guide_sha256`` -- an absent file and an empty set are the same state
        to every reader, so the caller can build its response without a second
        (racy) read.
        """

        return self._remove_waiver(topic_id, phase, finding_id)

    def _remove_waiver(
        self, topic_id: str, phase: str, finding_id: str
    ) -> tuple[WaiverResult, WaiverSet]:
        safe_id, _, _, _, report = self._compute_phase_report(topic_id, phase)
        guide_sha256 = report.guide_sha256
        with self._manifest_write_lock(safe_id):
            items = self._current_waiver_items_locked(safe_id, guide_sha256)
            filtered = [item for item in items if item["finding_id"] != finding_id]
            if filtered == items:
                new_set = self._build_waiver_set(guide_sha256, items)
            elif filtered:
                new_set = self._write_waiver_set_locked(safe_id, guide_sha256, filtered)
            else:
                self.waivers_path(safe_id).unlink(missing_ok=True)
                new_set = self._build_waiver_set(guide_sha256, [])
        return apply_waivers(report, new_set), new_set
```

This is a pure move of the existing body — **do not** change the branch logic. One read-modify-write per critical section; only `_locked` primitives inside the lock.

In `education_pipeline/daemon/write_api.py`, switch `create_waiver` to the public method (keep the surrounding comment block, which explains *why* the in-lock set is needed, but update its final paragraph to name the public method):

```python
    _, waiver_set = runs.record_waiver_with_set(topic_id, phase, finding_id, reason.strip())
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_runs.py tests/test_write_api.py tests/test_server.py tests/test_guide_waivers.py tests/test_release_gate_acceptance.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/runs.py education_pipeline/daemon/write_api.py tests/test_runs.py tests/test_write_api.py
git commit -m "refactor(runs): promote public record/remove waiver methods returning the in-lock WaiverSet"
```

---

## Task 5: `DELETE` waiver route — the cockpit can close a gate it opened

Carried triage item #1, and the sharpest user-facing gap in the milestone: the cockpit can **open** a gate (record a waiver) but never **re-close** one. A waiver recorded by mistake is unremovable from the UI; recovery is the CLI or hand-editing the workspace. The engine has supported removal since Wave 3 — it is simply not exposed.

**Files:**
- Modify: `education_pipeline/daemon/write_api.py` (add `delete_waiver` next to `create_waiver`)
- Modify: `education_pipeline/daemon/server.py` (add `do_DELETE` + `_api_delete_routes`; add `from urllib.parse import unquote`)
- Test: `tests/test_write_api.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `RunStore.remove_waiver_with_set(topic_id, phase, finding_id) -> tuple[WaiverResult, WaiverSet]` (Task 4); `read_api.validation_payload(runs, topic_id, phase) -> dict`.
- Produces (Task 6 depends on this exact route and response shape):

```
DELETE /v1/runs/{topic_id}/validation/{draft|final}/waivers/{finding_id}
  -> 200 {"waivers": {"schema_version": int, "guide_sha256": str,
                      "waivers": [{"finding_id": str, "reason": str}, ...]},
          ...validation_payload}
```

Identical response shape to `POST .../waivers`, so the cockpit can reuse its existing `WaiverResult` type verbatim.

**Two design notes the implementer must not "fix":**
1. **`finding_id` is URL-encoded and must be `unquote`d.** Finding ids embed a JSON path — e.g. `a11y.heading_order:/sections/0` — so they contain `/`. The client sends `encodeURIComponent(findingId)` (`%2F`), the `([^/?]+)` segment matches the encoded form, and the handler decodes it. The decoded id is only ever string-compared against waiver entries — it is **never** used to build a filesystem path — so decoding introduces no traversal surface.
2. **`DELETE` takes no body and no `guide_sha256` guard**, unlike `POST`. Removal is fail-safe by construction: `remove_waiver` recomputes the report and hash-binds internally, and a removal can only ever *close* a gate, never open one. An optimistic-concurrency guard would add a failure mode without preventing one.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_write_api.py
def test_delete_waiver_removes_it_and_returns_the_remaining_set(waiver_env):
    """Record a waiver, then delete it: the gate re-closes and the file is gone."""
    runs, topic_id, finding_id = waiver_env
    write_api.create_waiver(
        runs, topic_id, "final", finding_id, _report_sha(runs, topic_id), "reviewed"
    )
    assert runs.waivers_path(topic_id).exists()

    payload = write_api.delete_waiver(runs, topic_id, "final", finding_id)

    assert payload["waivers"]["waivers"] == []
    assert payload["report"]["summary"]["blocking"] >= 1
    assert not runs.waivers_path(topic_id).exists()


def test_delete_waiver_for_an_unwaived_finding_is_a_no_op(waiver_env):
    """Removing an id that was never waived must not create the waivers file."""
    runs, topic_id, _ = waiver_env

    payload = write_api.delete_waiver(runs, topic_id, "final", "never.waived:/root")

    assert payload["waivers"]["waivers"] == []
    assert not runs.waivers_path(topic_id).exists()
```

`waiver_env` and `_report_sha` stand for this module's **existing** fixture and hash helper behind its `create_waiver` tests — read them first and use their real names and return shapes. If no such fixture exists, build one from `test_runs._create_guide_run` + `_drive_guide_to_finalize_ready` + `_prompt_leak_guide_json` (the same trio the acceptance suite uses) rather than inventing new plumbing.

```python
# tests/test_server.py
def test_delete_waiver_route_removes_the_waiver(...):
    """Adapt this module's existing daemon boot helper and its POST-waiver test."""
    from urllib.parse import quote

    # ... boot daemon, drive a run to a waivable blocking finding, POST a waiver
    status, body = _request(
        "DELETE",
        f"/v1/runs/{topic}/validation/final/waivers/{quote(finding_id, safe='')}",
    )
    assert status == 200
    assert body["waivers"]["waivers"] == []


def test_delete_waiver_leaves_no_empty_waivers_file(...):
    """The waivers-file existence contract: read_api skips its per-poll gate
    recompute only when the file is ABSENT. Removing the last waiver over HTTP
    must unlink it, not write '{"waivers": []}'."""
    # ... POST a waiver, then DELETE it
    assert not runs.waivers_path(topic).exists()


def test_delete_unknown_path_is_404(...):
    status, body = _request("DELETE", "/v1/runs/nope/nonsense")
    assert status == 404
    assert body["error"]["code"] == "not_found"
```

Read `tests/test_server.py` first and reuse its existing daemon boot helper and request helper (the module has one; if the helper hardcodes GET/POST/PUT, extend it to take a method rather than writing a second one).

- [x] **Step 2: Run the tests, verify they fail**

Run: `python3 -m pytest tests/test_write_api.py tests/test_server.py -k "delete_waiver or delete_unknown" -v`
Expected: FAIL — `AttributeError: module 'write_api' has no attribute 'delete_waiver'`, and the HTTP tests fail with **501 Unsupported method ('DELETE')** from `BaseHTTPRequestHandler`, since no `do_DELETE` exists.

- [x] **Step 3: Implement**

In `education_pipeline/daemon/write_api.py`, add next to `create_waiver`:

```python
def delete_waiver(runs: RunStore, topic_id: str, phase: str, finding_id: str) -> dict:
    """Remove one waiver and return the resulting waiver set plus validation payload.

    Mirrors ``create_waiver``'s response shape so the cockpit reuses one type.

    No ``guide_sha256`` guard, unlike ``create_waiver``: removal is fail-safe
    by construction. ``remove_waiver_with_set`` recomputes the report and
    hash-binds internally, and a removal can only ever close a gate, never
    open one -- so an optimistic-concurrency check would add a failure mode
    without preventing one. Uses the public tuple method so the rendered set
    is the one written inside the locked critical section (an unlocked re-read
    would be racy).
    """

    _, waiver_set = runs.remove_waiver_with_set(topic_id, phase, finding_id)
    value = {
        "schema_version": waiver_set.schema_version,
        "guide_sha256": waiver_set.guide_sha256,
        "waivers": [
            {"finding_id": w.finding_id, "reason": w.reason} for w in waiver_set.waivers
        ],
    }
    return {"waivers": value, **read_api.validation_payload(runs, topic_id, phase)}
```

In `education_pipeline/daemon/server.py`, add the import at the top:

```python
from urllib.parse import unquote
```

and add the verb handler after `do_PUT`/`_api_put_routes`, mirroring `do_PUT`'s structure **exactly** — same pre-route `_guard()` inside the try, same exception arms, same last-resort handler, so nothing on this path can drop the socket:

```python
        def do_DELETE(self):
            # Wrap the whole verb, including the pre-route _guard() check,
            # so nothing on this path can escape to socketserver.
            self._response_started = False
            try:
                if not self._guard():
                    return
                return self._api_delete_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except write_api.ConflictError as exc:
                return self._error(409, exc.code, str(exc))
            except write_api.UnprocessableError as exc:
                return self._error(422, exc.code, str(exc), exc.details)
            except (GuideDocumentError, ContractError, GuideParseError) as exc:
                return self._error(422, "guide_not_renderable", str(exc))
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))
            except Exception as exc:  # last resort: never drop the connection
                return self._last_resort(exc)

        def _api_delete_routes(self):
            m = re.match(
                r"^/v1/runs/([^/?]+)/validation/(draft|final)/waivers/([^/?]+)$", self.path
            )
            if m:
                # Finding ids embed a JSON path (e.g. "a11y.heading_order:/sections/0"),
                # so the client percent-encodes the segment. The decoded id is only
                # string-compared against waiver entries -- never used to build a
                # filesystem path -- so decoding adds no traversal surface.
                return self._send(
                    200,
                    write_api.delete_waiver(
                        context.runs, m.group(1), m.group(2), unquote(m.group(3))
                    ),
                )
            self._error(404, "not_found", "unknown path")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_write_api.py tests/test_server.py tests/test_runs.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add education_pipeline/daemon/write_api.py education_pipeline/daemon/server.py tests/test_write_api.py tests/test_server.py
git commit -m "feat(daemon): add DELETE waiver route so a waiver can be removed from the cockpit"
```

---

## Task 6: Cockpit — unwaive affordance, and the findings badge stops shouting

Two cockpit changes. The unwaive control closes the parity gap Task 5 opened the door for; the badge fix is carried triage item #5 (`role="status"` is a live region, so with 5-second polling every count change re-announces to screen readers).

`ValidationFindingsPanel` already loads waivers, computes `waivedIds`, has a `"waived"` status filter, and renders a `waived` marker per finding — so the control has a home and needs no new data plumbing.

**Files:**
- Modify: `web/src/api/client.ts` (add `deleteWaiver` next to `postWaiver` ~line 192)
- Modify: `web/src/api/types.ts` (no new types needed — `DELETE` returns `WaiverResult`; confirm and leave unchanged)
- Modify: `web/src/components/ValidationFindingsPanel.tsx` (the finding `<li>` render ~line 204-222)
- Modify: `web/src/pages/RunBoardPage.tsx` (the findings badge, ~lines 149-156)
- Test: `web/src/components/ValidationFindingsPanel.test.tsx`, `web/src/pages/RunBoardPage.test.tsx`, `web/e2e/release-gates.spec.ts`

**Interfaces:**
- Consumes: `DELETE /v1/runs/{topic}/validation/{phase}/waivers/{finding_id}` returning `WaiverResult` (Task 5).
- Produces: `deleteWaiver(topicId, phase, findingId) => Promise<WaiverResult>` in `client.ts`.

- [x] **Step 1: Write the failing tests**

```tsx
// web/src/components/ValidationFindingsPanel.test.tsx
it("removes a waiver when Unwaive is clicked and re-blocks the gate", async () => {
  // Seed the existing mocks so one waivable blocking finding is already waived
  // (reuse this file's existing fixture + msw/vi mock style -- read it first).
  render(<ValidationFindingsPanel topicId="topic-a" phase="final" />);

  const unwaive = await screen.findByRole("button", { name: /unwaive/i });
  await userEvent.click(unwaive);

  await waitFor(() => expect(deleteWaiver).toHaveBeenCalledWith(
    "topic-a", "final", "content.prompt_leak:/modules/0",
  ));
  await waitFor(() => expect(screen.queryByText("waived")).not.toBeInTheDocument());
});

it("offers no Unwaive control when the report is stale", async () => {
  // A stale report must not offer gate mutations -- same rule the Waive button follows.
  render(<ValidationFindingsPanel topicId="topic-a" phase="final" />);
  await screen.findByText(/stale/i);
  expect(screen.queryByRole("button", { name: /unwaive/i })).not.toBeInTheDocument();
});
```

```tsx
// web/src/pages/RunBoardPage.test.tsx
it("does not announce the findings badge as a live region", async () => {
  // role="status" is a live region: with 5s polling every count change
  // re-announces to screen readers. The count must be a labelled span.
  render(<RunBoardPage />);
  const badge = await screen.findByLabelText(/2 findings/i);
  expect(badge).not.toHaveAttribute("role", "status");
  expect(badge).toHaveAttribute("aria-label", "2 findings");
});
```

```ts
// web/e2e/release-gates.spec.ts  (a NEW test block -- do not weaken the existing one)
test("release gate: a waiver can be removed from the cockpit", async ({ page }) => {
  // Reuse bootDaemon + this spec's existing seed/waive flow to reach an open
  // gate with one recorded waiver, then remove it and assert the gate re-closes.
  await page.getByRole("button", { name: /unwaive/i }).click();
  await expect(page.getByRole("button", { name: /waive/i })).toBeVisible();
  // The gate is closed again: export is refused.
  await expect(page.getByText(/blocking/i)).toBeVisible();
});
```

Read each test file first and match its existing mocking, fixture, and query conventions; the assertions above are the required behavior, not the required plumbing. The e2e reuses the `bootDaemon` helper (`web/e2e/helpers/daemon.ts`) this spec already imports.

- [x] **Step 2: Run the tests, verify they fail**

Run: `cd web && npm run test -- ValidationFindingsPanel RunBoardPage`
Expected: FAIL — no `Unwaive` button exists; the badge still carries `role="status"`.
Run: `cd web && npx playwright test e2e/release-gates.spec.ts`
Expected: FAIL — no unwaive control to click.

- [x] **Step 3: Implement**

In `web/src/api/client.ts`, add beside `postWaiver`:

```ts
export const deleteWaiver = (
  topicId: string,
  phase: "draft" | "final",
  findingId: string,
) =>
  apiDelete<WaiverResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/validation/${phase}/waivers/${encodeURIComponent(findingId)}`,
  );
```

If this module has no `apiDelete` helper, add one next to `apiPost`, following its exact shape (same base URL, same `X-EP-Token` header, same `ApiRequestError` mapping) with `method: "DELETE"` and no body. Do not hand-roll a second `fetch` wrapper.

In `web/src/components/ValidationFindingsPanel.tsx`, add the removal handler beside `submitWaiver`:

```tsx
  const removeWaiver = async (finding: ValidationFinding) => {
    if (!report || waiving) return;
    setWaiving(true);
    setFeedback(null);
    try {
      const result = await deleteWaiver(topicId, phase, finding.id);
      setReport(result.report);
      setWaivers(result.waivers.waivers);
      setWaiverState("current");
      onChanged();
    } catch (error) {
      setFeedback(feedbackFor(error));
    } finally {
      setWaiving(false);
    }
  };
```

This mirrors `submitWaiver` exactly: same guard, same `setFeedback(null)` reset, the same four state refreshes on success (`setReport` from the response — the counts must move or the panel will disagree with itself), the same `onChanged()` notification to the parent, the same `feedbackFor(error)` error surface, and the same `finally`. It differs only in taking no reason and clearing no form. **Do not invent new state or a new error path** — the panel already has `report`, `waivers`, `waiverState`, `waiving`, `feedback`, and the `feedbackFor` helper.

Then, in the finding `<li>`, add the control next to the existing `Waive…` button, gated on the same `state === "current"` freshness rule the Waive button uses:

```tsx
                    {waived && state === "current" && (
                      <button
                        type="button"
                        disabled={waiving}
                        onClick={() => void removeWaiver(finding)}
                      >Unwaive</button>
                    )}
```

Import `deleteWaiver` in the existing `client` import line.

In `web/src/pages/RunBoardPage.tsx`, drop the live region from the badge (keep the accessible name):

```tsx
                    <span
                      className="findings-badge"
                      aria-label={`${findingsCount} ${findingsCount === 1 ? "finding" : "findings"}`}
                    >
                      {findingsCount}
                    </span>
```

- [x] **Step 4: Run the web suites**

Run: `cd web && npm run test && npm run build && npx playwright test e2e/release-gates.spec.ts`
Expected: PASS (vitest green, tsc clean, both e2e tests in the spec green).

- [x] **Step 5: Commit**

```bash
git add web/src/api/client.ts web/src/components/ValidationFindingsPanel.tsx web/src/pages/RunBoardPage.tsx web/src/components/ValidationFindingsPanel.test.tsx web/src/pages/RunBoardPage.test.tsx web/e2e/release-gates.spec.ts
git commit -m "feat(web): remove a waiver from the cockpit; stop announcing the findings badge as a live region"
```

---

## Wave close

- [x] Run the wave-close checklist in the Wave Protocol section above (four-suite gate → update this plan doc + Wave Log → correct the audit's §7.1 over-claim and record the three owner rulings → commit → print the personalization Wave 0 kickoff prompt → stop).
