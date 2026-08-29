"""The one shared lone-surrogate scan, pinned against the scans it replaces.

``education_pipeline.text_scalars`` collapses four identical per-character
``0xD800 <= ord(character) <= 0xDFFF`` loops (guide validation's detector and
replacer, ``profiles._validate_unicode_scalar``, ``privacy._require_unicode_scalar``)
into one compiled character class. Python ``str`` stores lone surrogates as
ordinary code points and ``re`` matches them positionally, so the class is
exactly the old ordinal test -- these tests hold that claim to the letter.
"""

from __future__ import annotations

import pytest

from education_pipeline.config import ConfigError
from education_pipeline.profiles import LearnerProfile
from education_pipeline.privacy import normalize_private_value, profile_private_values
from education_pipeline.text_scalars import (
    SURROGATE_REPLACEMENT,
    has_surrogates,
    replace_surrogates,
)

REPLACEMENT = "\N{REPLACEMENT CHARACTER}"

#: The boundary of the surrogate block, plus one astral scalar that is encoded
#: as a surrogate *pair* in UTF-16 but is a single code point in a Python str.
BOUNDARY_CODE_POINTS = (0xD7FF, 0xD800, 0xDBFF, 0xDC00, 0xDFFF, 0xE000, 0x1F600)


def reference_has_surrogates(value: str) -> bool:
    """The per-character scan that lived in four modules."""

    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def reference_replace_surrogates(value: str) -> str:
    """The per-character replacement that lived in ``guides/validation.py``."""

    return "".join(
        REPLACEMENT if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in value
    )


def _samples() -> list[str]:
    values = ["", "plain text", "\N{REPLACEMENT CHARACTER}", "\U0001F600 astral"]
    for code_point in BOUNDARY_CODE_POINTS:
        character = chr(code_point)
        values.extend(
            [
                character,
                character * 3,
                f"a{character}b",
                f"{character}leading",
                f"trailing{character}",
                f"\U0001F600{character}é",
            ]
        )
    values.append("".join(chr(code_point) for code_point in BOUNDARY_CODE_POINTS))
    values.append("mixed \ud800 and \udfff and \ud7ff and \ue000 text")
    return values


SAMPLES = _samples()


@pytest.mark.parametrize("value", SAMPLES, ids=range(len(SAMPLES)))
def test_has_surrogates_matches_the_per_character_ordinal_scan(value: str) -> None:
    assert has_surrogates(value) is reference_has_surrogates(value)


@pytest.mark.parametrize("value", SAMPLES, ids=range(len(SAMPLES)))
def test_replace_surrogates_matches_the_per_character_replacement(value: str) -> None:
    assert replace_surrogates(value) == reference_replace_surrogates(value)


@pytest.mark.parametrize("code_point", BOUNDARY_CODE_POINTS)
def test_single_boundary_code_point_is_classified_by_the_surrogate_block(
    code_point: int,
) -> None:
    character = chr(code_point)
    inside_block = 0xD800 <= code_point <= 0xDFFF

    assert has_surrogates(character) is inside_block
    assert replace_surrogates(character) == (REPLACEMENT if inside_block else character)


def test_empty_string_has_no_surrogates_and_is_returned_unchanged() -> None:
    assert has_surrogates("") is False
    assert replace_surrogates("") == ""


def test_replacement_character_is_the_one_used_by_guide_validation() -> None:
    assert SURROGATE_REPLACEMENT == REPLACEMENT
    assert replace_surrogates("\ud800") == REPLACEMENT


def test_replace_surrogates_returns_the_same_object_when_nothing_matches() -> None:
    """The fast path is load-bearing: guide sanitization relies on identity."""

    value = "a clean \U0001F600 string"

    assert replace_surrogates(value) is value


def test_replace_surrogates_honours_an_explicit_replacement_verbatim() -> None:
    # A backslash in the replacement must not be read as a regex template.
    assert replace_surrogates("a\ud800b", r"\g<0>") == r"a\g<0>b"


# ---------------------------------------------------------------------------
# The three call sites still fail closed exactly as before.


def test_profile_metadata_still_rejects_lone_surrogates() -> None:
    from education_pipeline.profiles import parse_learner_profile

    with pytest.raises(ConfigError, match="Unicode scalar"):
        parse_learner_profile(
            {
                "id": "surrogate-metadata",
                "target_learner": "cohort",
                "metadata": {"key": "bad-\ud800-value"},
            }
        )


def test_privacy_normalization_still_rejects_lone_surrogates() -> None:
    with pytest.raises(ConfigError, match="Unicode scalar"):
        normalize_private_value("bad-\udfff-value")

    with pytest.raises(ConfigError, match="Unicode scalar"):
        profile_private_values(
            LearnerProfile(id="surrogate", target_learner="bad-\ud800-target")
        )


def test_guide_validation_still_replaces_lone_surrogates() -> None:
    from education_pipeline.guides.validation import (
        _has_invalid_scalar_codepoints,
        _replace_invalid_scalar_codepoints,
    )

    assert _has_invalid_scalar_codepoints("a\ud800b") is True
    assert _has_invalid_scalar_codepoints("a\ud7ffb") is False
    assert _replace_invalid_scalar_codepoints("a\ud800b") == f"a{REPLACEMENT}b"
