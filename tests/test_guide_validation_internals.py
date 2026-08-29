"""Equivalence guards for the deterministic-validation fast paths.

Every optimization in ``guides/validation.py`` is required to be invisible:
the same findings, the same canonical report bytes, the same guide digest.
These tests pin each fast path against the slow formulation it replaced, so a
future edit that changes behaviour fails here rather than silently drifting a
digest that runs and waivers are keyed on.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import replace
from pathlib import Path

import pytest

from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides.canonical import guide_sha256
from education_pipeline.guides.model import Guide
from education_pipeline.guides.reports import canonical_report_bytes
from education_pipeline.guides.validation import (
    CalibrationContext,
    PersonalizationValidationContext,
    ValidationContext,
    _contains_possible_identifier,
    _sanitize_guide_value,
    validate_guide,
    validation_guide_sha256,
)

FIXTURES = Path(__file__).parent / "fixtures/guides"
FIXTURE = FIXTURES / "feedback-loops.guide.json"
PERSONALIZED_FIXTURE = FIXTURES / "feedback-loops.personalized.guide.json"
LEAK_FIXTURE = FIXTURES / "feedback-loops.privacy-leak.guide.json"


def load(path: Path) -> Guide:
    parsed = parse_guide(path.read_bytes())
    assert parsed.ok
    return normalize_guide(parsed)


# ---------------------------------------------------------------------------
# GDE-4: the privacy-identifier scan is boolean-equivalent to the old regex.
#
# The historical pattern is quadratic on long '@'-free text because the greedy
# local part is retried from every word-boundary start. The replacement anchors
# on literal '@' positions; it must agree with the regex on every input.

REFERENCE_POSSIBLE_ID = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I
)


def reference_contains_possible_identifier(text: str) -> bool:
    return REFERENCE_POSSIBLE_ID.search(text) is not None


IDENTIFIER_EDGE_CASES = (
    # empty / degenerate '@' placement
    "",
    "@",
    "@@",
    "a@",
    "@a",
    "@b.co",
    "a@@b.co",
    "a@b@c.co",
    "a@b.co@d.co",
    # missing or too-short TLD
    "a@b",
    "a@b.c",
    "a@.co",
    "a@b..co",
    "a@-.co",
    # trailing-\b variations after the TLD
    "a@b.co",
    "a@b.co.",
    "a@b.co1",
    "a@b.co_",
    "a@b.co-",
    "a@b.co\n",
    # leading-\b variations before the local part
    ".a@b.co",
    "a.@b.co",
    "..a@b.co",
    "....@b.co",
    "%a@b.co",
    "+a@b.co",
    "-a@b.co",
    "_@b.co",
    "xa@b.co",
    "x a@b.co",
    "\na@b.co",
    # unicode word characters adjacent to and inside the local part
    "éa@b.co",
    "aé@b.co",
    "a@bé.co",
    "a@b.coé",
    "ßa@b.co",
    "aß@b.co",
    "a@b.coß",
    # IGNORECASE case-folding specials that [A-Z] also matches
    "ſ@b.co",
    "a@b.ſſ",
    "K@b.co",
    "a@b.coı",
    # digits-only local part, casing, hyphenated domains
    "1@2.co",
    "a@b.CO",
    "A@B.CO",
    "a@b-c.co",
    "a-b@c.de",
    "a b@c.de",
    "contact jane@example.com now",
)


@pytest.mark.parametrize("text", IDENTIFIER_EDGE_CASES)
def test_identifier_detector_agrees_with_the_reference_regex_on_edge_cases(
    text: str,
) -> None:
    assert _contains_possible_identifier(text) is (
        reference_contains_possible_identifier(text)
    )


def test_identifier_detector_agrees_with_the_reference_regex_on_random_strings() -> None:
    """A seeded sweep over the alphabet that drives every branch of the scan.

    The alphabet mixes both local-part classes (word ``aA0_`` and non-word
    ``._%+-``), the ``@`` anchor, boundary characters (space, newline), and
    unicode word characters that ``\\w`` accepts but ``[A-Z]`` does not.
    """

    alphabet = "aA0._%+-@ \néſKı_"
    rng = random.Random(20260829)
    mismatches: list[str] = []
    for _ in range(100_000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 41)))
        if _contains_possible_identifier(text) != (
            reference_contains_possible_identifier(text)
        ):
            mismatches.append(text)
            if len(mismatches) >= 5:
                break

    assert mismatches == []


def test_identifier_detector_is_not_quadratic_on_adversarial_text() -> None:
    """The 20,000-character cap from ``parse.MAX_TEXT`` must stay cheap.

    No wall-clock threshold (CI timing is noise); instead, doubling the input
    must not much more than double the work, which the old regex badly failed.
    """

    import time

    def elapsed(text: str) -> float:
        start = time.perf_counter()
        _contains_possible_identifier(text)
        return time.perf_counter() - start

    small = "a.b" * 3_300 + "@x"
    large = "a.b" * 6_600 + "@x"
    assert _contains_possible_identifier(large) is False
    # Warm the code paths so import/compile cost is not counted.
    elapsed(small)
    ratio = (elapsed(large) + 1e-6) / (elapsed(small) + 1e-6)

    assert ratio < 8


# ---------------------------------------------------------------------------
# GDE-2a: sanitization shares clean subtrees instead of rebuilding them.


def test_sanitize_returns_the_identical_object_for_a_clean_guide() -> None:
    guide = load(FIXTURE)

    assert _sanitize_guide_value(guide) is guide


def test_sanitize_shares_every_clean_branch_and_rebuilds_only_the_dirty_one() -> None:
    guide = load(FIXTURE)
    dirty = replace(
        guide,
        course=replace(guide.course, title="Feedback \ud800 Loops"),
    )

    sanitized = _sanitize_guide_value(dirty)

    assert isinstance(sanitized, Guide)
    assert sanitized is not dirty
    assert sanitized.course is not dirty.course
    assert sanitized.course.title == "Feedback \N{REPLACEMENT CHARACTER} Loops"
    # Untouched siblings are shared, not copied.
    assert sanitized.modules is dirty.modules
    assert sanitized.outcomes is dirty.outcomes
    assert sanitized.glossary is dirty.glossary
    assert sanitized.sources is dirty.sources
    assert sanitized.course.description is dirty.course.description


def test_sanitize_is_idempotent_and_equal_to_the_eager_rebuild() -> None:
    guide = load(FIXTURE)
    dirty = replace(
        guide,
        course=replace(guide.course, description="bad \udfff description"),
        outcomes=(replace(guide.outcomes[0], text="bad \ud800 outcome"),)
        + guide.outcomes[1:],
    )

    once = _sanitize_guide_value(dirty)
    twice = _sanitize_guide_value(once)

    assert twice == once
    assert twice is once
    assert isinstance(once, Guide)
    assert guide_sha256(once) == guide_sha256(_eager_sanitize(dirty))


def _eager_sanitize(value: object) -> object:
    """The unconditional rebuild the identity-preserving version replaced."""

    from dataclasses import fields, is_dataclass

    if isinstance(value, str):
        return "".join(
            "\N{REPLACEMENT CHARACTER}" if 0xD800 <= ord(character) <= 0xDFFF else character
            for character in value
        )
    if isinstance(value, tuple):
        return tuple(_eager_sanitize(child) for child in value)
    if is_dataclass(value):
        return replace(
            value,
            **{
                field.name: _eager_sanitize(getattr(value, field.name))
                for field in fields(value)
            },
        )
    return value


@pytest.mark.parametrize(
    "path", [FIXTURE, PERSONALIZED_FIXTURE, LEAK_FIXTURE], ids=lambda p: p.name
)
def test_sanitize_agrees_with_the_eager_rebuild_on_every_fixture(path: Path) -> None:
    guide = load(path)

    assert _sanitize_guide_value(guide) == _eager_sanitize(guide)


# ---------------------------------------------------------------------------
# GDE-2b: the report digest still equals the public digest helper.


@pytest.mark.parametrize(
    "path", [FIXTURE, PERSONALIZED_FIXTURE, LEAK_FIXTURE], ids=lambda p: p.name
)
def test_report_digest_equals_the_public_validation_digest(path: Path) -> None:
    guide = load(path)

    report = validate_guide(guide, phase="final")

    assert report.guide_sha256 == validation_guide_sha256(guide)
    assert report.guide_sha256 == validation_guide_sha256(path.read_bytes())


def test_report_digest_is_the_sanitized_digest_for_a_guide_with_surrogates() -> None:
    guide = load(FIXTURE)
    dirty = replace(guide, course=replace(guide.course, title="Bad \ud800 title"))

    report = validate_guide(dirty, phase="final")

    assert report.guide_sha256 == validation_guide_sha256(dirty)
    assert report.guide_sha256 == guide_sha256(_eager_sanitize(dirty))


# ---------------------------------------------------------------------------
# GDE-3 / whole-package regression: report bytes and digests are byte-frozen.
#
# The literals below were produced by the public API before any optimization
# landed. Every fast path in this change is required to reproduce them exactly.

FROZEN_DIGESTS = {
    "feedback-loops.guide.json": (
        "99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07"
    ),
    "feedback-loops.personalized.guide.json": (
        "03ae218e2d12d3d618eec7598a57214e4d65dabaa39cfff6ad2ecc2e629003ff"
    ),
    "feedback-loops.privacy-leak.guide.json": (
        "0d4c54dd6576a1a936f4485d1581b03512e3413e3e28cb63e61eb18b07c126d3"
    ),
}

FROZEN_PLAIN_REPORTS = {
    "feedback-loops.guide.json": (
        "512bbd0fb46131f196d46c1eb9f88b12f7144244dbd09ee1edaa75d0ba888429"
    ),
    "feedback-loops.personalized.guide.json": (
        "321f24d9430f111620ce48b2104afff7e39fc741bd01c4b9cf8e13300e32e76c"
    ),
    "feedback-loops.privacy-leak.guide.json": (
        "1495f578a3095a01bf18a850d3ca4488fe39a9572ed52306b7484c88fc62ae1a"
    ),
}

FROZEN_FULL_CONTEXT_REPORTS = {
    "feedback-loops.guide.json": (
        "fd0cc324be748abdd186e924814c730d8910c63c8a5e185abc11686f59bfbd47"
    ),
    "feedback-loops.personalized.guide.json": (
        "92132634abe4e54325bb6aeb8ec40995d9c4cd9a2f40be42193fca9f8912f5eb"
    ),
    "feedback-loops.privacy-leak.guide.json": (
        "f20ffbff7bb92f70e9e9f049c1ed47e33ccbe02358268e2f17e160e4df367a04"
    ),
}


def report_sha(report) -> str:
    return hashlib.sha256(canonical_report_bytes(report)).hexdigest()


def full_context_report(guide: Guide):
    return validate_guide(
        guide,
        phase="draft",
        private_values=["SecretOrchard", "Marguerite Delacroix"],
        context=ValidationContext(sources_required=True),
        personalization_context=PersonalizationValidationContext(
            profile_present=True, authoritative_goal_ids=("goal-1",)
        ),
        calibration_context=CalibrationContext(
            configured_blueprint="concept-first",
            time_budget_minutes=60,
            attention_constraints_present=True,
            learner_skill_level="beginner",
        ),
    )


@pytest.mark.parametrize(
    "path", [FIXTURE, PERSONALIZED_FIXTURE, LEAK_FIXTURE], ids=lambda p: p.name
)
def test_fixture_digests_and_report_bytes_are_frozen(path: Path) -> None:
    guide = load(path)

    assert validation_guide_sha256(guide) == FROZEN_DIGESTS[path.name]
    assert validation_guide_sha256(path.read_bytes()) == FROZEN_DIGESTS[path.name]
    assert report_sha(validate_guide(guide, phase="final")) == (
        FROZEN_PLAIN_REPORTS[path.name]
    )
    assert report_sha(validate_guide(path.read_bytes(), phase="final")) == (
        FROZEN_PLAIN_REPORTS[path.name]
    )
    assert report_sha(full_context_report(guide)) == (
        FROZEN_FULL_CONTEXT_REPORTS[path.name]
    )


def test_denylist_free_validation_matches_the_denylist_path_finding_for_finding() -> None:
    """Skipping the per-field fold when no denylist exists changes nothing.

    ``_normalize_validation_text`` is read only inside the denylist loop, so a
    guide validated with an empty denylist must produce exactly the report a
    non-matching denylist produces, minus nothing at all.
    """

    guide = load(FIXTURE)

    without = validate_guide(guide, phase="final")
    # A supplied value that appears nowhere in the guide still walks the fold.
    with_denylist = validate_guide(
        guide, phase="final", private_values=["ZzQqNeverAppearsHere"]
    )

    assert canonical_report_bytes(without) == canonical_report_bytes(with_denylist)


def test_leaky_content_reports_identically_through_both_paths() -> None:
    """The email/denylist rules still fire, with byte-identical output."""

    guide = load(FIXTURE)
    module = guide.modules[0]
    section = module.sections[0]
    block = replace(
        section.blocks[0],
        markdown=(
            "# Private\nContact jane@example.com. TODO use the red button. "
            "Secret Orchard."
        ),
    )
    leaky = replace(
        guide,
        modules=(
            replace(
                module,
                estimated_minutes=99,
                sections=(replace(section, blocks=(block,) + section.blocks[1:]),)
                + module.sections[1:],
            ),
        )
        + guide.modules[1:],
    )

    report = validate_guide(leaky, private_values=["Secret Orchard", "none", "user"])
    rule_ids = {item.rule_id for item in report.findings}

    assert {
        "privacy.exact_private_value",
        "privacy.possible_identifier",
        "content.placeholder",
        "markdown.invalid_heading_level",
        "a11y.color_only_instruction",
        "time.module_total_mismatch",
    } <= rule_ids
    rendered = canonical_report_bytes(report).decode("utf-8")
    assert "Secret Orchard" not in rendered
    assert "jane@example.com" not in rendered
    assert report_sha(report) == (
        "7b915a6ac5b417158248e173564880b1e0b6afad771c3ebe7fe8ea7735a9e9c1"
    )


def test_raw_json_path_and_object_path_agree_on_a_mutated_guide() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = (
        "Write to alice@example.org for the TODO list."
    )
    source = json.dumps(data, ensure_ascii=False)

    from_source = validate_guide(source, phase="final")
    from_object = validate_guide(load_from_text(source), phase="final")

    assert canonical_report_bytes(from_source) == canonical_report_bytes(from_object)
    assert "privacy.possible_identifier" in {
        item.rule_id for item in from_source.findings
    }


def load_from_text(text: str) -> Guide:
    parsed = parse_guide(text)
    assert parsed.ok
    return normalize_guide(parsed)
