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
    OPTIONAL_STAGES,
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
    assert SUPPORTED_STAGES == REQUIRED_STAGES + OPTIONAL_STAGES
    assert "audit" in STAGE_ORDER
    assert "audit" not in REASONING_STAGES


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


def test_loads_example_catalog_and_plan() -> None:
    root = Path(__file__).resolve().parents[1]

    catalog = load_model_catalog(root / "config" / "model-catalog.example.toml")
    plan = load_model_plan(root / "config" / "model-plan.example.toml", catalog=catalog)

    assert set(catalog.providers) == {"manual", "claude-code", "codex"}
    assert catalog.providers["manual"].models["prompt-only"].quality == "manual"
    assert plan.provider == "manual"
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
