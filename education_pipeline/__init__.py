"""Public package for local-first education guide generation."""

from education_pipeline.config import (
    DEFAULT_STAGE_RECOMMENDATIONS,
    STAGE_ORDER,
    ConfigError,
    ModelCatalog,
    ModelOption,
    ModelPlan,
    Provider,
    StageModelPlan,
    load_model_catalog,
    load_model_plan,
    parse_model_catalog,
    parse_model_plan,
)

__all__ = [
    "DEFAULT_STAGE_RECOMMENDATIONS",
    "STAGE_ORDER",
    "ConfigError",
    "ModelCatalog",
    "ModelOption",
    "ModelPlan",
    "Provider",
    "StageModelPlan",
    "load_model_catalog",
    "load_model_plan",
    "parse_model_catalog",
    "parse_model_plan",
]
