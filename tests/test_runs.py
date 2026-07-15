import concurrent.futures
import hashlib
import json
import threading
from pathlib import Path

import pytest

from education_pipeline import (
    AdvanceResult,
    ConfigError,
    ContentContract,
    GUIDE_V1_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    NextAction,
    PromptFile,
    ProfileStore,
    RunStatus,
    RunStore,
    StaleContentError,
    StageStatus,
    TopicStore,
)
from education_pipeline.guides import (
    REPORT_SCHEMA_VERSION,
    WaiverResult,
    build_guide_contract,
    canonical_guide_bytes,
    extract_outline_contract,
    extract_spec_contract,
    guide_sha256,
    normalize_guide,
    parse_guide,
    project_guide_markdown,
)
from education_pipeline.runs import OPTIONAL_STAGES, REQUIRED_STAGES, SUPPORTED_STAGES


def _create_legacy_run(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    """Create an explicit legacy Markdown run (post Wave 4 Slice C default flip)."""

    runs = RunStore(tmp_path)
    runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())
    return runs


def _ensure_legacy_run(runs: RunStore, topic_id: str) -> None:
    """Opt a run into the explicit legacy path before driving Markdown stages."""

    runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())


def _drive_spec_to_approved(runs: RunStore, topic_id: str) -> None:
    _ensure_legacy_run(runs, topic_id)
    result = runs.write_spec_prompt(topic_id, title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n", encoding="utf-8")
    runs.approve_stage(topic_id, "spec")


def _drive_outline_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_outline_prompt(topic_id)
    result.response_path.write_text("# Course Outline\n", encoding="utf-8")
    runs.approve_stage(topic_id, "outline")


def _drive_draft_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_draft_prompt(topic_id)
    result.response_path.write_text("# Systems Thinking\n", encoding="utf-8")
    runs.approve_stage(topic_id, "draft")


def _drive_qa_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_qa_prompt(topic_id)
    result.response_path.write_text("# QA Report\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa")


def _drive_repair_to_approved(runs: RunStore, topic_id: str, body: str = "# Systems Thinking\n") -> None:
    result = runs.write_repair_prompt(topic_id)
    result.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair")


def _drive_all_stages_to_approved(runs: RunStore, topic_id: str, repair_body: str = "# Systems Thinking\n") -> None:
    _drive_spec_to_approved(runs, topic_id)
    _drive_outline_to_approved(runs, topic_id)
    _drive_draft_to_approved(runs, topic_id)
    _drive_qa_to_approved(runs, topic_id)
    _drive_repair_to_approved(runs, topic_id, repair_body)


TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
audience = "early-career analysts"
goals = ["explain feedback loops"]
"""


PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "early-career analysts"
learning_goals = ["understand systems thinking"]

[learning_preferences]
preferred_visual_aids = ["flowcharts", "concept maps"]

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Early-career team learning systems thinking."
"""

PUBLISHABLE_PROFILE_TOML = """\
schema_version = 1
id = "publishable-profile"
target_learner = "team cohort"
professional_experience = "early-career analysts"
learning_goals = ["understand systems thinking"]

[privacy]
private_by_default = true
include_in_published_output = true
publishable_summary = "Early-career team learning systems thinking."
"""

VALID_SPEC_CONTRACT = {
    "contract_version": 1,
    "guide_schema_version": "1.0",
    "blueprint": "conceptual-foundations",
    "estimated_minutes": 30,
    "outcomes": [{"id": "identify-loop", "text": "Identify reinforcing and balancing feedback."}],
    "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    "personalization_requirements": ["Use gardening examples where they clarify the concept."],
    "source_policy": "Sources required for factual claims that are not common knowledge.",
}

VALID_OUTLINE_CONTRACT = {
    "contract_version": 1,
    "modules": {
        "feedback-loops": {
            "outcome_ids": ["identify-loop"],
            "estimated_minutes": 30,
            "interaction_types": ["knowledge_check", "worked_reveal"],
        },
    },
}


def _guide_spec_response(contract: dict | None = None) -> str:
    body = contract if contract is not None else VALID_SPEC_CONTRACT
    return (
        "# Course Specification: Systems Thinking\n\n"
        "## Learning Outcomes\n"
        "- Identify reinforcing and balancing feedback.\n\n"
        "```education-pipeline-contract+json\n"
        f"{json.dumps(body)}\n"
        "```\n"
    )


def _guide_outline_response(contract: dict | None = None) -> str:
    body = contract if contract is not None else VALID_OUTLINE_CONTRACT
    return (
        "# Course Outline: Systems Thinking\n\n"
        "## Modules\n"
        "1. Feedback loops\n\n"
        "```education-pipeline-outline+json\n"
        f"{json.dumps(body)}\n"
        "```\n"
    )


def _create_guide_run(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    TopicStore(tmp_path).save_topic_toml(topic_id, TOPIC_TOML)
    runs = RunStore(tmp_path)
    runs.create_run(topic_id, content_contract=ContentContract.interactive_guide_v1())
    return runs


def _drive_guide_spec_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_topic_spec_prompt(topic_id)
    result.response_path.write_text(_guide_spec_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "spec")


def _drive_guide_outline_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_outline_prompt(topic_id)
    result.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "outline")


GUIDE_FIXTURE = Path("tests/fixtures/guides/feedback-loops.guide.json").read_text(
    encoding="utf-8"
)
PERSONALIZED_GUIDE_FIXTURE = Path(
    "tests/fixtures/guides/feedback-loops.personalized.guide.json"
).read_text(encoding="utf-8")

PERSONALIZED_PROFILE_TOML = """\
schema_version = 1
id = "personalized-profile"
target_learner = "Synthetic learner cohort"
learning_goals = [
  "Synthetic private goal alpha",
  "Synthetic private goal beta",
  "Synthetic private goal gamma",
]

[learning_preferences]
preferred_visual_aids = ["flowcharts"]

[privacy]
private_by_default = true
include_in_published_output = false
"""

NO_GOAL_PROFILE_TOML = """\
schema_version = 1
id = "no-goal-profile"
target_learner = "Synthetic no-goal cohort"

[learning_preferences]
preferred_visual_aids = ["flowcharts"]

[privacy]
private_by_default = true
include_in_published_output = false
"""


def _create_profiled_guide_run(
    tmp_path: Path,
    *,
    profile_toml: str = PERSONALIZED_PROFILE_TOML,
    profile_id: str = "personalized-profile",
    topic_id: str = "systems-thinking",
) -> RunStore:
    TopicStore(tmp_path).save_topic_toml(topic_id, TOPIC_TOML)
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml(profile_id, profile_toml)
    profiles.attach_profile_to_topic(profile_id, topic_id)
    runs = RunStore(tmp_path)
    runs.create_run(topic_id)
    return runs


def _drive_profiled_guide_to_draft_approved(
    runs: RunStore,
    topic_id: str,
    body: str = PERSONALIZED_GUIDE_FIXTURE,
) -> None:
    spec = runs.write_topic_spec_prompt(topic_id)
    spec_contract = dict(VALID_SPEC_CONTRACT, guide_schema_version="1.1")
    spec.response_path.write_text(_guide_spec_response(spec_contract), encoding="utf-8")
    runs.approve_stage(topic_id, "spec")
    outline = runs.write_outline_prompt(topic_id)
    outline.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "outline")
    draft = runs.write_draft_prompt(topic_id)
    draft.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "draft")


def _drive_profiled_guide_to_finalize_ready(
    runs: RunStore,
    topic_id: str,
    *,
    body: str = PERSONALIZED_GUIDE_FIXTURE,
) -> None:
    _drive_profiled_guide_to_draft_approved(runs, topic_id, body)
    runs.validate_run(topic_id, "draft")
    qa = runs.write_qa_prompt(topic_id)
    qa.response_path.write_text("# QA findings\n\nNo major issues.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa")
    repair = runs.write_repair_prompt(topic_id)
    repair.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair")
    runs.validate_run(topic_id, "final")


def _valid_personalization_audit_response(runs: RunStore, topic_id: str) -> str:
    trace = json.loads(
        runs.personalization_trace_path(topic_id).read_text(encoding="utf-8")
    )
    guide = normalize_guide(
        parse_guide(runs.approved_path(topic_id, "repair").read_bytes())
    )
    fallback_module = guide.modules[0].id
    goals = []
    for item in trace["goals"]:
        evidence = []
        if item["serving_module_ids"]:
            evidence = [{"kind": "module", "id": item["serving_module_ids"][0]}]
        elif item["serving_outcome_ids"]:
            evidence = [{"kind": "outcome", "id": item["serving_outcome_ids"][0]}]
        goals.append(
            {
                "goal_id": item["goal_id"],
                "verdict": "served" if evidence else "missing",
                "evidence": evidence,
                "rationale": "Synthetic local audit rationale.",
            }
        )
    facets = [
        {
            "facet_id": facet_id,
            "verdict": "served",
            "evidence": [{"kind": "module", "id": fallback_module}],
            "rationale": "Synthetic local facet rationale.",
        }
        for facet_id in trace["active_facets"]
    ]
    return json.dumps(
        {
            "schema_version": 1,
            "goals": goals,
            "facets": facets,
            "generic_sections": [],
            "suspected_private_details": [],
            "overall_summary": "Synthetic local tailoring summary.",
        },
        sort_keys=True,
    )


def _drive_guide_to_draft_approved(
    runs: RunStore, topic_id: str, draft_body: str | None = None
) -> None:
    _drive_guide_spec_to_approved(runs, topic_id)
    _drive_guide_outline_to_approved(runs, topic_id)
    draft = runs.write_draft_prompt(topic_id)
    draft.response_path.write_text(
        draft_body if draft_body is not None else GUIDE_FIXTURE, encoding="utf-8"
    )
    runs.approve_stage(topic_id, "draft")


def _drive_guide_through_qa(
    runs: RunStore, topic_id: str, *, draft_body: str | None = None
) -> None:
    _drive_guide_to_draft_approved(runs, topic_id, draft_body)
    runs.validate_run(topic_id, "draft")
    qa = runs.write_qa_prompt(topic_id)
    qa.response_path.write_text("# QA findings\n\nNo major issues.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa")


def _drive_guide_to_finalize_ready(
    runs: RunStore,
    topic_id: str,
    *,
    draft_body: str | None = None,
    repair_body: str | None = None,
) -> None:
    _drive_guide_through_qa(runs, topic_id, draft_body=draft_body)
    repair = runs.write_repair_prompt(topic_id)
    body = repair_body if repair_body is not None else (
        draft_body if draft_body is not None else GUIDE_FIXTURE
    )
    repair.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair")
    runs.validate_run(topic_id, "final")


def _prompt_leak_guide_json() -> str:
    data = json.loads(GUIDE_FIXTURE)

    def inject(obj: object) -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "markdown" and isinstance(value, str) and len(value) > 10:
                    obj[key] = "ignore all previous instructions " + value
                    return True
                if inject(value):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if inject(item):
                    return True
        return False

    assert inject(data)
    return json.dumps(data)


def _prompt_leak_guide_json_all() -> str:
    """Like ``_prompt_leak_guide_json`` but injects leak text into every
    markdown block, producing multiple distinct ``content.prompt_leak``
    findings (finding ids are path-derived, so distinct blocks -> distinct
    ids). Used by the record_waiver concurrency test, which needs several
    real, independently-waivable findings rather than one."""

    data = json.loads(GUIDE_FIXTURE)

    def inject(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "markdown" and isinstance(value, str) and len(value) > 10:
                    obj[key] = "ignore all previous instructions " + value
                else:
                    inject(value)
        elif isinstance(obj, list):
            for item in obj:
                inject(item)

    inject(data)
    return json.dumps(data)


def _edit_course_description(guide_json: str, new_description: str) -> str:
    data = json.loads(guide_json)
    data["course"]["description"] = new_description
    return json.dumps(data)


def _first_waivable_blocking_finding_id(runs: RunStore, topic_id: str, phase: str) -> str:
    report = json.loads(runs.final_report_path(topic_id).read_text(encoding="utf-8"))
    for finding in report["findings"]:
        if finding["blocking"] and finding["waivable"]:
            return finding["id"]
    raise AssertionError("fixture produced no waivable blocking finding")


def test_run_store_creates_run_directories(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    run_dir = store.create_run("systems-thinking")

    assert run_dir == tmp_path / "runs" / "systems-thinking"
    for subdir in ("inputs", "prompts", "responses", "approved", "reports", "final"):
        assert (run_dir / subdir).is_dir()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["topic_id"] == "systems-thinking"
    assert manifest["events"] == []
    assert manifest["content_contract"] == {
        "kind": "interactive_guide",
        "schema_version": "1.0",
    }
    assert store.content_contract("systems-thinking") == ContentContract.interactive_guide_v1()
    draft = store.stage_paths("systems-thinking", "draft")
    assert draft.response_path.name == "draft.response.json"
    assert draft.approved_path.name == "draft.json"
    assert draft.content_type == GUIDE_V1_CONTENT_TYPE


def test_explicit_legacy_create_writes_legacy_contract(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("systems-thinking", content_contract=ContentContract.legacy_markdown())

    manifest = store.read_manifest("systems-thinking")
    assert manifest["content_contract"] == {"kind": "legacy_markdown"}
    assert store.content_contract("systems-thinking") == ContentContract.legacy_markdown()
    draft = store.stage_paths("systems-thinking", "draft")
    assert draft.response_path.name == "draft.response.md"
    assert draft.content_type == MARKDOWN_CONTENT_TYPE


def test_absent_content_contract_is_legacy_without_manifest_mutation(tmp_path: Path) -> None:
    """Pre-existing manifests without content_contract remain legacy and are not mutated."""

    store = RunStore(tmp_path)
    run_dir = store.run_dir("systems-thinking")
    for subdir in ("inputs", "prompts", "responses", "approved", "reports", "final"):
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    bare = {
        "schema_version": 1,
        "topic_id": "systems-thinking",
        "events": [],
    }
    store.manifest_path("systems-thinking").write_text(
        json.dumps(bare, indent=2) + "\n", encoding="utf-8"
    )
    before = store.manifest_path("systems-thinking").read_bytes()

    # create_run with no contract must not rewrite an existing bare manifest
    store.create_run("systems-thinking")

    assert store.content_contract("systems-thinking") == ContentContract.legacy_markdown()
    assert store.stage_paths("systems-thinking", "draft").content_type == MARKDOWN_CONTENT_TYPE
    assert store.manifest_path("systems-thinking").read_bytes() == before
    assert "content_contract" not in store.read_manifest("systems-thinking")


def test_explicit_guide_contract_round_trips_and_selects_json_artifacts(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    contract = ContentContract.interactive_guide_v1()
    store.create_run("systems-thinking", content_contract=contract)

    assert store.content_contract("systems-thinking") == contract
    draft = store.stage_paths("systems-thinking", "draft")
    assert draft.response_path.name == "draft.response.json"
    assert draft.approved_path.name == "draft.json"
    assert draft.content_type == GUIDE_V1_CONTENT_TYPE
    assert store.stage_paths("systems-thinking", "qa").content_type == MARKDOWN_CONTENT_TYPE


def test_content_contract_is_immutable_and_unsupported_contracts_fail_closed(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("systems-thinking")  # default → interactive_guide 1.0

    with pytest.raises(ConfigError, match="immutable content contract"):
        store.create_run(
            "systems-thinking",
            content_contract=ContentContract.legacy_markdown(),
        )
    with pytest.raises(ConfigError, match="unsupported content contract"):
        store.create_run(
            "other",
            content_contract=ContentContract("interactive_guide", "2.0"),
        )


def test_manifest_events_record_current_artifact_hashes(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    event = store.read_manifest("systems-thinking")["events"][-1]
    assert event["prompt_file_sha256"] == hashlib.sha256(
        result.prompt_path.read_bytes()
    ).hexdigest()
    assert "response_file_sha256" not in event


def test_manifest_write_goes_through_atomic_writer(tmp_path: Path, monkeypatch) -> None:
    """_write_manifest must go through the temp-file + os.replace path."""
    from education_pipeline import runs as runs_mod

    calls = []
    original = runs_mod._write_bytes_atomic

    def spy(path, data):
        calls.append(path.name)
        return original(path, data)

    monkeypatch.setattr(runs_mod, "_write_bytes_atomic", spy)
    store = runs_mod.RunStore(tmp_path)
    store.create_run("atomic-topic")
    assert "manifest.json" in calls


def test_concurrent_manifest_events_are_all_recorded(tmp_path: Path) -> None:
    """Two writer threads appending events must not lose either event."""
    from education_pipeline.runs import RunStore

    store = RunStore(tmp_path)
    store.create_run("locked-topic")

    def append(n: int) -> None:
        store.append_manifest_event("locked-topic", {"action": f"evt-{n}"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(50)))

    manifest = store.read_manifest("locked-topic")
    actions = [e["action"] for e in manifest["events"] if e.get("action", "").startswith("evt-")]
    assert sorted(actions) == sorted(f"evt-{n}" for n in range(50))
    # File must still be valid JSON (no torn write)
    json.loads(store.manifest_path("locked-topic").read_text(encoding="utf-8"))


def test_concurrent_mixed_manifest_writers_all_recorded(tmp_path: Path) -> None:
    """Mirrors the daemon worker path (jobs.py): concurrent threads drive both
    ``_append_event`` (via ``ingest_response(force=True)``, as ``ingest_response``
    does on a re-ingest) and ``record_stage_provenance`` against the same
    topic's manifest. Every provenance entry and every event must survive, and
    the manifest must remain valid JSON. This is expected to fail if either
    the ``_append_event`` lock or the ``record_stage_provenance`` lock is
    removed, since both do an unlocked read-modify-write of the same file
    against a shared list of pre-existing entries.
    """
    store = _create_legacy_run(tmp_path, "mixed-writers-topic")
    store.write_spec_prompt("mixed-writers-topic", title="Mixed Writers")
    store.ingest_response("mixed-writers-topic", "spec", "initial response")

    event_count = 40
    provenance_count = 40

    def append_event(n: int) -> None:
        store.ingest_response(
            "mixed-writers-topic", "spec", f"replacement response {n}", force=True
        )

    def append_provenance(n: int) -> None:
        store.record_stage_provenance(
            "mixed-writers-topic",
            "spec",
            provider="claude-code",
            model="claude-x",
            effort=f"effort-{n}",
            source="provider",
            job_id=f"job-{n}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(append_event, n) for n in range(event_count)]
        futures += [pool.submit(append_provenance, n) for n in range(provenance_count)]
        for future in futures:
            future.result()

    manifest = store.read_manifest("mixed-writers-topic")

    replaced_events = [e for e in manifest["events"] if e.get("action") == "response_replaced"]
    assert len(replaced_events) == event_count

    provenance_entries = manifest["stage_provenance"]
    assert len(provenance_entries) == provenance_count
    assert sorted(e["effort"] for e in provenance_entries) == sorted(
        f"effort-{n}" for n in range(provenance_count)
    )

    # File must still be valid JSON (no torn write from either writer path)
    json.loads(store.manifest_path("mixed-writers-topic").read_text(encoding="utf-8"))


def test_concurrent_record_waiver_calls_all_survive(tmp_path: Path) -> None:
    """Regression test for the daemon's create_waiver read-modify-write:
    several threads waiving several *different* findings on the same run's
    waivers file must all survive, and no thread may crash with
    FileNotFoundError from a colliding hardcoded temp filename. Mirrors
    ``test_concurrent_mixed_manifest_writers_all_recorded`` but exercises
    ``RunStore.record_waiver`` (which write_api.create_waiver must delegate to
    rather than hand-rolling its own read-modify-write + temp file).

    ``record_waiver`` now hash-binds to the current report and validates the
    finding exists and is waivable, so (unlike the pre-refactor version of
    this test) it needs real, independently-waivable findings rather than
    made-up ids -- a guide with a leaked prompt-instruction phrase in every
    markdown block gives one real ``content.prompt_leak`` finding per block.
    """
    topic_id = "systems-thinking"
    store = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json_all()
    _drive_guide_to_draft_approved(store, topic_id, draft_body=leak_json)
    report_path = store.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    finding_ids = sorted(
        f["id"]
        for f in report["findings"]
        if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    )
    assert len(finding_ids) >= 5

    def record(finding_id: str) -> None:
        store.record_waiver(topic_id, "draft", finding_id, f"reason for {finding_id}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(record, finding_id) for finding_id in finding_ids]
        for future in futures:
            future.result()

    waiver_set = store.load_waiver_set(topic_id)
    assert waiver_set is not None
    assert sorted(w.finding_id for w in waiver_set.waivers) == finding_ids

    # File must still be valid JSON (no torn write, no lost update)
    json.loads(store.waivers_path(topic_id).read_text(encoding="utf-8"))

    result = store.gate_result(topic_id, "draft")
    assert result.gate_open is True


def test_record_waiver_flips_gate_open_for_waivable_blocker(tmp_path: Path) -> None:
    """The core waive contract: recording a waiver for a real, currently
    blocking, waivable finding must flip ``gate_result`` from blocked to
    open -- not merely persist a waiver file. A test that only checks the
    file was written would pass even if the gate math were broken."""

    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    report_path = runs.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    )
    assert finding["waivable"] is True

    before = runs.gate_result(topic_id, "draft")
    assert before.gate_open is False

    result = runs.record_waiver(topic_id, "draft", finding["id"], "Intentional example text.")
    assert isinstance(result, WaiverResult)
    assert result.gate_open is True
    assert finding["id"] in result.waived_finding_ids

    after = runs.gate_result(topic_id, "draft")
    assert after.gate_open is True


def test_record_waiver_rejects_empty_reason(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    report_path = runs.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    )

    with pytest.raises(ConfigError):
        runs.record_waiver(topic_id, "draft", finding["id"], "   ")

    # Rejected attempt must not have persisted a waivers file, and the gate
    # must remain blocked.
    assert not runs.waivers_path(topic_id).exists()
    assert runs.gate_result(topic_id, "draft").gate_open is False


def test_record_waiver_rejects_non_waivable_finding(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    bad = json.loads(GUIDE_FIXTURE)
    bad["schema_version"] = "2.0"
    bad_json = json.dumps(bad)
    runs = _create_guide_run(tmp_path, topic_id)
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=bad_json)
    report_path = runs.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    blockers = [f for f in report["findings"] if f["blocking"]]
    assert blockers
    finding = blockers[0]
    assert finding["waivable"] is False

    with pytest.raises(ConfigError):
        runs.record_waiver(topic_id, "draft", finding["id"], "Please let this through.")

    assert runs.gate_result(topic_id, "draft").gate_open is False


def test_remove_waiver_closes_gate_again(tmp_path: Path) -> None:
    """The inverse of the waive contract: removing a waiver for the sole
    waived blocker must flip the gate back closed, proving remove_waiver
    actually mutates the persisted waiver set rather than being a no-op
    that happens to leave a passing test behind."""

    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    report_path = runs.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    )

    waived = runs.record_waiver(topic_id, "draft", finding["id"], "Intentional example text.")
    assert waived.gate_open is True

    result = runs.remove_waiver(topic_id, "draft", finding["id"])
    assert isinstance(result, WaiverResult)
    assert result.gate_open is False
    assert finding["id"] not in result.waived_finding_ids

    after = runs.gate_result(topic_id, "draft")
    assert after.gate_open is False

    # This was the sole waiver on the topic, so removing it must delete the
    # waivers file entirely rather than leaving a `{"waivers": []}` husk on
    # disk -- see test_unwaive_of_the_last_waiver_deletes_the_waivers_file
    # for why that matters (it silently defeats a poll optimization).
    assert not runs.waivers_path(topic_id).exists()
    assert runs.load_waiver_set(topic_id) is None


def test_remove_waiver_missing_finding_is_a_noop(tmp_path: Path) -> None:
    """Removing a waiver that was never recorded should not raise -- it's
    already in the desired end state."""

    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    runs.validate_run(topic_id, "draft")

    result = runs.remove_waiver(topic_id, "draft", "does-not-exist")
    assert isinstance(result, WaiverResult)
    assert result.gate_open is False


def test_unwaive_nonexistent_finding_on_topic_with_no_waivers_file_creates_none(
    tmp_path: Path,
) -> None:
    """Regression for the hot-path optimization in the daemon's poll handler
    (``read_api.py``, which skips the expensive ``gate_result`` recompute
    only when ``load_waiver_set(...) is None``, i.e. no waivers file on
    disk): ``unwaive`` of a finding id that was never waived, on a topic
    with no waivers file, must leave NO waivers file on disk. Writing an
    empty ``{"waivers": []}`` file here would silently and permanently
    defeat that optimization for this topic."""

    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    runs.validate_run(topic_id, "draft")

    assert not runs.waivers_path(topic_id).exists()

    result = runs.remove_waiver(topic_id, "draft", "does-not-exist")
    assert isinstance(result, WaiverResult)
    assert not runs.waivers_path(topic_id).exists()


def test_unwaive_that_removes_nothing_does_not_rewrite_existing_waivers_file(
    tmp_path: Path,
) -> None:
    """An ``unwaive`` call for a finding id that is not present in an
    *existing* waiver set must be a true no-op on disk -- it must not
    rewrite (and thereby risk destroying) the persisted file, even though
    the resulting logical waiver set is unchanged either way."""

    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    report_path = runs.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    )

    runs.record_waiver(topic_id, "draft", finding["id"], "Intentional example text.")
    waivers_path = runs.waivers_path(topic_id)
    before_mtime_ns = waivers_path.stat().st_mtime_ns
    before_bytes = waivers_path.read_bytes()

    result = runs.remove_waiver(topic_id, "draft", "does-not-exist")
    assert isinstance(result, WaiverResult)
    assert result.gate_open is True

    assert waivers_path.stat().st_mtime_ns == before_mtime_ns
    assert waivers_path.read_bytes() == before_bytes


def test_unwaive_of_the_last_waiver_deletes_the_waivers_file(tmp_path: Path) -> None:
    """Regression for Important #1 of the Wave-3 whole-wave review:
    ``remove_waiver`` used to write ``{"waivers": []}`` back to disk when the
    removed waiver was the last one, instead of deleting the file. An
    empty-but-present waivers file is not equivalent to no waivers file --
    the daemon's poll handler (``read_api.py``, around line 196) skips its
    expensive per-poll ``gate_result`` recompute only when
    ``load_waiver_set(...) is None``, so a lingering empty file silently and
    permanently defeats that optimization for the rest of the run's life.

    This waives a real blocking finding (closing the gate), then unwaives it
    (the only waiver on the topic), and asserts both that the file is gone
    from disk *and* that ``load_waiver_set`` -- the exact call the poll
    optimization guards on -- reports ``None``, not an empty WaiverSet."""

    topic_id = "systems-thinking"
    runs = _create_guide_run(tmp_path, topic_id)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    report_path = runs.validate_run(topic_id, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    )

    waived = runs.record_waiver(topic_id, "draft", finding["id"], "Intentional example text.")
    assert waived.gate_open is True
    assert runs.waivers_path(topic_id).exists()

    result = runs.remove_waiver(topic_id, "draft", finding["id"])
    assert isinstance(result, WaiverResult)
    assert result.gate_open is False

    assert not runs.waivers_path(topic_id).exists()
    assert runs.load_waiver_set(topic_id) is None


def test_record_waiver_with_set_returns_the_written_set(tmp_path):
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)
    finding_id = _first_waivable_blocking_finding_id(runs, tid, "final")

    result, waiver_set = runs.record_waiver_with_set(tid, "final", finding_id, "reviewed")

    assert result.gate_open is True
    assert [w.finding_id for w in waiver_set.waivers] == [finding_id]
    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    assert waiver_set.guide_sha256 == report["guide_sha256"]


def test_remove_waiver_with_set_returns_the_empty_set_and_leaves_no_file(tmp_path):
    """Removing the last waiver must unlink the file, not write an empty one:
    read_api skips its per-poll gate recompute only when the file is ABSENT,
    so an empty file would permanently defeat that optimization for this topic."""
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)
    finding_id = _first_waivable_blocking_finding_id(runs, tid, "final")
    runs.record_waiver(tid, "final", finding_id, "reviewed")
    assert runs.waivers_path(tid).exists()

    result, waiver_set = runs.remove_waiver_with_set(tid, "final", finding_id)

    assert result.gate_open is False
    assert waiver_set.waivers == ()
    assert not runs.waivers_path(tid).exists()
    assert runs.load_waiver_set(tid) is None


def test_remove_waiver_with_set_no_op_writes_nothing(tmp_path):
    """Removing an id that was never waived must not create the file."""
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    leak_json = _prompt_leak_guide_json()
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)

    result, waiver_set = runs.remove_waiver_with_set(tid, "final", "never.waived:/root")

    assert waiver_set.waivers == ()
    assert not runs.waivers_path(tid).exists()
    assert result.gate_open is False


def test_manifest_write_lock_is_not_reentrant(tmp_path: Path) -> None:
    """``_manifest_write_lock`` must be a plain, non-reentrant lock: a second
    acquisition on the SAME thread must block (never silently succeed).
    Reentrancy would let a method take the lock, call another
    lock-taking method on the same thread, and have that inner call's
    read-modify-write get silently clobbered by the outer method's later
    write of its now-stale in-memory manifest snapshot -- a lost update
    with no error raised. A plain lock instead fails loud (blocks/deadlocks)
    the moment nesting is attempted, which is far preferable. This pins the
    revert away from ``threading.RLock``.
    """
    store = _create_legacy_run(tmp_path, "non-reentrant-lock-topic")
    lock = store._manifest_write_lock("non-reentrant-lock-topic")

    with lock:
        # A non-reentrant lock blocks even on the SAME thread if re-entered
        # directly -- this is exactly what a nested lock-taking method call
        # would do, and it must NOT succeed.
        acquired_again = lock.acquire(timeout=0.2)
        assert not acquired_again, "manifest write lock must not be reentrant"


def test_composed_manifest_write_via_locked_primitives_preserves_both_writes(
    tmp_path: Path,
) -> None:
    """Pins the correct composition shape from Finding 1: a method that takes
    ``_manifest_write_lock`` once and then calls the unlocked ``_locked``
    primitives (``_append_manifest_event_locked``,
    ``_record_stage_provenance_locked``) performs exactly one manifest
    read-modify-write cycle per critical section, so composing a manifest
    event with a stage-provenance entry never loses either write -- this is
    the shape Wave 2's findings/quality-report writer needs to use.
    """
    store = _create_legacy_run(tmp_path, "composed-write-topic")
    topic_id = "composed-write-topic"

    def compose(n: int) -> None:
        with store._manifest_write_lock(topic_id):
            store._append_manifest_event_locked(topic_id, {"action": f"composed-evt-{n}"})
            store._record_stage_provenance_locked(
                topic_id,
                "spec",
                provider="claude-code",
                model="claude-x",
                effort=f"composed-effort-{n}",
                source="provider",
                job_id=f"composed-job-{n}",
            )

    count = 30
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(compose, range(count)))

    manifest = store.read_manifest(topic_id)
    events = [
        e["action"] for e in manifest["events"] if e.get("action", "").startswith("composed-evt-")
    ]
    assert sorted(events) == sorted(f"composed-evt-{n}" for n in range(count))

    provenance = manifest["stage_provenance"]
    assert len(provenance) == count
    assert sorted(p["effort"] for p in provenance) == sorted(
        f"composed-effort-{n}" for n in range(count)
    )

    # File must still be valid JSON (no torn write, no lost update).
    json.loads(store.manifest_path(topic_id).read_text(encoding="utf-8"))


def test_write_spec_prompt_writes_prompt_and_response_stub(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)

    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    assert isinstance(result, PromptFile)
    assert result.stage == "spec"
    assert result.topic_id == "systems-thinking"
    assert result.artifact.stage == "spec"

    run_dir = tmp_path / "runs" / "systems-thinking"
    assert result.prompt_path == run_dir / "prompts" / "spec.prompt.md"
    assert result.response_path == run_dir / "responses" / "spec.response.md"
    assert result.stub_path == run_dir / "responses" / "spec.SAVE_RESPONSE_HERE.md"

    assert result.prompt_path.read_text(encoding="utf-8").startswith("# Spec Stage Prompt\n")
    assert "No learner profile is attached." in result.prompt_path.read_text(encoding="utf-8")

    assert not result.response_path.exists()
    assert result.stub_path.exists()
    stub_text = result.stub_path.read_text(encoding="utf-8")
    assert "spec.response.md" in stub_text
    assert "ignored" in stub_text.lower()


def test_write_spec_prompt_uses_attached_profile_snapshot(tmp_path: Path) -> None:
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("visual-profile", PROFILE_TOML)
    profiles.attach_profile_to_topic("visual-profile", "systems-thinking")

    runs = _create_legacy_run(tmp_path)
    result = runs.write_spec_prompt("systems-thinking", title="Systems Thinking")

    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "# Learner Profile Context" in prompt_text
    assert "- Professional experience: early-career analysts" in prompt_text
    assert "No learner profile is attached." not in prompt_text


def test_write_spec_prompt_records_manifest_event(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)

    store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    manifest = store.read_manifest("systems-thinking")
    assert len(manifest["events"]) == 1
    event = manifest["events"][0]
    assert event["stage"] == "spec"
    assert event["action"] == "prompt_written"
    assert event["prompt_file"] == "prompts/spec.prompt.md"
    assert event["response_file"] == "responses/spec.response.md"
    assert isinstance(event["recorded_at"], str) and event["recorded_at"]


def test_write_spec_prompt_refuses_overwrite_without_opt_in(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)
    store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    store.write_spec_prompt("systems-thinking", title="Systems Thinking", overwrite=True)

    manifest = store.read_manifest("systems-thinking")
    assert len(manifest["events"]) == 2


def test_has_ingested_response_ignores_stub(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    assert store.has_ingested_response("systems-thinking", "spec") is False

    result.response_path.write_text("# Course Specification\n", encoding="utf-8")

    assert store.has_ingested_response("systems-thinking", "spec") is True


def test_write_topic_spec_prompt_uses_stored_topic(tmp_path: Path) -> None:
    topics = TopicStore(tmp_path)
    topics.save_topic_toml("systems-thinking", TOPIC_TOML)

    runs = _create_legacy_run(tmp_path)
    result = runs.write_topic_spec_prompt("systems-thinking")

    assert isinstance(result, PromptFile)
    assert result.stage == "spec"
    assert result.topic_id == "systems-thinking"

    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "- Title: Systems Thinking" in prompt_text
    assert "- Audience: early-career analysts" in prompt_text
    assert "- Goals: explain feedback loops" in prompt_text

    manifest = runs.read_manifest("systems-thinking")
    assert manifest["events"][0]["stage"] == "spec"


def test_write_topic_spec_prompt_uses_attached_profile_snapshot(tmp_path: Path) -> None:
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("visual-profile", PROFILE_TOML)
    profiles.attach_profile_to_topic("visual-profile", "systems-thinking")
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)

    result = _create_legacy_run(tmp_path).write_topic_spec_prompt("systems-thinking")

    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "# Learner Profile Context" in prompt_text
    assert "- Professional experience: early-career analysts" in prompt_text


def test_write_topic_spec_prompt_missing_topic_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="topic file not found"):
        RunStore(tmp_path).write_topic_spec_prompt("systems-thinking")


def test_approve_stage_promotes_ingested_response(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n", encoding="utf-8")

    approved_path = store.approve_stage("systems-thinking", "spec")

    assert approved_path == tmp_path / "runs" / "systems-thinking" / "approved" / "spec.md"
    assert approved_path.read_text(encoding="utf-8") == "# Course Specification\n"
    assert store.read_approved("systems-thinking", "spec") == "# Course Specification\n"

    events = store.read_manifest("systems-thinking")["events"]
    assert events[-1]["stage"] == "spec"
    assert events[-1]["action"] == "response_approved"
    assert events[-1]["approved_file"] == "approved/spec.md"


def test_approve_stage_requires_ingested_response(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path)
    store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    with pytest.raises(ConfigError, match="no ingested response to approve"):
        store.approve_stage("systems-thinking", "spec")


def test_write_outline_prompt_uses_approved_spec_and_topic(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    spec = runs.write_topic_spec_prompt("systems-thinking")
    spec.response_path.write_text(
        "# Course Specification: Systems Thinking\n\n## Learning Outcomes\n- Explain loops.\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "spec")

    result = runs.write_outline_prompt("systems-thinking")

    assert result.stage == "outline"
    assert result.prompt_path == tmp_path / "runs" / "systems-thinking" / "prompts" / "outline.prompt.md"
    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "## Approved Specification" in prompt_text
    assert "- Explain loops." in prompt_text
    assert "- Title: Systems Thinking" in prompt_text


def test_write_outline_prompt_requires_approved_spec(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)

    with pytest.raises(ConfigError, match="approved spec response not found"):
        RunStore(tmp_path).write_outline_prompt("systems-thinking")


def test_write_draft_prompt_uses_approved_outline(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")

    outline = runs.write_outline_prompt("systems-thinking")
    outline.response_path.write_text(
        "# Course Outline: Systems Thinking\n\n## Modules\n1. Feedback loops\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "outline")

    result = runs.write_draft_prompt("systems-thinking")

    assert result.stage == "draft"
    assert result.prompt_path == tmp_path / "runs" / "systems-thinking" / "prompts" / "draft.prompt.md"
    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "## Approved Outline" in prompt_text
    assert "1. Feedback loops" in prompt_text
    assert "- Title: Systems Thinking" in prompt_text


def test_write_draft_prompt_requires_approved_outline(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="approved outline response not found"):
        runs.write_draft_prompt("systems-thinking")


def test_write_qa_prompt_uses_approved_artifacts(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")
    runs.write_outline_prompt("systems-thinking").response_path.write_text(
        "# Course Outline: Systems Thinking\n\n## Modules\n1. Feedback loops\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "outline")
    runs.write_draft_prompt("systems-thinking").response_path.write_text(
        "# Systems Thinking\n\n## Feedback loops\nA reinforcing loop amplifies change.\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "draft")

    result = runs.write_qa_prompt("systems-thinking")

    assert result.stage == "qa"
    assert result.prompt_path == tmp_path / "runs" / "systems-thinking" / "prompts" / "qa.prompt.md"
    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "## Draft Under Review" in prompt_text
    assert "A reinforcing loop amplifies change." in prompt_text
    assert "1. Feedback loops" in prompt_text
    assert "# Course Specification\n" in prompt_text


def test_write_qa_prompt_requires_approved_draft(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")
    _drive_outline_to_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="approved draft response not found"):
        runs.write_qa_prompt("systems-thinking")


def test_write_repair_prompt_uses_approved_draft_and_qa(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")
    _drive_outline_to_approved(runs, "systems-thinking")
    runs.write_draft_prompt("systems-thinking").response_path.write_text(
        "# Systems Thinking\n\n## Feedback loops\nA reinforcing loop amplifies change.\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "draft")
    runs.write_qa_prompt("systems-thinking").response_path.write_text(
        "# QA Report\n\n## Findings\n1. major - Add the boundaries module.\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "qa")

    result = runs.write_repair_prompt("systems-thinking")

    assert result.stage == "repair"
    assert result.prompt_path == tmp_path / "runs" / "systems-thinking" / "prompts" / "repair.prompt.md"
    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "## Approved QA Findings" in prompt_text
    assert "1. major - Add the boundaries module." in prompt_text
    assert "A reinforcing loop amplifies change." in prompt_text


def test_write_repair_prompt_requires_approved_qa(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")
    _drive_outline_to_approved(runs, "systems-thinking")
    _drive_draft_to_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="approved qa response not found"):
        runs.write_repair_prompt("systems-thinking")


def test_finalize_run_writes_final_guide(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(
        runs, "systems-thinking", repair_body="# Systems Thinking\n\nCorrected content.\n"
    )

    final_path = runs.finalize_run("systems-thinking")

    assert final_path == tmp_path / "runs" / "systems-thinking" / "final" / "guide.md"
    assert final_path.read_text(encoding="utf-8") == "# Systems Thinking\n\nCorrected content.\n"
    assert runs.is_finalized("systems-thinking") is True

    events = runs.read_manifest("systems-thinking")["events"]
    assert events[-1]["stage"] == "finalize"
    assert events[-1]["action"] == "finalized"
    assert events[-1]["final_file"] == "final/guide.md"


def test_finalize_run_requires_approved_repair(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")
    _drive_outline_to_approved(runs, "systems-thinking")
    _drive_draft_to_approved(runs, "systems-thinking")
    _drive_qa_to_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="approved repair response not found"):
        runs.finalize_run("systems-thinking")


def test_finalize_run_refuses_overwrite_without_opt_in(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")
    runs.finalize_run("systems-thinking")

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        runs.finalize_run("systems-thinking")

    assert runs.finalize_run("systems-thinking", overwrite=True).name == "guide.md"


def test_run_status_next_action_is_finalize_then_done(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")

    status = runs.run_status("systems-thinking")
    assert all(s.approved for s in status.stages if s.stage in REQUIRED_STAGES)
    assert next(s for s in status.stages if s.stage == "audit").state == "not_run"
    assert status.finalized is False
    assert status.next_action.action == "finalize"
    assert status.next_action.stage is None

    runs.finalize_run("systems-thinking")

    status = runs.run_status("systems-thinking")
    assert status.finalized is True
    assert status.next_action.action == "done"


def test_run_status_reports_pending_before_any_work(tmp_path: Path) -> None:
    status = RunStore(tmp_path).run_status("systems-thinking")

    assert isinstance(status, RunStatus)
    assert status.topic_id == "systems-thinking"
    assert tuple(s.stage for s in status.stages) == SUPPORTED_STAGES
    assert all(
        not s.prompt_written and not s.response_ingested and not s.approved
        for s in status.stages
    )
    assert status.stages[0].state == "pending"
    assert status.next_action == NextAction(
        topic_id="systems-thinking",
        stage="spec",
        action="write_prompt",
        detail=status.next_action.detail,
    )


def test_run_status_exposes_unrun_audit_without_changing_next_action(tmp_path: Path) -> None:
    status = RunStore(tmp_path).run_status("systems-thinking")

    assert tuple(s.stage for s in status.stages) == SUPPORTED_STAGES
    assert tuple(s.stage for s in status.stages[:-1]) == REQUIRED_STAGES
    assert tuple(s.stage for s in status.stages[-1:]) == OPTIONAL_STAGES
    audit = status.stages[-1]
    assert audit.state == "not_run"
    assert (status.next_action.stage, status.next_action.action) == ("spec", "write_prompt")


def test_existing_complete_run_remains_done_when_audit_has_not_run(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")
    runs.finalize_run("systems-thinking")

    status = runs.run_status("systems-thinking")
    assert status.next_action.action == "done"
    assert next(s for s in status.stages if s.stage == "audit").state == "not_run"


def test_audit_stage_uses_json_artifacts_and_stale_state_wins(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    paths = runs.stage_paths("systems-thinking", "audit")

    assert paths.content_type == "application/json"
    assert paths.response_path.name == "audit.response.json"
    assert paths.approved_path.name == "audit.json"
    assert StageStatus(
        stage="audit",
        prompt_written=True,
        response_ingested=True,
        approved=True,
        stale=True,
    ).state == "stale"


def test_audit_stage_refuses_an_unbound_handwritten_prompt(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    paths = runs.stage_paths("systems-thinking", "audit")
    paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path.write_text("AUDIT PROMPT", encoding="utf-8")

    with pytest.raises(StaleContentError, match="audit prompt is stale"):
        runs.ingest_response("systems-thinking", "audit", '{"findings": []}')
    assert runs.stage_status("systems-thinking", "audit").state == "stale"


def test_personalization_audit_requires_current_final_validation_profile_and_trace(
    tmp_path: Path,
) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_draft_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="final validation is not current"):
        runs.prepare_personalization_audit("systems-thinking")

    _drive_profiled_guide_to_finalize_ready(
        _create_profiled_guide_run(tmp_path / "ready"), "systems-thinking"
    )
    ready = RunStore(tmp_path / "ready")
    ready.personalization_trace_path("systems-thinking").unlink()
    with pytest.raises(ConfigError, match="personalization trace is not current"):
        ready.prepare_personalization_audit("systems-thinking")

    unprofiled = _create_guide_run(tmp_path / "unprofiled")
    _drive_guide_to_finalize_ready(unprofiled, "systems-thinking")
    with pytest.raises(ConfigError) as caught:
        unprofiled.prepare_personalization_audit("systems-thinking")
    assert str(caught.value) == (
        "personalization audit unavailable: no attached profile snapshot"
    )


def test_prepare_ingest_and_approve_audit_binds_exact_inputs_and_safe_projection(
    tmp_path: Path,
) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)

    prepared = runs.prepare_personalization_audit(tid)
    assert prepared.prompt_path == runs.run_dir(tid) / "prompts" / "audit.prompt.md"
    assert prepared.response_path == runs.run_dir(tid) / "responses" / "audit.response.json"
    assert prepared.artifact.stage == "audit"
    assert runs.audit_state(tid) == "not_run"
    assert runs.audit_prompt_is_current(tid) is True
    prompt_event = runs._latest_stage_event(tid, "audit", "prompt_written")
    assert prompt_event is not None
    assert prompt_event["guide_sha256"] == json.loads(
        runs.personalization_trace_path(tid).read_text(encoding="utf-8")
    )["guide_sha256"]
    assert prompt_event["profile_snapshot_file_sha256"] == hashlib.sha256(
        ProfileStore(tmp_path).topic_profile_snapshot_path(tid).read_bytes()
    ).hexdigest()
    assert prompt_event["personalization_trace_file_sha256"] == hashlib.sha256(
        runs.personalization_trace_path(tid).read_bytes()
    ).hexdigest()

    response = _valid_personalization_audit_response(runs, tid)
    assert runs.ingest_response(tid, "audit", response).name == "audit.response.json"
    assert runs.audit_state(tid) == "not_run"
    assert runs.approve_stage(tid, "audit").name == "audit.json"
    projection = runs.audit_projection_path(tid)
    assert projection.name == "personalization-audit-projection.json"
    assert projection.is_file()
    assert runs.audit_state(tid) == "current"
    assert runs.stage_status(tid, "audit").state == "approved"

    public_bytes = projection.read_bytes()
    private_hashes = (
        prompt_event["profile_snapshot_file_sha256"],
        prompt_event["personalization_trace_file_sha256"],
        hashlib.sha256(runs.approved_path(tid, "audit").read_bytes()).hexdigest(),
    )
    for private_hash in private_hashes:
        assert private_hash.encode("ascii") not in public_bytes
    approval = runs._latest_stage_event(tid, "audit", "response_approved")
    assert approval is not None
    assert approval["approved_file_sha256"] == hashlib.sha256(
        runs.approved_path(tid, "audit").read_bytes()
    ).hexdigest()
    assert approval["audit_projection_file_sha256"] == hashlib.sha256(
        projection.read_bytes()
    ).hexdigest()


def test_identical_audit_prompt_rebuild_preserves_current_approval(tmp_path: Path) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    runs.prepare_personalization_audit(tid)
    runs.ingest_response(tid, "audit", _valid_personalization_audit_response(runs, tid))
    runs.approve_stage(tid, "audit")
    original_prompt = runs.stage_paths(tid, "audit").prompt_path.read_bytes()
    original_projection = runs.audit_projection_path(tid).read_bytes()
    assert runs.audit_state(tid) == "current"

    runs.prepare_personalization_audit(tid, overwrite=True)

    assert runs.stage_paths(tid, "audit").prompt_path.read_bytes() == original_prompt
    assert runs.audit_projection_path(tid).read_bytes() == original_projection
    assert runs.audit_state(tid) == "current"
    assert runs.stage_status(tid, "audit").state == "approved"


def test_audit_before_or_after_finalize_is_equivalent_and_never_required(
    tmp_path: Path,
) -> None:
    before = _create_profiled_guide_run(tmp_path / "before")
    after = _create_profiled_guide_run(tmp_path / "after")
    tid = "systems-thinking"
    for runs in (before, after):
        _drive_profiled_guide_to_finalize_ready(runs, tid)

    before.prepare_personalization_audit(tid)
    before_prompt = before.stage_paths(tid, "audit").prompt_path.read_bytes()
    response = _valid_personalization_audit_response(before, tid)
    before.ingest_response(tid, "audit", response)
    before.approve_stage(tid, "audit")
    before.finalize_run(tid)

    after.finalize_run(tid)
    assert after.run_status(tid).next_action.action == "done"
    assert after.export_run(tid, format="html").is_file()
    after.prepare_personalization_audit(tid)
    assert after.stage_paths(tid, "audit").prompt_path.read_bytes() == before_prompt
    after.ingest_response(tid, "audit", _valid_personalization_audit_response(after, tid))
    after.approve_stage(tid, "audit")
    assert after.audit_projection_path(tid).read_bytes() == before.audit_projection_path(
        tid
    ).read_bytes()
    assert after.run_status(tid).next_action.action == "done"


def test_trace_tamper_stales_audit_and_exact_regeneration_restores_it(
    tmp_path: Path,
) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    runs.prepare_personalization_audit(tid)
    runs.ingest_response(tid, "audit", _valid_personalization_audit_response(runs, tid))
    runs.approve_stage(tid, "audit")
    assert runs.audit_state(tid) == "current"

    trace_path = runs.personalization_trace_path(tid)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["active_facets"] = []
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    assert runs.audit_state(tid) == "stale"
    assert runs.audit_prompt_is_current(tid) is False
    assert runs.stage_status(tid, "audit").state == "stale"
    with pytest.raises(StaleContentError, match="audit prompt is stale"):
        runs.ingest_response(tid, "audit", "{}", force=True)

    runs.validate_run(tid, "final")
    runs.prepare_personalization_audit(tid, overwrite=True)
    assert runs.audit_state(tid) == "current"
    assert runs.audit_prompt_is_current(tid) is True
    assert runs.require_provider_ready_prompt(tid, "audit") == runs.stage_paths(
        tid, "audit"
    ).prompt_path


def test_rebuild_for_different_current_inputs_does_not_revive_old_approval(
    tmp_path: Path,
) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    runs.prepare_personalization_audit(tid)
    runs.ingest_response(tid, "audit", _valid_personalization_audit_response(runs, tid))
    runs.approve_stage(tid, "audit")
    assert runs.audit_state(tid) == "current"

    profiles = ProfileStore(tmp_path)
    replacement = PERSONALIZED_PROFILE_TOML.replace(
        "Synthetic private goal alpha", "Synthetic replacement goal alpha"
    )
    profiles.save_profile_toml("personalized-profile", replacement, overwrite=True)
    profiles.attach_profile_to_topic("personalized-profile", tid, overwrite=True)
    runs.validate_run(tid, "final")
    assert runs.audit_state(tid) == "stale"

    runs.prepare_personalization_audit(tid, overwrite=True)

    assert runs.audit_prompt_is_current(tid) is True
    assert runs.audit_state(tid) == "stale"
    assert runs.stage_status(tid, "audit").state == "stale"


def test_provider_ready_audit_prompt_refuses_missing_and_stale_inputs(tmp_path: Path) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)

    with pytest.raises(ConfigError, match="audit prompt is missing"):
        runs.require_provider_ready_prompt(tid, "audit")
    runs.prepare_personalization_audit(tid)
    runs.approved_path(tid, "repair").write_text("{}", encoding="utf-8")
    with pytest.raises(StaleContentError, match="audit prompt is stale"):
        runs.require_provider_ready_prompt(tid, "audit")


@pytest.mark.parametrize("mutation", ["repair", "profile"])
def test_repair_or_profile_replacement_invalidates_an_approved_audit(
    tmp_path: Path, mutation: str
) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    runs.prepare_personalization_audit(tid)
    runs.ingest_response(tid, "audit", _valid_personalization_audit_response(runs, tid))
    runs.approve_stage(tid, "audit")

    if mutation == "repair":
        runs.approved_path(tid, "repair").write_text("{}", encoding="utf-8")
    else:
        profiles = ProfileStore(tmp_path)
        replacement = PERSONALIZED_PROFILE_TOML.replace(
            "Synthetic private goal alpha", "Synthetic replacement goal alpha"
        )
        profiles.save_profile_toml(
            "personalized-profile", replacement, overwrite=True
        )
        profiles.attach_profile_to_topic(
            "personalized-profile", tid, overwrite=True
        )

    assert runs.audit_state(tid) == "stale"
    assert runs.audit_prompt_is_current(tid) is False


def test_audit_ingest_and_approval_shape_errors_are_safe(tmp_path: Path) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    runs.prepare_personalization_audit(tid)

    with pytest.raises(ConfigError) as ingest_error:
        runs.ingest_response(tid, "audit", '{"secret":"PLANTED PRIVATE VALUE"}')
    assert "PLANTED PRIVATE VALUE" not in str(ingest_error.value)

    valid = _valid_personalization_audit_response(runs, tid)
    runs.ingest_response(tid, "audit", valid)
    runs.response_path(tid, "audit").write_text(
        '{"secret":"SECOND PLANTED PRIVATE VALUE"}', encoding="utf-8"
    )
    with pytest.raises(ConfigError) as approval_error:
        runs.approve_stage(tid, "audit")
    assert "SECOND PLANTED PRIVATE VALUE" not in str(approval_error.value)


def test_failed_audit_projection_write_cannot_leave_approval_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    tid = "systems-thinking"
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    runs.prepare_personalization_audit(tid)
    runs.ingest_response(tid, "audit", _valid_personalization_audit_response(runs, tid))
    runs.approve_stage(tid, "audit")
    assert runs.audit_state(tid) == "current"
    runs.ingest_response(
        tid,
        "audit",
        _valid_personalization_audit_response(runs, tid).replace(
            "Synthetic local tailoring summary.",
            "Synthetic replacement tailoring summary.",
        ),
        force=True,
    )

    import education_pipeline.runs as runs_module

    real_write = runs_module._write_bytes_atomic

    def fail_projection(path: Path, data: bytes) -> None:
        if path == runs.audit_projection_path(tid):
            raise OSError("synthetic projection write failure")
        real_write(path, data)

    monkeypatch.setattr(runs_module, "_write_bytes_atomic", fail_projection)
    with pytest.raises(OSError, match="synthetic projection write failure"):
        runs.approve_stage(tid, "audit", overwrite=True)
    assert runs.audit_state(tid) == "stale"
    assert runs.stage_status(tid, "audit").state == "stale"


def test_run_status_advances_through_spec_substates(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)

    result = runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    action = runs.run_status("systems-thinking").next_action
    assert (action.stage, action.action) == ("spec", "save_response")

    result.response_path.write_text("# Course Specification\n", encoding="utf-8")
    action = runs.run_status("systems-thinking").next_action
    assert (action.stage, action.action) == ("spec", "approve")

    runs.approve_stage("systems-thinking", "spec")
    status = runs.run_status("systems-thinking")
    assert status.stages[0].state == "approved"
    assert (status.next_action.stage, status.next_action.action) == ("outline", "write_prompt")


def test_advance_writes_the_next_prompt(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)

    result = runs.advance("systems-thinking")

    assert isinstance(result, AdvanceResult)
    assert result.performed == "write_prompt"
    assert (tmp_path / "runs" / "systems-thinking" / "prompts" / "spec.prompt.md").exists()
    assert result.status.next_action.action == "save_response"


def test_advance_pauses_on_human_steps(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    runs.advance("systems-thinking")  # writes the spec prompt

    result = runs.advance("systems-thinking")

    assert result.performed is None
    assert result.status.next_action.action == "save_response"


def test_advance_finalizes_when_all_stages_approved(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")

    result = runs.advance("systems-thinking")

    assert result.performed == "finalize"
    assert result.status.finalized is True
    assert result.status.next_action.action == "done"


def test_advance_is_noop_when_done(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")
    runs.finalize_run("systems-thinking")

    result = runs.advance("systems-thinking")

    assert result.performed is None
    assert result.status.next_action.action == "done"


def test_advance_drives_a_full_run_with_human_steps(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)

    for _ in range(50):
        status = runs.advance("systems-thinking").status
        action = status.next_action
        if action.action == "done":
            break
        if action.action == "save_response":
            runs.stage_paths("systems-thinking", action.stage).response_path.write_text(
                f"# {action.stage} output\n", encoding="utf-8"
            )
        elif action.action == "approve":
            runs.approve_stage("systems-thinking", action.stage)
    else:  # pragma: no cover - guards against a non-converging loop
        raise AssertionError("advance did not reach done")

    final_status = runs.run_status("systems-thinking")
    assert final_status.finalized is True
    assert final_status.next_action.action == "done"
    assert (tmp_path / "runs" / "systems-thinking" / "final" / "guide.md").exists()


def test_export_run_writes_html(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(
        runs, "systems-thinking", repair_body="# Systems Thinking\n\nCorrected content.\n"
    )
    runs.finalize_run("systems-thinking")

    path = runs.export_run("systems-thinking", format="html")

    assert path == tmp_path / "runs" / "systems-thinking" / "final" / "guide.html"
    html = path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "<h1>Systems Thinking</h1>" in html
    assert "<p>Corrected content.</p>" in html

    events = runs.read_manifest("systems-thinking")["events"]
    assert events[-1]["stage"] == "export"
    assert events[-1]["action"] == "exported"
    assert events[-1]["export_file"] == "final/guide.html"


def test_export_run_writes_markdown_bundle(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking", repair_body="# Systems Thinking\n")
    runs.finalize_run("systems-thinking")

    path = runs.export_run("systems-thinking", format="markdown")

    assert path == tmp_path / "runs" / "systems-thinking" / "final" / "guide.bundle.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "title: Systems Thinking\n" in text
    assert "topic_id: systems-thinking\n" in text
    assert "# Systems Thinking" in text


def test_export_run_requires_finalized(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="not finalized"):
        runs.export_run("systems-thinking", format="html")


def test_export_run_rejects_unknown_format(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")
    runs.finalize_run("systems-thinking")

    with pytest.raises(ConfigError, match="unsupported export format"):
        runs.export_run("systems-thinking", format="pdf")


def test_stage_status_rejects_unsupported_stage(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported run stage"):
        RunStore(tmp_path).stage_status("systems-thinking", "finalize")


def test_stage_status_returns_flags(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")

    status = runs.stage_status("systems-thinking", "spec")

    assert isinstance(status, StageStatus)
    assert status.prompt_written is True
    assert status.response_ingested is False
    assert status.approved is False


def test_list_run_ids_returns_started_runs(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)
    assert runs.list_run_ids() == ()

    runs.create_run("beta-topic", content_contract=ContentContract.legacy_markdown())
    runs.create_run("alpha-topic", content_contract=ContentContract.legacy_markdown())
    runs.write_spec_prompt("beta-topic", title="Beta")
    runs.write_spec_prompt("alpha-topic", title="Alpha")

    assert runs.list_run_ids() == ("alpha-topic", "beta-topic")


def test_run_store_rejects_path_traversal_topic_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(ConfigError, match="topic id must match"):
        store.create_run("../escape")

    with pytest.raises(ConfigError, match="topic id must match"):
        store.write_spec_prompt("../escape", title="Systems Thinking")


def test_write_spec_prompt_rejects_unknown_stage_helper(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(ConfigError, match="unsupported run stage"):
        store.stage_paths("systems-thinking", "finalize")


def test_ingest_response_writes_response_atomically(tmp_path):
    runs = _create_legacy_run(tmp_path)
    path = runs.ingest_response("systems-thinking", "draft", "# Draft body\n")
    assert path == runs.response_path("systems-thinking", "draft")
    assert path.read_text(encoding="utf-8") == "# Draft body\n"
    assert runs.has_ingested_response("systems-thinking", "draft")


def test_ingest_response_rejects_empty(tmp_path):
    runs = _create_legacy_run(tmp_path)
    with pytest.raises(ConfigError):
        runs.ingest_response("systems-thinking", "draft", "   \n\t ")


def test_ingest_response_refuses_clobber_unless_forced(tmp_path):
    runs = _create_legacy_run(tmp_path)
    runs.ingest_response("systems-thinking", "draft", "first\n")
    with pytest.raises(ConfigError):
        runs.ingest_response("systems-thinking", "draft", "second\n")
    path = runs.ingest_response("systems-thinking", "draft", "second\n", force=True)
    assert path.read_text(encoding="utf-8") == "second\n"


def test_append_manifest_event_records_event(tmp_path):
    runs = _create_legacy_run(tmp_path)
    runs.append_manifest_event(
        "systems-thinking", {"stage": "draft", "action": "job", "job_id": "j1"}
    )
    events = runs.read_manifest("systems-thinking")["events"]
    assert events[-1]["action"] == "job"
    assert events[-1]["job_id"] == "j1"
    assert "recorded_at" in events[-1]


def test_record_stage_provenance_appends_and_preserves_prior_entries(tmp_path):
    runs = _create_legacy_run(tmp_path)
    runs.record_stage_provenance(
        "systems-thinking",
        "draft",
        provider="fake",
        model="m",
        effort="high",
        source="override",
        job_id="j1",
    )
    runs.record_stage_provenance(
        "systems-thinking",
        "draft",
        provider="fake",
        model="m2",
        effort=None,
        source="default",
        job_id="j2",
    )
    entries = runs.read_manifest("systems-thinking")["stage_provenance"]
    assert len(entries) == 2
    first, second = entries
    assert first == {
        "stage": "draft",
        "provider": "fake",
        "model": "m",
        "effort": "high",
        "source": "override",
        "job_id": "j1",
        "recorded_at": first["recorded_at"],
    }
    assert "recorded_at" in first
    assert second["model"] == "m2"
    assert second["job_id"] == "j2"
    # prior entry preserved, not overwritten
    assert entries[0]["job_id"] == "j1"


def test_record_stage_provenance_defaults_job_id_to_none(tmp_path):
    runs = _create_legacy_run(tmp_path)
    runs.record_stage_provenance(
        "systems-thinking",
        "spec",
        provider="manual",
        model=None,
        effort=None,
        source="manual",
    )
    entry = runs.read_manifest("systems-thinking")["stage_provenance"][0]
    assert entry["job_id"] is None
    assert entry["model"] is None
    assert entry["effort"] is None


def test_export_path_names_and_bad_format(tmp_path):
    from education_pipeline.config import ConfigError
    from education_pipeline.runs import RunStore

    runs = RunStore(tmp_path)
    assert runs.export_path("t", "html").name == "guide.html"
    assert runs.export_path("t", "markdown").name == "guide.bundle.md"
    import pytest

    with pytest.raises(ConfigError):
        runs.export_path("t", "docx")


def _response_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_edit_response_rewrites_content_and_records_event(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path, "t")
    path = store.ingest_response("t", "draft", "old body\n")

    result = store.edit_response(
        "t", "draft", "new body\n", base_sha256=_response_sha(path)
    )

    assert result == path
    assert path.read_text(encoding="utf-8") == "new body\n"
    assert _response_sha(path) == hashlib.sha256(b"new body\n").hexdigest()
    events = store.read_manifest("t")["events"]
    edited = [e for e in events if e["action"] == "response_edited"]
    assert len(edited) == 1
    assert edited[0]["stage"] == "draft"
    assert edited[0]["response_file"] == "responses/draft.response.md"
    assert edited[0]["recorded_at"]


def test_edit_response_rejects_stale_hash(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path, "t")
    path = store.ingest_response("t", "draft", "old body\n")
    loaded_sha = _response_sha(path)
    path.write_text("changed by someone else\n", encoding="utf-8")

    with pytest.raises(StaleContentError):
        store.edit_response("t", "draft", "my edit\n", base_sha256=loaded_sha)

    # The concurrent edit is never overwritten.
    assert path.read_text(encoding="utf-8") == "changed by someone else\n"


def test_edit_response_requires_existing_response(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path, "t")

    with pytest.raises(ConfigError):
        store.edit_response("t", "draft", "text\n", base_sha256="0" * 64)


def test_edit_response_rejects_empty_text(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path, "t")
    path = store.ingest_response("t", "draft", "old body\n")

    with pytest.raises(ConfigError):
        store.edit_response("t", "draft", "   \n", base_sha256=_response_sha(path))


def test_edit_response_rejects_bad_stage_and_topic(tmp_path: Path) -> None:
    store = _create_legacy_run(tmp_path, "t")

    with pytest.raises(ConfigError):
        store.edit_response("t", "bogus", "text\n", base_sha256="0" * 64)
    with pytest.raises(ConfigError):
        store.edit_response("../evil", "draft", "text\n", base_sha256="0" * 64)


# --- guide-v1 approval gates, prompts, and contract file --------------------


def test_guide_v1_spec_approval_requires_contract_block(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path)
    result = runs.write_topic_spec_prompt("systems-thinking")
    result.response_path.write_text("# Spec without a contract fence\n", encoding="utf-8")
    before_events = list(runs.read_manifest("systems-thinking")["events"])
    approved = runs.approved_path("systems-thinking", "spec")

    with pytest.raises(ConfigError, match=r"cannot approve spec for guide run.*fenced") as exc_info:
        runs.approve_stage("systems-thinking", "spec")

    assert "education-pipeline-contract+json" in str(exc_info.value)
    assert not approved.exists()
    events = runs.read_manifest("systems-thinking")["events"]
    assert events == before_events
    assert not any(e.get("action") == "response_approved" for e in events)
    assert runs.run_status("systems-thinking").next_action.action == "approve"


def test_guide_v1_spec_approval_with_valid_block_succeeds(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path)
    result = runs.write_topic_spec_prompt("systems-thinking")
    result.response_path.write_text(_guide_spec_response(), encoding="utf-8")

    approved = runs.approve_stage("systems-thinking", "spec")

    assert approved.exists()
    assert extract_spec_contract(approved.read_text(encoding="utf-8")) == VALID_SPEC_CONTRACT
    events = runs.read_manifest("systems-thinking")["events"]
    assert events[-1]["action"] == "response_approved"
    assert events[-1]["stage"] == "spec"


def test_guide_v1_outline_approval_requires_block_and_conflict_checks(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path)
    _drive_guide_spec_to_approved(runs, "systems-thinking")
    outline = runs.write_outline_prompt("systems-thinking")

    outline.response_path.write_text("# Outline without fence\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"cannot approve outline for guide run.*fenced"):
        runs.approve_stage("systems-thinking", "outline")
    assert not runs.approved_path("systems-thinking", "outline").exists()

    bad_version = {**VALID_OUTLINE_CONTRACT, "contract_version": 2}
    outline.response_path.write_text(_guide_outline_response(bad_version), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"cannot approve outline for guide run"):
        runs.approve_stage("systems-thinking", "outline")

    unknown_outcome = {
        "contract_version": 1,
        "modules": {
            "feedback-loops": {
                "outcome_ids": ["missing-outcome"],
                "estimated_minutes": 30,
                "interaction_types": ["knowledge_check"],
            },
        },
    }
    outline.response_path.write_text(_guide_outline_response(unknown_outcome), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"cannot approve outline for guide run.*unknown outcome"):
        runs.approve_stage("systems-thinking", "outline")
    assert not runs.approved_path("systems-thinking", "outline").exists()

    outline.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    approved = runs.approve_stage("systems-thinking", "outline")
    assert extract_outline_contract(approved.read_text(encoding="utf-8")) == VALID_OUTLINE_CONTRACT


def test_guide_v1_draft_prompt_writes_immutable_guide_contract(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path)
    _drive_guide_spec_to_approved(runs, "systems-thinking")
    _drive_guide_outline_to_approved(runs, "systems-thinking")

    expected = build_guide_contract(VALID_SPEC_CONTRACT, VALID_OUTLINE_CONTRACT)
    result = runs.write_draft_prompt("systems-thinking")
    contract_path = tmp_path / "runs" / "systems-thinking" / "inputs" / "guide-contract.json"
    assert contract_path.read_bytes() == expected

    # Unchanged upstream + overwrite leaves bytes identical.
    runs.write_draft_prompt("systems-thinking", overwrite=True)
    assert contract_path.read_bytes() == expected

    # Reapprove outline with different modules; overwrite=False refuses divergent rewrite.
    alt_outline = {
        "contract_version": 1,
        "modules": {
            "boundaries": {
                "outcome_ids": ["identify-loop"],
                "estimated_minutes": 20,
                "interaction_types": ["scenario", "reflection"],
            },
        },
    }
    outline_paths = runs.stage_paths("systems-thinking", "outline")
    outline_paths.response_path.write_text(_guide_outline_response(alt_outline), encoding="utf-8")
    runs.approve_stage("systems-thinking", "outline", overwrite=True)

    with pytest.raises(ConfigError, match="immutable"):
        runs.write_draft_prompt("systems-thinking", overwrite=False)

    assert contract_path.read_bytes() == expected

    runs.write_draft_prompt("systems-thinking", overwrite=True)
    rewritten = build_guide_contract(VALID_SPEC_CONTRACT, alt_outline)
    assert contract_path.read_bytes() == rewritten
    assert result.stage == "draft"


def test_guide_v1_prompt_text_contains_contract_markers(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path)

    spec = runs.write_topic_spec_prompt("systems-thinking")
    assert "education-pipeline-contract+json" in spec.prompt_path.read_text(encoding="utf-8")

    spec.response_path.write_text(_guide_spec_response(), encoding="utf-8")
    runs.approve_stage("systems-thinking", "spec")
    outline = runs.write_outline_prompt("systems-thinking")
    assert "education-pipeline-outline+json" in outline.prompt_path.read_text(encoding="utf-8")

    outline.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage("systems-thinking", "outline")
    draft = runs.write_draft_prompt("systems-thinking")
    draft_text = draft.prompt_path.read_text(encoding="utf-8")
    contract_bytes = build_guide_contract(VALID_SPEC_CONTRACT, VALID_OUTLINE_CONTRACT)
    assert contract_bytes.decode("utf-8") in draft_text
    assert "Return exactly one JSON object" in draft_text


def test_guide_v1_contract_omits_non_publishable_profile_summary(tmp_path: Path) -> None:
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("visual-profile", PROFILE_TOML)
    profiles.attach_profile_to_topic("visual-profile", "systems-thinking")
    runs = _create_guide_run(tmp_path)
    _drive_guide_spec_to_approved(runs, "systems-thinking")
    _drive_guide_outline_to_approved(runs, "systems-thinking")

    runs.write_draft_prompt("systems-thinking")
    payload = json.loads(
        (tmp_path / "runs" / "systems-thinking" / "inputs" / "guide-contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert "publishable_profile_summary" not in payload


def test_guide_v1_contract_includes_publishable_profile_summary(tmp_path: Path) -> None:
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("publishable-profile", PUBLISHABLE_PROFILE_TOML)
    profiles.attach_profile_to_topic("publishable-profile", "systems-thinking")
    runs = _create_guide_run(tmp_path)
    _drive_guide_spec_to_approved(runs, "systems-thinking")
    _drive_guide_outline_to_approved(runs, "systems-thinking")

    runs.write_draft_prompt("systems-thinking")
    payload = json.loads(
        (tmp_path / "runs" / "systems-thinking" / "inputs" / "guide-contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["publishable_profile_summary"] == "Early-career team learning systems thinking."


def test_guide_v1_prompt_written_events_record_upstream_hashes(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path)
    _drive_guide_spec_to_approved(runs, "systems-thinking")

    runs.write_outline_prompt("systems-thinking")
    outline_event = next(
        e
        for e in reversed(runs.read_manifest("systems-thinking")["events"])
        if e["action"] == "prompt_written" and e["stage"] == "outline"
    )
    spec_approved = runs.approved_path("systems-thinking", "spec")
    assert outline_event["source_spec_file"] == "approved/spec.md"
    assert outline_event["source_spec_file_sha256"] == hashlib.sha256(
        spec_approved.read_bytes()
    ).hexdigest()

    outline = runs.stage_paths("systems-thinking", "outline")
    outline.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage("systems-thinking", "outline")
    runs.write_draft_prompt("systems-thinking")

    draft_event = next(
        e
        for e in reversed(runs.read_manifest("systems-thinking")["events"])
        if e["action"] == "prompt_written" and e["stage"] == "draft"
    )
    outline_approved = runs.approved_path("systems-thinking", "outline")
    contract_path = tmp_path / "runs" / "systems-thinking" / "inputs" / "guide-contract.json"
    assert draft_event["source_outline_file"] == "approved/outline.md"
    assert draft_event["source_outline_file_sha256"] == hashlib.sha256(
        outline_approved.read_bytes()
    ).hexdigest()
    assert draft_event["contract_file"] == "inputs/guide-contract.json"
    assert draft_event["contract_file_sha256"] == hashlib.sha256(contract_path.read_bytes()).hexdigest()


def test_ingest_response_force_records_replaced_response_hash(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    old_text = "first response\n"
    path = runs.ingest_response("systems-thinking", "draft", old_text)
    old_sha = hashlib.sha256(old_text.encode("utf-8")).hexdigest()

    runs.ingest_response("systems-thinking", "draft", "second response\n", force=True)

    events = runs.read_manifest("systems-thinking")["events"]
    replaced = [e for e in events if e["action"] == "response_replaced"]
    assert len(replaced) == 1
    assert replaced[0]["stage"] == "draft"
    assert replaced[0]["replaced_response_file"] == "responses/draft.response.md"
    assert replaced[0]["replaced_response_file_sha256"] == old_sha
    assert path.read_text(encoding="utf-8") == "second response\n"
    assert hashlib.sha256(path.read_bytes()).hexdigest() != old_sha


def test_guide_v1_write_spec_prompt_uses_guide_compiler(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking", content_contract=ContentContract.interactive_guide_v1())
    result = runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    assert "education-pipeline-contract+json" in result.prompt_path.read_text(encoding="utf-8")


# --- Wave 4 Slice B: validation lifecycle, freshness, guarded finalization ---


def test_guide_v1_full_walk_via_advance(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    actions: list[tuple[str | None, str]] = []

    def snapshot() -> tuple[str | None, str]:
        na = runs.run_status(tid).next_action
        return (na.stage, na.action)

    # Machine: write_prompt for spec
    assert snapshot() == ("spec", "write_prompt")
    assert runs.advance(tid).performed == "write_prompt"
    runs.stage_paths(tid, "spec").response_path.write_text(
        _guide_spec_response(), encoding="utf-8"
    )
    assert snapshot() == ("spec", "approve")
    runs.approve_stage(tid, "spec")

    assert snapshot() == ("outline", "write_prompt")
    assert runs.advance(tid).performed == "write_prompt"
    runs.stage_paths(tid, "outline").response_path.write_text(
        _guide_outline_response(), encoding="utf-8"
    )
    runs.approve_stage(tid, "outline")

    assert snapshot() == ("draft", "write_prompt")
    assert runs.advance(tid).performed == "write_prompt"
    runs.stage_paths(tid, "draft").response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs.approve_stage(tid, "draft")

    assert snapshot() == ("draft", "validate")
    actions.append(snapshot())
    assert runs.advance(tid).performed == "validate"
    assert runs.report_state(tid, "draft") == "current"

    assert snapshot() == ("qa", "write_prompt")
    assert runs.advance(tid).performed == "write_prompt"
    runs.stage_paths(tid, "qa").response_path.write_text("# QA\n", encoding="utf-8")
    runs.approve_stage(tid, "qa")

    assert snapshot() == ("repair", "write_prompt")
    assert runs.advance(tid).performed == "write_prompt"
    runs.stage_paths(tid, "repair").response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs.approve_stage(tid, "repair")

    assert snapshot() == ("repair", "validate")
    actions.append(snapshot())
    assert runs.advance(tid).performed == "validate"
    assert runs.report_state(tid, "final") == "current"

    assert snapshot() == (None, "finalize")
    actions.append(snapshot())
    assert runs.advance(tid).performed == "finalize"
    assert snapshot() == (None, "done")
    actions.append(snapshot())

    assert ("draft", "validate") in actions
    assert ("repair", "validate") in actions
    assert (None, "finalize") in actions
    assert (None, "done") in actions

    contract = tmp_path / "runs" / tid / "inputs" / "guide-contract.json"
    assert contract.is_file()
    assert runs.draft_report_path(tid).is_file()
    assert runs.final_report_path(tid).is_file()

    expected_guide = normalize_guide(parse_guide(GUIDE_FIXTURE))
    assert runs.final_guide_json_path(tid).read_bytes() == canonical_guide_bytes(expected_guide)
    assert runs.final_guide_md_path(tid).read_text(encoding="utf-8") == project_guide_markdown(
        expected_guide
    )

    finalized = next(
        e
        for e in reversed(runs.read_manifest(tid)["events"])
        if e["action"] == "finalized"
    )
    assert finalized["guide_sha256"] == guide_sha256(expected_guide)
    assert "final_json_file_sha256" in finalized
    assert "final_md_file_sha256" in finalized
    assert "source_file_sha256" in finalized
    assert "report_file_sha256" in finalized
    assert runs.is_finalized(tid)


def test_guide_v1_qa_prompt_gate_and_content(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_draft_approved(runs, tid)

    with pytest.raises(ConfigError, match="draft validation"):
        runs.write_qa_prompt(tid)

    runs.validate_run(tid, "draft")
    result = runs.write_qa_prompt(tid)
    text = result.prompt_path.read_text(encoding="utf-8")
    assert "report_schema_version" in text
    assert "<<<BEGIN UNTRUSTED DATA" in text

    event = next(
        e
        for e in reversed(runs.read_manifest(tid)["events"])
        if e["action"] == "prompt_written" and e["stage"] == "qa"
    )
    draft_approved = runs.approved_path(tid, "draft")
    report = runs.draft_report_path(tid)
    assert event["source_draft_file_sha256"] == hashlib.sha256(
        draft_approved.read_bytes()
    ).hexdigest()
    assert event["draft_report_file_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()


def test_guide_v1_repair_prompt_content_and_event_extras(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(runs, tid)

    result = runs.write_repair_prompt(tid)
    text = result.prompt_path.read_text(encoding="utf-8")
    contract_bytes = (tmp_path / "runs" / tid / "inputs" / "guide-contract.json").read_bytes()
    assert contract_bytes.decode("utf-8") in text
    assert "report_schema_version" in text

    event = next(
        e
        for e in reversed(runs.read_manifest(tid)["events"])
        if e["action"] == "prompt_written" and e["stage"] == "repair"
    )
    assert "source_draft_file_sha256" in event
    assert "source_qa_file_sha256" in event
    assert "draft_report_file_sha256" in event
    assert "contract_file_sha256" in event


def test_guide_v1_unparseable_draft_blocks_qa(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_draft_approved(runs, tid, draft_body="not json {")

    report_path = runs.validate_run(tid, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["findings"]
    assert report["guide_sha256"] == hashlib.sha256(b"not json {").hexdigest()

    with pytest.raises(ConfigError, match="malformed"):
        runs.write_qa_prompt(tid)

    na = runs.run_status(tid).next_action
    assert na.stage == "draft"
    assert na.action == "resolve_findings"


def test_guide_v1_idempotent_revalidation(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_draft_approved(runs, tid)

    first = runs.validate_run(tid, "draft").read_bytes()
    second = runs.validate_run(tid, "draft").read_bytes()
    assert first == second


def test_guide_v1_draft_edit_invalidates_report_and_qa(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(runs, tid)

    draft_report = runs.draft_report_path(tid)
    qa_approved = runs.approved_path(tid, "qa")
    assert draft_report.is_file()
    assert qa_approved.is_file()
    report_before = draft_report.read_bytes()

    draft_paths = runs.stage_paths(tid, "draft")
    base_sha = hashlib.sha256(draft_paths.response_path.read_bytes()).hexdigest()
    edited = _edit_course_description(
        draft_paths.response_path.read_text(encoding="utf-8"),
        "Edited course description for invalidation test.",
    )
    runs.edit_response(tid, "draft", edited, base_sha256=base_sha)
    runs.approve_stage(tid, "draft", overwrite=True)

    assert runs.report_state(tid, "draft") == "stale"
    assert draft_report.is_file()
    assert draft_report.read_bytes() == report_before
    assert qa_approved.is_file()

    na = runs.run_status(tid).next_action
    assert (na.stage, na.action) == ("draft", "validate")
    qa_status = next(s for s in runs.run_status(tid).stages if s.stage == "qa")
    assert qa_status.stale is True


def test_guide_v1_repair_edit_unfinalizes_without_deleting_artifacts(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)
    runs.finalize_run(tid)

    final_json = runs.final_guide_json_path(tid)
    final_md = runs.final_guide_md_path(tid)
    assert final_json.is_file() and final_md.is_file()
    assert runs.is_finalized(tid)

    repair_paths = runs.stage_paths(tid, "repair")
    base_sha = hashlib.sha256(repair_paths.response_path.read_bytes()).hexdigest()
    edited = _edit_course_description(
        repair_paths.response_path.read_text(encoding="utf-8"),
        "Edited repair description after finalize.",
    )
    runs.edit_response(tid, "repair", edited, base_sha256=base_sha)
    runs.approve_stage(tid, "repair", overwrite=True)

    assert runs.report_state(tid, "final") == "stale"
    assert runs.is_finalized(tid) is False
    assert runs.run_status(tid).finalized is False
    na = runs.run_status(tid).next_action
    assert (na.stage, na.action) == ("repair", "validate")
    assert final_json.is_file() and final_md.is_file()


def test_pre_current_report_is_stale_even_when_content_is_unchanged(tmp_path: Path) -> None:
    """An older report predates the current contract. Against unchanged content it
    must NOT sit "current" forever -- it must read stale so the existing
    re-run affordance re-derives it at the current schema."""

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)
    assert runs.report_state(tid, "final") == "current"

    report_path = runs.final_report_path(tid)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["report_schema_version"] == REPORT_SCHEMA_VERSION
    report["report_schema_version"] = REPORT_SCHEMA_VERSION - 1
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    assert runs.report_state(tid, "final") == "stale"


def test_report_missing_schema_version_is_stale(tmp_path: Path) -> None:
    """A report with no version key at all is older still -- also stale."""

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)

    report_path = runs.final_report_path(tid)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["report_schema_version"]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    assert runs.report_state(tid, "final") == "stale"


def test_current_v2_report_stays_current(tmp_path: Path) -> None:
    """Regression guard: the version check must not make a healthy v2 report
    stale (which would livelock every run at 'stale')."""

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)
    assert runs.report_state(tid, "final") == "current"
    assert runs.report_state(tid, "final") == "current"


def test_guide_v1_waivable_blocker_waiver_and_staleness(tmp_path: Path) -> None:
    tid = "systems-thinking"
    leak_json = _prompt_leak_guide_json()
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)

    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    leak_findings = [
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    ]
    assert leak_findings
    finding_id = leak_findings[0]["id"]
    assert leak_findings[0]["waivable"] is True

    na = runs.run_status(tid).next_action
    assert (na.stage, na.action) == ("repair", "resolve_findings")
    with pytest.raises(ConfigError, match="blocking"):
        runs.finalize_run(tid)

    waiver_payload = {
        "schema_version": 1,
        "guide_sha256": report["guide_sha256"],
        "waivers": [{"finding_id": finding_id, "reason": "Intentional red-team phrase in example."}],
    }
    runs.waivers_path(tid).write_text(json.dumps(waiver_payload) + "\n", encoding="utf-8")

    na = runs.run_status(tid).next_action
    assert na.action == "finalize"
    final_path = runs.finalize_run(tid)
    assert final_path == runs.final_guide_json_path(tid)
    assert runs.is_finalized(tid)

    repair_paths = runs.stage_paths(tid, "repair")
    base_sha = hashlib.sha256(repair_paths.response_path.read_bytes()).hexdigest()
    re_leak = json.loads(leak_json)

    def tweak(obj: object) -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "markdown" and isinstance(value, str):
                    obj[key] = value + " different tail"
                    return True
                if tweak(value):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if tweak(item):
                    return True
        return False

    assert tweak(re_leak)
    new_text = json.dumps(re_leak)
    runs.edit_response(tid, "repair", new_text, base_sha256=base_sha)
    runs.approve_stage(tid, "repair", overwrite=True)
    runs.validate_run(tid, "final")

    na = runs.run_status(tid).next_action
    assert (na.stage, na.action) == ("repair", "resolve_findings")


def test_guide_v1_non_waivable_blocker_cannot_be_bypassed(tmp_path: Path) -> None:
    tid = "systems-thinking"
    bad = json.loads(GUIDE_FIXTURE)
    bad["schema_version"] = "2.0"
    bad_json = json.dumps(bad)
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid, draft_body=GUIDE_FIXTURE, repair_body=bad_json)

    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    blockers = [f for f in report["findings"] if f["blocking"]]
    assert blockers
    finding_id = blockers[0]["id"]
    assert blockers[0]["waivable"] is False

    runs.waivers_path(tid).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "guide_sha256": report["guide_sha256"],
                "waivers": [{"finding_id": finding_id, "reason": "Please let this through."}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    na = runs.run_status(tid).next_action
    assert (na.stage, na.action) == ("repair", "resolve_findings")
    with pytest.raises(ConfigError, match="blocking|rejected|cannot finalize"):
        runs.finalize_run(tid)


def test_guide_v1_partial_finalization_leaves_no_finalized_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)

    def boom(_guide: object) -> str:
        raise RuntimeError("projection failed")

    monkeypatch.setattr("education_pipeline.runs.project_guide_markdown", boom)
    with pytest.raises(RuntimeError, match="projection failed"):
        runs.finalize_run(tid)

    events = runs.read_manifest(tid)["events"]
    assert not any(e.get("action") == "finalized" for e in events)
    assert runs.is_finalized(tid) is False
    assert runs.run_status(tid).finalized is False
    assert runs.approved_path(tid, "repair").is_file()
    assert runs.final_report_path(tid).is_file()
    assert not runs.final_guide_json_path(tid).exists()

    monkeypatch.undo()
    path = runs.finalize_run(tid)
    assert path == runs.final_guide_json_path(tid)
    assert runs.is_finalized(tid)


def test_guide_v1_failure_between_final_writes_never_reports_finalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from education_pipeline import runs as runs_module

    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)

    real_write = runs_module._write_bytes_atomic

    def fail_on_markdown(path: Path, data: bytes) -> None:
        if path.name == "guide.md":
            raise RuntimeError("disk full between final writes")
        real_write(path, data)

    monkeypatch.setattr(runs_module, "_write_bytes_atomic", fail_on_markdown)
    with pytest.raises(RuntimeError, match="between final writes"):
        runs.finalize_run(tid)

    # guide.json may have landed, but the run must never report finalized.
    events = runs.read_manifest(tid)["events"]
    assert not any(e.get("action") == "finalized" for e in events)
    assert runs.is_finalized(tid) is False
    assert runs.run_status(tid).finalized is False
    assert runs.approved_path(tid, "repair").is_file()

    monkeypatch.undo()
    runs.finalize_run(tid, overwrite=True)
    assert runs.is_finalized(tid)


def test_guide_v1_export_uses_canonical_final_and_records_provenance(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(runs, tid)
    runs.finalize_run(tid)

    exported = runs.export_run(tid)
    html = exported.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert 'data-guide-mode="export"' in html
    event = runs.read_manifest(tid)["events"][-1]
    assert event["source_file"] == "final/guide.json"
    assert event["report_file"] == "reports/final-validation.json"
    assert event["guide_schema_version"] == "1.0"
    assert len(event["runtime_css_sha256"]) == 64
    assert len(event["runtime_js_sha256"]) == 64


def test_final_validation_report_includes_computed_static_checks(tmp_path: Path) -> None:
    """A healthy run's final report has no runtime.* findings; the context was computed."""
    tid = "systems-thinking"
    store = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(store, tid)
    repair = store.write_repair_prompt(tid)
    repair.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    store.approve_stage(tid, "repair")
    report_path = store.validate_run(tid, "final")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert not [f for f in report["findings"] if f["rule_id"].startswith("runtime.")]


def test_export_refuses_when_render_fails(tmp_path: Path, monkeypatch) -> None:
    tid = "systems-thinking"
    store = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(store, tid)

    from education_pipeline import runs as runs_mod
    from education_pipeline.guides.static_checks import StaticCheckResult
    from education_pipeline.guides.validation import ValidationContext

    def broken(guide, assets=None):
        return StaticCheckResult(ValidationContext(render_succeeded=False), None)

    monkeypatch.setattr(runs_mod, "compute_static_checks", broken)
    store.validate_run(tid, "final")
    with pytest.raises(runs_mod.ConfigError, match="blocking finding"):
        store.finalize_run(tid, overwrite=True)


def test_final_validation_size_limit_applies_before_parsing(tmp_path: Path) -> None:
    """An oversized-but-parseable final source keeps the size-limit blocker and a current report."""
    tid = "systems-thinking"
    store = _create_guide_run(tmp_path, tid)
    _drive_guide_through_qa(store, tid)
    oversized = GUIDE_FIXTURE + " " * 2_000_001
    repair = store.write_repair_prompt(tid)
    repair.response_path.write_text(oversized, encoding="utf-8")
    store.approve_stage(tid, "repair")

    report_path = store.validate_run(tid, "final")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "schema.size_limit" in [f["rule_id"] for f in report["findings"]]
    assert store.report_state(tid, "final") == "current"


def test_export_writes_exactly_the_checked_document(tmp_path: Path) -> None:
    tid = "systems-thinking"
    store = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(store, tid)
    store.validate_run(tid, "final")
    store.finalize_run(tid, overwrite=True)
    export_path = store.export_run(tid, format="html", overwrite=True)

    from education_pipeline.guides import compute_static_checks

    source = store.read_approved(tid, "repair")
    guide = normalize_guide(parse_guide(source))
    assert export_path.read_text(encoding="utf-8") == compute_static_checks(guide).document


@pytest.fixture
def guide_v1_run(tmp_path: Path):
    tid = "systems-thinking"
    store = _create_guide_run(tmp_path, tid)
    _drive_guide_to_finalize_ready(store, tid)
    return store, tid


def test_export_writes_sidecar_quality_report_and_manifest_event(guide_v1_run):
    store, topic_id = guide_v1_run
    store.validate_run(topic_id, "final")
    store.finalize_run(topic_id, overwrite=True)
    export_path = store.export_run(topic_id, format="html", overwrite=True)
    sidecar = store.export_report_path(topic_id)
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["gate"]["open"] is True
    assert payload["export"]["file_sha256"] == hashlib.sha256(export_path.read_bytes()).hexdigest()
    manifest = store.read_manifest(topic_id)
    exported = [e for e in manifest["events"] if e.get("action") == "exported"][-1]
    assert exported["quality_report_sha256"] == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    assert exported["quality_report_file"] == _relative_to_run(sidecar, store, topic_id)


def test_reexport_produces_byte_identical_quality_report(guide_v1_run):
    store, topic_id = guide_v1_run
    store.validate_run(topic_id, "final")
    store.finalize_run(topic_id, overwrite=True)
    store.export_run(topic_id, format="html", overwrite=True)
    first = store.export_report_path(topic_id).read_bytes()
    store.export_run(topic_id, format="html", overwrite=True)
    assert store.export_report_path(topic_id).read_bytes() == first


def test_export_state_tracks_optional_audit_without_mutating_old_artifacts(
    tmp_path: Path,
) -> None:
    tid = "systems-thinking"
    store = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_finalize_ready(store, tid)
    store.finalize_run(tid)
    export_path = store.export_run(tid)
    sidecar_path = store.export_report_path(tid)
    original_export = export_path.read_bytes()
    original_sidecar = sidecar_path.read_bytes()
    deterministic_report = store.final_report_path(tid).read_bytes()

    assert store.export_state(tid) == "current"
    assert json.loads(original_sidecar)["audit"]["state"] == "not_run"

    store.prepare_personalization_audit(tid)
    response = _valid_personalization_audit_response(store, tid)
    store.ingest_response(tid, "audit", response)
    assert store.audit_state(tid) == "not_run"
    assert store.export_state(tid) == "current"

    store.approve_stage(tid, "audit")
    assert store.audit_state(tid) == "current"
    assert store.export_state(tid) == "stale"
    assert store.run_status(tid).next_action.action == "done"
    assert export_path.read_bytes() == original_export
    assert sidecar_path.read_bytes() == original_sidecar
    assert store.final_report_path(tid).read_bytes() == deterministic_report
    combined = store.combined_findings(tid)
    assert any(finding.stage == "audit" for finding in combined)
    assert store.gate_result(tid, "final").gate_open is True

    store.export_run(tid, overwrite=True)
    assert store.export_state(tid) == "current"
    sidecar = sidecar_path.read_bytes()
    payload = json.loads(sidecar)
    assert payload["audit"]["state"] == "current"
    assert payload["audit"]["safe_audit_projection_sha256"] == hashlib.sha256(
        store.audit_projection_path(tid).read_bytes()
    ).hexdigest()
    assert payload["audit"]["safe_trace_projection_sha256"]
    assert any(finding["stage"] == "audit" for finding in payload["report"]["findings"])
    for private in (
        "Synthetic private goal alpha",
        "Synthetic local audit rationale.",
        "Synthetic local tailoring summary.",
        hashlib.sha256(store.approved_path(tid, "audit").read_bytes()).hexdigest(),
        hashlib.sha256(store.personalization_trace_path(tid).read_bytes()).hexdigest(),
    ):
        assert private.encode("utf-8") not in sidecar

    store.prepare_personalization_audit(tid, overwrite=True)
    store.ingest_response(tid, "audit", response, force=True)
    assert store.audit_state(tid) == "current"
    assert store.export_state(tid) == "current"

    store.audit_projection_path(tid).write_bytes(
        store.audit_projection_path(tid).read_bytes() + b"\n"
    )
    assert store.audit_state(tid) == "stale"
    assert store.export_state(tid) == "stale"
    assert store.run_status(tid).next_action.action == "done"


def test_schema_v1_sidecar_is_stale_for_reexport_but_run_stays_done(
    guide_v1_run,
) -> None:
    store, tid = guide_v1_run
    store.finalize_run(tid)
    store.export_run(tid)
    sidecar_path = store.export_report_path(tid)
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload["quality_report_schema_version"] = 1
    sidecar_path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.export_state(tid) == "stale"
    assert store.run_status(tid).next_action.action == "done"


def test_export_state_binds_final_report_and_quality_report_schema(
    guide_v1_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, tid = guide_v1_run
    store.finalize_run(tid)
    store.export_run(tid)
    assert store.export_state(tid) == "current"

    import education_pipeline.runs as runs_module

    monkeypatch.setattr(runs_module, "QUALITY_REPORT_SCHEMA_VERSION", 999)
    assert store.export_state(tid) == "stale"
    monkeypatch.undo()

    report_path = store.final_report_path(tid)
    original_report = report_path.read_bytes()
    report = json.loads(original_report)
    report["validator_version"] = "next-validator"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert store.export_state(tid) == "stale"

    report_path.write_bytes(original_report)
    assert store.export_state(tid) == "current"
    report = json.loads(original_report)
    report["report_schema_version"] = REPORT_SCHEMA_VERSION - 1
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert store.export_state(tid) == "stale"


def test_private_exclusion_reason_does_not_change_any_public_export_hash(
    tmp_path: Path,
) -> None:
    tid = "systems-thinking"
    changed_payload = json.loads(PERSONALIZED_GUIDE_FIXTURE)
    changed_payload["course"]["goal_exclusions"][0]["reason"] = (
        "A distinct private exclusion rationale for the same opaque goal."
    )
    changed_body = json.dumps(changed_payload)
    sidecars = []
    exports = []
    local_reports = []
    for root, body in (
        (tmp_path / "first", PERSONALIZED_GUIDE_FIXTURE),
        (tmp_path / "second", changed_body),
    ):
        store = _create_profiled_guide_run(root)
        _drive_profiled_guide_to_finalize_ready(store, tid, body=body)
        store.finalize_run(tid)
        exports.append(store.export_run(tid).read_bytes())
        sidecars.append(store.export_report_path(tid).read_bytes())
        local_reports.append(store.final_report_path(tid).read_bytes())

    assert local_reports[0] != local_reports[1]
    assert exports[0] == exports[1]
    assert sidecars[0] == sidecars[1]


def test_export_uses_one_runtime_asset_snapshot(
    guide_v1_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, tid = guide_v1_run
    store.finalize_run(tid)
    import education_pipeline.runs as runs_module
    from education_pipeline.guide_runtime import RuntimeAssets, load_runtime_assets

    first = load_runtime_assets()
    second = RuntimeAssets(first.css + "/* second load */", first.javascript)
    values = iter((first, second))
    calls = []

    def distinguishable_load():
        calls.append(1)
        return next(values)

    monkeypatch.setattr(runs_module, "load_runtime_assets", distinguishable_load)
    export = store.export_run(tid)
    sidecar = json.loads(store.export_report_path(tid).read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert hashlib.sha256(first.css.encode()).hexdigest() == sidecar["export"][
        "runtime_css_sha256"
    ]
    assert "second load" not in export.read_text(encoding="utf-8")


def test_trace_replacement_between_freshness_check_and_projection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = "systems-thinking"
    store = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_finalize_ready(store, tid)
    store.finalize_run(tid)
    trace_path = store.personalization_trace_path(tid)
    original = trace_path.read_bytes()
    import education_pipeline.runs as runs_module

    real_fresh = runs_module.personalization_trace_is_fresh

    def replace_after_check(current, *, expected_trace):
        result = real_fresh(current, expected_trace=expected_trace)
        trace_path.write_bytes(original + b"\n")
        return result

    monkeypatch.setattr(
        runs_module, "personalization_trace_is_fresh", replace_after_check
    )
    with pytest.raises(ConfigError, match="changed during export"):
        store.export_run(tid)


def test_audit_projection_replacement_waits_for_immutable_export_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = "systems-thinking"
    store = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_finalize_ready(store, tid)
    store.prepare_personalization_audit(tid)
    store.ingest_response(tid, "audit", _valid_personalization_audit_response(store, tid))
    store.approve_stage(tid, "audit")
    store.finalize_run(tid)
    projection = store.audit_projection_path(tid)
    original = projection.read_bytes()
    started = threading.Event()
    finished = threading.Event()
    real_parse = RunStore._parse_safe_audit_projection
    worker = None

    def parse_then_schedule_replacement(self, projection_bytes):
        nonlocal worker

        def replace_under_topic_lock():
            started.set()
            with self._manifest_write_lock(tid):
                projection.write_bytes(original + b"\n")
            finished.set()

        worker = threading.Thread(target=replace_under_topic_lock)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)
        return real_parse(self, projection_bytes)

    monkeypatch.setattr(
        RunStore, "_parse_safe_audit_projection", parse_then_schedule_replacement
    )
    assert store.export_run(tid).is_file()
    assert worker is not None
    worker.join(timeout=2)
    assert finished.is_set()
    assert store.export_state(tid) == "stale"


def _relative_to_run(path: Path, store, topic_id: str) -> str:
    return path.relative_to(store.run_dir(topic_id)).as_posix()


def test_legacy_run_untouched_by_guide_validation(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(runs, "systems-thinking")

    status = runs.run_status("systems-thinking")
    assert all(stage.stale is False for stage in status.stages)
    with pytest.raises(ConfigError, match="validation applies only to guide runs"):
        runs.validate_run("systems-thinking", "draft")
    assert status.next_action.action == "finalize"


# --- Wave 4 Slice C: new-run default flip and explicit legacy path ----------


def test_create_run_default_is_interactive_guide_v1(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("systems-thinking")

    manifest = store.read_manifest("systems-thinking")
    assert manifest["content_contract"] == {
        "kind": "interactive_guide",
        "schema_version": "1.0",
    }
    assert store.content_contract("systems-thinking") == ContentContract.interactive_guide_v1()
    draft = store.stage_paths("systems-thinking", "draft")
    assert draft.response_path.suffix == ".json"
    assert draft.approved_path.name == "draft.json"
    assert draft.content_type == GUIDE_V1_CONTENT_TYPE


def test_implicit_write_spec_prompt_creates_guide_v1_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    assert store.content_contract("systems-thinking") == ContentContract.interactive_guide_v1()
    assert "education-pipeline-contract+json" in result.prompt_path.read_text(encoding="utf-8")
    assert store.read_manifest("systems-thinking")["content_contract"] == {
        "kind": "interactive_guide",
        "schema_version": "1.0",
    }


def test_explicit_legacy_creation_is_byte_compatible_and_drives_to_finalize(
    tmp_path: Path,
) -> None:
    from education_pipeline.prompts import SpecPromptInput, compile_spec_prompt

    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)

    manifest = runs.read_manifest("systems-thinking")
    assert manifest["content_contract"] == {"kind": "legacy_markdown"}
    draft = runs.stage_paths("systems-thinking", "draft")
    assert draft.response_path.name == "draft.response.md"
    assert draft.approved_path.name == "draft.md"

    result = runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    expected = compile_spec_prompt(
        SpecPromptInput(topic_id="systems-thinking", title="Systems Thinking")
    )
    assert result.prompt_path.read_bytes() == expected.text.encode("utf-8")

    result.response_path.write_text("# Course Specification\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "spec")
    _drive_outline_to_approved(runs, "systems-thinking")
    _drive_draft_to_approved(runs, "systems-thinking")
    _drive_qa_to_approved(runs, "systems-thinking")
    _drive_repair_to_approved(runs, "systems-thinking", "# Systems Thinking\n")
    final = runs.finalize_run("systems-thinking")
    assert final.name == "guide.md"
    assert runs.is_finalized("systems-thinking") is True


def test_mixed_workspace_legacy_and_guide_v1_progress_independently(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("legacy-topic", TOPIC_TOML.replace(
        'id = "systems-thinking"', 'id = "legacy-topic"'
    ).replace("Systems Thinking", "Legacy Topic"))
    TopicStore(tmp_path).save_topic_toml("guide-topic", TOPIC_TOML.replace(
        'id = "systems-thinking"', 'id = "guide-topic"'
    ).replace("Systems Thinking", "Guide Topic"))

    runs = RunStore(tmp_path)
    runs.create_run("legacy-topic", content_contract=ContentContract.legacy_markdown())
    runs.create_run("guide-topic")  # default → interactive_guide 1.0

    assert runs.list_run_ids() == ("guide-topic", "legacy-topic")
    assert runs.content_contract("legacy-topic") == ContentContract.legacy_markdown()
    assert runs.content_contract("guide-topic") == ContentContract.interactive_guide_v1()

    # Drive legacy fully to finalized while guide sits mid-lifecycle.
    _drive_all_stages_to_approved(runs, "legacy-topic", repair_body="# Legacy Topic\n")
    runs.finalize_run("legacy-topic")
    assert runs.is_finalized("legacy-topic") is True
    assert runs.run_status("legacy-topic").next_action.action == "done"

    guide_spec = runs.write_spec_prompt("guide-topic", title="Guide Topic")
    assert "education-pipeline-contract+json" in guide_spec.prompt_path.read_text(
        encoding="utf-8"
    )
    guide_status = runs.run_status("guide-topic")
    assert guide_status.next_action.action == "save_response"
    assert guide_status.next_action.stage == "spec"
    assert guide_status.finalized is False
    assert runs.is_finalized("legacy-topic") is True


def test_read_plan_overrides_returns_empty_dict_for_fresh_run(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)

    assert runs.read_plan_overrides("systems-thinking") == {}


# --- Personalization Wave 2: source 1.1 trace lifecycle ---------------------


def test_profiled_new_run_selects_1_1_but_existing_1_0_is_immutable(
    tmp_path: Path,
) -> None:
    profiled = _create_profiled_guide_run(tmp_path / "new")
    assert profiled.content_contract("systems-thinking") == ContentContract.interactive_guide_v1_1()
    assert profiled.read_manifest("systems-thinking")["content_contract"] == {
        "kind": "interactive_guide",
        "schema_version": "1.1",
    }
    draft = profiled.stage_paths("systems-thinking", "draft")
    repair = profiled.stage_paths("systems-thinking", "repair")
    assert draft.content_type.endswith("version=1.1")
    assert repair.content_type.endswith("version=1.1")
    assert GUIDE_V1_CONTENT_TYPE.endswith("version=1.0")

    old_root = tmp_path / "old"
    old = _create_guide_run(old_root)
    profiles = ProfileStore(old_root)
    profiles.save_profile_toml("personalized-profile", PERSONALIZED_PROFILE_TOML)
    profiles.attach_profile_to_topic("personalized-profile", "systems-thinking")
    old.create_run("systems-thinking")
    assert old.content_contract("systems-thinking") == ContentContract.interactive_guide_v1()
    assert old.stage_paths("systems-thinking", "draft").content_type == GUIDE_V1_CONTENT_TYPE


def test_profiled_prompt_and_response_contract_propagate_schema_1_1(tmp_path: Path) -> None:
    runs = _create_profiled_guide_run(tmp_path)
    spec = runs.write_topic_spec_prompt("systems-thinking")
    spec_text = spec.prompt_path.read_text(encoding="utf-8")
    assert '"guide_schema_version": "1.1"' in spec_text
    assert "goal-001" in spec_text

    spec.response_path.write_text(
        _guide_spec_response(dict(VALID_SPEC_CONTRACT, guide_schema_version="1.1")),
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "spec")
    outline = runs.write_outline_prompt("systems-thinking")
    assert "goal-001" in outline.prompt_path.read_text(encoding="utf-8")
    assert runs.stage_paths("systems-thinking", "draft").content_type.endswith("version=1.1")


def test_draft_and_final_validation_write_canonical_trace_without_draft_regression(
    tmp_path: Path,
) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_draft_approved(runs, tid)
    runs.validate_run(tid, "draft")
    trace_path = runs.personalization_trace_path(tid)
    draft_trace = trace_path.read_bytes()
    assert json.loads(draft_trace)["guide_sha256"] == guide_sha256(
        normalize_guide(parse_guide(PERSONALIZED_GUIDE_FIXTURE))
    )
    assert runs.personalization_trace_state(tid, phase="draft") == "current"
    assert runs.report_state(tid, "draft") == "current"

    qa = runs.write_qa_prompt(tid)
    qa.response_path.write_text("# QA\n", encoding="utf-8")
    runs.approve_stage(tid, "qa")
    repair = runs.write_repair_prompt(tid)
    final_source = json.loads(PERSONALIZED_GUIDE_FIXTURE)
    final_source["course"]["description"] += " Final candidate."
    repair.response_path.write_text(json.dumps(final_source), encoding="utf-8")
    runs.approve_stage(tid, "repair")
    runs.validate_run(tid, "final")

    assert trace_path.read_bytes() != draft_trace
    assert runs.personalization_trace_state(tid, phase="final") == "current"
    assert runs.report_state(tid, "draft") == "current"
    assert runs.report_state(tid, "final") == "current"
    assert runs.run_status(tid).next_action.action == "finalize"


@pytest.mark.parametrize("with_goals", [True, False])
def test_current_draft_report_does_not_depend_on_mutable_shared_trace_before_qa(
    tmp_path: Path,
    with_goals: bool,
) -> None:
    tid = "systems-thinking"
    if with_goals:
        runs = _create_profiled_guide_run(tmp_path)
        body = PERSONALIZED_GUIDE_FIXTURE
    else:
        runs = _create_profiled_guide_run(
            tmp_path,
            profile_toml=NO_GOAL_PROFILE_TOML,
            profile_id="no-goal-profile",
        )
        source = json.loads(GUIDE_FIXTURE)
        source["schema_version"] = "1.1"
        body = json.dumps(source)
    _drive_profiled_guide_to_draft_approved(runs, tid, body)
    runs.validate_run(tid, "draft")
    assert runs.report_state(tid, "draft") == "current"
    runs.personalization_trace_path(tid).unlink()

    next_action = runs.run_status(tid).next_action
    assert (next_action.stage, next_action.action) == ("qa", "write_prompt")


def test_profile_snapshot_replacement_stales_reports_and_trace(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    assert runs.report_state(tid, "draft") == "current"
    assert runs.report_state(tid, "final") == "current"
    assert runs.personalization_trace_state(tid, phase="final") == "current"

    changed = PERSONALIZED_PROFILE_TOML.replace(
        "Synthetic private goal alpha", "Synthetic replacement goal alpha"
    )
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("personalized-profile", changed, overwrite=True)
    profiles.attach_profile_to_topic("personalized-profile", tid, overwrite=True)

    assert runs.report_state(tid, "draft") == "stale"
    assert runs.report_state(tid, "final") == "stale"
    assert runs.personalization_trace_state(tid, phase="final") == "stale"


@pytest.mark.parametrize("trace_body", [None, b"not-json", b'{}\n'])
def test_missing_or_malformed_goal_trace_refuses_finalize_and_export(
    tmp_path: Path,
    trace_body: bytes | None,
) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    trace = runs.personalization_trace_path(tid)
    if trace_body is None:
        trace.unlink()
    else:
        trace.write_bytes(trace_body)

    assert runs.report_state(tid, "final") == "current"
    assert runs.personalization_trace_state(tid, phase="final") in {"missing", "stale"}
    assert runs.run_status(tid).next_action.action == "resolve_findings"
    with pytest.raises(ConfigError, match="personalization trace"):
        runs.finalize_run(tid)

    runs.validate_run(tid, "final")
    runs.finalize_run(tid)
    trace.write_bytes(b"not-json")
    with pytest.raises(ConfigError, match="personalization trace"):
        runs.export_run(tid)


def test_well_formed_but_stale_goal_trace_refuses_release(tmp_path: Path) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_finalize_ready(runs, tid)
    trace_path = runs.personalization_trace_path(tid)
    stale = json.loads(trace_path.read_text(encoding="utf-8"))
    stale["guide_sha256"] = "0" * 64
    trace_path.write_text(
        json.dumps(stale, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert runs.report_state(tid, "final") == "current"
    assert runs.personalization_trace_state(tid, phase="final") == "stale"
    with pytest.raises(ConfigError, match="personalization trace is stale"):
        runs.finalize_run(tid)


def test_no_goal_profile_trace_is_observable_but_does_not_gate_release(
    tmp_path: Path,
) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(
        tmp_path,
        profile_toml=NO_GOAL_PROFILE_TOML,
        profile_id="no-goal-profile",
    )
    unannotated_1_1 = json.loads(GUIDE_FIXTURE)
    unannotated_1_1["schema_version"] = "1.1"
    body = json.dumps(unannotated_1_1)
    _drive_profiled_guide_to_finalize_ready(runs, tid, body=body)
    trace = runs.personalization_trace_path(tid)
    payload = json.loads(trace.read_text(encoding="utf-8"))
    assert payload["goals"] == []
    assert payload["active_facets"]
    trace.unlink()

    assert runs.report_state(tid, "final") == "current"
    assert runs.run_status(tid).next_action.action == "finalize"
    runs.finalize_run(tid)
    assert runs.export_run(tid).is_file()


def test_malformed_annotations_leave_current_report_and_stale_prior_trace(
    tmp_path: Path,
) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_draft_approved(runs, tid)
    runs.validate_run(tid, "draft")
    trace = runs.personalization_trace_path(tid)
    prior_trace = trace.read_bytes()

    malformed = json.loads(PERSONALIZED_GUIDE_FIXTURE)
    malformed["modules"][0]["serves_goals"] = ["not-a-goal-id"]
    draft_paths = runs.stage_paths(tid, "draft")
    draft_paths.response_path.write_text(json.dumps(malformed), encoding="utf-8")
    runs.approve_stage(tid, "draft", overwrite=True)
    runs.validate_run(tid, "draft")

    assert runs.report_state(tid, "draft") == "current"
    assert trace.read_bytes() == prior_trace
    assert runs.personalization_trace_state(tid, phase="draft") == "stale"
    assert runs.run_status(tid).next_action.action == "resolve_findings"


@pytest.mark.parametrize(
    ("run_contract", "response_version"),
    [
        (ContentContract.interactive_guide_v1(), "1.1"),
        (ContentContract.interactive_guide_v1_1(), "1.0"),
    ],
)
def test_spec_approval_rejects_run_contract_version_mismatch(
    tmp_path: Path,
    run_contract: ContentContract,
    response_version: str,
) -> None:
    tid = "systems-thinking"
    TopicStore(tmp_path).save_topic_toml(tid, TOPIC_TOML)
    runs = RunStore(tmp_path)
    runs.create_run(tid, content_contract=run_contract)
    spec = runs.write_topic_spec_prompt(tid)
    spec.response_path.write_text(
        _guide_spec_response(
            dict(VALID_SPEC_CONTRACT, guide_schema_version=response_version)
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="content contract|schema version"):
        runs.approve_stage(tid, "spec")
    assert not runs.approved_path(tid, "spec").exists()


def test_invalid_scalar_annotation_persists_current_blocking_report_and_stale_trace(
    tmp_path: Path,
) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_draft_approved(runs, tid)
    runs.validate_run(tid, "draft")
    trace_path = runs.personalization_trace_path(tid)
    prior_trace = trace_path.read_bytes()

    invalid = json.loads(PERSONALIZED_GUIDE_FIXTURE)
    invalid["course"]["goal_exclusions"][0]["reason"] = "invalid-\ud800-reason"
    draft = runs.stage_paths(tid, "draft")
    draft.response_path.write_text(json.dumps(invalid), encoding="utf-8")
    runs.approve_stage(tid, "draft", overwrite=True)

    report_path = runs.validate_run(tid, "draft")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        finding["rule_id"] == "schema.invalid_value" and finding["blocking"]
        for finding in report["findings"]
    )
    assert runs.report_state(tid, "draft") == "current"
    assert trace_path.read_bytes() == prior_trace
    assert runs.personalization_trace_state(tid, phase="draft") == "stale"
    assert runs.run_status(tid).next_action.action == "resolve_findings"


def test_profile_snapshot_parse_and_hash_come_from_one_byte_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_draft_approved(runs, tid)
    snapshot_path = ProfileStore(tmp_path).topic_profile_snapshot_path(tid)
    replacement = PERSONALIZED_PROFILE_TOML.replace(
        "Synthetic private goal alpha", "Synthetic replacement goal alpha"
    ).encode("utf-8")
    real_read = RunStore._read_attached_profile_snapshot
    swapped = False

    def racing_read(store: RunStore, topic_id: str):
        nonlocal swapped
        snapshot = real_read(store, topic_id)
        if store.root == runs.root and not swapped:
            swapped = True
            snapshot_path.write_bytes(replacement)
        return snapshot

    monkeypatch.setattr(RunStore, "_read_attached_profile_snapshot", racing_read)
    runs.validate_run(tid, "draft")
    trace = json.loads(
        runs.personalization_trace_path(tid).read_text(encoding="utf-8")
    )
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    assert trace["goals"][0]["goal_text"] not in snapshot_text
    assert runs.report_state(tid, "draft") == "stale"


def test_concurrent_validation_serializes_report_trace_and_event_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from education_pipeline import runs as runs_module

    tid = "systems-thinking"
    runs = _create_profiled_guide_run(tmp_path)
    _drive_profiled_guide_to_draft_approved(runs, tid)
    source_path = runs.stage_paths(tid, "draft").approved_path
    source_a = source_path.read_bytes()
    changed = json.loads(PERSONALIZED_GUIDE_FIXTURE)
    changed["course"]["description"] += " Concurrent candidate B."
    source_b = (json.dumps(changed, sort_keys=True) + "\n").encode("utf-8")

    real_write = runs_module._write_bytes_atomic
    a_trace_written = threading.Event()
    release_a = threading.Event()
    b_write_attempt = threading.Event()
    captures: dict[str, dict[str, str]] = {"validator-a": {}, "validator-b": {}}

    def controlled_write(path: Path, data: bytes) -> None:
        name = threading.current_thread().name
        if name in captures and path.name in {
            "draft-validation.json",
            "personalization-trace.json",
        }:
            captures[name][path.name] = hashlib.sha256(data).hexdigest()
            if name == "validator-b":
                b_write_attempt.set()
        real_write(path, data)
        if name == "validator-a" and path.name == "personalization-trace.json":
            a_trace_written.set()
            assert release_a.wait(5)

    monkeypatch.setattr(runs_module, "_write_bytes_atomic", controlled_write)
    errors: list[BaseException] = []

    def validate() -> None:
        try:
            runs.validate_run(tid, "draft")
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread_a = threading.Thread(target=validate, name="validator-a")
    thread_a.start()
    assert a_trace_written.wait(5)
    source_path.write_bytes(source_b)
    thread_b = threading.Thread(target=validate, name="validator-b")
    thread_b.start()
    b_was_blocked = not b_write_attempt.wait(0.5)
    release_a.set()
    thread_a.join(5)
    thread_b.join(5)
    assert not errors
    assert not thread_a.is_alive() and not thread_b.is_alive()
    assert b_was_blocked

    expected = {
        (
            hashlib.sha256(source_a).hexdigest(),
            captures["validator-a"]["draft-validation.json"],
            captures["validator-a"]["personalization-trace.json"],
        ),
        (
            hashlib.sha256(source_b).hexdigest(),
            captures["validator-b"]["draft-validation.json"],
            captures["validator-b"]["personalization-trace.json"],
        ),
    }
    events = [
        event
        for event in runs.read_manifest(tid)["events"]
        if event.get("action") == "validated" and event.get("phase") == "draft"
    ][-2:]
    actual = {
        (
            event["source_file_sha256"],
            event["report_file_sha256"],
            event["personalization_trace_file_sha256"],
        )
        for event in events
    }
    assert actual == expected


def test_plan_overrides_path_is_under_run_dir(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)

    path = runs.plan_overrides_path("systems-thinking")

    assert path == runs.run_dir("systems-thinking") / "model-plan-overrides.json"


def test_write_plan_overrides_round_trips_through_a_fresh_run_store(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    overrides = {"stages": {"qa": {"model": "opus", "effort": "low"}}}

    runs.write_plan_overrides("systems-thinking", overrides)

    # Simulate a daemon restart: a brand-new RunStore over the same root.
    reloaded = RunStore(tmp_path)
    assert reloaded.read_plan_overrides("systems-thinking") == overrides


def test_write_plan_overrides_is_atomic_and_overwrites_prior_contents(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)

    runs.write_plan_overrides("systems-thinking", {"stages": {"qa": {"model": "opus"}}})
    runs.write_plan_overrides("systems-thinking", {"stages": {"draft": {"effort": "high"}}})

    assert runs.read_plan_overrides("systems-thinking") == {
        "stages": {"draft": {"effort": "high"}}
    }
    # No stray temp files left behind in the run directory.
    leftovers = [p for p in runs.run_dir("systems-thinking").glob(".tmp-*")]
    assert leftovers == []


def test_read_plan_overrides_rejects_malformed_json(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    path = runs.plan_overrides_path("systems-thinking")
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ConfigError, match="model-plan overrides"):
        runs.read_plan_overrides("systems-thinking")


def test_read_plan_overrides_rejects_json_array_top_level(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    path = runs.plan_overrides_path("systems-thinking")
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigError, match="model-plan overrides"):
        runs.read_plan_overrides("systems-thinking")


def test_read_plan_overrides_rejects_non_mapping_stages(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    path = runs.plan_overrides_path("systems-thinking")
    path.write_text('{"stages": []}', encoding="utf-8")

    with pytest.raises(ConfigError, match="model-plan overrides"):
        runs.read_plan_overrides("systems-thinking")


def test_write_plan_overrides_empty_dict_writes_empty_overrides(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)

    runs.write_plan_overrides("systems-thinking", {})

    assert runs.plan_overrides_path("systems-thinking").exists()
    assert runs.read_plan_overrides("systems-thinking") == {}
