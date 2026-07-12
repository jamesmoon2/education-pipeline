"""Configuration parsing for model catalogs and stage model plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import json
import tomllib


STAGE_ORDER = (
    "profile",
    "spec",
    "outline",
    "draft",
    "qa",
    "repair",
    "finalize",
    "export",
)

DEFAULT_STAGE_RECOMMENDATIONS = MappingProxyType(
    {
        "profile": "fast_or_strong_summary",
        "spec": "strong_contract_design",
        "outline": "premium_reasoning",
        "draft": "strong_longform_generation",
        "qa": "fast_cheap_check",
        "repair": "strong_or_premium_repair",
        "finalize": "local_only",
        "export": "local_only",
    }
)


class ConfigError(ValueError):
    """Raised when a model catalog or model plan is invalid."""


@dataclass(frozen=True)
class ModelOption:
    """A model/runtime option exposed by a provider catalog."""

    id: str
    label: str
    description: str = ""
    quality: str | None = None
    default_effort: str | None = None
    argv_model: str | None = None
    extra_args: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Provider:
    """A configured model provider/runtime."""

    id: str
    label: str
    description: str = ""
    models: Mapping[str, ModelOption] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCatalog:
    """Provider catalog loaded from ``model-catalog.toml``."""

    providers: Mapping[str, Provider]

    def require_provider(self, provider_id: str) -> Provider:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.providers)) or "none"
            raise ConfigError(
                f"model plan references unknown provider {provider_id!r}; known providers: {known}"
            ) from exc


@dataclass(frozen=True)
class StageModelPlan:
    """Effective model settings for one pipeline stage."""

    stage: str
    recommendation: str
    model: str | None = None
    effort: str | None = None
    provider: str | None = None


@dataclass(frozen=True)
class ModelPlan:
    """Stage-by-stage model plan loaded from ``model-plan.toml``."""

    provider: str
    stages: Mapping[str, StageModelPlan]

    def stage(self, stage_name: str) -> StageModelPlan:
        try:
            return self.stages[stage_name]
        except KeyError as exc:
            known = ", ".join(STAGE_ORDER)
            raise ConfigError(f"unknown stage {stage_name!r}; known stages: {known}") from exc


def load_model_catalog(path: str | Path) -> ModelCatalog:
    """Load and validate a model catalog TOML file."""

    data = _load_toml(path)
    return parse_model_catalog(data)


def load_model_plan(path: str | Path, catalog: ModelCatalog | None = None) -> ModelPlan:
    """Load and validate a model plan TOML file."""

    data = _load_toml(path)
    return parse_model_plan(data, catalog=catalog)


def parse_model_catalog(data: Mapping[str, Any]) -> ModelCatalog:
    providers_data = data.get("providers")
    if not isinstance(providers_data, list) or not providers_data:
        raise ConfigError("model catalog must define at least one [[providers]] table")

    providers: dict[str, Provider] = {}
    for index, raw_provider in enumerate(providers_data, start=1):
        if not isinstance(raw_provider, Mapping):
            raise ConfigError(f"provider entry #{index} must be a table")

        provider_id = _required_string(raw_provider, "id", f"provider entry #{index}")
        if provider_id in providers:
            raise ConfigError(f"duplicate provider id {provider_id!r}")

        label = _optional_string(raw_provider, "label", provider_id, f"provider {provider_id!r}")
        description = _optional_string(raw_provider, "description", "", f"provider {provider_id!r}")
        models = _parse_models(raw_provider, provider_id)
        providers[provider_id] = Provider(
            id=provider_id,
            label=label,
            description=description,
            models=models,
        )

    return ModelCatalog(providers=providers)


def parse_model_plan(
    data: Mapping[str, Any],
    catalog: ModelCatalog | None = None,
) -> ModelPlan:
    provider_id = _required_string(data, "provider", "model plan")
    base_provider = catalog.require_provider(provider_id) if catalog is not None else None

    raw_stages = data.get("stages", {})
    if not isinstance(raw_stages, Mapping):
        raise ConfigError("model plan [stages] must be a table")

    unknown_stages = sorted(set(raw_stages) - set(STAGE_ORDER))
    if unknown_stages:
        known = ", ".join(STAGE_ORDER)
        unknown = ", ".join(unknown_stages)
        raise ConfigError(f"unknown model-plan stage(s): {unknown}; known stages: {known}")

    stages: dict[str, StageModelPlan] = {}
    for stage_name in STAGE_ORDER:
        raw_stage = raw_stages.get(stage_name, {})
        if not isinstance(raw_stage, Mapping):
            raise ConfigError(f"model plan stage {stage_name!r} must be a table")

        recommendation = _optional_string(
            raw_stage,
            "recommendation",
            DEFAULT_STAGE_RECOMMENDATIONS[stage_name],
            f"stage {stage_name!r}",
        )
        model = _optional_string(raw_stage, "model", None, f"stage {stage_name!r}")
        effort = _optional_string(raw_stage, "effort", None, f"stage {stage_name!r}")
        stage_provider = _optional_string(raw_stage, "provider", provider_id, f"stage {stage_name!r}")

        active_provider = base_provider
        if catalog is not None and stage_provider != provider_id:
            active_provider = catalog.require_provider(stage_provider)

        if active_provider is not None and model is not None and active_provider.models and model not in active_provider.models:
            known = ", ".join(sorted(active_provider.models))
            raise ConfigError(
                f"stage {stage_name!r} references unknown model {model!r} "
                f"for provider {stage_provider!r}; known models: {known}"
            )

        stages[stage_name] = StageModelPlan(
            stage=stage_name,
            provider=stage_provider,
            model=model,
            effort=effort,
            recommendation=recommendation,
        )

    return ModelPlan(provider=provider_id, stages=stages)


def emit_model_plan_toml(plan: ModelPlan) -> str:
    """Serialize a ModelPlan back to model-plan.toml. Narrow by design: this
    schema only ever holds strings, so JSON string escaping (valid TOML
    basic-string syntax) covers every value."""

    def q(value: str) -> str:
        return json.dumps(value)

    lines = [f"provider = {q(plan.provider)}", ""]
    for stage_name in STAGE_ORDER:
        stage = plan.stages[stage_name]
        body: list[str] = []
        if stage.provider is not None and stage.provider != plan.provider:
            body.append(f"provider = {q(stage.provider)}")
        if stage.model is not None:
            body.append(f"model = {q(stage.model)}")
        if stage.effort is not None:
            body.append(f"effort = {q(stage.effort)}")
        if stage.recommendation != DEFAULT_STAGE_RECOMMENDATIONS[stage_name]:
            body.append(f"recommendation = {q(stage.recommendation)}")
        if body:
            lines.append(f"[stages.{stage_name}]")
            lines.extend(body)
            lines.append("")
    return "\n".join(lines)


def apply_overrides(
    plan: ModelPlan,
    overrides: Mapping[str, Any],
    catalog: ModelCatalog | None = None,
) -> ModelPlan:
    """Overlay sparse per-run overrides onto a plan. Implementation: rebuild the
    raw mapping (provider + per-stage dicts from `plan`), deep-merge
    overrides["stages"], and re-run parse_model_plan(..., catalog=catalog) so
    every existing validation rule applies to the merged result."""

    raw: dict[str, Any] = {"provider": plan.provider, "stages": {}}
    for stage_name in STAGE_ORDER:
        stage = plan.stages[stage_name]
        body: dict[str, Any] = {}
        if stage.provider is not None and stage.provider != plan.provider:
            body["provider"] = stage.provider
        if stage.model is not None:
            body["model"] = stage.model
        if stage.effort is not None:
            body["effort"] = stage.effort
        if stage.recommendation != DEFAULT_STAGE_RECOMMENDATIONS[stage_name]:
            body["recommendation"] = stage.recommendation
        if body:
            raw["stages"][stage_name] = body

    override_stages = overrides.get("stages", {})
    if not isinstance(override_stages, Mapping):
        raise ConfigError("overrides['stages'] must be a table")

    for stage_name, stage_override in override_stages.items():
        if not isinstance(stage_override, Mapping):
            raise ConfigError(f"override for stage {stage_name!r} must be a table")
        merged_stage = dict(raw["stages"].get(stage_name, {}))
        merged_stage.update(stage_override)
        raw["stages"][stage_name] = merged_stage

    return parse_model_plan(raw, catalog=catalog)


REASONING_STAGES = frozenset({"spec", "outline", "repair"})
_QUALITY_RANK = {"fast": 0, "strong": 1, "premium": 2}


def weak_stage_warning(catalog: ModelCatalog, stage_plan: StageModelPlan) -> str | None:
    """A human-readable warning when a below-'strong' model is chosen for a reasoning-heavy stage."""

    if stage_plan.stage not in REASONING_STAGES or stage_plan.provider is None or stage_plan.model is None:
        return None
    provider = catalog.providers.get(stage_plan.provider)
    option = provider.models.get(stage_plan.model) if provider is not None else None
    if option is None or option.quality is None:
        return None
    if _QUALITY_RANK.get(option.quality, _QUALITY_RANK["strong"]) < _QUALITY_RANK["strong"]:
        return (
            f"stage {stage_plan.stage!r} is reasoning-heavy; "
            f"{option.label} is rated {option.quality!r} — consider a strong or premium model"
        )
    return None


def _load_toml(path: str | Path) -> Mapping[str, Any]:
    config_path = Path(path)
    try:
        with config_path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc


def _parse_models(raw_provider: Mapping[str, Any], provider_id: str) -> Mapping[str, ModelOption]:
    raw_models = raw_provider.get("models", [])
    if raw_models is None:
        raw_models = []
    if not isinstance(raw_models, list):
        raise ConfigError(f"provider {provider_id!r} models must use [[providers.models]] tables")

    models: dict[str, ModelOption] = {}
    for index, raw_model in enumerate(raw_models, start=1):
        if not isinstance(raw_model, Mapping):
            raise ConfigError(f"model entry #{index} for provider {provider_id!r} must be a table")

        context = f"model entry #{index} for provider {provider_id!r}"
        model_id = _required_string(raw_model, "id", context)
        if model_id in models:
            raise ConfigError(f"duplicate model id {model_id!r} for provider {provider_id!r}")

        label = _optional_string(raw_model, "label", model_id, context)
        description = _optional_string(raw_model, "description", "", context)
        quality = _optional_string(raw_model, "quality", None, context)
        default_effort = _optional_string(raw_model, "default_effort", None, context)
        argv_model = _optional_string(raw_model, "argv_model", None, context)
        extra_args = _parse_extra_args(raw_model, context)
        reserved = {
            "id",
            "label",
            "description",
            "quality",
            "default_effort",
            "argv_model",
            "extra_args",
        }
        metadata = {key: value for key, value in raw_model.items() if key not in reserved}
        models[model_id] = ModelOption(
            id=model_id,
            label=label,
            description=description,
            quality=quality,
            default_effort=default_effort,
            argv_model=argv_model,
            extra_args=extra_args,
            metadata=metadata,
        )

    return models


def _required_string(data: Mapping[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} must define non-empty string {key!r}")
    return value


def _optional_string(
    data: Mapping[str, Any],
    key: str,
    default: str | None,
    context: str,
) -> str | None:
    if key not in data:
        return default
    value = data[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} field {key!r} must be a non-empty string when set")
    return value


def _parse_extra_args(data: Mapping[str, Any], context: str) -> tuple[str, ...]:
    value = data.get("extra_args")
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{context} field 'extra_args' must be a list of strings")
    return tuple(value)
