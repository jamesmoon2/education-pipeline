from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
import json
from pathlib import Path
import hashlib
import tomllib

import pytest

from education_pipeline import (
    PROFILE_SCHEMA_VERSION,
    ConfigError,
    LearnerPreferences,
    LearnerPrivacy,
    LearnerProfile,
    load_learner_profile,
    parse_learner_profile,
    render_profile_prompt_context,
    render_profile_public_summary,
)
from education_pipeline.privacy import (
    ProfileWarning,
    SensitivityTier,
    canonical_profile_sha256,
    canonical_profile_toml_bytes,
    normalize_private_value,
    private_value_fingerprint,
    profile_field_sensitivity,
    profile_private_values,
    profile_summary_warnings,
    profile_to_dict,
)


def test_loads_example_learner_profile() -> None:
    root = Path(__file__).resolve().parents[1]

    profile = load_learner_profile(root / "config" / "learner-profile.example.toml")

    assert isinstance(profile, LearnerProfile)
    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.id == "public-beginner-analytics"
    assert profile.target_learner == "public audience"
    assert profile.professional_experience == "entry-level operations or administrative work"
    assert profile.adjacent_domains == ("spreadsheet formulas", "basic chart reading")
    assert profile.learning_goals == (
        "understand core analytics concepts",
        "practice interpreting simple datasets",
    )
    assert isinstance(profile.learning_preferences, LearnerPreferences)
    assert profile.learning_preferences.explanation_style == "visual-first with concise text"
    assert profile.learning_preferences.preferred_modalities == (
        "visual",
        "hands-on practice",
        "reading",
    )
    assert profile.learning_preferences.preferred_visual_aids == (
        "flowcharts",
        "concept maps",
        "comparison tables",
        "annotated examples",
    )
    assert profile.learning_preferences.diagram_frequency == (
        "frequent for new concepts and multi-step processes"
    )
    assert profile.learning_preferences.worked_example_preference == "before abstract theory"
    assert profile.localization.locale == "en-US"
    assert profile.privacy.private_by_default is True
    assert profile.privacy.include_in_published_output is False
    assert profile.privacy.publishable_summary == (
        "Beginner public audience seeking a practical analytics foundation."
    )
    assert profile.can_publish_summary is False
    assert profile.metadata["source"] == "synthetic public example"


def test_minimal_profile_defaults_to_private_local_profile() -> None:
    profile = parse_learner_profile(
        {
            "id": "cohort-a",
            "target_learner": "team cohort",
        }
    )

    assert profile.id == "cohort-a"
    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.adjacent_domains == ()
    assert profile.learning_goals == ()
    assert profile.professional_experience is None
    assert profile.learning_preferences.preferred_modalities == ()
    assert profile.learning_preferences.preferred_visual_aids == ()
    assert profile.learning_preferences.explanation_style is None
    assert profile.localization.locale is None
    assert profile.privacy.private_by_default is True
    assert profile.privacy.include_in_published_output is False
    assert profile.privacy.publishable_summary is None
    assert profile.can_publish_summary is False


def test_profile_allows_explicit_publishable_summary() -> None:
    profile = parse_learner_profile(
        {
            "id": "public-summary",
            "target_learner": "public audience",
            "privacy": {
                "include_in_published_output": True,
                "publishable_summary": "Public audience with beginner-level context.",
            },
        }
    )

    assert profile.can_publish_summary is True


def test_profile_parses_learning_preferences() -> None:
    profile = parse_learner_profile(
        {
            "id": "visual-learner",
            "target_learner": "individual",
            "learning_preferences": {
                "preferred_modalities": ["visual", "hands-on"],
                "explanation_style": "diagram-led",
                "preferred_visual_aids": ["flowcharts", "timelines"],
                "diagram_frequency": "frequent",
                "interaction_style": "guided sequence",
                "practice_style": ["worked scenarios"],
                "feedback_style": "direct correction with rationale",
                "worked_example_preference": "side-by-side with theory",
                "common_sticking_points": ["multi-step branching logic"],
                "attention_constraints": ["short sessions"],
                "review_style": ["quick recap", "spaced review"],
            },
        }
    )

    preferences = profile.learning_preferences

    assert preferences.preferred_modalities == ("visual", "hands-on")
    assert preferences.explanation_style == "diagram-led"
    assert preferences.preferred_visual_aids == ("flowcharts", "timelines")
    assert preferences.diagram_frequency == "frequent"
    assert preferences.interaction_style == "guided sequence"
    assert preferences.practice_style == ("worked scenarios",)
    assert preferences.feedback_style == "direct correction with rationale"
    assert preferences.worked_example_preference == "side-by-side with theory"
    assert preferences.common_sticking_points == ("multi-step branching logic",)
    assert preferences.attention_constraints == ("short sessions",)
    assert preferences.review_style == ("quick recap", "spaced review")


def test_profile_rejects_publishing_without_summary() -> None:
    with pytest.raises(ConfigError, match="requires a non-empty privacy.publishable_summary"):
        parse_learner_profile(
            {
                "id": "unsafe",
                "target_learner": "individual",
                "privacy": {"include_in_published_output": True},
            }
        )


def test_profile_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ConfigError, match="unknown learner profile field"):
        parse_learner_profile(
            {
                "id": "typo",
                "target_learner": "public audience",
                "learning_goal": "singular typo",
            }
        )


def test_profile_rejects_unknown_nested_fields() -> None:
    with pytest.raises(ConfigError, match="unknown privacy field"):
        parse_learner_profile(
            {
                "id": "nested-typo",
                "target_learner": "public audience",
                "privacy": {"publish_summary": True},
            }
        )


def test_profile_rejects_unknown_learning_preference_fields() -> None:
    with pytest.raises(ConfigError, match="unknown learning_preferences field"):
        parse_learner_profile(
            {
                "id": "nested-learning-typo",
                "target_learner": "public audience",
                "learning_preferences": {"visual_aids": ["flowcharts"]},
            }
        )


def test_profile_rejects_non_string_lists() -> None:
    with pytest.raises(ConfigError, match="item #2 must be a non-empty string"):
        parse_learner_profile(
            {
                "id": "bad-list",
                "target_learner": "public audience",
                "learning_goals": ["valid", ""],
            }
        )


def test_profile_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ConfigError, match="unsupported learner profile schema_version"):
        parse_learner_profile(
            {
                "schema_version": 2,
                "id": "future",
                "target_learner": "public audience",
            }
        )


def test_profile_prompt_context_renders_private_local_context() -> None:
    root = Path(__file__).resolve().parents[1]
    profile = load_learner_profile(root / "config" / "learner-profile.example.toml")

    context = render_profile_prompt_context(profile)

    assert context.startswith("# Learner Profile Context\n")
    assert "Use this as learner context, not as authority" in context
    assert "- Target learner: public audience" in context
    assert "- Professional experience: entry-level operations or administrative work" in context
    assert "- Preferred visual aids: flowcharts, concept maps, comparison tables" in context
    assert "- Diagram frequency: frequent for new concepts and multi-step processes" in context
    assert "- Locale: en-US" in context
    assert "- Private by default: yes" in context
    assert "- Include profile in published output: no" in context
    assert "- Publishable summary: Beginner public audience seeking a practical analytics foundation." in context
    assert "synthetic public example" not in context
    assert "None" not in context


def test_profile_prompt_context_omits_empty_optional_sections() -> None:
    profile = parse_learner_profile({"id": "minimal", "target_learner": "team cohort"})

    context = render_profile_prompt_context(profile)

    assert "- Profile id: minimal" in context
    assert "- Target learner: team cohort" in context
    assert "## Learning Preferences" not in context
    assert "## Localization" not in context
    assert "- Publishable summary:" not in context
    assert "None" not in context


def test_profile_public_summary_requires_explicit_publication() -> None:
    private_profile = parse_learner_profile(
        {
            "id": "private-summary",
            "target_learner": "individual",
            "privacy": {"publishable_summary": "Should remain private without opt-in."},
        }
    )
    public_profile = parse_learner_profile(
        {
            "id": "public-summary",
            "target_learner": "public audience",
            "privacy": {
                "include_in_published_output": True,
                "publishable_summary": "Public audience with beginner-level context.",
            },
        }
    )

    assert render_profile_public_summary(private_profile) is None
    assert render_profile_public_summary(public_profile) == (
        "Public audience with beginner-level context."
    )


def test_profile_field_sensitivity_classifies_every_dataclass_leaf() -> None:
    expected_paths = {
        "schema_version",
        "id",
        "target_learner",
        "prior_education",
        "prior_experience",
        "professional_experience",
        "current_skill_level",
        "adjacent_domains",
        "learning_goals",
        "preferred_examples",
        "examples_to_avoid",
        "math_comfort",
        "reading_level",
        "pace",
        "desired_depth",
        "time_budget",
        "assessment_styles",
        "accessibility_constraints",
        "tone_preference",
        "sensitive_areas",
        "learning_preferences.preferred_modalities",
        "learning_preferences.explanation_style",
        "learning_preferences.preferred_visual_aids",
        "learning_preferences.diagram_frequency",
        "learning_preferences.interaction_style",
        "learning_preferences.practice_style",
        "learning_preferences.feedback_style",
        "learning_preferences.worked_example_preference",
        "learning_preferences.common_sticking_points",
        "learning_preferences.attention_constraints",
        "learning_preferences.review_style",
        "localization.jurisdiction",
        "localization.locale",
        "localization.units",
        "localization.language_register",
        "privacy.private_by_default",
        "privacy.include_in_published_output",
        "privacy.publishable_summary",
        "metadata.*",
    }

    sensitivity = profile_field_sensitivity()

    def leaf_paths(value: object, prefix: str = "") -> set[str]:
        paths: set[str] = set()
        for item in fields(value):
            path = f"{prefix}.{item.name}" if prefix else item.name
            child = getattr(value, item.name)
            if is_dataclass(child):
                paths.update(leaf_paths(child, path))
            elif path == "metadata":
                paths.add("metadata.*")
            else:
                paths.add(path)
        return paths

    assert isinstance(sensitivity["target_learner"], SensitivityTier)
    assert set(sensitivity) == expected_paths
    assert set(sensitivity) == leaf_paths(LearnerProfile(id="test", target_learner="test"))
    assert sensitivity["target_learner"] == SensitivityTier.HIGH
    assert sensitivity["professional_experience"] == SensitivityTier.HIGH
    assert sensitivity["metadata.*"] == SensitivityTier.HIGH
    assert sensitivity["learning_goals"] == SensitivityTier.MEDIUM
    assert sensitivity["learning_preferences.attention_constraints"] == SensitivityTier.MEDIUM
    assert sensitivity["privacy.publishable_summary"] == SensitivityTier.LOW
    with pytest.raises(TypeError):
        sensitivity["id"] = SensitivityTier.LOW  # type: ignore[index]


def test_profile_private_values_recurses_metadata_normalizes_and_deduplicates() -> None:
    profile = parse_learner_profile(
        {
            "id": "  Cohort   Alpha ",
            "target_learner": "  Named   Learner Group ",
            "learning_goals": ["Master   Event Sourcing", "named learner group"],
            "math_comfort": "Advanced",
            "privacy": {
                "publishable_summary": "Named Learner Group studying Master Event Sourcing.",
            },
            "metadata": {
                "nested": {
                    "organization": "  Secret   Orchard  ",
                    "details": ["Internal Project Cedar", {"duplicate": "secret orchard"}],
                },
                "count": 7,
                "enabled": True,
            },
        }
    )

    assert profile_private_values(profile) == (
        "cohort alpha",
        "named learner group",
        "master event sourcing",
        "secret orchard",
        "internal project cedar",
    )


def test_profile_private_values_excludes_short_generic_low_risk_and_summary_values() -> None:
    profile = parse_learner_profile(
        {
            "id": "user",
            "target_learner": "student",
            "prior_education": "N/A",
            "learning_goals": ["SQL"],
            "math_comfort": "Advanced",
            "pace": "Self-paced",
            "privacy": {
                "publishable_summary": "Unique publishable summary only",
            },
            "metadata": {"generic": "unknown", "short": "abcd"},
        }
    )

    assert profile_private_values(profile) == ()
    assert normalize_private_value("  Secret\n Orchard ") == "secret orchard"
    assert private_value_fingerprint("  Secret\n Orchard ") == hashlib.sha256(
        b"secret orchard"
    ).hexdigest()[:12]


def test_profile_summary_warnings_are_safe_field_path_fingerprint_only() -> None:
    profile = parse_learner_profile(
        {
            "id": "cohort-alpha",
            "target_learner": "Secret Orchard Fellows",
            "learning_goals": ["Master event sourcing"],
            "privacy": {
                "include_in_published_output": True,
                "publishable_summary": (
                    "SECRET ORCHARD FELLOWS will master   event sourcing through examples."
                ),
            },
        }
    )

    warnings = profile_summary_warnings(profile)

    assert warnings == (
        ProfileWarning(
            code="privacy.summary_contains_private_value",
            field_path="target_learner",
            fingerprint=private_value_fingerprint("Secret Orchard Fellows"),
        ),
        ProfileWarning(
            code="privacy.summary_contains_private_value",
            field_path="learning_goals",
            fingerprint=private_value_fingerprint("Master event sourcing"),
        ),
    )
    rendered = repr(warnings).casefold()
    assert "secret orchard fellows" not in rendered
    assert "master event sourcing" not in rendered
    assert all(len(item.fingerprint) == 12 for item in warnings)


def test_profile_summary_warnings_require_publication_opt_in() -> None:
    profile = parse_learner_profile(
        {
            "id": "cohort-alpha",
            "target_learner": "Secret Orchard Fellows",
            "privacy": {"publishable_summary": "Secret Orchard Fellows"},
        }
    )

    assert profile_summary_warnings(profile) == ()


@pytest.mark.parametrize(
    ("metadata", "path"),
    [
        ({"bad": None}, "metadata.*"),
        ({"bad": float("nan")}, "metadata.*"),
        ({"bad": float("inf")}, "metadata.*"),
        ({"bad": b"bytes"}, "metadata.*"),
        ({"bad": date(2026, 7, 13)}, "metadata.*"),
        ({"bad": time(12, 30)}, "metadata.*"),
        ({"bad": datetime(2026, 7, 13, 12, 30)}, "metadata.*"),
        ({"bad": 2**63}, "metadata.*"),
        ({"bad": ("tuple",)}, "metadata.*"),
        ({"bad": {7: "non-string key"}}, "metadata.*"),
        ({"nested": [{"bad": object()}]}, "metadata.*[0]"),
    ],
)
def test_profile_rejects_metadata_outside_json_toml_intersection(
    metadata: object,
    path: str,
) -> None:
    with pytest.raises(ConfigError) as exc_info:
        parse_learner_profile(
            {
                "id": "bad-metadata",
                "target_learner": "cohort",
                "metadata": metadata,
            }
        )
    assert path in str(exc_info.value)


def test_profile_codec_revalidates_directly_constructed_profile_metadata() -> None:
    profile = LearnerProfile(
        id="direct-profile",
        target_learner="cohort",
        metadata={"nested": {"bad": None}},
    )

    with pytest.raises(ConfigError, match=r"metadata\.\*"):
        canonical_profile_toml_bytes(profile)


def test_profile_mapping_toml_mapping_round_trip_is_deterministic() -> None:
    source = {
        "target_learner": "Data platform team",
        "id": "platform-team",
        "learning_goals": ["Understand event sourcing"],
        "learning_preferences": {
            "review_style": ["spaced review"],
            "preferred_modalities": ["visual"],
        },
        "metadata": {
            "cohort": {"region": "west", "number": 3},
            "flags": [True, False],
            "ratio": 1.25,
        },
    }

    canonical = canonical_profile_toml_bytes(source)
    reparsed = parse_learner_profile(tomllib.loads(canonical.decode("utf-8")))

    assert profile_to_dict(reparsed) == profile_to_dict(parse_learner_profile(source))
    json.dumps(profile_to_dict(reparsed))
    assert canonical_profile_toml_bytes(reparsed) == canonical
    assert canonical.endswith(b"\n")
    assert canonical_profile_sha256(reparsed) == hashlib.sha256(canonical).hexdigest()


def test_canonical_profile_bytes_ignore_equivalent_input_mapping_order() -> None:
    first = {
        "id": "ordered-profile",
        "target_learner": "Platform engineers",
        "metadata": {
            "zeta": {"second": 2, "first": 1},
            "alpha": ["one", {"right": False, "left": True}],
        },
        "privacy": {"private_by_default": True},
    }
    second = {
        "privacy": {"private_by_default": True},
        "metadata": {
            "alpha": ["one", {"left": True, "right": False}],
            "zeta": {"first": 1, "second": 2},
        },
        "target_learner": "Platform engineers",
        "id": "ordered-profile",
    }

    assert canonical_profile_toml_bytes(first) == canonical_profile_toml_bytes(second)


def test_metadata_diagnostics_and_warning_paths_never_expose_authored_keys() -> None:
    hostile_key = "SECRET-authored-metadata-key"
    with pytest.raises(ConfigError) as exc_info:
        parse_learner_profile(
            {
                "id": "unsafe-metadata",
                "target_learner": "cohort",
                "metadata": {hostile_key: object()},
            }
        )

    assert hostile_key not in str(exc_info.value)
    assert "metadata.*" in str(exc_info.value)

    profile = parse_learner_profile(
        {
            "id": "warning-paths",
            "target_learner": "cohort",
            "metadata": {
                hostile_key: [
                    {"SECOND-secret-key": "Protected Orchard Identifier"},
                ]
            },
            "privacy": {
                "include_in_published_output": True,
                "publishable_summary": "Protected Orchard Identifier",
            },
        }
    )

    assert profile_summary_warnings(profile) == (
        ProfileWarning(
            code="privacy.summary_contains_private_value",
            field_path="metadata.*[0]",
            fingerprint=private_value_fingerprint("Protected Orchard Identifier"),
        ),
    )
    assert hostile_key not in repr(profile_summary_warnings(profile))
    assert "SECOND-secret-key" not in repr(profile_summary_warnings(profile))


def test_canonical_profile_toml_escapes_del_in_values_and_keys() -> None:
    source = {
        "id": "del-profile",
        "target_learner": "Cohort\x7fName",
        "metadata": {"key\x7fsegment": "value\x7fsegment"},
    }

    canonical = canonical_profile_toml_bytes(source)
    decoded = canonical.decode("utf-8")
    reparsed = parse_learner_profile(tomllib.loads(decoded))

    assert "\x7f" not in decoded
    assert "\\u007f" in decoded.casefold()
    assert profile_to_dict(reparsed) == profile_to_dict(parse_learner_profile(source))


@pytest.mark.parametrize(
    "source",
    [
        {
            "id": "surrogate-value",
            "target_learner": "bad-\ud800-value",
        },
        {
            "id": "surrogate-key",
            "target_learner": "cohort",
            "metadata": {"bad-\udfff-key": "safe value"},
        },
    ],
)
def test_canonical_profile_toml_rejects_lone_surrogates_safely(source: dict) -> None:
    with pytest.raises(ConfigError, match="Unicode scalar") as exc_info:
        canonical_profile_toml_bytes(source)

    assert not isinstance(exc_info.value.__cause__, UnicodeEncodeError)


def test_metadata_rejects_hostile_numeric_subclasses_without_rendering_them() -> None:
    class HostileInt(int):
        def __str__(self) -> str:
            raise AssertionError("must not render hostile int")

    class HostileFloat(float):
        def __repr__(self) -> str:
            raise AssertionError("must not render hostile float")

    for value in (HostileInt(7), HostileFloat(1.25)):
        with pytest.raises(ConfigError, match=r"metadata\.\*"):
            parse_learner_profile(
                {
                    "id": "hostile-number",
                    "target_learner": "cohort",
                    "metadata": {"caller-key": value},
                }
            )


def test_direct_profile_metadata_cannot_bypass_tuple_or_dataclass_restrictions() -> None:
    @dataclass(frozen=True)
    class HostileMetadata:
        value: str

    for metadata in (
        {"bad": ("tuple",)},
        {"bad": HostileMetadata("must not be projected")},
    ):
        profile = LearnerProfile(
            id="direct-profile",
            target_learner="cohort",
            metadata=metadata,
        )
        with pytest.raises(ConfigError, match=r"metadata\.\*"):
            profile_to_dict(profile)


@pytest.mark.parametrize(
    "source",
    [
        {7: "bad", "id": "bad-key", "target_learner": "cohort"},
        {"id": "bad-key", "target_learner": "cohort", "localization": {7: "bad"}},
        {
            "id": "bad-key",
            "target_learner": "cohort",
            "learning_preferences": {7: "bad"},
        },
        {"id": "bad-key", "target_learner": "cohort", "privacy": {7: "bad"}},
    ],
)
def test_profile_tables_reject_non_string_keys_with_safe_config_error(source: dict) -> None:
    with pytest.raises(ConfigError, match="string keys") as exc_info:
        parse_learner_profile(source)

    assert "7" not in str(exc_info.value)


def test_parsed_metadata_is_deeply_frozen_and_projects_back_to_json_shape() -> None:
    profile = parse_learner_profile(
        {
            "id": "frozen-metadata",
            "target_learner": "cohort",
            "metadata": {
                "nested": {"value": "fixed"},
                "items": ["first", {"value": "second"}],
            },
        }
    )
    canonical_before = canonical_profile_toml_bytes(profile)

    with pytest.raises(TypeError):
        profile.metadata["new"] = "mutation"  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.metadata["nested"]["value"] = "mutation"  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.metadata["items"][0] = "mutation"  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.metadata["items"][1]["value"] = "mutation"  # type: ignore[index]

    assert canonical_profile_toml_bytes(profile) == canonical_before
    assert profile_to_dict(profile)["metadata"] == {
        "nested": {"value": "fixed"},
        "items": ["first", {"value": "second"}],
    }


def test_canonical_profile_toml_roundtrips_valid_non_bmp_unicode() -> None:
    source = {
        "id": "emoji-profile",
        "target_learner": "Engineering cohort 😀",
        "learning_goals": ["Launch safely 🚀"],
        "metadata": {
            "quoted emoji 😀 key": "Astronomy learners 🌌",
            "nested": {"another 🚀 key": ["Practice 🧭"]},
        },
    }

    canonical = canonical_profile_toml_bytes(source)
    reparsed = parse_learner_profile(tomllib.loads(canonical.decode("utf-8")))

    assert "😀" in canonical.decode("utf-8")
    assert "🚀" in canonical.decode("utf-8")
    assert profile_to_dict(reparsed) == profile_to_dict(parse_learner_profile(source))


@pytest.mark.parametrize(
    ("profile", "operation"),
    [
        (
            LearnerProfile(id="protected-surrogate", target_learner="bad-\ud800-target"),
            profile_private_values,
        ),
        (
            LearnerProfile(
                id="summary-surrogate",
                target_learner="cohort",
                privacy=LearnerPrivacy(
                    include_in_published_output=True,
                    publishable_summary="bad-\udfff-summary",
                ),
            ),
            profile_summary_warnings,
        ),
        (
            LearnerProfile(
                id="metadata-surrogate",
                target_learner="cohort",
                metadata={"safe-key": {"nested": ["bad-\ud800-metadata"]}},
            ),
            profile_private_values,
        ),
    ],
)
def test_privacy_operations_reject_lone_surrogates_before_fingerprinting(
    profile: LearnerProfile,
    operation: object,
) -> None:
    with pytest.raises(ConfigError, match="Unicode scalar") as exc_info:
        operation(profile)  # type: ignore[operator]

    assert not isinstance(exc_info.value.__cause__, UnicodeEncodeError)
