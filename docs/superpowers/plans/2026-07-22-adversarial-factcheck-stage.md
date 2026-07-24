# Adversarial Fact-Check Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class guide-v1 model stage `factcheck` between `qa` and `repair` that produces a Markdown findings report consumed by repair, while stripping deep factual work from model QA and leaving legacy markdown runs unchanged.

**Architecture:** Keep the existing stage lifecycle (prompt → response → explicit approve). Rebase the derived config chain on `GUIDE_V1_REQUIRED_STAGES` so `SUPPORTED_STAGES` / `PRESET_STAGES` / `STAGE_ORDER` pick up `factcheck` automatically. Drive guide-v1 `next_action` through `qa → factcheck → repair` with a grandfathering rule (skip factcheck when repair is already approved *and still current*; a stale grandfathered repair has to earn a factcheck before it can be rebuilt). Surface guide-aware progress via public `RunStore.required_stages(topic_id)`.

**Tech Stack:** Python 3.11+ stdlib package (`education_pipeline/`), pytest, React/TypeScript cockpit (`web/`), Vite/vitest. No new runtime dependencies.

**Spec:** [`docs/superpowers/specs/2026-07-22-adversarial-factcheck-stage-design.md`](../specs/2026-07-22-adversarial-factcheck-stage-design.md)

## Global Constraints

- **Stdlib only** at Python runtime (pytest is the only dev dependency).
- **TDD:** write/adjust failing tests before production code in every task.
- **Guide-v1 only** for the required factcheck path; legacy markdown never requires factcheck.
- **No web search / tools / structured claim JSON / quality-report projection** in this milestone.
- **Grandfathering:** guide-v1 `next_action` requires factcheck **iff repair is not yet approved**.
- **Deterministic finalize/export gates unchanged.**
- Stage id is exactly `factcheck` (UI label “Fact-check”).
- Keep config derivation: `SUPPORTED_STAGES = GUIDE_V1_REQUIRED_STAGES + OPTIONAL_STAGES` (do not hand-write `STAGE_ORDER` / `PRESET_STAGES` literals).
- **Preset back-compat:** `parse_model_catalog` backfills a missing `factcheck` preset row from that preset's `repair` row (factcheck only — every other stage stays strict per `test_preset_rejects_missing_stage`). Pre-feature user catalogs must keep loading unchanged.
- **Green commits:** every Python task ends with the full suite (`python3 -m pytest --tb=line`), not a file-scoped run. Sole exception: Task 3 may leave `tests/test_example_project.py` red; Task 4 (example builder) runs immediately after and restores green.
- **Pre-flight (before Task 1):** merge `origin/main` into this branch — PR #32 rewrote the run-board tests and e2e selectors this plan touches — then rebuild the cockpit bundle (`cd web && npm ci && npm run build`) so the daemon serves a fresh `web/dist` during e2e.

## File map

| File | Responsibility |
| --- | --- |
| `education_pipeline/config.py` | `GUIDE_V1_REQUIRED_STAGES`, rebased `SUPPORTED_STAGES`, recommendation for `factcheck` |
| `education_pipeline/__init__.py` | Export `GUIDE_V1_REQUIRED_STAGES` |
| `config/model-catalog.example.toml` | Preset rows for `factcheck` on each provider table |
| `education_pipeline/prompts.py` | New factcheck compiler; QA accuracy strip; repair/module-repair consume factcheck |
| `education_pipeline/runs.py` | `required_stages`, `write_factcheck_prompt`, next_action, approve hashes, stale, repair writers |
| `education_pipeline/daemon/read_api.py` | Guide-aware `_completion_summary` |
| `web/src/lib/planHelp.ts` | Stage help copy for factcheck + repair |
| `scripts/build_example.py` | Insert factcheck in example build sequence |
| `tests/test_config.py` | Topology, derivation order, plan-TOML back-compat |
| `tests/test_prompts.py` | Compiler contracts + intentional pin updates for qa/repair |
| `tests/test_runs.py` | Engine behavior, drivers, full walk, grandfathering |
| `tests/test_server.py` | `config_server` preset fixture + catalog payload stage-set assertion gain `factcheck` |
| `tests/test_cli.py` | `--repair-module` advance tests drive through factcheck |
| `tests/test_write_api.py` / daemon tests as needed | Completion totals if covered |
| `web/src/**/*.test.tsx` | Stage-order fixtures that hardcode stage lists |

---

### Task 1: Config topology, catalog presets, package export

**Files:**
- Modify: `education_pipeline/config.py`
- Modify: `education_pipeline/__init__.py`
- Modify: `config/model-catalog.example.toml`
- Test: `tests/test_config.py`
- Modify: `tests/test_server.py` (`config_server` preset fixture + stage-set assertion)

**Interfaces:**
- Produces: `GUIDE_V1_REQUIRED_STAGES: tuple[str, ...]`
- Produces: `SUPPORTED_STAGES = GUIDE_V1_REQUIRED_STAGES + OPTIONAL_STAGES`
- Produces: `DEFAULT_STAGE_RECOMMENDATIONS["factcheck"] == "strong_adversarial_check"`
- Consumes: none

- [ ] **Step 1: Write the failing topology tests**

In `tests/test_config.py`, update imports and replace/extend `test_audit_stage_topology_is_optional_model_powered_and_not_reasoning`:

```python
from education_pipeline.config import (
    GUIDE_V1_REQUIRED_STAGES,
    OPTIONAL_STAGES,
    PRESET_STAGES,
    REQUIRED_STAGES,
    SUPPORTED_STAGES,
    REASONING_STAGES,
    DEFAULT_STAGE_RECOMMENDATIONS,
    STAGE_ORDER,
)

def test_factcheck_stage_topology_derivation_and_order() -> None:
    assert REQUIRED_STAGES == ("spec", "outline", "draft", "qa", "repair")
    assert GUIDE_V1_REQUIRED_STAGES == (
        "spec", "outline", "draft", "qa", "factcheck", "repair"
    )
    assert OPTIONAL_STAGES == ("audit",)
    assert SUPPORTED_STAGES == GUIDE_V1_REQUIRED_STAGES + OPTIONAL_STAGES
    assert PRESET_STAGES == ("profile",) + SUPPORTED_STAGES
    assert STAGE_ORDER == ("profile",) + SUPPORTED_STAGES + ("finalize", "export")
    # factcheck sits between qa and repair everywhere derived
    for seq in (GUIDE_V1_REQUIRED_STAGES, SUPPORTED_STAGES, PRESET_STAGES, STAGE_ORDER):
        assert seq.index("qa") < seq.index("factcheck") < seq.index("repair")
    assert "factcheck" not in REQUIRED_STAGES
    assert "factcheck" not in OPTIONAL_STAGES
    assert "factcheck" not in REASONING_STAGES
    assert DEFAULT_STAGE_RECOMMENDATIONS["factcheck"] == "strong_adversarial_check"
    assert DEFAULT_STAGE_RECOMMENDATIONS["qa"] == "fast_cheap_check"


def test_model_plan_without_factcheck_table_still_loads_with_default() -> None:
    """Pre-feature plan TOMLs omit factcheck; loader fills from defaults."""
    plan = parse_model_plan(
        {
            "provider": "manual",
            "stages": {
                "qa": {"model": "prompt-only"},
                "repair": {"model": "prompt-only"},
            },
        }
    )
    assert "factcheck" in plan.stages
    assert plan.stage("factcheck").recommendation == "strong_adversarial_check"
    assert plan.stage("factcheck").model is None


def test_preset_missing_factcheck_backfills_from_repair() -> None:
    """Pre-feature catalogs omit factcheck preset rows; parser copies the repair row."""
    stages = _full_stage_map()
    del stages["factcheck"]
    stages["repair"] = {"model": "opus-4-8", "effort": "high"}
    data = _catalog_data_with_preset({"id": "p", "stages": {"claude-code": stages}})
    catalog = parse_model_catalog(data)
    assert catalog.presets[0].stages["claude-code"]["factcheck"] == PresetStage(
        model="opus-4-8", effort="high"
    )
```

(`_full_stage_map` at `tests/test_config.py:510` derives from `PRESET_STAGES`, so all other preset tests self-heal once the constant grows; `test_preset_rejects_missing_stage` deletes `audit` and must keep raising.)

Also update the existing topology assertion that still says:

```python
assert SUPPORTED_STAGES == REQUIRED_STAGES + OPTIONAL_STAGES
```

to the new derivation (or delete it once the new test covers it).

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_config.py::test_factcheck_stage_topology_derivation_and_order tests/test_config.py::test_model_plan_without_factcheck_table_still_loads_with_default -v
```

Expected: FAIL — `GUIDE_V1_REQUIRED_STAGES` not defined / `factcheck` missing from recommendations.

- [ ] **Step 3: Implement config + export + catalog**

`education_pipeline/config.py`:

```python
REQUIRED_STAGES = ("spec", "outline", "draft", "qa", "repair")
GUIDE_V1_REQUIRED_STAGES = (
    "spec",
    "outline",
    "draft",
    "qa",
    "factcheck",
    "repair",
)
OPTIONAL_STAGES = ("audit",)
SUPPORTED_STAGES = GUIDE_V1_REQUIRED_STAGES + OPTIONAL_STAGES

PRESET_STAGES = ("profile",) + SUPPORTED_STAGES
STAGE_ORDER = ("profile",) + SUPPORTED_STAGES + ("finalize", "export")

DEFAULT_STAGE_RECOMMENDATIONS = MappingProxyType(
    {
        "profile": "fast_or_strong_summary",
        "spec": "strong_contract_design",
        "outline": "premium_reasoning",
        "draft": "strong_longform_generation",
        "qa": "fast_cheap_check",
        "factcheck": "strong_adversarial_check",
        "repair": "strong_or_premium_repair",
        "audit": "strong_personalization_audit",
        "finalize": "local_only",
        "export": "local_only",
    }
)
```

`education_pipeline/__init__.py`: import and list `GUIDE_V1_REQUIRED_STAGES` next to `REQUIRED_STAGES` in both the import block and `__all__`.

`config/model-catalog.example.toml` — insert a `factcheck` row **after `qa` and before `repair`** in every `[presets.stages.*]` table (six tables: max-quality/balanced/cost-efficient × claude-code/codex). Choose models at least as strong as that preset’s repair (or draft) row — not the cheap QA model. Example for max-quality claude-code:

```toml
qa = { model = "opus-4-8", effort = "medium" }
factcheck = { model = "opus-4-8", effort = "high" }
repair = { model = "opus-4-8", effort = "high" }
```

Mirror for codex with that preset’s strong model (`sol` on max-quality). For cost-efficient, use the same mid-tier as repair (`sonnet-5` / `terra`), effort `medium`.

**Preset back-compat** in `parse_model_catalog` — the strict per-stage loop (`config.py:475`, raises `ConfigError` on any missing stage) would reject every pre-feature user catalog that defines presets. Special-case exactly `factcheck`: when its row is absent, copy the preset's `repair` row (guaranteed present in old catalogs by the same strict loop) instead of raising. All other stages stay strict.

```python
for stage_name in PRESET_STAGES:
    raw_stage = raw_map.get(stage_name)
    if raw_stage is None and stage_name == "factcheck":
        # Pre-feature catalogs predate the factcheck stage; reuse the
        # repair row, which the strict loop guarantees below.
        raw_stage = raw_map.get("repair")
    if raw_stage is None:
        raise ConfigError(...)
```

(Order note: `repair` follows `factcheck` in `PRESET_STAGES`, so read the raw mapping — `raw_map.get("repair")` — not the parsed `stage_map`.)

**Test fixtures with hand-written preset rows:** `tests/test_server.py` `config_server` (~line 148) hardcodes the stage rows — add `"factcheck": {"model": "strong-m"},` between `qa` and `repair`, and add `"factcheck"` to the expected set in `test_config_catalog_includes_presets` (line 2873). Without the fixture edit the backfill would still let it load, but the payload assertion must name the new stage explicitly.

- [ ] **Step 4: Run config tests, then the full suite**

```bash
python3 -m pytest tests/test_config.py -v
python3 -m pytest --tb=line
```

Expected: PASS (including example catalog load). The full-suite run guards the topology ripple — `run_status` iterates `SUPPORTED_STAGES` (`runs.py:633`), so `factcheck` now appears in every run's stage list. If any other test hardcodes a stage list, fix it the same way (insert `factcheck` between `qa` and `repair`); do **not** change engine behavior in this task.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/config.py education_pipeline/__init__.py \
  config/model-catalog.example.toml tests/test_config.py tests/test_server.py
git commit -m "feat(config): add guide-v1 factcheck to stage topology and presets"
```

---

### Task 2: Prompt compilers (factcheck, QA strip, repair consume)

**Files:**
- Modify: `education_pipeline/prompts.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `compile_guide_v1_factcheck_prompt(topic, *, approved_spec, approved_outline, draft_guide_json, qa_findings_markdown, draft_findings_json, profile=None, blueprint=None) -> PromptArtifact` with `artifact.stage == "factcheck"`
- Produces: `compile_guide_v1_repair_prompt(..., factcheck_findings_markdown: str, ...)`
- Produces: `compile_guide_v1_module_repair_prompt(..., factcheck_findings_markdown: str, ...)`
- Produces: guide-v1 QA section `## Scope Checks` (no deep accuracy); legacy QA keeps light accuracy bullet
- Consumes: existing `_compile_stage_prompt`, `_untrusted_block`, `_blueprint_rubric_lines` / `_blueprint_contract_lines`

- [ ] **Step 1: Write failing compiler tests**

Add near other guide-v1 tests in `tests/test_prompts.py` (import the new symbol):

```python
def test_compile_guide_v1_factcheck_prompt_is_adversarial_markdown_report() -> None:
    topic = Topic(id="systems-thinking", title="Systems Thinking")
    artifact = compile_guide_v1_factcheck_prompt(
        topic,
        approved_spec=APPROVED_SPEC,
        approved_outline=APPROVED_OUTLINE,
        draft_guide_json=GUIDE_DRAFT_JSON,
        qa_findings_markdown=APPROVED_QA,
        draft_findings_json=GUIDE_DRAFT_FINDINGS_JSON,
    )
    assert artifact.stage == "factcheck"
    assert artifact.text.startswith("# Fact-Check Stage Prompt\n")
    assert "adversarial" in artifact.text.lower()
    for heading in (
        "## Claim Inventory",
        "## Findings",
        "## Unsupported Or Uncertain Claims",
        "## Repair Instructions",
        "## Approved Specification",
        "## Draft Under Review",
        "## Approved Model-QA Findings",
        "## Deterministic Draft Findings",
    ):
        assert heading in artifact.text
    assert "2. `## Verdict`" in artifact.text
    assert GUIDE_DRAFT_JSON in artifact.text
    assert APPROVED_QA in artifact.text
    assert "BEGIN UNTRUSTED DATA" in artifact.text
    assert "Never invent sources" in artifact.text or "never invent sources" in artifact.text.lower()


def test_compile_guide_v1_qa_prompt_drops_deep_accuracy_for_factcheck() -> None:
    artifact = compile_guide_v1_qa_prompt(
        Topic(id="systems-thinking", title="Systems Thinking"),
        approved_spec=APPROVED_SPEC,
        approved_outline=APPROVED_OUTLINE,
        draft_guide_json=GUIDE_DRAFT_JSON,
        draft_findings_json=GUIDE_DRAFT_FINDINGS_JSON,
    )
    assert "## Scope Checks" in artifact.text or "Scope Checks" in artifact.text
    assert "Scope And Accuracy Checks" not in artifact.text
    assert "factcheck" in artifact.text.lower()
    # deep claim verification belongs to factcheck
    assert "factual errors, and unsupported claims" not in artifact.text


def test_legacy_qa_prompt_keeps_light_accuracy_note() -> None:
    """Legacy pipelines have no factcheck stage: QA keeps a light accuracy
    duty and the prompt must never mention factcheck (contradictory
    instructions otherwise)."""
    artifact = compile_qa_prompt(
        Topic(id="systems-thinking", title="Systems Thinking"),
        approved_spec=APPROVED_SPEC,
        approved_outline=APPROVED_OUTLINE,
        approved_draft="# Draft\n",
    )
    assert "obvious factual" in artifact.text.lower() or "unsupported claims" in artifact.text.lower()
    assert "factcheck" not in artifact.text.lower()
    assert "fact-check" not in artifact.text.lower()


def test_compile_guide_v1_repair_prompt_embeds_factcheck_findings() -> None:
    contract = build_guide_contract(GUIDE_SPEC_CONTRACT, GUIDE_OUTLINE_CONTRACT)
    factcheck = "# Fact-Check Report\n\n## Findings\n1. **major** — bad claim\n"
    artifact = compile_guide_v1_repair_prompt(
        Topic(id="systems-thinking", title="Systems Thinking"),
        draft_guide_json=GUIDE_DRAFT_JSON,
        qa_findings_markdown=APPROVED_QA,
        factcheck_findings_markdown=factcheck,
        draft_findings_json=GUIDE_DRAFT_FINDINGS_JSON,
        guide_contract=contract,
    )
    assert "## Approved Fact-Check Findings" in artifact.text
    assert factcheck in artifact.text
    assert "fact-check" in artifact.text.lower() or "factcheck" in artifact.text.lower()
```

Update **every** existing call site of `compile_guide_v1_repair_prompt` and `compile_guide_v1_module_repair_prompt` in this file to pass `factcheck_findings_markdown=...` (use a short fixture string). That includes `_compile_guide_v1_prompts` and the SHA256 pin harness.

For the pin test: after implementation, **recompute** `qa` and `repair` hashes intentionally (authorized prompt-surface change). Do **not** change hashes for `spec`/`outline`/`draft` unless their text actually changes (it should not).

```bash
# after implementation, compute new pins:
python3 - <<'PY'
from tests.test_prompts import _compile_guide_v1_prompts, _sha256_text
for stage, text in _compile_guide_v1_prompts().items():
    print(stage, _sha256_text(text))
PY
```

**Legacy pins change too:** `_LEGACY_PROMPT_TEXT_SHA256["qa"]` (`tests/test_prompts.py:119`, asserted in two places) must be recomputed — `compile_qa_prompt` shares `_QA_OUTPUT_AND_QUALITY_LINES`, so the `## Scope Checks` rename plus the legacy accuracy bullet change its text. Recompute it the same way (compile the legacy qa artifact with the pin test's own fixtures and `_sha256_text`), or read the new digest from the pin test's assertion diff. The other legacy pins (`spec`, `topic_spec`, `outline`, `draft`, `repair`) must **not** change.

Paste only the new `qa` and `repair` digests into `_GUIDE_V1_NO_BLUEPRINT_PROMPT_TEXT_SHA256`. Add `factcheck` to `_compile_guide_v1_prompts` only if you also add a pin for it; optional for this milestone (spec does not require a factcheck pin). Prefer **not** pinning factcheck until its text stabilizes, but include it in a non-pin smoke test above.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_prompts.py -k "factcheck or deep_accuracy or light_accuracy or embeds_factcheck" -v
```

Expected: FAIL — import/signature errors.

- [ ] **Step 3: Implement prompt compilers**

In `education_pipeline/prompts.py`:

1. **Shared QA output lines** — change section 5 to scope-only; add quality-bar note that fact verification is the factcheck stage:

```python
_QA_OUTPUT_AND_QUALITY_LINES = (
    "## Output Format",
    "Return markdown with exactly these sections:",
    "1. `# QA Report: <title>`",
    "2. `## Verdict` - one of pass, revise, or fail, with a one-line justification.",
    "3. `## Outcome Coverage` - for each specification outcome, mark covered, partial, or missing, citing the module.",
    "4. `## Findings` - a numbered list. For each: severity (blocker, major, minor), location (module or section), what is wrong, and why it matters.",
    "5. `## Scope Checks` - flag out-of-scope material relative to the approved specification and outline.",
    "6. `## Repair Instructions` - concrete fixes the repair stage can apply, ordered by severity.",
    "",
    "## Quality Bar",
    "- Judge the draft only against the approved specification and outline, not personal preference.",
    "- Record every missing or partial outcome as a finding.",
    "- Make findings specific and located; avoid vague notes.",
    "- Do not rewrite the draft here; describe each fix precisely for the repair stage.",
    "- Separate blocking problems from minor polish.",
    "- Flag any contradiction between the specification and outline instead of guessing.",
    "- Keep private learner details out of publishable report text unless explicitly allowed.",
)

_GUIDE_QA_FACTCHECK_NOTE_LINES = (
    "- Factual claim verification is handled by the factcheck stage; do not duplicate it.",
)

_LEGACY_QA_ACCURACY_LINES = (
    "- Flag obvious factual errors and unsupported claims.",
)
```

The factcheck note is **guide-v1-only** — the shared tuple contains neither bullet, so the legacy prompt never references a stage its pipeline doesn't have.

2. **`compile_qa_prompt` (legacy)** — pass `output_and_quality_lines=_QA_OUTPUT_AND_QUALITY_LINES + _LEGACY_QA_ACCURACY_LINES`. Guide-v1 `compile_guide_v1_qa_prompt` passes `_QA_OUTPUT_AND_QUALITY_LINES + _GUIDE_QA_FACTCHECK_NOTE_LINES`.

3. **New `_FACTCHECK_HEADER_LINES` / `_FACTCHECK_OUTPUT_AND_QUALITY_LINES`** matching spec §4.1 (adversarial posture; six output sections; never invent sources; do not rewrite).

4. **`compile_guide_v1_factcheck_prompt`** — mirror `compile_guide_v1_qa_prompt` structure:

```python
def compile_guide_v1_factcheck_prompt(
    topic: Topic,
    *,
    approved_spec: str,
    approved_outline: str,
    draft_guide_json: str,
    qa_findings_markdown: str,
    draft_findings_json: str,
    profile: LearnerProfile | None = None,
    blueprint: Blueprint | None = None,
) -> PromptArtifact:
    _required_block(draft_guide_json, "draft guide JSON")
    _required_block(qa_findings_markdown, "QA findings")
    _required_block(draft_findings_json, "draft findings")
    return _compile_stage_prompt(
        stage="factcheck",
        pre_topic_lines=_blueprint_rubric_lines(blueprint),  # same hook style as QA
        header_lines=_FACTCHECK_HEADER_LINES,
        sections=(
            ("## Approved Specification", "...", "specification", approved_spec),
            ("## Approved Outline", "...", "outline", approved_outline),
            (
                "## Draft Under Review",
                "The normalized draft guide JSON to fact-check.",
                "draft",
                _untrusted_block("draft guide JSON", draft_guide_json),
            ),
            (
                "## Approved Model-QA Findings",
                "Pedagogical context only; do not re-litigate pure pedagogy findings.",
                "qa findings",
                _untrusted_block("approved model-QA findings", qa_findings_markdown),
            ),
            (
                "## Deterministic Draft Findings",
                "Machine-generated validation findings. Do not waste effort restating pure structural issues.",
                "draft findings",
                _untrusted_block("deterministic draft findings", draft_findings_json),
            ),
        ),
        output_and_quality_lines=_FACTCHECK_OUTPUT_AND_QUALITY_LINES,
        topic=topic,
        profile=profile,
    )
```

(Use the same section-tuple shape `_compile_stage_prompt` already expects — copy from `compile_guide_v1_qa_prompt` exactly.)

5. **Repair** — add required `factcheck_findings_markdown` to both whole-guide and module-scoped compilers. Insert section after model-QA findings:

```python
(
    "## Approved Fact-Check Findings",
    "The required factual fixes. Resolve every blocker and major finding.",
    "factcheck findings",
    _untrusted_block("approved fact-check findings", factcheck_findings_markdown),
),
```

Update `_REPAIR_HEADER_LINES` / `_GUIDE_REPAIR_OUTPUT_AND_QUALITY_LINES` / module quality lines:

- Apply approved **QA and fact-check** findings.
- Resolve every blocker and major finding from **both** reports.
- On factual conflict, prefer fact-check; on pedagogy/coverage, prefer QA; irreconcilable → note in Downstream Prompt Notes.

Module-scoped: also filter factcheck finding items by module (reuse `_split_qa_finding_items` on the factcheck markdown if the report uses a `## Findings` section — same helper works on any report with that heading). If filtering is too invasive for v1, embed the full factcheck report as context and keep module filtering only for QA + deterministic findings (acceptable if documented in a code comment). **Prefer full embed for v1** to avoid inventing a second splitter contract.

- [ ] **Step 4: Run prompt tests, then the full suite**

```bash
python3 -m pytest tests/test_prompts.py -v
python3 -m pytest --tb=line
```

Expected: PASS after pin updates and call-site signature fixes.

**Two-task signature bridge:** `runs.py::write_repair_prompt` calls `compile_guide_v1_repair_prompt` today and is not touched until Task 3. To keep this commit green, declare `factcheck_findings_markdown: str = ""` (temporary default) in both repair compilers, and when empty: skip its `_required_block` check and omit the `## Approved Fact-Check Findings` section entirely. Task 3 removes the default and makes the block required in the same commit that updates the `runs.py` call sites.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): add factcheck compiler; split accuracy out of QA"
```

---

### Task 3: RunStore engine — required_stages, write_factcheck, next_action, stale, repair

**Files:**
- Modify: `education_pipeline/runs.py`
- Modify: `education_pipeline/prompts.py` (drop the temporary `factcheck_findings_markdown = ""` default from Task 2; make the block required)
- Test: `tests/test_runs.py`
- Test: `tests/test_cli.py` (`--repair-module` advance tests drive through factcheck)

**Interfaces:**
- Produces: `RunStore.required_stages(topic_id: str) -> tuple[str, ...]`
- Produces: `RunStore.write_factcheck_prompt(topic_id, *, overwrite=False) -> PromptFile`
- Produces: guide-v1 loop `("qa", "factcheck", "repair")` with grandfathering
- Produces: repair/module-repair require + bind `source_factcheck_file`
- Produces: stale tracking for `factcheck` and repair’s `source_factcheck_file_sha256`
- Consumes: `compile_guide_v1_factcheck_prompt`, `GUIDE_V1_REQUIRED_STAGES`, `REQUIRED_STAGES`

- [ ] **Step 1: Write failing engine tests**

Add helpers and tests in `tests/test_runs.py`:

```python
FACTCHECK_FIXTURE = """# Fact-Check Report: Systems Thinking

## Verdict
pass — no material factual errors.

## Claim Inventory
1. "Feedback loops couple stocks and flows" — module feedback-loops, type: definition

## Findings
(none)

## Unsupported Or Uncertain Claims
(none)

## Repair Instructions
(none)
"""


def _drive_guide_through_factcheck(
    runs: RunStore, topic_id: str, *, draft_body: str | None = None
) -> None:
    _drive_guide_through_qa(runs, topic_id, draft_body=draft_body)
    fc = runs.write_factcheck_prompt(topic_id)
    fc.response_path.write_text(FACTCHECK_FIXTURE, encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck")


def test_required_stages_depends_on_content_contract(tmp_path: Path) -> None:
    from education_pipeline.config import GUIDE_V1_REQUIRED_STAGES, REQUIRED_STAGES

    guide = _create_guide_run(tmp_path, "guide-topic")
    assert guide.required_stages("guide-topic") == GUIDE_V1_REQUIRED_STAGES

    legacy = _create_legacy_run(tmp_path)  # existing helper
    # use whatever topic id _create_legacy_run uses (systems-thinking)
    assert legacy.required_stages("systems-thinking") == REQUIRED_STAGES


def test_write_factcheck_prompt_embeds_upstream_and_hashes(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(runs, tid)
    result = runs.write_factcheck_prompt(tid)
    text = result.prompt_path.read_text(encoding="utf-8")
    assert "Fact-Check" in text
    assert "BEGIN UNTRUSTED DATA" in text
    event = next(
        e
        for e in reversed(runs.read_manifest(tid)["events"])
        if e["action"] == "prompt_written" and e["stage"] == "factcheck"
    )
    assert "source_draft_file_sha256" in event
    assert "source_qa_file_sha256" in event


def test_write_factcheck_prompt_requires_approved_qa(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_draft_approved(runs, tid)
    runs.validate_run(tid, "draft")
    with pytest.raises(ConfigError, match="qa"):
        runs.write_factcheck_prompt(tid)


def test_write_factcheck_refuses_legacy_runs(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    # drive legacy to approved qa using existing helpers if present; else minimal path
    with pytest.raises(ConfigError, match="interactive-guide|guide"):
        runs.write_factcheck_prompt("systems-thinking")


def test_guide_v1_next_action_inserts_factcheck_between_qa_and_repair(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(runs, tid)
    na = runs.run_status(tid).next_action
    assert na.stage == "factcheck"
    assert na.action == "write_prompt"


def test_guide_v1_repair_requires_factcheck_and_embeds_it(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(runs, tid)
    with pytest.raises(ConfigError, match="factcheck"):
        runs.write_repair_prompt(tid)
    _drive_guide_through_factcheck(runs, tid)  # will double-run qa — redefine carefully
```

**Driver note:** implement `_drive_guide_through_factcheck` as QA-through + factcheck only (above). Change `_drive_guide_to_finalize_ready` and `_drive_profiled_guide_to_finalize_ready` to call through factcheck before repair:

```python
def _drive_guide_to_finalize_ready(...):
    _drive_guide_through_factcheck(runs, topic_id, draft_body=draft_body)
    repair = runs.write_repair_prompt(topic_id)
    ...
```

Same for profiled helper (write factcheck after QA approve).

Continue tests:

```python
def test_repair_prompt_event_binds_factcheck(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_factcheck(runs, tid)
    result = runs.write_repair_prompt(tid)
    assert "Approved Fact-Check Findings" in result.prompt_path.read_text(encoding="utf-8")
    event = next(
        e for e in reversed(runs.read_manifest(tid)["events"])
        if e["action"] == "prompt_written" and e["stage"] == "repair"
    )
    assert "source_factcheck_file_sha256" in event


def test_factcheck_stale_when_qa_reapproved(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_factcheck(runs, tid)
    # re-write qa response and reapprove with overwrite
    qa_paths = runs.stage_paths(tid, "qa")
    qa_paths.response_path.write_text("# QA findings\n\nChanged.\n", encoding="utf-8")
    runs.approve_stage(tid, "qa", overwrite=True)
    assert runs.stage_status(tid, "factcheck").stale is True


def test_repair_stale_when_factcheck_reapproved(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_factcheck(runs, tid)
    repair = runs.write_repair_prompt(tid)
    repair.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs.approve_stage(tid, "repair")
    fc = runs.stage_paths(tid, "factcheck")
    fc.response_path.write_text(FACTCHECK_FIXTURE + "\n# touch\n", encoding="utf-8")
    runs.approve_stage(tid, "factcheck", overwrite=True)
    assert runs.stage_status(tid, "repair").stale is True


def test_grandfather_skips_factcheck_when_repair_already_approved(tmp_path: Path) -> None:
    """Simulate a pre-feature run: QA + repair approved, no factcheck artifacts."""
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(runs, tid)
    # Bypass write_repair_prompt's new factcheck requirement by writing repair
    # the old way only works before Task 3 impl — after impl, construct state:
    # Option A: temporarily call internal approve after planting repair approved file.
    # Preferred: drive through factcheck normally then DELETE factcheck approved
    # is wrong. Instead plant repair approval without factcheck using low-level files
    # only for this regression:
    repair_paths = runs.stage_paths(tid, "repair")
    repair_paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    repair_paths.prompt_path.write_text("# planted repair prompt\n", encoding="utf-8")
    repair_paths.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    repair_paths.approved_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs._append_event(
        tid,
        stage="repair",
        action="response_approved",
        files={
            "prompt_file": repair_paths.prompt_path,
            "approved_file": repair_paths.approved_path,
            "source_draft_file": runs.stage_paths(tid, "draft").approved_path,
            "source_qa_file": runs.stage_paths(tid, "qa").approved_path,
        },
    )
    # no factcheck approved
    assert not runs.stage_paths(tid, "factcheck").approved_path.exists()
    na = runs.run_status(tid).next_action
    # should not demand factcheck
    assert not (na.stage == "factcheck")
    # should proceed to final validate or finalize once validation is done
    assert na.action in {"validate", "finalize", "resolve_findings", "done"}
```

If `_append_event` is awkward in tests, prefer: after full implementation, add a test-only path that plants approved repair via the same helpers used elsewhere, **or** drive with an env flag — cleaner approach used in this repo: **approve repair through `write_repair_prompt` before factcheck is required** is impossible after the change. So planting approved repair files + manifest event is correct for grandfathering.

Also update `test_guide_v1_full_walk_via_advance` to expect factcheck between QA and repair:

```python
    runs.approve_stage(tid, "qa")
    assert snapshot() == ("factcheck", "write_prompt")
    assert runs.advance(tid).performed == "write_prompt"
    runs.stage_paths(tid, "factcheck").response_path.write_text(FACTCHECK_FIXTURE, encoding="utf-8")
    runs.approve_stage(tid, "factcheck")
    assert snapshot() == ("repair", "write_prompt")
```

- [ ] **Step 2: Run selected tests to verify fail**

```bash
python3 -m pytest tests/test_runs.py -k "factcheck or required_stages or grandfather or full_walk_via_advance" -v
```

Expected: FAIL.

- [ ] **Step 3: Implement RunStore changes**

Import `GUIDE_V1_REQUIRED_STAGES` from config (already imports `REQUIRED_STAGES`).

**`required_stages`:**

```python
def required_stages(self, topic_id: str) -> tuple[str, ...]:
    """Required model stages for progress/next-action of this run."""
    if self.content_contract(topic_id).kind == "interactive_guide":
        return GUIDE_V1_REQUIRED_STAGES
    return REQUIRED_STAGES
```

**`stage_status`:** extend stale set:

```python
if approved and self._is_guide_v1(paths.topic_id) and paths.stage in {
    "qa", "factcheck", "repair"
}:
    stale = self._stage_upstream_stale(paths.topic_id, paths.stage)
```

**`_write_stage_prompt` writers dict:** add `"factcheck": self.write_factcheck_prompt`.

**`_next_action_guide_v1` loop:**

```python
for stage_name in ("qa", "factcheck", "repair"):
    status = by_stage[stage_name]
    if (
        stage_name == "factcheck"
        and by_stage["repair"].approved
        and not by_stage["factcheck"].approved
    ):
        # Grandfather pre-feature runs that already approved repair.
        continue
    if status.approved and status.stale:
        return self._stale_stage_rebuild_action(topic_id, stage_name)
    pending = self._pending_stage_action(topic_id, status)
    if pending is not None:
        return pending
```

**`write_factcheck_prompt`:** clone `write_qa_prompt` guide-v1 path, but:

- refuse if not guide-v1
- require approved QA (`read_approved(..., "qa")`)
- require current draft validation + parseable draft
- call `compile_guide_v1_factcheck_prompt(...)`
- `extra_event_files`: `source_draft_file`, `source_qa_file`, `draft_report_file`

**`approve_stage` file bindings:**

```python
if self._is_guide_v1(paths.topic_id) and paths.stage in {"qa", "factcheck", "repair"}:
    files["source_draft_file"] = self.stage_paths(...draft...).approved_path
    if paths.stage in {"factcheck", "repair"}:
        files["source_qa_file"] = self.stage_paths(...qa...).approved_path
    if paths.stage == "repair":
        files["source_factcheck_file"] = self.stage_paths(...factcheck...).approved_path
```

Only attach `source_factcheck_file` when the approved factcheck file exists (grandfathered repairs may lack it — then omit the key so stale logic does not false-positive).

**`_stage_upstream_stale`:** after existing draft check:

```python
if stage in {"factcheck", "repair"}:
    # compare source_qa_file_sha256 (same as today's repair branch)
    ...
if stage == "repair":
    recorded_fc = event.get("source_factcheck_file_sha256")
    if recorded_fc is not None:
        fc_path = self.stage_paths(topic_id, "factcheck").approved_path
        if not fc_path.is_file():
            return True
        if recorded_fc != hashlib.sha256(fc_path.read_bytes()).hexdigest():
            return True
```

**`_stale_stage_rebuild_action`:** generalize the post-draft hash checks:

- for `factcheck` and `repair`: also compare QA hash from `prompt_written` event
- for `repair`: also compare factcheck hash when recorded

**`write_repair_prompt` (guide-v1):**

```python
approved_factcheck = self.read_approved(safe_id, "factcheck")  # raises if missing
...
artifact = compile_guide_v1_repair_prompt(
    ...,
    qa_findings_markdown=approved_qa,
    factcheck_findings_markdown=approved_factcheck,
    ...
)
extra_files["source_factcheck_file"] = self.stage_paths(safe_id, "factcheck").approved_path
```

**`write_module_repair_prompt`:** same factcheck requirement + extra file; update the error message that currently says “approve the qa stage first” to require factcheck as well (e.g. “approve the qa and factcheck stages first”).

- [ ] **Step 4: Run engine tests**

```bash
python3 -m pytest tests/test_runs.py -k "factcheck or required_stages or grandfather or full_walk or repair_prompt or guide_v1" -v --tb=short
```

Fix fallout in drivers (`_drive_guide_to_finalize_ready`, profiled finalize helper, any test that called `write_repair_prompt` right after QA).

Sweep every caller **in this task** (moved up from the example-builder task so fallout lands in the same commit that causes it):

```bash
rg -n "write_repair_prompt|through_qa|GUIDE_V1_REQUIRED|\"qa\", \"repair\"" \
  education_pipeline tests scripts web
```

Known hits outside `tests/test_runs.py`:

- `tests/test_cli.py:638` (`test_advance_repair_module_writes_scoped_prompt`) and `:657` (`test_advance_repair_module_unknown_module_is_usage_error`) call `test_runs._drive_guide_through_qa` then `advance --repair-module`; after this task next_action lands on factcheck there, so switch them to `test_runs._drive_guide_through_factcheck`.
- `tests/test_write_api.py` and `tests/test_release_gate_acceptance.py` import the `test_runs` drivers and heal automatically once those drivers go through factcheck.
- `scripts/build_example.py` is fixed in Task 4; `tests/test_example_project.py` is the **only** file allowed to stay red at the end of this task.

Then the full suite:

```bash
python3 -m pytest --tb=line
```

Expected: PASS except `tests/test_example_project.py` (byte-pinned regeneration cannot reach repair until the example gains a factcheck fixture — Task 4 restores it).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/runs.py education_pipeline/prompts.py \
  tests/test_runs.py tests/test_cli.py tests/test_prompts.py
git commit -m "feat(runs): guide-v1 factcheck stage with stale tracking and grandfathering"
```

---

### Task 4: Example builder + committed example fixture

Runs immediately after the engine change: `tests/test_example_project.py` regenerates the committed export by driving a real run through `build_example.build_export`, and Task 3 made that run require factcheck. This task restores a fully green suite in the very next commit.

**Files:**
- Modify: `scripts/build_example.py`
- Add: factcheck response fixture under `examples/feedback-loops/responses/`
- Check: `education_pipeline/guides/reports.py` `STAGES` set — **only** add `factcheck` if a test or validator requires stages from run status to be members; otherwise leave unchanged (factcheck does not project findings in v1)

- [ ] **Step 1: Update `scripts/build_example.py`**

If the example workspace is guide-v1, insert factcheck:

```python
stage_bodies = {
    ...
    "qa": (responses / "qa.md").read_text(...),
    "factcheck": (responses / "factcheck.md").read_text(...),  # add fixture file if needed
    "repair": ...
}
prompt_writers = {
    ...
    "qa": runs.write_qa_prompt,
    "factcheck": runs.write_factcheck_prompt,
    "repair": runs.write_repair_prompt,
}
for stage in ("spec", "outline", "draft", "qa", "factcheck", "repair"):
    ...
```

If the example responses directory has no factcheck fixture, create a minimal `examples/.../factcheck.md` (or whatever path the script uses) with a pass report skeleton matching Appendix A of the spec.

- [ ] **Step 2: Verify the pinned regeneration, then the full suite**

```bash
python3 -m pytest tests/test_example_project.py -v
python3 -m pytest --tb=line
```

Expected: PASS. The export bytes must **not** change (factcheck findings are not projected into the export in v1), so the committed `examples/feedback-loops/export/` artifacts stay valid. If `test_committed_export_matches_a_regeneration` reports changed bytes, stop and investigate — do not regenerate the committed export to paper over it.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_example.py examples  # fixture added
git commit -m "chore: include factcheck in example build sequence"
```

---

### Task 5: Daemon completion summary

**Files:**
- Modify: `education_pipeline/daemon/read_api.py`
- Test: prefer an existing daemon/topics list test if present; else add focused unit-style test by importing `_completion_summary`

**Interfaces:**
- Consumes: `RunStore.required_stages(topic_id)`
- Produces: `stages_total` / `stages_approved` against the run’s required sequence

- [ ] **Step 1: Write failing completion test**

Search for existing topics-list tests in `tests/test_server.py` / `tests/test_write_api.py`. If none assert `stages_total`, add in `tests/test_runs.py` or a small daemon test:

```python
def test_completion_summary_uses_run_required_stages(tmp_path: Path) -> None:
    from education_pipeline.daemon.read_api import _completion_summary
    from education_pipeline.config import GUIDE_V1_REQUIRED_STAGES, REQUIRED_STAGES

    guide_runs = _create_guide_run(tmp_path, "g1")
    # minimal fake run payload shape used by _completion_summary
    status = guide_runs.run_status("g1")
    run = {
        "stages": [
            {"stage": s.stage, "approved": s.approved}
            for s in status.stages
        ]
    }
    summary = _completion_summary(guide_runs, "g1", run)
    assert summary["stages_total"] == len(GUIDE_V1_REQUIRED_STAGES)

    legacy = _create_legacy_run(tmp_path)
    # ensure systems-thinking legacy exists
    lstatus = legacy.run_status("systems-thinking")
    lrun = {
        "stages": [
            {"stage": s.stage, "approved": s.approved}
            for s in lstatus.stages
        ]
    }
    lsummary = _completion_summary(legacy, "systems-thinking", lrun)
    assert lsummary["stages_total"] == len(REQUIRED_STAGES)
```

- [ ] **Step 2: Run to verify fail**

```bash
python3 -m pytest tests/test_runs.py::test_completion_summary_uses_run_required_stages -v
```

Expected: FAIL — still uses global `REQUIRED_STAGES` (guide total 5).

- [ ] **Step 3: Implement**

In `education_pipeline/daemon/read_api.py`:

```python
def _completion_summary(runs: RunStore, topic_id: str, run: dict | None) -> dict | None:
    if run is None:
        return None
    required = set(runs.required_stages(topic_id))
    approved = sum(
        1
        for stage in run["stages"]
        if stage["stage"] in required and stage["approved"]
    )
    ...
    return {
        "stages_approved": approved,
        "stages_total": len(required),
        "exported": exported,
    }
```

Remove unused `REQUIRED_STAGES` import if no longer referenced in this module.

- [ ] **Step 4: Run test**

```bash
python3 -m pytest tests/test_runs.py::test_completion_summary_uses_run_required_stages -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/read_api.py tests/test_runs.py
git commit -m "feat(daemon): guide-aware stage completion totals via required_stages"
```

---

### Task 6: Cockpit help copy + hardcoded stage fixtures

**Files:**
- Modify: `web/src/lib/planHelp.ts`
- Modify: `web/src/pages/SettingsPage.test.tsx` (`STAGES` list at ~line 81) and `web/src/components/RunPlanPanel.test.tsx` (`STAGES` at ~line 40)
- Modify: `web/src/pages/RunBoardPage.test.tsx` — **rewritten by PR #32**: `PLAN_STAGES` array (~line 61) and the full per-stage `RunStatus` fixtures (~line 92) both need a `factcheck` entry between `qa` and `repair`
- Modify: `web/e2e/full-run.spec.ts` (guide-v1 test only), `web/e2e/blueprints.spec.ts`, `web/e2e/personalization.spec.ts`, `web/e2e/release-gates.spec.ts` — each drives a guide-v1 run qa → repair through the cockpit and must gain a factcheck paste/approve step (see Step 4)
- Test: vitest for planHelp if present; otherwise SettingsPage tests that render stage rows

**PR #32 non-impacts (do not touch):** `PipelineStepper.tsx` renders `status.stages.map(...)` and `StageViewerPage`/`StageContentView` take `content_type` from the daemon (`stage_paths` already types factcheck as markdown) — factcheck flows through all three with zero component changes. `web/e2e/editor.spec.ts` and full-run's first test use `--legacy-markdown` runs; leave their five-stage loops alone. `NewRunPage.tsx:442`'s hardcoded list is a cosmetic loading fallback — optional nit only.

**Interfaces:**
- Produces: `STAGE_HELP.factcheck` string; updated `STAGE_HELP.repair`
- Consumes: API already returns stages from `STAGE_ORDER` once daemon/config ship

- [ ] **Step 1: Write / update failing UI test**

In `web/src/pages/SettingsPage.test.tsx`, update:

```ts
const STAGES = [
  "profile", "spec", "outline", "draft", "qa", "factcheck",
  "repair", "audit", "finalize", "export",
];
```

If a test asserts repair help text, update expectation.

Optionally add a tiny unit test file or extend an existing one:

```ts
import { STAGE_HELP } from "../lib/planHelp";

expect(STAGE_HELP.factcheck).toMatch(/fact/i);
expect(STAGE_HELP.repair).toMatch(/fact-check/i);
```

- [ ] **Step 2: Run vitest subset**

```bash
cd web && npm run test -- --run src/pages/SettingsPage.test.tsx src/lib/planHelp.ts
```

(If planHelp has no test file, run SettingsPage + any failing stage-list tests.)

- [ ] **Step 3: Implement copy**

`web/src/lib/planHelp.ts`:

```ts
  qa: "Checks the draft against the spec for pedagogy, coverage, and scope — not deep factual verification.",
  factcheck: "Adversarially checks factual claims in the draft. Findings go to repair along with model-QA findings.",
  repair: "Fixes the problems QA and fact-check found.",
```

Update other hardcoded stage arrays in tests to insert `"factcheck"` after `"qa"` wherever they mirror `STAGE_ORDER` / plan rows. **Do not** force factcheck into `NewRunPage` mocks that only list required legacy stages unless those mocks claim to be full plan order.

- [ ] **Step 4: Insert the factcheck step into the four guide-v1 e2e specs**

Each spec advances a guide-v1 run and pastes/approves `qa` then `repair`. After Task 3, "Advance" following qa approval writes a **factcheck** prompt, so `Response for repair` never appears. Between the qa approval and the repair advance in each spec, insert:

```ts
await page.getByRole("button", { name: "Advance" }).click();
await page.getByRole("button", { name: "Paste response…" }).click();
await page
  .getByLabel("Response for factcheck")
  .fill("# Fact-Check Report\n\n## Verdict\npass — no material factual errors.\n\n## Findings\n(none)\n");
await page.getByRole("button", { name: "Save response" }).click();
await page.getByRole("button", { name: "Approve factcheck" }).click();
```

(Adapt to each spec's local helpers — `pasteAndApprove(page, "factcheck", ...)` where the spec uses that helper.) Affected: `full-run.spec.ts` **guide-v1 test only**, `blueprints.spec.ts`, `personalization.spec.ts`, `release-gates.spec.ts` (both of its qa approvals sit in the repair → re-run loop; trace the flow rather than pattern-matching). Do **not** touch the `--legacy-markdown` flows.

- [ ] **Step 5: Re-run vitest and the affected e2e specs**

```bash
cd web && npm run test -- --run
npm run build   # daemon serves web/dist during e2e; stale bundles mask UI changes
npx playwright test e2e/full-run.spec.ts e2e/blueprints.spec.ts \
  e2e/personalization.spec.ts e2e/release-gates.spec.ts
```

Expected: PASS (or only pre-existing failures unrelated to this work — fix any breakage you introduced).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/planHelp.ts web/src/pages/SettingsPage.test.tsx \
  web/src/pages/RunBoardPage.test.tsx web/src/components/RunPlanPanel.test.tsx \
  web/e2e/full-run.spec.ts web/e2e/blueprints.spec.ts \
  web/e2e/personalization.spec.ts web/e2e/release-gates.spec.ts
# only files you actually changed
git commit -m "feat(web): factcheck stage help, fixture order, and e2e flows"
```

---

### Task 7: Full verification gate

**Files:** none intended (fixes only if red)

- [ ] **Step 1: Python suite**

```bash
python3 -m pytest -v --tb=line
```

Expected: PASS.

- [ ] **Step 2: Web typecheck + unit tests**

```bash
cd web && npm run build && npm run test -- --run
```

Expected: `tsc --noEmit` clean; vitest PASS.

- [ ] **Step 3: Full Playwright suite** (required since PR #32 — four guide-v1 specs now cross the factcheck stage)

```bash
cd web && npm run build && npm run e2e
```

Expected: PASS, including the @axe-core accessibility checks against the stepper's factcheck step. Do **not** add new factcheck-specific browser tests in this milestone; Task 6's edits to the four existing specs are the full e2e scope.

- [ ] **Step 4: Final commit only if fixes were needed**

```bash
git add -A
git status
git commit -m "test: green up residual factcheck fallout"
```

- [ ] **Step 5: Update design status line (optional doc nit)**

In the design spec header, set:

```markdown
- **Status:** Implementation plan ready — see `docs/superpowers/plans/2026-07-22-adversarial-factcheck-stage.md`
```

```bash
git add docs/superpowers/specs/2026-07-22-adversarial-factcheck-stage-design.md
git commit -m "docs: point factcheck design at implementation plan"
```

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| `GUIDE_V1_REQUIRED_STAGES` + derived `SUPPORTED_STAGES` / `PRESET_STAGES` / `STAGE_ORDER` | 1 |
| `DEFAULT_STAGE_RECOMMENDATIONS["factcheck"]` + catalog presets | 1 |
| Export `GUIDE_V1_REQUIRED_STAGES` from package | 1 |
| Plan TOML missing factcheck still loads | 1 |
| `compile_guide_v1_factcheck_prompt` Markdown contract | 2 |
| QA strip deep accuracy; legacy light note | 2 |
| Repair + module repair consume factcheck findings | 2 |
| Preset catalogs missing factcheck still load (backfill from repair row) | 1 |
| `tests/test_server.py` preset fixture + stage-set assertion | 1 |
| Legacy QA pin recompute (`_LEGACY_PROMPT_TEXT_SHA256["qa"]`) | 2 |
| Legacy QA prompt never mentions factcheck (guide-only note tuple) | 2 |
| `RunStore.required_stages(topic_id)` | 3 |
| `write_factcheck_prompt` + advance writer map | 3 |
| `next_action` qa→factcheck→repair + grandfathering | 3 |
| Manifest hashes + stale for factcheck and repair | 3 |
| CLI `--repair-module` drivers through factcheck | 3 |
| Example builder sequence + committed example fixture | 4 |
| Daemon completion uses `required_stages` | 5 |
| Cockpit `planHelp` copy | 6 |
| Guide-v1 e2e specs cross factcheck (PR #32 stepper flows) | 6 |
| Full test gate incl. required Playwright run | 7 |
| No tool-using / JSON claim UI / quality-report projection | Explicit non-goals — no task |
| REASONING_STAGES unchanged | Task 1 assertion |

## Self-review notes (plan author)

- **Placeholder scan:** no TBD steps; pin recompute has an exact command.
- **Type consistency:** `factcheck_findings_markdown: str` on both repair compilers; `required_stages(topic_id) -> tuple[str, ...]`.
- **Grandfathering** implemented only in `next_action` (not by making `write_repair_prompt` optional factcheck) — new repairs always need factcheck; old approved repairs skip the stage.
- **SHA256 pins** for `qa`/`repair` will change; `spec`/`outline`/`draft` must not.
- **Module repair factcheck filtering:** v1 embeds full factcheck report (simpler, matches “prefer full embed”).

## Review amendments (2026-07-22, post-verification against the codebase)

1. **Preset back-compat.** The preset parser is strict (`config.py:475` raises on any missing stage), so pre-feature user catalogs with presets — and the `config_server` fixture in `tests/test_server.py` — would fail to load at Task 1. Added a factcheck-only backfill from the preset's `repair` row (all other stages stay strict), the matching test, and the `tests/test_server.py` fixture/assertion updates. This extends the spec's back-compat table (§ "Model plans missing `factcheck` row"), which covered plan TOMLs but not preset catalogs.
2. **Legacy prompt pins.** `_LEGACY_PROMPT_TEXT_SHA256["qa"]` changes because `compile_qa_prompt` shares `_QA_OUTPUT_AND_QUALITY_LINES`; Task 2 now recomputes it explicitly. Added a two-task signature bridge (temporary `factcheck_findings_markdown = ""` default) so Task 2's commit stays green while `runs.py` still calls the old repair-compiler shape; Task 3 removes the default.
3. **Green-commit sequencing.** Moved the fallout grep and the `tests/test_cli.py` `--repair-module` driver fixes into Task 3, and reordered the example-builder work to Task 4 (immediately after the engine change) since `tests/test_example_project.py` byte-pins a full regeneration. Every Python task now gates on the full pytest suite; the only sanctioned intermediate red is `test_example_project.py` between Tasks 3 and 4.
4. **Legacy QA prompt coherence.** The "factual verification is handled by factcheck" quality-bar note moved to a guide-v1-only tuple; the legacy accuracy bullet no longer mentions factcheck, and the legacy test asserts the word never appears in legacy QA prompts.
5. **PR #32 (pipeline stepper) fallout — 2026-07-24.** Four guide-v1 e2e specs (`full-run` guide test, `blueprints`, `personalization`, `release-gates`) drive qa → repair through the cockpit and break at Task 3; Task 6 now inserts a factcheck paste/approve step in each and Task 7's e2e run is required, not optional. `RunBoardPage.test.tsx` was rewritten (`PLAN_STAGES` + per-stage fixtures need factcheck rows). Confirmed non-impacts: `PipelineStepper`/`StageViewerPage`/`StageContentView` are data-driven and `stage_paths` already types factcheck as markdown. Added pre-flight: merge `origin/main` and rebuild `web/dist` before Task 1.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-22-adversarial-factcheck-stage.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
