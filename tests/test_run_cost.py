"""Cost tracking and reporting (thread T06).

Covers: Codex-style byte-based cost estimation (``education_pipeline.cost``),
durable per-job cost persistence (``JobRunner`` / ``Job`` / ``JobStore``),
cost aggregation in the run-status API payload and the topic-library
payload, and the CLI ``status`` cost summary line.

None of this behavior exists yet; every test here is expected to fail
against the current tree (missing module / unexpected constructor keyword /
missing dict key), not against a typo in this file.

Assumed shapes/signatures this thread introduces (not yet implemented):

* ``education_pipeline/cost.py`` (new module):

  - ``PRICE_TABLE: dict[str, float]`` -- a small, explicitly-a-placeholder
    per-model price table. Contents/units are not pinned by these tests.
  - ``estimate_cost_usd(prompt_bytes: int, response_bytes: int, model_id: str) -> dict``
    returns ``{"usd": float, "source": "estimate"}`` when ``model_id`` is a
    key of ``PRICE_TABLE``, else ``{"usd": None, "source": None}``. Uses a
    4 bytes/token ratio internally (not asserted directly here); more bytes
    must never cost less.

* ``education_pipeline.daemon.jobs.Job`` gains two new fields, persisted
  like every other field via ``Job.to_dict()`` / ``JobStore.save()``:

  - ``cost_usd: float | None = None``
  - ``cost_source: str | None = None``  (``"provider" | "estimate" | None``)

  ``JobRunner.execute()`` populates them after parsing a stage response:
  ``"provider"`` + the adapter's ``metadata["total_cost_usd"]`` when
  present, else an ``"estimate"`` from ``education_pipeline.cost.
  estimate_cost_usd`` keyed off prompt/response byte counts and the
  resolved model id, else ``None``/``None`` when the model is unknown to
  the price table.

* ``education_pipeline.daemon.read_api.run_status_payload`` gains a new
  optional parameter ``jobs: JobStore | None = None`` (default keeps every
  existing call site working unchanged). When given, the payload gains::

      "cost": {
          "stages": {"<stage>": {"usd": float|None,
                                  "source": "provider"|"estimate"|None,
                                  "jobs": int}},
          "run_usd": float|None,
          "run_source": "provider"|"estimate"|"mixed"|None,
      }

  Per stage, ``usd``/``jobs`` sum over *every* job recorded for that stage
  with ``status == "succeeded"`` -- all attempts, not just the newest,
  since retries cost money. Per-stage ``source`` is ``"provider"`` when
  every contributing job's cost came from the adapter, ``"estimate"`` when
  every contributing job's cost was estimated, or ``None`` when no job for
  that stage has a known cost. Mixing provider- and estimate-sourced jobs
  *within one stage* is left undefined by this thread and not exercised
  below; ``run_source`` is ``"mixed"`` precisely when different *stages*
  disagree. Job statuses other than ``"succeeded"`` are out of scope here.

* ``education_pipeline.daemon.read_api.list_topics`` gains the same
  optional ``jobs`` parameter and, when given, adds:

  - top-level ``"cost": {"workspace_usd": float|None}`` -- sum of every
    topic's run cost, or ``None`` when no topic has any known cost.
  - per topic entry ``"cost": {"run_usd": float|None}`` -- that topic's
    ``run_status_payload(...)["cost"]["run_usd"]``.

* CLI ``education-pipeline status <topic>`` prints an extra line shaped
  like ``cost: $0.42 (provider)`` (2 decimal places; source one of
  provider/estimate/mixed) whenever the run's ``cost.run_usd`` is known,
  and prints no such line otherwise.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

from education_pipeline import ContentContract, RunStore
from education_pipeline.cli import main
from education_pipeline.daemon import read_api
from education_pipeline.daemon.jobs import Job, JobRunner, JobStore
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"


# ---------------------------------------------------------------------------
# education_pipeline.cost.estimate_cost_usd
# ---------------------------------------------------------------------------


def test_estimate_cost_usd_known_model_returns_labeled_number():
    from education_pipeline.cost import PRICE_TABLE, estimate_cost_usd

    assert PRICE_TABLE, "PRICE_TABLE must ship with at least one placeholder entry"
    model_id = next(iter(PRICE_TABLE))

    result = estimate_cost_usd(1000, 4000, model_id)

    assert result["source"] == "estimate"
    assert isinstance(result["usd"], float)
    assert result["usd"] > 0


def test_estimate_cost_usd_unknown_model_returns_null_source():
    from education_pipeline.cost import estimate_cost_usd

    result = estimate_cost_usd(1000, 4000, "totally-unknown-model-xyz-123")

    assert result["usd"] is None
    assert result["source"] is None


def test_estimate_cost_usd_is_monotonic_in_bytes():
    from education_pipeline.cost import PRICE_TABLE, estimate_cost_usd

    model_id = next(iter(PRICE_TABLE))
    smaller = estimate_cost_usd(100, 100, model_id)
    larger = estimate_cost_usd(10_000, 10_000, model_id)

    assert smaller["usd"] < larger["usd"]


# ---------------------------------------------------------------------------
# JobRunner persistence: cost_usd / cost_source land on disk
# ---------------------------------------------------------------------------


class _BaseFakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])


class ProviderCostRunner(_BaseFakeRunner):
    """Mirrors the Claude Code adapter: the CLI's own JSON reports a cost."""

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={"total_cost_usd": 0.1234})


class NoCostRunner(_BaseFakeRunner):
    """Mirrors the Codex adapter: no cost in the provider's own output."""

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _setup(tmp_path, runner, provider="fake", model="m"):
    register_runner(runner)
    from education_pipeline import parse_model_catalog, parse_model_plan

    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    runs.stage_paths("t", "draft").prompt_path.parent.mkdir(parents=True, exist_ok=True)
    runs.stage_paths("t", "draft").prompt_path.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog(
        {"providers": [{"id": provider, "models": [{"id": model, "argv_model": "x"}]}]}
    )
    plan = parse_model_plan(
        {"provider": provider, "stages": {"draft": {"model": model}}}, catalog
    )
    store = JobStore(tmp_path)
    return runs, catalog, plan, store


def test_job_runner_persists_provider_reported_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    runs, catalog, plan, store = _setup(tmp_path, ProviderCostRunner())
    job = store.create("t", "draft", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "succeeded"
    assert done.cost_usd == pytest.approx(0.1234)
    assert done.cost_source == "provider"

    # Durable: a *fresh* read of job.json (not the in-memory object) carries it.
    raw = json.loads(store._job_json("t", job.id).read_text(encoding="utf-8"))
    assert raw["cost_usd"] == pytest.approx(0.1234)
    assert raw["cost_source"] == "provider"


def test_job_runner_falls_back_to_estimate_when_provider_reports_no_cost(
    tmp_path, monkeypatch
):
    from education_pipeline import cost as cost_mod

    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    monkeypatch.setitem(cost_mod.PRICE_TABLE, "m", 0.000001)
    runs, catalog, plan, store = _setup(tmp_path, NoCostRunner())
    job = store.create("t", "draft", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "succeeded"
    assert done.cost_source == "estimate"
    assert isinstance(done.cost_usd, float)
    assert done.cost_usd > 0

    raw = json.loads(store._job_json("t", job.id).read_text(encoding="utf-8"))
    assert raw["cost_source"] == "estimate"
    assert raw["cost_usd"] == pytest.approx(done.cost_usd)


def test_job_runner_leaves_cost_null_when_model_unknown_to_price_table(
    tmp_path, monkeypatch
):
    from education_pipeline import cost as cost_mod

    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    monkeypatch.delitem(cost_mod.PRICE_TABLE, "m", raising=False)
    runs, catalog, plan, store = _setup(tmp_path, NoCostRunner())
    job = store.create("t", "draft", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "succeeded"
    assert done.cost_usd is None
    assert done.cost_source is None

    raw = json.loads(store._job_json("t", job.id).read_text(encoding="utf-8"))
    assert raw.get("cost_usd") is None
    assert raw.get("cost_source") is None


# ---------------------------------------------------------------------------
# read_api.run_status_payload: per-stage / per-run cost aggregation
# ---------------------------------------------------------------------------


def _make_run(tmp_path):
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    return runs


def _succeeded_job(store, topic_id, stage, *, cost_usd, cost_source):
    job = Job(
        id=store.create(topic_id, stage, "fake", "m", None).id,
        topic_id=topic_id,
        stage=stage,
        provider="fake",
        model="m",
        effort=None,
        status="succeeded",
        cost_usd=cost_usd,
        cost_source=cost_source,
    )
    store.save(job)
    return job


def test_run_status_payload_sums_provider_cost_across_stage_retries(tmp_path):
    runs = _make_run(tmp_path)
    store = JobStore(tmp_path)
    _succeeded_job(store, "t", "draft", cost_usd=0.10, cost_source="provider")
    _succeeded_job(store, "t", "draft", cost_usd=0.20, cost_source="provider")

    payload = read_api.run_status_payload(runs, "t", jobs=store)

    draft_cost = payload["cost"]["stages"]["draft"]
    assert draft_cost["usd"] == pytest.approx(0.30)
    assert draft_cost["source"] == "provider"
    assert draft_cost["jobs"] == 2
    assert payload["cost"]["run_usd"] == pytest.approx(0.30)
    assert payload["cost"]["run_source"] == "provider"


def test_run_status_payload_run_source_mixed_across_stages(tmp_path):
    runs = _make_run(tmp_path)
    store = JobStore(tmp_path)
    _succeeded_job(store, "t", "draft", cost_usd=0.10, cost_source="provider")
    _succeeded_job(store, "t", "qa", cost_usd=0.20, cost_source="estimate")

    payload = read_api.run_status_payload(runs, "t", jobs=store)

    cost = payload["cost"]
    assert cost["stages"]["draft"]["source"] == "provider"
    assert cost["stages"]["qa"]["source"] == "estimate"
    assert cost["run_usd"] == pytest.approx(0.30)
    assert cost["run_source"] == "mixed"


def test_run_status_payload_cost_null_when_nothing_known(tmp_path):
    runs = _make_run(tmp_path)
    store = JobStore(tmp_path)
    # A succeeded job whose cost could not be determined at all.
    _succeeded_job(store, "t", "draft", cost_usd=None, cost_source=None)

    payload = read_api.run_status_payload(runs, "t", jobs=store)

    cost = payload["cost"]
    assert cost["stages"]["draft"] == {"usd": None, "source": None, "jobs": 1}
    # A stage nothing ever ran for.
    assert cost["stages"]["outline"] == {"usd": None, "source": None, "jobs": 0}
    assert cost["run_usd"] is None
    assert cost["run_source"] is None


def test_run_status_payload_omits_no_cost_data_without_jobs_of_note(tmp_path):
    """No job records at all for the run still yields a well-formed, all-null cost block."""
    runs = _make_run(tmp_path)
    store = JobStore(tmp_path)

    payload = read_api.run_status_payload(runs, "t", jobs=store)

    assert payload["cost"]["run_usd"] is None
    assert payload["cost"]["run_source"] is None
    for stage_cost in payload["cost"]["stages"].values():
        assert stage_cost == {"usd": None, "source": None, "jobs": 0}


# ---------------------------------------------------------------------------
# read_api.list_topics: workspace + per-topic cost totals
# ---------------------------------------------------------------------------


def test_list_topics_includes_per_topic_and_workspace_cost(tmp_path):
    from education_pipeline.workspace import ProfileStore, TopicStore

    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    runs.create_run("g", content_contract=ContentContract.legacy_markdown())
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "T"\n', encoding="utf-8"
    )
    (topics_dir / "g.toml").write_text(
        'schema_version = 1\nid = "g"\ntitle = "G"\n', encoding="utf-8"
    )
    store = JobStore(tmp_path)
    _succeeded_job(store, "t", "draft", cost_usd=0.50, cost_source="provider")
    # topic "g" has a run but no job records at all.

    payload = read_api.list_topics(
        TopicStore(tmp_path), runs, ProfileStore(tmp_path), jobs=store
    )

    by_id = {entry["id"]: entry for entry in payload["topics"]}
    assert by_id["t"]["cost"]["run_usd"] == pytest.approx(0.50)
    assert by_id["g"]["cost"]["run_usd"] is None
    assert payload["cost"]["workspace_usd"] == pytest.approx(0.50)


def test_list_topics_workspace_cost_null_when_nothing_known(tmp_path):
    from education_pipeline.workspace import ProfileStore, TopicStore

    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "T"\n', encoding="utf-8"
    )
    store = JobStore(tmp_path)

    payload = read_api.list_topics(
        TopicStore(tmp_path), runs, ProfileStore(tmp_path), jobs=store
    )

    assert payload["cost"]["workspace_usd"] is None


# ---------------------------------------------------------------------------
# read_api.list_topics: last observed cost per stage (thread T07)
#
# The settings plan editor shows, beside each stage's model choice, what the
# most recent run of that stage actually cost -- so the person choosing a
# model is looking at a real observation rather than a price table. That is a
# workspace-wide question, not a per-topic one, so it rides on the topics
# payload's existing top-level ``cost`` block as
# ``stages: {<stage>: {"usd": float, "source": str, "observed_at": str|None}}``.
# Only stages with at least one costed job appear; the newest costed job for a
# stage wins, by its ``ended_at`` timestamp.
# ---------------------------------------------------------------------------


def _topics_workspace(tmp_path, *topic_ids):
    from education_pipeline.workspace import ProfileStore, TopicStore

    runs = RunStore(tmp_path)
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    for topic_id in topic_ids:
        runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())
        (topics_dir / f"{topic_id}.toml").write_text(
            f'schema_version = 1\nid = "{topic_id}"\ntitle = "{topic_id}"\n',
            encoding="utf-8",
        )
    return TopicStore(tmp_path), runs, ProfileStore(tmp_path)


def _costed_job(store, topic_id, stage, *, cost_usd, cost_source, ended_at):
    job = _succeeded_job(
        store, topic_id, stage, cost_usd=cost_usd, cost_source=cost_source
    )
    job.ended_at = ended_at
    store.save(job)
    return job


def test_list_topics_reports_the_newest_costed_job_per_stage(tmp_path):
    topics, runs, profiles = _topics_workspace(tmp_path, "t")
    store = JobStore(tmp_path)
    _costed_job(
        store,
        "t",
        "draft",
        cost_usd=0.10,
        cost_source="estimate",
        ended_at="2026-07-01T00:00:00+00:00",
    )
    _costed_job(
        store,
        "t",
        "draft",
        cost_usd=0.40,
        cost_source="provider",
        ended_at="2026-07-02T00:00:00+00:00",
    )

    payload = read_api.list_topics(topics, runs, profiles, jobs=store)

    draft = payload["cost"]["stages"]["draft"]
    assert draft["usd"] == pytest.approx(0.40)
    assert draft["source"] == "provider"
    assert draft["observed_at"] == "2026-07-02T00:00:00+00:00"


def test_list_topics_omits_stages_with_no_costed_job(tmp_path):
    topics, runs, profiles = _topics_workspace(tmp_path, "t")
    store = JobStore(tmp_path)
    _costed_job(
        store,
        "t",
        "draft",
        cost_usd=0.10,
        cost_source="estimate",
        ended_at="2026-07-01T00:00:00+00:00",
    )
    # Ran, but nothing is known about what it cost: not an observation.
    _costed_job(
        store,
        "t",
        "qa",
        cost_usd=None,
        cost_source=None,
        ended_at="2026-07-03T00:00:00+00:00",
    )

    stages = read_api.list_topics(topics, runs, profiles, jobs=store)["cost"]["stages"]

    assert set(stages) == {"draft"}
    assert "outline" not in stages


def test_list_topics_last_observed_cost_spans_topics(tmp_path):
    """The plan editor is workspace-wide, so every topic's jobs count."""
    topics, runs, profiles = _topics_workspace(tmp_path, "t", "g")
    store = JobStore(tmp_path)
    _costed_job(
        store,
        "g",
        "outline",
        cost_usd=0.25,
        cost_source="provider",
        ended_at="2026-07-04T00:00:00+00:00",
    )

    stages = read_api.list_topics(topics, runs, profiles, jobs=store)["cost"]["stages"]

    assert stages["outline"]["usd"] == pytest.approx(0.25)


def test_list_topics_last_observed_cost_absent_without_a_job_store(tmp_path):
    topics, runs, profiles = _topics_workspace(tmp_path, "t")

    assert "cost" not in read_api.list_topics(topics, runs, profiles)


# ---------------------------------------------------------------------------
# CLI: `education-pipeline status <topic>` cost line
# ---------------------------------------------------------------------------

TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
goals = ["explain feedback loops"]
"""


def _run(ws: Path, *args: str) -> int:
    return main(["--workspace", str(ws), *args])


def test_cli_status_prints_cost_line_when_known(tmp_path, capsys):
    ws = tmp_path / "ws"
    topic_file = tmp_path / "topic.toml"
    topic_file.write_text(TOPIC_TOML, encoding="utf-8")
    _run(ws, "topic", "import", str(topic_file))
    _run(ws, "create", "systems-thinking", "--legacy-markdown")
    capsys.readouterr()

    store = JobStore(ws)
    _succeeded_job(store, "systems-thinking", "draft", cost_usd=0.4231, cost_source="provider")

    assert _run(ws, "status", "systems-thinking") == 0
    out = capsys.readouterr().out
    assert "cost: $0.42 (provider)" in out


def test_cli_status_omits_cost_line_when_unknown(tmp_path, capsys):
    ws = tmp_path / "ws"
    topic_file = tmp_path / "topic.toml"
    topic_file.write_text(TOPIC_TOML, encoding="utf-8")
    _run(ws, "topic", "import", str(topic_file))
    _run(ws, "create", "systems-thinking", "--legacy-markdown")
    capsys.readouterr()

    assert _run(ws, "status", "systems-thinking") == 0
    out = capsys.readouterr().out
    assert "cost:" not in out
