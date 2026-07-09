from pathlib import Path

import pytest

from education_pipeline import (
    DEFAULT_STAGE_RECOMMENDATIONS,
    STAGE_ORDER,
    ConfigError,
    load_model_catalog,
    load_model_plan,
    parse_model_catalog,
    parse_model_plan,
)


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
