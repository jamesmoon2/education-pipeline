import tomllib
from pathlib import Path

import pytest

from education_pipeline import (
    DEFAULT_STAGE_RECOMMENDATIONS,
    STAGE_ORDER,
    ConfigError,
    StageModelPlan,
    load_model_catalog,
    load_model_plan,
    parse_model_catalog,
    parse_model_plan,
)
from education_pipeline.config import (
    GUIDE_V1_REQUIRED_STAGES,
    OPTIONAL_STAGES,
    PRESET_STAGES,
    Preset,
    PresetStage,
    REASONING_STAGES,
    REQUIRED_STAGES,
    SUPPORTED_STAGES,
    apply_overrides,
    apply_overrides_lenient,
    emit_model_plan_toml,
    weak_stage_warning,
)


def test_audit_stage_topology_is_optional_model_powered_and_not_reasoning() -> None:
    assert REQUIRED_STAGES == ("spec", "outline", "draft", "qa", "repair")
    assert OPTIONAL_STAGES == ("audit",)
    assert SUPPORTED_STAGES == GUIDE_V1_REQUIRED_STAGES + OPTIONAL_STAGES
    assert "audit" in STAGE_ORDER
    assert "audit" not in REASONING_STAGES


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


def test_model_plan_parses_and_overrides_audit_stage() -> None:
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "manual"},
                {"id": "codex", "models": [{"id": "audit-model"}]},
            ]
        }
    )
    plan = parse_model_plan(
        {
            "provider": "manual",
            "stages": {
                "audit": {
                    "provider": "codex",
                    "model": "audit-model",
                    "effort": "high",
                }
            },
        },
        catalog=catalog,
    )

    assert plan.stage("audit") == StageModelPlan(
        stage="audit",
        recommendation="strong_personalization_audit",
        provider="codex",
        model="audit-model",
        effort="high",
    )

    reset = apply_overrides(
        plan,
        {"stages": {"audit": {"provider": "manual", "model": None}}},
        catalog=catalog,
    )
    assert reset.stage("audit").provider == "manual"
    assert reset.stage("audit").model is None


EXAMPLE_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "model-catalog.example.toml"
)
EXAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "model-plan.example.toml"
)


def test_loads_example_catalog_and_plan() -> None:
    catalog = load_model_catalog(EXAMPLE_CATALOG_PATH)
    plan = load_model_plan(EXAMPLE_PLAN_PATH, catalog=catalog)

    assert set(catalog.providers) == {"manual", "claude-code", "codex"}
    assert catalog.providers["manual"].models["prompt-only"].quality == "manual"
    assert plan.provider == "claude-code"
    assert tuple(plan.stages) == STAGE_ORDER
    assert plan.stage("outline").recommendation == "premium_reasoning"
    assert plan.stage("finalize").recommendation == "local_only"


def test_missing_stage_recommendations_fall_back_to_defaults() -> None:
    plan = parse_model_plan({"provider": "manual", "stages": {"outline": {"model": "prompt-only"}}})

    assert plan.stage("profile").recommendation == DEFAULT_STAGE_RECOMMENDATIONS["profile"]
    assert plan.stage("outline").recommendation == DEFAULT_STAGE_RECOMMENDATIONS["outline"]
    assert plan.stage("outline").model == "prompt-only"


def test_catalog_rejects_duplicate_provider_ids() -> None:
    with pytest.raises(ConfigError, match="duplicate provider id"):
        parse_model_catalog(
            {
                "providers": [
                    {"id": "manual", "label": "Manual"},
                    {"id": "manual", "label": "Manual again"},
                ]
            }
        )


def test_plan_rejects_unknown_provider_when_catalog_is_supplied() -> None:
    catalog = parse_model_catalog({"providers": [{"id": "manual", "label": "Manual"}]})

    with pytest.raises(ConfigError, match="unknown provider"):
        parse_model_plan({"provider": "missing"}, catalog=catalog)


def test_plan_rejects_unknown_stage_names() -> None:
    with pytest.raises(ConfigError, match="unknown model-plan stage"):
        parse_model_plan({"provider": "manual", "stages": {"publish": {"recommendation": "local"}}})


def test_parse_model_plan_strict_keys_rejects_unknown_stage_key() -> None:
    """The owner decided: strict at write, lenient on disk. `strict_keys=True`
    (used only by the daemon's PUT /v1/config/plan write path) must reject a
    misspelled/unknown stage-override key instead of silently discarding it,
    the same way `apply_overrides`'s existing allowlist does."""

    with pytest.raises(ConfigError, match="unknown stage-override key"):
        parse_model_plan(
            {"provider": "manual", "stages": {"draft": {"modle": "opus"}}},
            strict_keys=True,
        )


def test_parse_model_plan_default_lenient_ignores_unknown_stage_key() -> None:
    """Guards the owner's decision from the other direction: the disk loader
    (default `strict_keys=False`) must keep loading a plan whose stage table
    has a stray key exactly as it did before this change -- tightening the
    disk loader was explicitly ruled out."""

    plan = parse_model_plan(
        {"provider": "manual", "stages": {"draft": {"modle": "opus"}}}
    )
    assert plan.stage("draft").model is None


def test_load_model_plan_toml_with_stray_stage_key_still_loads(tmp_path: Path) -> None:
    """Regression guard for the owner's 'lenient on disk' decision: an
    existing workspace's hand-edited model-plan.toml containing a stray stage
    key must still load exactly as today, even though the same key is now
    rejected on the PUT write path."""

    plan_path = tmp_path / "model-plan.toml"
    plan_path.write_text(
        'provider = "manual"\n\n[stages.draft]\nmodle = "opus"\n',
        encoding="utf-8",
    )
    plan = load_model_plan(plan_path)
    assert plan.provider == "manual"
    assert plan.stage("draft").model is None


def test_plan_rejects_unknown_model_when_provider_has_catalog_models() -> None:
    catalog = parse_model_catalog(
        {
            "providers": [
                {
                    "id": "codex",
                    "label": "Codex",
                    "models": [{"id": "balanced", "label": "Balanced"}],
                }
            ]
        }
    )

    with pytest.raises(ConfigError, match="unknown model"):
        parse_model_plan({"provider": "codex", "stages": {"qa": {"model": "not-real"}}}, catalog=catalog)


def test_stage_level_provider_override_is_validated() -> None:
    catalog = parse_model_catalog(
        {
            "providers": [
                {
                    "id": "manual",
                    "label": "Manual",
                    "models": [{"id": "prompt-only", "label": "Prompt only"}],
                },
                {
                    "id": "codex",
                    "label": "Codex",
                    "models": [{"id": "fast-check", "label": "Fast check"}],
                },
            ]
        }
    )

    plan = parse_model_plan(
        {
            "provider": "manual",
            "stages": {
                "qa": {"provider": "codex", "model": "fast-check", "effort": "low"},
                "repair": {"model": "prompt-only"},
            },
        },
        catalog=catalog,
    )

    assert plan.stage("qa").provider == "codex"
    assert plan.stage("qa").model == "fast-check"
    assert plan.stage("qa").effort == "low"
    assert plan.stage("repair").provider == "manual"
    assert plan.stage("repair").model == "prompt-only"


def test_model_option_parses_argv_model_and_extra_args():
    catalog = parse_model_catalog(
        {
            "providers": [
                {
                    "id": "claude-code",
                    "models": [
                        {
                            "id": "premium",
                            "argv_model": "claude-opus-4-8",
                            "extra_args": ["--reasoning", "high"],
                            "note": "kept in metadata",
                        }
                    ],
                }
            ]
        }
    )
    option = catalog.providers["claude-code"].models["premium"]
    assert option.argv_model == "claude-opus-4-8"
    assert option.extra_args == ("--reasoning", "high")
    assert option.metadata == {"note": "kept in metadata"}


def test_model_option_argv_defaults_and_extra_args_type_checked():
    catalog = parse_model_catalog(
        {"providers": [{"id": "codex", "models": [{"id": "balanced"}]}]}
    )
    option = catalog.providers["codex"].models["balanced"]
    assert option.argv_model is None
    assert option.extra_args == ()

    import pytest

    from education_pipeline import ConfigError

    with pytest.raises(ConfigError):
        parse_model_catalog(
            {
                "providers": [
                    {"id": "codex", "models": [{"id": "x", "extra_args": "not-a-list"}]}
                ]
            }
        )


def _catalog_with_quality(quality):
    return parse_model_catalog({"providers": [{"id": "p", "models": [{"id": "m", "label": "M", "quality": quality}]}]})


def test_weak_warning_fires_for_fast_model_on_reasoning_stage():
    catalog = _catalog_with_quality("fast")
    stage = StageModelPlan(stage="outline", recommendation="premium_reasoning", provider="p", model="m")
    assert weak_stage_warning(catalog, stage) is not None


def test_no_warning_for_strong_premium_unset_quality_or_non_reasoning_stage():
    strong = _catalog_with_quality("strong")
    stage = StageModelPlan(stage="outline", recommendation="premium_reasoning", provider="p", model="m")
    assert weak_stage_warning(strong, stage) is None
    unset = parse_model_catalog({"providers": [{"id": "p", "models": [{"id": "m", "label": "M"}]}]})
    assert weak_stage_warning(unset, stage) is None
    fast = _catalog_with_quality("fast")
    qa = StageModelPlan(stage="qa", recommendation="fast_cheap_check", provider="p", model="m")
    assert weak_stage_warning(fast, qa) is None


def test_emit_model_plan_toml_round_trips():
    catalog = parse_model_catalog({"providers": [
        {"id": "claude-code", "models": [{"id": "opus", "label": "Opus"}]},
        {"id": "codex", "models": [{"id": "gpt", "label": "GPT"}]},
        {"id": "manual"},
    ]})
    plan = parse_model_plan({
        "provider": "claude-code",
        "stages": {
            "draft": {"provider": "codex", "model": "gpt", "effort": "high"},
            "qa": {"provider": "manual"},
            "outline": {"model": "opus", "recommendation": "premium_reasoning"},
        },
    }, catalog=catalog)
    text = emit_model_plan_toml(plan)
    assert parse_model_plan(tomllib.loads(text), catalog=catalog) == plan


def test_emit_escapes_special_characters():
    plan = parse_model_plan({"provider": 'we"ird\\id'}, catalog=None)
    assert parse_model_plan(tomllib.loads(emit_model_plan_toml(plan))) == plan


def _plan_and_catalog():
    catalog = parse_model_catalog(
        {
            "providers": [
                {
                    "id": "claude-code",
                    "models": [
                        {"id": "opus", "label": "Opus"},
                        {"id": "sonnet", "label": "Sonnet"},
                    ],
                },
                {
                    "id": "codex",
                    "models": [{"id": "gpt", "label": "GPT"}],
                },
            ]
        }
    )
    plan = parse_model_plan(
        {
            "provider": "claude-code",
            "stages": {
                "outline": {"model": "opus", "effort": "high"},
                "qa": {"model": "sonnet"},
            },
        },
        catalog=catalog,
    )
    return plan, catalog


def test_apply_overrides_changes_only_the_overridden_stage():
    plan, catalog = _plan_and_catalog()

    merged = apply_overrides(
        plan,
        {"stages": {"qa": {"model": "opus", "effort": "low"}}},
        catalog=catalog,
    )

    assert merged.stage("qa").model == "opus"
    assert merged.stage("qa").effort == "low"
    # Untouched stage is preserved exactly.
    assert merged.stage("outline") == plan.stage("outline")
    assert merged.provider == plan.provider


def test_apply_overrides_preserves_unset_keys_within_overridden_stage():
    plan, catalog = _plan_and_catalog()

    merged = apply_overrides(
        plan,
        {"stages": {"outline": {"effort": "medium"}}},
        catalog=catalog,
    )

    # model stays as the plan had it; only effort changes.
    assert merged.stage("outline").model == "opus"
    assert merged.stage("outline").effort == "medium"


def test_apply_overrides_rejects_unknown_stage():
    plan, catalog = _plan_and_catalog()

    with pytest.raises(ConfigError, match="unknown model-plan stage"):
        apply_overrides(plan, {"stages": {"publish": {"model": "opus"}}}, catalog=catalog)


def test_apply_overrides_rejects_unknown_model():
    plan, catalog = _plan_and_catalog()

    with pytest.raises(ConfigError, match="unknown model"):
        apply_overrides(plan, {"stages": {"qa": {"model": "not-real"}}}, catalog=catalog)


def test_apply_overrides_rejects_unknown_provider():
    plan, catalog = _plan_and_catalog()

    with pytest.raises(ConfigError, match="unknown provider"):
        apply_overrides(plan, {"stages": {"qa": {"provider": "not-real"}}}, catalog=catalog)


def test_apply_overrides_rejects_unknown_stage_override_keys():
    plan, catalog = _plan_and_catalog()

    with pytest.raises(ConfigError, match="unknown stage-override key"):
        apply_overrides(plan, {"stages": {"qa": {"modle": "opus"}}}, catalog=catalog)


def test_apply_overrides_with_empty_overrides_returns_equivalent_plan():
    plan, catalog = _plan_and_catalog()

    merged = apply_overrides(plan, {}, catalog=catalog)

    assert merged == plan


def test_apply_overrides_lenient_applies_valid_stages_and_reports_invalid_ones():
    plan, catalog = _plan_and_catalog()

    effective, errors = apply_overrides_lenient(
        plan,
        {
            "stages": {
                "outline": {"effort": "medium"},
                "qa": {"model": "not-real"},
            }
        },
        catalog=catalog,
    )

    # Valid stage override applied.
    assert effective.stage("outline").effort == "medium"
    assert effective.stage("outline").model == "opus"
    # Invalid stage override reported, and that stage keeps its prior value.
    assert set(errors) == {"qa"}
    assert "not-real" in errors["qa"]
    assert effective.stage("qa").model == "sonnet"


def test_apply_overrides_lenient_all_valid_returns_no_errors():
    plan, catalog = _plan_and_catalog()

    effective, errors = apply_overrides_lenient(
        plan,
        {"stages": {"qa": {"model": "opus", "effort": "low"}}},
        catalog=catalog,
    )

    assert errors == {}
    assert effective.stage("qa").model == "opus"
    assert effective.stage("qa").effort == "low"


def test_apply_overrides_lenient_all_invalid_returns_errors_for_each_and_unchanged_plan():
    plan, catalog = _plan_and_catalog()

    effective, errors = apply_overrides_lenient(
        plan,
        {
            "stages": {
                "outline": {"model": "not-real"},
                "qa": {"provider": "not-real"},
            }
        },
        catalog=catalog,
    )

    assert set(errors) == {"outline", "qa"}
    assert effective == plan


def test_apply_overrides_lenient_with_empty_overrides_returns_equivalent_plan_and_no_errors():
    plan, catalog = _plan_and_catalog()

    effective, errors = apply_overrides_lenient(plan, {}, catalog=catalog)

    assert errors == {}
    assert effective == plan


def test_apply_overrides_lenient_degrades_unknown_key_to_stage_error():
    plan, catalog = _plan_and_catalog()

    effective, errors = apply_overrides_lenient(
        plan, {"stages": {"qa": {"modle": "opus"}}}, catalog=catalog
    )

    assert "qa" in errors and "modle" in errors["qa"]
    assert effective.stage("qa").model == "sonnet"


def test_apply_overrides_lenient_rejects_non_table_stages():
    plan, catalog = _plan_and_catalog()

    with pytest.raises(ConfigError, match="overrides\\['stages'\\]"):
        apply_overrides_lenient(plan, {"stages": "nope"}, catalog=catalog)


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
