# Cockpit Usability + Real Model Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder model catalog with real Claude/Codex models plus three recommended presets, and make the cockpit's forms self-explanatory (tooltips, enlargeable fields, larger type).

**Architecture:** Presets are data in the catalog TOML, parsed by `education_pipeline/config.py`, served read-only through the existing `GET /v1/config/catalog` payload, and applied client-side by filling the Settings page's existing overrides map (persisted via the unchanged `PUT /v1/config/plan`). UI help is a single reusable `InfoTip` component plus per-form copy maps.

**Tech Stack:** Python 3.11+ stdlib only (pytest for tests), React 18 + TypeScript (vitest, Playwright + @axe-core).

**Spec:** `docs/superpowers/specs/2026-07-17-cockpit-usability-model-catalog-design.md`

## Global Constraints

- Python runtime is **standard library only**; `pytest` is the sole dev dependency. No new npm dependencies either.
- Strict TDD: every behavior change lands with its test in the same commit; write the failing test first.
- Model-driven stages are exactly `profile, spec, outline, draft, qa, repair, audit`; `finalize`/`export` are local-only and never carry model config.
- Catalog `quality` values must stay within the ranked vocabulary `fast` < `strong` < `premium` (`_QUALITY_RANK` in `config.py`); novel names silently rank as "strong" and defeat `weak_stage_warning`.
- Real model ids: Claude Code `argv_model` values are `claude-fable-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`; Codex `argv_model` values are `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`.
- Effort values are `low` / `medium` / `high` only.
- Help copy voice: plain language, concrete examples, no internal jargon (matches `web/src/lib/labels.ts` conventions).
- All commands run from the repo root unless the step says otherwise; web commands run from `web/`.

### The three presets (canonical data — used by Tasks 1, 3, 6, 8)

Claude Code mapping (model id / effort):

| Stage | max-quality | balanced | cost-efficient |
|---|---|---|---|
| profile | opus-4-8 / medium | sonnet-5 / medium | haiku-4-5 / low |
| spec | fable-5 / high | fable-5 / high | sonnet-5 / medium |
| outline | fable-5 / high | opus-4-8 / high | sonnet-5 / medium |
| draft | opus-4-8 / high | opus-4-8 / medium | sonnet-5 / medium |
| qa | opus-4-8 / medium | haiku-4-5 / medium | haiku-4-5 / low |
| repair | opus-4-8 / high | opus-4-8 / medium | sonnet-5 / medium |
| audit | opus-4-8 / high | opus-4-8 / medium | sonnet-5 / medium |

Codex mapping (corollary: Fable/Opus → sol, Sonnet → terra, Haiku → luna; same efforts):

| Stage | max-quality | balanced | cost-efficient |
|---|---|---|---|
| profile | sol / medium | terra / medium | luna / low |
| spec | sol / high | sol / high | terra / medium |
| outline | sol / high | sol / high | terra / medium |
| draft | sol / high | sol / medium | terra / medium |
| qa | sol / medium | luna / medium | luna / low |
| repair | sol / high | sol / medium | terra / medium |
| audit | sol / high | sol / medium | terra / medium |

---

### Task 1: Preset parsing in `config.py`

**Files:**
- Modify: `education_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: existing `ConfigError`, `Provider`, `ModelCatalog`, `_required_string`, `_optional_string`, `SUPPORTED_STAGES`.
- Produces (later tasks rely on these exact names):
  - `PRESET_STAGES: tuple[str, ...]` — `("profile",) + SUPPORTED_STAGES`
  - `@dataclass(frozen=True) class PresetStage: model: str; effort: str | None = None`
  - `@dataclass(frozen=True) class Preset: id: str; label: str; description: str = ""; stages: Mapping[str, Mapping[str, PresetStage]] = field(default_factory=dict)`
  - `ModelCatalog.presets: tuple[Preset, ...] = ()` (new field with default — existing constructions stay valid)
  - `parse_model_catalog` parses and validates `[[presets]]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` (imports at top of file already include `parse_model_catalog`, `ConfigError`, `pytest`; add `Preset, PresetStage, PRESET_STAGES` to the import from `education_pipeline.config`):

```python
def _catalog_data_with_preset(preset: dict) -> dict:
    return {
        "providers": [
            {
                "id": "claude-code",
                "label": "Claude Code",
                "models": [
                    {"id": "opus-4-8", "label": "Opus 4.8", "quality": "premium"},
                    {"id": "haiku-4-5", "label": "Haiku 4.5", "quality": "fast"},
                ],
            }
        ],
        "presets": [preset],
    }


def _full_stage_map(model: str = "opus-4-8") -> dict:
    return {stage: {"model": model} for stage in PRESET_STAGES}


def test_catalog_parses_presets() -> None:
    data = _catalog_data_with_preset(
        {
            "id": "balanced",
            "label": "Balanced",
            "description": "Good default.",
            "stages": {
                "claude-code": {
                    **_full_stage_map(),
                    "qa": {"model": "haiku-4-5", "effort": "medium"},
                }
            },
        }
    )
    catalog = parse_model_catalog(data)
    assert len(catalog.presets) == 1
    preset = catalog.presets[0]
    assert preset.id == "balanced" and preset.label == "Balanced"
    assert preset.stages["claude-code"]["qa"] == PresetStage(
        model="haiku-4-5", effort="medium"
    )
    assert preset.stages["claude-code"]["spec"].effort is None


def test_catalog_without_presets_has_empty_tuple() -> None:
    data = {"providers": [{"id": "manual", "label": "Manual"}]}
    assert parse_model_catalog(data).presets == ()


def test_preset_rejects_duplicate_ids() -> None:
    data = _catalog_data_with_preset(
        {"id": "p", "stages": {"claude-code": _full_stage_map()}}
    )
    data["presets"].append(
        {"id": "p", "stages": {"claude-code": _full_stage_map()}}
    )
    with pytest.raises(ConfigError, match="duplicate preset id"):
        parse_model_catalog(data)


def test_preset_rejects_unknown_provider() -> None:
    data = _catalog_data_with_preset(
        {"id": "p", "stages": {"ghost": _full_stage_map()}}
    )
    with pytest.raises(ConfigError, match="unknown provider 'ghost'"):
        parse_model_catalog(data)


def test_preset_rejects_unknown_model() -> None:
    stages = _full_stage_map()
    stages["spec"] = {"model": "ghost-model"}
    data = _catalog_data_with_preset({"id": "p", "stages": {"claude-code": stages}})
    with pytest.raises(ConfigError, match="unknown model 'ghost-model'"):
        parse_model_catalog(data)


def test_preset_rejects_missing_stage() -> None:
    stages = _full_stage_map()
    del stages["audit"]
    data = _catalog_data_with_preset({"id": "p", "stages": {"claude-code": stages}})
    with pytest.raises(ConfigError, match="missing stage 'audit'"):
        parse_model_catalog(data)


def test_preset_rejects_unknown_stage_and_bad_effort() -> None:
    stages = _full_stage_map()
    stages["finalize"] = {"model": "opus-4-8"}
    data = _catalog_data_with_preset({"id": "p", "stages": {"claude-code": stages}})
    with pytest.raises(ConfigError, match="unknown stage"):
        parse_model_catalog(data)

    stages = _full_stage_map()
    stages["spec"] = {"model": "opus-4-8", "effort": "turbo"}
    data = _catalog_data_with_preset({"id": "p", "stages": {"claude-code": stages}})
    with pytest.raises(ConfigError, match="effort"):
        parse_model_catalog(data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py -k preset -v`
Expected: FAIL — `ImportError: cannot import name 'Preset'` (or NameError for `PRESET_STAGES`).

- [ ] **Step 3: Implement preset parsing**

In `education_pipeline/config.py`:

Add after `SUPPORTED_STAGES` (line ~15):

```python
PRESET_STAGES = ("profile",) + SUPPORTED_STAGES
_EFFORT_VALUES = frozenset({"low", "medium", "high"})
```

Add the dataclasses after `Provider` (line ~62):

```python
@dataclass(frozen=True)
class PresetStage:
    """One stage's model choice inside a recommended preset."""

    model: str
    effort: str | None = None


@dataclass(frozen=True)
class Preset:
    """A named per-stage recommendation, mapped per provider."""

    id: str
    label: str
    description: str = ""
    stages: Mapping[str, Mapping[str, PresetStage]] = field(default_factory=dict)
```

Change `ModelCatalog` to carry presets (keep `require_provider` as is):

```python
@dataclass(frozen=True)
class ModelCatalog:
    """Provider catalog loaded from ``model-catalog.toml``."""

    providers: Mapping[str, Provider]
    presets: tuple[Preset, ...] = ()
```

At the end of `parse_model_catalog`, replace `return ModelCatalog(providers=providers)` with:

```python
    presets = _parse_presets(data, providers)
    return ModelCatalog(providers=providers, presets=presets)
```

Add the parser (near `_parse_models`):

```python
def _parse_presets(
    data: Mapping[str, Any], providers: Mapping[str, Provider]
) -> tuple[Preset, ...]:
    raw_presets = data.get("presets", [])
    if raw_presets is None:
        raw_presets = []
    if not isinstance(raw_presets, list):
        raise ConfigError("presets must use [[presets]] tables")

    presets: list[Preset] = []
    seen: set[str] = set()
    for index, raw_preset in enumerate(raw_presets, start=1):
        if not isinstance(raw_preset, Mapping):
            raise ConfigError(f"preset entry #{index} must be a table")
        preset_id = _required_string(raw_preset, "id", f"preset entry #{index}")
        if preset_id in seen:
            raise ConfigError(f"duplicate preset id {preset_id!r}")
        seen.add(preset_id)
        context = f"preset {preset_id!r}"
        label = _optional_string(raw_preset, "label", preset_id, context)
        description = _optional_string(raw_preset, "description", "", context)
        raw_stage_maps = raw_preset.get("stages")
        if not isinstance(raw_stage_maps, Mapping) or not raw_stage_maps:
            raise ConfigError(
                f"{context} must define at least one [presets.stages.<provider>] table"
            )
        stage_maps: dict[str, Mapping[str, PresetStage]] = {}
        for provider_id, raw_map in raw_stage_maps.items():
            if provider_id not in providers:
                raise ConfigError(f"{context} references unknown provider {provider_id!r}")
            if not isinstance(raw_map, Mapping):
                raise ConfigError(f"{context} stages for {provider_id!r} must be a table")
            unknown = sorted(set(raw_map) - set(PRESET_STAGES))
            if unknown:
                raise ConfigError(
                    f"{context} names unknown stage {unknown[0]!r} for provider {provider_id!r}"
                )
            stage_map: dict[str, PresetStage] = {}
            for stage_name in PRESET_STAGES:
                raw_stage = raw_map.get(stage_name)
                if raw_stage is None:
                    raise ConfigError(
                        f"{context} is missing stage {stage_name!r} for provider {provider_id!r}"
                    )
                if not isinstance(raw_stage, Mapping):
                    raise ConfigError(
                        f"{context} stage {stage_name!r} for {provider_id!r} must be a table"
                    )
                stage_context = f"{context} stage {stage_name!r} ({provider_id!r})"
                model_id = _required_string(raw_stage, "model", stage_context)
                if model_id not in providers[provider_id].models:
                    raise ConfigError(
                        f"{stage_context} references unknown model {model_id!r}"
                    )
                effort = _optional_string(raw_stage, "effort", None, stage_context)
                if effort is not None and effort not in _EFFORT_VALUES:
                    raise ConfigError(
                        f"{stage_context} effort must be one of low, medium, high"
                    )
                extra = sorted(set(raw_stage) - {"model", "effort"})
                if extra:
                    raise ConfigError(f"{stage_context} has unknown key {extra[0]!r}")
                stage_map[stage_name] = PresetStage(model=model_id, effort=effort)
            stage_maps[provider_id] = stage_map
        presets.append(
            Preset(id=preset_id, label=label, description=description, stages=stage_maps)
        )
    return tuple(presets)
```

Note: `_optional_string(raw, key, default, context)` — check the existing signature at ~line 370 and match argument order exactly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: all PASS (new preset tests plus every pre-existing test).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/config.py tests/test_config.py
git commit -m "feat(config): parse and validate recommended presets in the model catalog"
```

---

### Task 2: Serve presets in the catalog payload

**Files:**
- Modify: `education_pipeline/daemon/read_api.py:746-766` (`catalog_payload`)
- Test: `tests/test_server.py` (near `test_config_catalog_lists_providers_and_models`, ~line 2815)

**Interfaces:**
- Consumes: `ModelCatalog.presets` from Task 1.
- Produces: `GET /v1/config/catalog` payload gains `"presets"` — a list of `{"id", "label", "description", "stages": {provider_id: {stage: {"model": str, "effort": str | None}}}}`. The web client (Task 6) relies on exactly these key names.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server.py` next to the existing catalog test. Find the `config_server` fixture and extend its catalog TOML with a preset over its existing providers (the fixture defines providers `manual`, `fake`, `nope` — read the fixture and use two real model ids from the `fake` provider; the fixture's models are `m` and `strong-m`):

```python
def test_config_catalog_includes_presets(config_server):
    status, payload = _req(config_server, "GET", "/v1/config/catalog")
    assert status == 200
    assert isinstance(payload["presets"], list)
    preset = {p["id"]: p for p in payload["presets"]}["test-preset"]
    assert preset["label"] == "Test preset"
    stage_map = preset["stages"]["fake"]
    assert set(stage_map) == {"profile", "spec", "outline", "draft", "qa", "repair", "audit"}
    assert stage_map["spec"] == {"model": "strong-m", "effort": "high"}
    assert stage_map["qa"] == {"model": "m", "effort": None}
```

And extend the fixture's catalog TOML string with (adjusting only if the fixture's provider/model ids differ from `fake`/`m`/`strong-m`):

```toml
[[presets]]
id = "test-preset"
label = "Test preset"
description = "Preset used by payload tests."

[presets.stages.fake]
profile = { model = "m" }
spec = { model = "strong-m", effort = "high" }
outline = { model = "strong-m" }
draft = { model = "strong-m" }
qa = { model = "m" }
repair = { model = "strong-m" }
audit = { model = "strong-m" }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_server.py::test_config_catalog_includes_presets -v`
Expected: FAIL — `KeyError: 'presets'`.

- [ ] **Step 3: Implement**

In `catalog_payload` (read_api.py), change the return to include presets:

```python
    return {
        "providers": providers,
        "presets": [
            {
                "id": preset.id,
                "label": preset.label,
                "description": preset.description,
                "stages": {
                    provider_id: {
                        stage_name: {"model": ps.model, "effort": ps.effort}
                        for stage_name, ps in stage_map.items()
                    }
                    for provider_id, stage_map in preset.stages.items()
                },
            }
            for preset in catalog.presets
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -k "config" -v`
Expected: PASS (new test plus all existing config route tests — they tolerate the added key because they index into `payload["providers"]`).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/read_api.py tests/test_server.py
git commit -m "feat(daemon): include recommended presets in the catalog payload"
```

---

### Task 3: Real example catalog and default plan

**Files:**
- Modify: `config/model-catalog.example.toml` (full replace)
- Modify: `config/model-plan.example.toml` (full replace)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: parsing/validation from Task 1.
- Produces: package defaults every fresh workspace loads (`daemon/__init__.py` falls back to these when the workspace has no `config/*.toml`). Preset ids are exactly `max-quality`, `balanced`, `cost-efficient` — Tasks 6–8 rely on these ids and on catalog model ids `fable-5`, `opus-4-8`, `sonnet-5`, `haiku-4-5`, `sol`, `terra`, `luna`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` (the file's existing `test_loads_example_catalog_and_plan` shows how the example paths are resolved — reuse the same path constant/helper it uses):

```python
def test_example_catalog_ships_real_models_and_three_presets() -> None:
    catalog = load_model_catalog(EXAMPLE_CATALOG_PATH)
    claude = catalog.providers["claude-code"]
    assert {m.id for m in claude.models.values()} == {
        "fable-5", "opus-4-8", "sonnet-5", "haiku-4-5",
    }
    assert claude.models["fable-5"].argv_model == "claude-fable-5"
    assert claude.models["opus-4-8"].argv_model == "claude-opus-4-8"
    assert claude.models["sonnet-5"].argv_model == "claude-sonnet-5"
    assert claude.models["haiku-4-5"].argv_model == "claude-haiku-4-5"
    codex = catalog.providers["codex"]
    assert {m.id for m in codex.models.values()} == {"sol", "terra", "luna"}
    assert codex.models["sol"].argv_model == "gpt-5.6-sol"
    assert codex.models["terra"].argv_model == "gpt-5.6-terra"
    assert codex.models["luna"].argv_model == "gpt-5.6-luna"
    assert catalog.providers["manual"].label == "Manual copy/paste"
    assert [p.id for p in catalog.presets] == [
        "max-quality", "balanced", "cost-efficient",
    ]
    for preset in catalog.presets:
        assert set(preset.stages) == {"claude-code", "codex"}


def test_example_plan_defaults_to_claude_code_balanced() -> None:
    catalog = load_model_catalog(EXAMPLE_CATALOG_PATH)
    plan = load_model_plan(EXAMPLE_PLAN_PATH, catalog)
    assert plan.provider == "claude-code"
    balanced = {p.id: p for p in catalog.presets}["balanced"].stages["claude-code"]
    for stage_name in PRESET_STAGES:
        stage = plan.stage(stage_name)
        assert stage.model == balanced[stage_name].model, stage_name
        assert stage.effort == balanced[stage_name].effort, stage_name


def test_example_plan_has_no_weak_stage_warnings() -> None:
    catalog = load_model_catalog(EXAMPLE_CATALOG_PATH)
    plan = load_model_plan(EXAMPLE_PLAN_PATH, catalog)
    for stage_name in PRESET_STAGES:
        stage = plan.stage(stage_name)
        effective = StageModelPlan(
            stage=stage.stage,
            recommendation=stage.recommendation,
            model=stage.model,
            effort=stage.effort,
            provider=stage.provider or plan.provider,
        )
        assert weak_stage_warning(catalog, effective) is None, stage_name
```

(`EXAMPLE_CATALOG_PATH` / `EXAMPLE_PLAN_PATH`: reuse whatever constant `test_loads_example_catalog_and_plan` uses — if it inlines paths, define these two constants beside it pointing at `config/model-catalog.example.toml` and `config/model-plan.example.toml` relative to the repo root. Import `weak_stage_warning`, `StageModelPlan`, `load_model_catalog`, `load_model_plan` from `education_pipeline.config`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py -k example -v`
Expected: the three new tests FAIL (old catalog has no `fable-5` etc.); `test_loads_example_catalog_and_plan` still passes.

- [ ] **Step 3: Replace `config/model-catalog.example.toml`**

Full new contents:

```toml
# Default model catalog. A workspace may override this by writing its own
# config/model-catalog.toml; these are the shipped defaults.

[[providers]]
id = "claude-code"
label = "Claude Code"
description = "Run stages through the Claude Code CLI installed on this machine."

[[providers.models]]
id = "fable-5"
label = "Fable 5"
description = "Deepest reasoning for course design; slowest and most expensive."
quality = "premium"
default_effort = "high"
argv_model = "claude-fable-5"

[[providers.models]]
id = "opus-4-8"
label = "Opus 4.8"
description = "Strong long-form writing and revision; the workhorse for content stages."
quality = "premium"
default_effort = "high"
argv_model = "claude-opus-4-8"

[[providers.models]]
id = "sonnet-5"
label = "Sonnet 5"
description = "Near-Opus quality at lower cost; good balance for most stages."
quality = "strong"
default_effort = "medium"
argv_model = "claude-sonnet-5"

[[providers.models]]
id = "haiku-4-5"
label = "Haiku 4.5"
description = "Fast and inexpensive; best for mechanical checks and summaries."
quality = "fast"
default_effort = "low"
argv_model = "claude-haiku-4-5"

[[providers]]
id = "codex"
label = "Codex"
description = "Run stages through the Codex CLI installed on this machine."

[[providers.models]]
id = "sol"
label = "GPT-5.6 Sol"
description = "OpenAI's flagship tier; deepest reasoning in the GPT-5.6 family."
quality = "premium"
default_effort = "high"
argv_model = "gpt-5.6-sol"

[[providers.models]]
id = "terra"
label = "GPT-5.6 Terra"
description = "Balanced tier; strong everyday quality at mid cost."
quality = "strong"
default_effort = "medium"
argv_model = "gpt-5.6-terra"

[[providers.models]]
id = "luna"
label = "GPT-5.6 Luna"
description = "Fast, low-cost tier; best for mechanical checks and summaries."
quality = "fast"
default_effort = "low"
argv_model = "gpt-5.6-luna"

[[providers]]
id = "manual"
label = "Manual copy/paste"
description = "No CLI required — copy each stage prompt into any model UI, then paste the response back."

[[providers.models]]
id = "prompt-only"
label = "Prompt-only handoff"
description = "You choose and run the model yourself; this tool only prepares prompts and ingests responses."
quality = "manual"

[[presets]]
id = "max-quality"
label = "Max quality"
description = "The strongest model at every step. Slowest and most expensive."

[presets.stages.claude-code]
profile = { model = "opus-4-8", effort = "medium" }
spec = { model = "fable-5", effort = "high" }
outline = { model = "fable-5", effort = "high" }
draft = { model = "opus-4-8", effort = "high" }
qa = { model = "opus-4-8", effort = "medium" }
repair = { model = "opus-4-8", effort = "high" }
audit = { model = "opus-4-8", effort = "high" }

[presets.stages.codex]
profile = { model = "sol", effort = "medium" }
spec = { model = "sol", effort = "high" }
outline = { model = "sol", effort = "high" }
draft = { model = "sol", effort = "high" }
qa = { model = "sol", effort = "medium" }
repair = { model = "sol", effort = "high" }
audit = { model = "sol", effort = "high" }

[[presets]]
id = "balanced"
label = "Balanced"
description = "Deep design where it counts, fast models for mechanical steps."

[presets.stages.claude-code]
profile = { model = "sonnet-5", effort = "medium" }
spec = { model = "fable-5", effort = "high" }
outline = { model = "opus-4-8", effort = "high" }
draft = { model = "opus-4-8", effort = "medium" }
qa = { model = "haiku-4-5", effort = "medium" }
repair = { model = "opus-4-8", effort = "medium" }
audit = { model = "opus-4-8", effort = "medium" }

[presets.stages.codex]
profile = { model = "terra", effort = "medium" }
spec = { model = "sol", effort = "high" }
outline = { model = "sol", effort = "high" }
draft = { model = "sol", effort = "medium" }
qa = { model = "luna", effort = "medium" }
repair = { model = "sol", effort = "medium" }
audit = { model = "sol", effort = "medium" }

[[presets]]
id = "cost-efficient"
label = "Cost efficient"
description = "Capable mid-tier models throughout; cheapest way to a full course."

[presets.stages.claude-code]
profile = { model = "haiku-4-5", effort = "low" }
spec = { model = "sonnet-5", effort = "medium" }
outline = { model = "sonnet-5", effort = "medium" }
draft = { model = "sonnet-5", effort = "medium" }
qa = { model = "haiku-4-5", effort = "low" }
repair = { model = "sonnet-5", effort = "medium" }
audit = { model = "sonnet-5", effort = "medium" }

[presets.stages.codex]
profile = { model = "luna", effort = "low" }
spec = { model = "terra", effort = "medium" }
outline = { model = "terra", effort = "medium" }
draft = { model = "terra", effort = "medium" }
qa = { model = "luna", effort = "low" }
repair = { model = "terra", effort = "medium" }
audit = { model = "terra", effort = "medium" }
```

Note: the `manual` provider's model keeps `quality = "manual"` exactly as today (existing behavior; unknown quality ranks as "strong" which is fine for a provider presets never reference).

- [ ] **Step 4: Replace `config/model-plan.example.toml`**

Full new contents (the Balanced / claude-code column, keeping the existing recommendation strings):

```toml
provider = "claude-code"

[stages.profile]
recommendation = "fast_or_strong_summary"
model = "sonnet-5"
effort = "medium"

[stages.spec]
recommendation = "strong_contract_design"
model = "fable-5"
effort = "high"

[stages.outline]
recommendation = "premium_reasoning"
model = "opus-4-8"
effort = "high"

[stages.draft]
recommendation = "strong_longform_generation"
model = "opus-4-8"
effort = "medium"

[stages.qa]
recommendation = "fast_cheap_check"
model = "haiku-4-5"
effort = "medium"

[stages.repair]
recommendation = "strong_or_premium_repair"
model = "opus-4-8"
effort = "medium"

[stages.audit]
recommendation = "strong_personalization_audit"
model = "opus-4-8"
effort = "medium"
```

- [ ] **Step 5: Run the full Python suite**

Run: `python3 -m pytest`
Expected: all PASS. If any pre-existing test asserted the old placeholder catalog contents (e.g. model id `"balanced"` or provider default `manual`), update that test to the new defaults — the new defaults are the intended behavior.

- [ ] **Step 6: Commit**

```bash
git add config/model-catalog.example.toml config/model-plan.example.toml tests/test_config.py
git commit -m "feat(config): ship real Claude/Codex model catalog, three presets, and a Claude Code default plan"
```

---

### Task 4: Type-scale bump

**Files:**
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces: root font 18px; no CSS class/token renames — later tasks depend on nothing here.

- [ ] **Step 1: Raise the root size**

In `web/src/styles.css`, in the `/* base rules */` section (above `body`), add:

```css
/* 18px root — the whole rem scale reads ~2px larger (usability audit). */
html { font-size: 112.5%; }
```

- [ ] **Step 2: Floor the small sizes**

Replace every `font-size: 0.75rem` with `font-size: 0.8125rem` and every `font-size: 0.8125rem` with `font-size: 0.875rem`. Order matters — do the `0.8125rem → 0.875rem` replacements first, then `0.75rem → 0.8125rem`:

```bash
cd web
perl -pi -e 's/font-size: 0\.8125rem/font-size: 0.875rem/g' src/styles.css
perl -pi -e 's/font-size: 0\.75rem/font-size: 0.8125rem/g' src/styles.css
grep -c "font-size: 0.75rem" src/styles.css   # expect 0
```

- [ ] **Step 3: Verify build and visual smoke**

Run (from `web/`): `npm run build && npm run test`
Expected: build passes, all vitest suites pass.

Run: `npx playwright test e2e/smoke.spec.ts`
Expected: PASS (no horizontal overflow / layout assertions break).

- [ ] **Step 4: Commit**

```bash
git add web/src/styles.css
git commit -m "feat(web): raise the type scale to an 18px root and floor small text"
```

---

### Task 5: InfoTip component

**Files:**
- Create: `web/src/components/InfoTip.tsx`
- Modify: `web/src/styles.css` (append component styles)
- Test: `web/src/components/InfoTip.test.tsx`

**Interfaces:**
- Produces: `export default function InfoTip({ label, text }: { label: string; text: string })` — a ⓘ button with `aria-label` of `` `About ${label}` ``; tooltip text node has `role="tooltip"` and is referenced by `aria-describedby` while open. Tasks 7, 9, 11, 12 import it as `import InfoTip from "./InfoTip"` (components) or `"../components/InfoTip"` (pages).

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/InfoTip.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import InfoTip from "./InfoTip";

describe("InfoTip", () => {
  it("is hidden until focused and exposes the text as a described tooltip", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Brief" text="What the course should cover." />);
    const trigger = screen.getByRole("button", { name: "About Brief" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.tab();
    expect(trigger).toHaveFocus();
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("What the course should cover.");
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);

    await user.tab();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("dismisses on Escape and toggles on click", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Brief" text="Help." />);
    const trigger = screen.getByRole("button", { name: "About Brief" });

    await user.click(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npx vitest run src/components/InfoTip.test.tsx`
Expected: FAIL — cannot resolve `./InfoTip`.

- [ ] **Step 3: Implement the component**

Create `web/src/components/InfoTip.tsx`:

```tsx
import { useId, useState } from "react";

export interface InfoTipProps {
  /** The field/control name the tip explains; used in the accessible name. */
  label: string;
  /** Plain-language explanation shown in the tooltip. */
  text: string;
}

export default function InfoTip({ label, text }: InfoTipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className="info-tip">
      <button
        type="button"
        className="info-tip-trigger"
        aria-label={`About ${label}`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span aria-hidden="true">ⓘ</span>
      </button>
      {open && (
        <span role="tooltip" id={id} className="info-tip-bubble">
          {text}
        </span>
      )}
    </span>
  );
}
```

Append to `web/src/styles.css`:

```css
/* ---------------------------------------------------------------- info tip */
.info-tip { position: relative; display: inline-block; margin-left: var(--ep-space-1); }
.info-tip-trigger {
  border: none;
  background: none;
  padding: 0 0.125rem;
  min-height: 0;
  color: var(--ep-color-text-muted);
  cursor: help;
  line-height: 1;
}
.info-tip-trigger:hover, .info-tip-trigger:focus-visible { color: var(--ep-color-accent); }
.info-tip-bubble {
  position: absolute;
  bottom: calc(100% + var(--ep-space-1));
  left: 50%;
  transform: translateX(-50%);
  z-index: 30;
  width: max-content;
  max-width: 36ch;
  padding: var(--ep-space-2) var(--ep-space-3);
  border: 1px solid var(--ep-color-border);
  border-radius: var(--ep-radius-control);
  background: var(--ep-color-surface);
  color: var(--ep-color-text);
  font-size: 0.875rem;
  line-height: 1.45;
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.15);
}
```

If existing `button` base styles (background/border/min-height) override the trigger, keep the `.info-tip-trigger` selector after them in the file so it wins.

- [ ] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/components/InfoTip.test.tsx && npm run build`
Expected: PASS, clean type-check.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/InfoTip.tsx web/src/components/InfoTip.test.tsx web/src/styles.css
git commit -m "feat(web): accessible InfoTip tooltip component"
```

---

### Task 6: Preset picker on the Settings page

**Files:**
- Modify: `web/src/api/types.ts` (after `CatalogProvider`, ~line 506)
- Modify: `web/src/api/client.ts:476-477` (`getConfigCatalog`)
- Modify: `web/src/pages/SettingsPage.tsx`
- Test: `web/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: catalog payload `presets` from Task 2; ids `max-quality`/`balanced`/`cost-efficient` from Task 3.
- Produces (Task 7 relies on these):
  - types: `export interface PresetStagePayload { model: string; effort: string | null }` and `export interface CatalogPreset { id: string; label: string; description: string; stages: Record<string, Record<string, PresetStagePayload>> }`
  - `getConfigCatalog` returns `{ providers: CatalogProvider[]; presets: CatalogPreset[] }`
  - SettingsPage state: `presets: CatalogPreset[]`, `presetProvider: string`.

- [ ] **Step 1: Write the failing tests**

In `web/src/pages/SettingsPage.test.tsx`: add presets to the mocked catalog response and new tests. Update the top-level `catalog` fixture module scope with:

```tsx
import type { CatalogPreset } from "../api/types";

const presets: CatalogPreset[] = [
  {
    id: "balanced",
    label: "Balanced",
    description: "Deep design where it counts.",
    stages: {
      "claude-code": {
        profile: { model: "sonnet", effort: "medium" },
        spec: { model: "sonnet", effort: "high" },
        outline: { model: "sonnet", effort: "high" },
        draft: { model: "sonnet", effort: "medium" },
        qa: { model: "sonnet", effort: "medium" },
        repair: { model: "sonnet", effort: "medium" },
        audit: { model: "sonnet", effort: "medium" },
      },
      codex: {
        profile: { model: "gpt", effort: "medium" },
        spec: { model: "gpt", effort: "high" },
        outline: { model: "gpt", effort: "high" },
        draft: { model: "gpt", effort: "medium" },
        qa: { model: "gpt", effort: "medium" },
        repair: { model: "gpt", effort: "medium" },
        audit: { model: "gpt", effort: "medium" },
      },
    },
  },
];
```

Change the `setup` helper's catalog mock to `vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog, presets });` and add tests:

```tsx
it("applies a preset to every stage row for the selected provider", async () => {
  const user = userEvent.setup();
  setup();
  await screen.findByText("Default model plan");
  await user.click(screen.getByRole("button", { name: /Balanced/ }));
  const specRow = document.querySelector('[data-stage="spec"]')!;
  expect(
    within(specRow as HTMLElement).getByLabelText("Model for spec"),
  ).toHaveValue("sonnet");
  expect(
    within(specRow as HTMLElement).getByLabelText("Effort for spec"),
  ).toHaveValue("high");
});

it("applies the codex mapping when the preset provider toggle is switched", async () => {
  const user = userEvent.setup();
  setup();
  await screen.findByText("Default model plan");
  await user.click(screen.getByRole("radio", { name: "Codex" }));
  await user.click(screen.getByRole("button", { name: /Balanced/ }));
  const qaRow = document.querySelector('[data-stage="qa"]')!;
  expect(
    within(qaRow as HTMLElement).getByLabelText("Provider for qa"),
  ).toHaveValue("codex");
  expect(
    within(qaRow as HTMLElement).getByLabelText("Model for qa"),
  ).toHaveValue("gpt");
});

it("saves preset-applied overrides through putConfigPlan", async () => {
  const user = userEvent.setup();
  vi.mocked(putConfigPlan).mockResolvedValue(makePlan());
  setup();
  await screen.findByText("Default model plan");
  await user.click(screen.getByRole("button", { name: /Balanced/ }));
  await user.click(screen.getByRole("button", { name: "Save" }));
  const [, , stages] = vi.mocked(putConfigPlan).mock.calls[0];
  expect(stages.spec).toEqual({ provider: "claude-code", model: "sonnet", effort: "high" });
});
```

Also update any existing test that clicks "Use recommended (all stages)" — that button is removed in this task; rewrite those assertions against the new preset buttons (a preset click fills rows rather than clearing them).

- [ ] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npx vitest run src/pages/SettingsPage.test.tsx`
Expected: new tests FAIL (no preset buttons; catalog mock type error until types change).

- [ ] **Step 3: Implement**

`web/src/api/types.ts` — add after `CatalogProvider`:

```tsx
export interface PresetStagePayload {
  model: string;
  effort: string | null;
}

export interface CatalogPreset {
  id: string;
  label: string;
  description: string;
  stages: Record<string, Record<string, PresetStagePayload>>;
}
```

`web/src/api/client.ts`:

```tsx
export const getConfigCatalog = () =>
  api<{ providers: CatalogProvider[]; presets: CatalogPreset[] }>("/v1/config/catalog");
```

(import `CatalogPreset` in the client's type imports.)

`web/src/pages/SettingsPage.tsx`:

1. Add state:

```tsx
const [presets, setPresets] = useState<CatalogPreset[]>([]);
const [presetProvider, setPresetProvider] = useState<string>("claude-code");
```

2. In `load()` after `setCatalog(...)`:

```tsx
setPresets(catalogResp.presets ?? []);
const presetProviders = new Set(
  (catalogResp.presets ?? []).flatMap((p) => Object.keys(p.stages)),
);
setPresetProvider(
  presetProviders.has(planResp.provider) ? planResp.provider : "claude-code",
);
```

3. Replace `useRecommendedAll` with:

```tsx
const applyPreset = (preset: CatalogPreset) => {
  const mapping = preset.stages[presetProvider];
  if (!mapping) return;
  setOverrides(() => {
    const next: Record<string, StageOverride> = {};
    for (const [stageName, choice] of Object.entries(mapping)) {
      next[stageName] = {
        provider: presetProvider,
        model: choice.model,
        effort: choice.effort ?? undefined,
      };
    }
    return next;
  });
};

const presetProviderIds = Array.from(
  new Set(presets.flatMap((p) => Object.keys(p.stages))),
);
```

4. Replace the toolbar block (the "Use recommended (all stages)" button) with:

```tsx
<div className="preset-picker">
  <fieldset className="preset-provider-toggle">
    <legend>Recommended presets for</legend>
    {presetProviderIds.map((providerId) => (
      <label key={providerId}>
        <input
          type="radio"
          name="preset-provider"
          value={providerId}
          checked={presetProvider === providerId}
          onChange={() => setPresetProvider(providerId)}
        />
        {catalog.find((p) => p.id === providerId)?.label ?? providerId}
      </label>
    ))}
  </fieldset>
  <div className="preset-buttons" role="group" aria-label="Recommended presets">
    {presets.map((preset) => (
      <button key={preset.id} type="button" onClick={() => applyPreset(preset)}>
        <span className="preset-label">{preset.label}</span>
        <span className="preset-description">{preset.description}</span>
      </button>
    ))}
  </div>
  <p className="field-help">
    A preset fills every stage below; adjust any row before saving.
  </p>
</div>
<div className="toolbar" role="toolbar" aria-label="Plan actions">
  <button type="button" disabled={save.busy} onClick={doSave}>
    Save
  </button>
</div>
```

When `presets.length === 0` render nothing for the picker (legacy catalogs).

5. Append styles to `web/src/styles.css`:

```css
/* ------------------------------------------------------------ preset picker */
.preset-picker { margin: var(--ep-space-3) 0; }
.preset-provider-toggle { border: none; padding: 0; margin: 0 0 var(--ep-space-2); display: flex; gap: var(--ep-space-3); align-items: center; }
.preset-provider-toggle legend { float: left; margin-right: var(--ep-space-3); color: var(--ep-color-text-muted); }
.preset-buttons { display: flex; gap: var(--ep-space-2); flex-wrap: wrap; }
.preset-buttons button { display: flex; flex-direction: column; align-items: flex-start; gap: var(--ep-space-1); text-align: left; max-width: 18rem; }
.preset-label { font-weight: 600; }
.preset-description { font-size: 0.875rem; color: var(--ep-color-text-muted); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/pages/SettingsPage.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/types.ts web/src/api/client.ts web/src/pages/SettingsPage.tsx web/src/pages/SettingsPage.test.tsx web/src/styles.css
git commit -m "feat(web): three recommended presets with a provider toggle on Settings"
```

---

### Task 7: Stage row reset-to-default and stage tooltips

**Files:**
- Create: `web/src/lib/planHelp.ts`
- Modify: `web/src/components/PlanStageRow.tsx`
- Modify: `web/src/pages/SettingsPage.tsx` (pass the new prop)
- Test: `web/src/components/PlanStageRow.test.tsx`

**Interfaces:**
- Consumes: `InfoTip` (Task 5); `CatalogPreset` (Task 6).
- Produces:
  - `planHelp.ts` exports `STAGE_HELP: Record<string, string>`, `PROVIDER_HELP: string`, `EFFORT_HELP: string`.
  - `PlanStageRow` gains prop `resetValue: StageOverride | null` — the value its "Reset to default" button applies (`null` keeps the legacy clear-to-provider-default behavior).

- [ ] **Step 1: Write the failing tests**

In `web/src/components/PlanStageRow.test.tsx` add (mirroring the file's existing render helpers):

```tsx
it("reset button applies the provided default override", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderRow({
    resetValue: { provider: "claude-code", model: "sonnet", effort: "high" },
    onChange,
  });
  await user.click(screen.getByRole("button", { name: "Reset to default" }));
  expect(onChange).toHaveBeenCalledWith("spec", {
    provider: "claude-code",
    model: "sonnet",
    effort: "high",
  });
});

it("reset button clears the override when no default is provided", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderRow({ resetValue: null, onChange });
  await user.click(screen.getByRole("button", { name: "Reset to default" }));
  expect(onChange).toHaveBeenCalledWith("spec", null);
});

it("shows a stage explanation tooltip", async () => {
  const user = userEvent.setup();
  renderRow({});
  await user.click(screen.getByRole("button", { name: "About spec stage" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent(/course contract/);
});
```

(`renderRow` = the file's existing helper that renders a `spec` stage row; extend it to accept and forward `resetValue`, defaulting to `null`.) Update any existing test that clicks the old "Use recommended" per-row button to use the "Reset to default" name.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npx vitest run src/components/PlanStageRow.test.tsx`
Expected: FAIL — unknown prop / button names not found.

- [ ] **Step 3: Implement**

Create `web/src/lib/planHelp.ts`:

```tsx
// Plain-language explanations for the model-plan surface (design system §3.4).
export const STAGE_HELP: Record<string, string> = {
  profile: "Summarizes the attached learner profile into guidance the other stages can use.",
  spec: "Turns your topic brief into the course contract — scope, modules, and success criteria — that every later stage builds against.",
  outline: "Expands the spec into a module-by-module lesson outline.",
  draft: "Writes the full course content from the outline.",
  qa: "Checks the draft against the spec and flags problems.",
  repair: "Fixes the problems QA found.",
  audit: "Optional review of how well the course matches the attached learner profile.",
};

export const PROVIDER_HELP =
  "Which tool runs this stage. Claude Code and Codex run automatically through their CLIs; Manual copy/paste means you run the prompt yourself in any model UI.";

export const EFFORT_HELP =
  "How much reasoning the model is asked to spend on this stage. Higher effort is slower and costs more.";
```

In `PlanStageRow.tsx`:

1. Add to props: `resetValue: StageOverride | null;`
2. Import `InfoTip` and the help constants.
3. Replace `const useRecommended = () => onChange(stage.stage, null);` with:

```tsx
const resetToDefault = () =>
  onChange(stage.stage, resetValue ? { ...resetValue } : null);
```

4. Button becomes:

```tsx
<button type="button" onClick={resetToDefault}>
  Reset to default
</button>
```

5. Stage name gains a tooltip (only when help exists):

```tsx
<span className="plan-stage-name">
  {stage.stage}
  {STAGE_HELP[stage.stage] && (
    <InfoTip label={`${stage.stage} stage`} text={STAGE_HELP[stage.stage]} />
  )}
</span>
```

6. Provider and Effort labels gain `<InfoTip label={`provider for ${stage.stage}`} text={PROVIDER_HELP} />` and `<InfoTip label={`effort for ${stage.stage}`} text={EFFORT_HELP} />` beside the label text (inside the `<label>`, before the `<select>`).

In `SettingsPage.tsx`, compute the row's reset value from the **balanced** preset for the row's currently-displayed provider and pass it:

```tsx
const balanced = presets.find((p) => p.id === "balanced") ?? presets[0] ?? null;

const resetValueFor = (stageName: string, providerId: string): StageOverride | null => {
  const choice = balanced?.stages[providerId]?.[stageName];
  if (!choice) return null;
  return { provider: providerId, model: choice.model, effort: choice.effort ?? undefined };
};
```

and in the render loop:

```tsx
{plan.stages.map((stage) => {
  const display = displayStage(stage, overrides[stage.stage], plan.provider);
  return (
    <PlanStageRow
      key={stage.stage}
      stage={display}
      catalog={catalog}
      providers={providers}
      resetValue={resetValueFor(stage.stage, display.provider ?? plan.provider)}
      onChange={handleRowChange}
    />
  );
})}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/components/PlanStageRow.test.tsx src/pages/SettingsPage.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/planHelp.ts web/src/components/PlanStageRow.tsx web/src/components/PlanStageRow.test.tsx web/src/pages/SettingsPage.tsx web/src/styles.css
git commit -m "feat(web): stage tooltips and preset-aware reset-to-default on plan rows"
```

---

### Task 8: Presets end-to-end (Playwright + axe)

**Files:**
- Modify: `web/e2e/model-plan.spec.ts`

**Interfaces:**
- Consumes: the spec's own fixture catalog TOML (`MODEL_CATALOG_TOML` constant), preset picker UI from Task 6.

- [ ] **Step 1: Extend the fixture catalog**

Append to the spec's `MODEL_CATALOG_TOML` string a presets section referencing the fixture's existing providers/models (`claude-code` with `balanced`/`quick`, `codex` — check the fixture's codex model ids and use them):

```toml
[[presets]]
id = "balanced"
label = "Balanced"
description = "Fixture preset."

[presets.stages.claude-code]
profile = { model = "balanced" }
spec = { model = "balanced", effort = "high" }
outline = { model = "balanced" }
draft = { model = "balanced" }
qa = { model = "quick", effort = "low" }
repair = { model = "balanced" }
audit = { model = "balanced" }
```

(plus a `[presets.stages.codex]` table over the fixture's codex model ids, same shape).

- [ ] **Step 2: Write the failing test**

Add to `model-plan.spec.ts` (using the file's existing page/navigation helpers):

```tsx
test("preset fills every stage row, saves, and survives reload", async ({ page }) => {
  await page.goto(`${baseURL}/settings`);
  await page.getByRole("button", { name: /Balanced/ }).click();
  const specRow = page.locator('[data-stage="spec"]');
  await expect(specRow.getByLabel("Model for spec")).toHaveValue("balanced");
  await expect(specRow.getByLabel("Effort for spec")).toHaveValue("high");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.reload();
  await expect(
    page.locator('[data-stage="qa"]').getByLabel("Model for qa"),
  ).toHaveValue("quick");
});

test("settings page with a tooltip open passes axe", async ({ page }) => {
  await page.goto(`${baseURL}/settings`);
  await page.getByRole("button", { name: "About spec stage" }).click();
  await expect(page.getByRole("tooltip")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
```

Import `AxeBuilder` the same way the existing axe-using specs do (`import AxeBuilder from "@axe-core/playwright";` — copy the exact import from `web/e2e/smoke.spec.ts` or wherever axe is already used).

- [ ] **Step 3: Run the spec**

Run (from `web/`): `npx playwright test e2e/model-plan.spec.ts`
Expected: the two new tests PASS along with the existing ones. (If existing tests in this spec asserted the old "Use recommended (all stages)" button, update them to the preset picker.)

- [ ] **Step 4: Commit**

```bash
git add web/e2e/model-plan.spec.ts
git commit -m "test(e2e): presets fill, persist, and pass axe on the settings page"
```

---

### Task 9: Learner-profile field help

**Files:**
- Create: `web/src/lib/profileHelp.ts`
- Modify: `web/src/components/ProfileForm.tsx` (the `Field` component, lines 18-37)
- Test: `web/src/components/ProfileForm.test.tsx`

**Interfaces:**
- Consumes: `InfoTip` (Task 5). `Field` already receives each field's `path` — help lookup is keyed by that exact path string.
- Produces: `PROFILE_HELP: Record<string, string>` in `web/src/lib/profileHelp.ts`.

- [ ] **Step 1: Write the failing test**

Add to `web/src/components/ProfileForm.test.tsx` (reuse the file's existing render helper/fixture profile):

```tsx
it("renders an info tip for every labeled field", () => {
  renderForm(); // the file's existing helper that renders ProfileForm with a fixture profile
  for (const label of [
    "Target learner",
    "Prior education",
    "Adjacent domains",
    "Learning goals",
    "Math comfort",
    "Reading level",
    "Pace",
    "Preferred modalities",
    "Jurisdiction",
    "Private by default",
    "Publishable summary",
  ]) {
    expect(
      screen.getByRole("button", { name: `About ${label}` }),
    ).toBeInTheDocument();
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run src/components/ProfileForm.test.tsx`
Expected: FAIL — no "About …" buttons.

- [ ] **Step 3: Create the copy map**

Create `web/src/lib/profileHelp.ts` with exactly this copy (keys are the `path` values `Field` already receives):

```tsx
// Plain-language help for every learner-profile field, keyed by field path.
export const PROFILE_HELP: Record<string, string> = {
  schema_version: "Internal format version of this profile file. You don't need to change it.",
  id: "Short identifier used in filenames, e.g. jamie or team-onboarding. Letters, digits, dots, dashes, underscores.",
  target_learner: "Who this course is for, in a sentence. Example: 'My 12-year-old who loves Minecraft' or 'Junior analysts new to SQL'.",
  prior_education: "Formal schooling that's relevant, e.g. 'college algebra' or 'no formal CS background'.",
  prior_experience: "Hands-on experience with this subject so far, if any.",
  professional_experience: "Work background that shapes which examples will land.",
  current_skill_level: "Where the learner is starting from: beginner, intermediate, returning after a break…",
  adjacent_domains: "Subjects the learner already knows that lessons can build bridges from. One per line.",
  learning_goals: "What the learner wants to be able to do after the course. One goal per line.",
  preferred_examples: "Domains or themes examples should draw from (sports, cooking, games…). One per line.",
  examples_to_avoid: "Topics or themes to keep out of examples. One per line.",
  math_comfort: "How much math the learner is happy to see, in your own words — e.g. 'avoid equations' or 'algebra is fine'.",
  reading_level: "The reading level the course should aim for, e.g. 'middle school' or 'plain professional English'.",
  pace: "How quickly to move through material, e.g. 'slow and thorough' or 'brisk with recaps'.",
  desired_depth: "How deep to go: quick overview, working knowledge, or expert detail.",
  time_budget: "Total time the learner can give the course, e.g. '30 minutes a day for two weeks'.",
  assessment_styles: "How the learner likes to be tested (quizzes, projects, flashcards…). One per line.",
  accessibility_constraints: "Anything the course must accommodate — dyslexia-friendly text, screen-reader use, no audio… One per line.",
  tone_preference: "The voice the course should use, e.g. 'encouraging', 'straight to the point', or 'playful'.",
  sensitive_areas: "Subjects to handle carefully or skip entirely. One per line.",
  "learning_preferences.preferred_modalities": "How the learner best absorbs material: reading, diagrams, worked examples, practice problems… One per line.",
  "learning_preferences.explanation_style": "How explanations should be built, e.g. 'intuition first, then formalism'.",
  "learning_preferences.preferred_visual_aids": "Kinds of visuals that help: flowcharts, tables, timelines… One per line.",
  "learning_preferences.diagram_frequency": "How often to include diagrams, e.g. 'every concept' or 'only when essential'.",
  "learning_preferences.interaction_style": "How interactive lessons should feel, e.g. 'frequent check-ins' or 'read straight through'.",
  "learning_preferences.practice_style": "The kinds of practice that work: drills, open-ended projects, spaced review… One per line.",
  "learning_preferences.feedback_style": "How feedback should sound, e.g. 'gentle and specific' or 'direct'.",
  "learning_preferences.worked_example_preference": "How much worked examples should carry the teaching, e.g. 'show one before every exercise'.",
  "learning_preferences.common_sticking_points": "Where this learner tends to get stuck, so the course slows down there. One per line.",
  "learning_preferences.attention_constraints": "Focus limits to design around — short sessions, minimal walls of text… One per line.",
  "learning_preferences.review_style": "How the course should reinforce earlier material: summaries, spaced repetition, cumulative quizzes… One per line.",
  "localization.jurisdiction": "Country or region whose laws and conventions examples should follow, e.g. 'US' or 'Germany'.",
  "localization.locale": "Language/region code for the course text, e.g. 'en-US'.",
  "localization.units": "Measurement system for examples: metric or imperial.",
  "localization.language_register": "How formal the language should be, e.g. 'casual' or 'formal'.",
  "privacy.private_by_default": "When on, profile details stay out of anything you publish unless explicitly marked publishable.",
  "privacy.include_in_published_output": "When on, the publishable summary below is included in exported courses.",
  "privacy.publishable_summary": "A short learner description that is safe to publish with the course, if you choose to include it.",
  "metadata.*": "Extra structured notes for your own use. Everything here is passed to the models with the rest of the profile.",
};
```

- [ ] **Step 4: Render tips in `Field`**

In `ProfileForm.tsx`, import `InfoTip` and `PROFILE_HELP`, then change `Field`'s label span:

```tsx
<span className="profile-field-label">
  {label} <SensitivityBadge tier={sensitivity[path]} />
  {PROFILE_HELP[path] && <InfoTip label={label} text={PROFILE_HELP[path]} />}
</span>
```

The metadata editor heading (line ~259) gains `\n<InfoTip label="Metadata" text={PROFILE_HELP["metadata.*"]} />` beside its `SensitivityBadge`.

- [ ] **Step 5: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/components/ProfileForm.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/profileHelp.ts web/src/components/ProfileForm.tsx web/src/components/ProfileForm.test.tsx
git commit -m "feat(web): explanatory tooltips on every learner-profile field"
```

---

### Task 10: Enlargeable profile fields

**Files:**
- Modify: `web/src/components/ProfileForm.tsx` (the `input`, `preferenceInput`, `localizationInput` helpers, lines 212-236)
- Modify: `web/src/styles.css`
- Test: `web/src/components/ProfileForm.test.tsx`

**Interfaces:**
- Consumes: nothing new. Stored values remain single-line strings — newlines are normalized to spaces on change, so the TOML profile shape is untouched.
- The `id` field stays a single-line `<input>` (it is a constrained identifier, not free text). `schema_version` (number, readOnly), checkboxes, selects, and metadata key inputs are unchanged.

- [ ] **Step 1: Write the failing tests**

```tsx
it("free-text fields are textareas and normalize newlines to spaces", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderForm({ onChange }); // existing helper, forwarding onChange
  const mathComfort = screen.getByLabelText("Math comfort");
  expect(mathComfort.tagName).toBe("TEXTAREA");
  await user.type(mathComfort, "algebra fine{enter}no proofs");
  const last = onChange.mock.calls.at(-1)![0];
  expect(last.math_comfort).toBe("algebra fine no proofs");
});

it("profile id stays a single-line input", () => {
  renderForm();
  expect(screen.getByLabelText("Profile id").tagName).toBe("INPUT");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npx vitest run src/components/ProfileForm.test.tsx`
Expected: FAIL — `mathComfort.tagName` is `"INPUT"`.

- [ ] **Step 3: Implement**

In `ProfileForm.tsx` add a normalization helper next to `lines`:

```tsx
const singleLine = (value: string) => value.replace(/\s*\n\s*/g, " ");
```

Change the `input` helper so `id` keeps an `<input>` and every other key renders a textarea:

```tsx
const input = (label: string, key: keyof LearnerProfile, path = String(key), required = false) => (
  <Field label={label} path={path} sensitivity={sensitivity}>
    {key === "id" ? (
      <input
        required={required}
        disabled={disabled || idLocked}
        value={(value[key] as string | undefined) ?? ""}
        onChange={(event) => set(key, event.target.value as never)}
      />
    ) : (
      <textarea
        rows={2}
        required={required}
        disabled={disabled}
        value={(value[key] as string | undefined) ?? ""}
        onChange={(event) =>
          key === "target_learner"
            ? set(key, singleLine(event.target.value) as never)
            : optional(key, singleLine(event.target.value))
        }
      />
    )}
  </Field>
);
```

Change `preferenceInput` and `localizationInput` the same way — `<input …>` becomes `<textarea rows={2} …>` with the value run through `singleLine(...)` before the existing trim-to-undefined logic:

```tsx
const preferenceInput = (label: string, key: keyof LearnerProfile["learning_preferences"]) => (
  <Field label={label} path={`learning_preferences.${String(key)}`} sensitivity={sensitivity}>
    <textarea
      rows={2}
      disabled={disabled}
      value={(value.learning_preferences[key] as string | undefined) ?? ""}
      onChange={(event) => {
        const text = singleLine(event.target.value);
        preference(key, (text.trim() ? text : undefined) as never);
      }}
    />
  </Field>
);

const localizationInput = (label: string, key: keyof LearnerProfile["localization"]) => (
  <Field label={label} path={`localization.${String(key)}`} sensitivity={sensitivity}>
    <textarea
      rows={2}
      disabled={disabled}
      value={value.localization[key] ?? ""}
      onChange={(event) => {
        const text = singleLine(event.target.value);
        localization(key, (text.trim() ? text : undefined) as never);
      }}
    />
  </Field>
);
```

Append to `web/src/styles.css`:

```css
/* Profile free-text fields grow with content and stay user-resizable. */
.profile-field textarea { resize: vertical; min-height: 2.5rem; }
@supports (field-sizing: content) {
  .profile-field textarea { field-sizing: content; max-height: 24rem; }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/components/ProfileForm.test.tsx && npm run build`
Expected: PASS. Also run `npx vitest run src/pages/ProfileEditorPage.test.tsx src/pages/ProfilesPage.test.tsx` — fix any assertions that assumed `<input>` tags (query by label, not tag).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ProfileForm.tsx web/src/components/ProfileForm.test.tsx web/src/styles.css
git commit -m "feat(web): every free-text profile field is an enlargeable textarea"
```

---

### Task 11: New-course wizard help and topic-id validation

**Files:**
- Create: `web/src/lib/newRunHelp.ts`
- Modify: `web/src/pages/NewRunPage.tsx`
- Test: `web/src/pages/NewRunPage.test.tsx`

**Interfaces:**
- Consumes: `InfoTip` (Task 5).
- Produces: `NEW_RUN_HELP: Record<string, string>` and `TOPIC_ID_PATTERN` in `newRunHelp.ts`. The pattern mirrors the daemon's `_ARTIFACT_ID_PATTERN` (`education_pipeline/workspace.py:21`): `/^[A-Za-z0-9][A-Za-z0-9._-]*$/`.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/pages/NewRunPage.test.tsx` (reuse its existing router/render setup; the wizard must be advanced past the learner step first — copy the existing navigation helper):

```tsx
it("shows help for the brief and topic id", async () => {
  const user = userEvent.setup();
  await renderAtTopicStep(); // existing helper or: render page, click Continue on learner step
  await user.click(screen.getByRole("button", { name: "About Topic id" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent(/intro-to-sql/);
  expect(screen.getByLabelText("Topic id")).toHaveAttribute(
    "placeholder",
    "intro-to-sql",
  );
});

it("rejects a malformed topic id before continuing", async () => {
  const user = userEvent.setup();
  await renderAtTopicStep();
  await user.type(screen.getByLabelText("Topic id"), "bad id!");
  await user.type(screen.getByLabelText("Title"), "A Title");
  expect(
    screen.getByText(/letters, digits, dots, dashes/i),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  await user.clear(screen.getByLabelText("Topic id"));
  await user.type(screen.getByLabelText("Topic id"), "intro-to-sql");
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npx vitest run src/pages/NewRunPage.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Create the copy map and wire it in**

Create `web/src/lib/newRunHelp.ts`:

```tsx
// Plain-language help for the new-course wizard.
export const TOPIC_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export const NEW_RUN_HELP: Record<string, string> = {
  learner: "Attaching a learner profile personalizes the whole course to that person. You can also continue without one for a generic course.",
  topic_id: "Short folder-safe identifier for this course, e.g. intro-to-sql. Start with a letter or digit; then letters, digits, dots, dashes, or underscores.",
  brief: "2–4 sentences on what the course should cover and why the learner wants it. The models design the whole course from this — the more specific, the better.",
  audience: "Who the course is written for if no learner profile is attached, e.g. 'busy professionals new to investing'.",
  goals: "What the learner should be able to do afterward. One goal per line.",
  time_budget: "Rough total learning time in minutes; the outline sizes modules to fit.",
  toml: "Advanced: paste a complete topic definition in TOML instead of describing it field by field.",
  blueprint: "A blueprint is the pedagogical pattern for the course — how lessons, practice, and assessment are arranged. The recommendation is based on your topic.",
};
```

In `NewRunPage.tsx`:

1. Import `InfoTip` and `NEW_RUN_HELP, TOPIC_ID_PATTERN`.
2. Topic id field becomes:

```tsx
<label>
  Topic id
  <InfoTip label="Topic id" text={NEW_RUN_HELP.topic_id} />
  <input
    value={id}
    placeholder="intro-to-sql"
    onChange={(e) => setId(e.target.value)}
  />
</label>
{idInvalid && (
  <p className="error field-validation-error">
    Topic id must start with a letter or digit and use only letters, digits,
    dots, dashes, and underscores.
  </p>
)}
```

with, above the return:

```tsx
const idInvalid = id.trim().length > 0 && !TOPIC_ID_PATTERN.test(id.trim());
```

3. Change `topicReady`:

```tsx
const topicReady =
  mode === "describe"
    ? id.trim().length > 0 && !idInvalid && title.trim().length > 0
    : toml.trim().length > 0;
```

4. Add `<InfoTip label="Brief" text={NEW_RUN_HELP.brief} />` after the `Brief` label text, and a placeholder on its textarea: `placeholder="e.g. A hands-on introduction to SQL for analysts who live in spreadsheets today — enough to query, join, and summarize real tables confidently."`. Same pattern for Audience (`NEW_RUN_HELP.audience`), Goals (`NEW_RUN_HELP.goals`), Time budget (`NEW_RUN_HELP.time_budget`), the Paste-TOML textarea (`NEW_RUN_HELP.toml`).
5. Learner step: add `<p className="field-help">{NEW_RUN_HELP.learner}</p>` under the heading. Blueprint step: `<p className="field-help">{NEW_RUN_HELP.blueprint}</p>` under its heading.

- [ ] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npx vitest run src/pages/NewRunPage.test.tsx && npm run build`
Expected: PASS. Also run `npx playwright test e2e/new-run.spec.ts` and fix any selector drift (labels unchanged, so expect PASS).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/newRunHelp.ts web/src/pages/NewRunPage.tsx web/src/pages/NewRunPage.test.tsx
git commit -m "feat(web): wizard tooltips, placeholders, and client-side topic-id validation"
```

---

### Task 12: UI audit sweep

**Files:**
- Modify: `web/src/pages/TopicListPage.tsx`, `web/src/pages/RunBoardPage.tsx`, `web/src/pages/StageViewerPage.tsx`, `web/src/components/ValidationFindingsPanel.tsx`, `web/src/components/JobsPanel.tsx`, `web/src/components/ExportControls.tsx`, `web/src/components/CanonicalGuidePreview.tsx`, `web/src/components/PersonalizationPanel.tsx` — as findings require
- Test: each touched component's existing `.test.tsx`

**Interfaces:**
- Consumes: `InfoTip` (Task 5); voice conventions from `web/src/lib/labels.ts`.

This is an audit: read each file, list every label/button a first-time user could not parse, and fix it with an InfoTip or a `field-help` line. Known concrete items (do these; add others you find):

- [ ] **Step 1: Waiver vocabulary.** In `ValidationFindingsPanel.tsx`, wherever the waive control renders, add: `<InfoTip label="Waive" text="Waiving a finding accepts it as-is: it stops blocking finalize but stays recorded with your reason." />` and assert the tip's presence in `ValidationFindingsPanel.test.tsx` (`screen.getByRole("button", { name: "About Waive" })`).

- [ ] **Step 2: Canonical guide vocabulary.** In `CanonicalGuidePreview.tsx`, add near the heading: `<InfoTip label="Canonical guide" text="The cleaned-up, validated version of the draft that finalize will publish." />`; assert in its test.

- [ ] **Step 3: Jobs vocabulary.** In `JobsPanel.tsx`, add near the heading: `<InfoTip label="Jobs" text="Background runs of stage prompts through a provider CLI. Each job's log shows exactly what the model was asked and answered." />`; assert in its test.

- [ ] **Step 4: Provider availability wording.** In `SettingsPage.tsx`, under the "Provider availability" heading add: `<p className="field-help">Available means the provider's CLI was found on this machine. Unavailable providers can still be selected in the plan — runs will use the manual copy/paste flow until the CLI is installed.</p>`; assert the text in `SettingsPage.test.tsx`.

- [ ] **Step 5: Sweep the rest.** Read the remaining files in the list. For every unexplained term or bare control, add an InfoTip/help line using the same voice (concrete, learner-language, no internal nouns). Every added affordance gets a `getByRole("button", { name: "About …" })` assertion in that component's test file. If a page needs no change, note it in the commit message body.

- [ ] **Step 6: Axe with tooltips open on profile and wizard pages.** In `web/e2e/profiles.spec.ts` and `web/e2e/new-run.spec.ts`, add one test each (same `AxeBuilder` import as Task 8): open the page, click one InfoTip trigger (`About Target learner` / `About Brief`), assert `getByRole("tooltip")` is visible, run `new AxeBuilder({ page }).analyze()`, expect `results.violations` to equal `[]`.

- [ ] **Step 7: Run the web suites**

Run (from `web/`): `npm run test && npm run build && npx playwright test e2e/profiles.spec.ts e2e/new-run.spec.ts`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A web/src
git commit -m "feat(web): usability sweep — explain waivers, canonical guide, jobs, and remaining jargon"
```

---

### Task 13: Full verification

- [ ] **Step 1: Python suite**

Run: `python3 -m pytest`
Expected: all PASS.

- [ ] **Step 2: Web unit + type-check**

Run (from `web/`): `npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 3: Full e2e**

Run (from `web/`): `npm run e2e`
Expected: all PASS, including axe checks.

- [ ] **Step 4: Live smoke against a real workspace**

```bash
mkdir -p /tmp/ep-smoke-ws && education-pipeline --workspace /tmp/ep-smoke-ws workspace check --fix
education-pipeline ui --workspace /tmp/ep-smoke-ws --no-browser
```

Open the printed URL: Settings shows the three presets and real model names; a fresh plan defaults to Claude Code/Balanced; profile editor shows tooltips and resizable fields; new-course wizard validates the topic id. Then `education-pipeline --workspace /tmp/ep-smoke-ws daemon stop`.

- [ ] **Step 5: Commit any straggler fixes; do not merge**

Leave integration (PR vs merge) to the finishing-a-development-branch flow with the user.
