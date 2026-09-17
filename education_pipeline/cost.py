"""Cost estimation and aggregation for provider-executed stages.

A provider that reports its own spend is always believed first (the Claude
Code CLI emits ``total_cost_usd`` in its JSON result). Providers that report
nothing -- Codex, today -- get a coarse byte-based estimate instead, so the
cockpit can show *something* rather than a blank where the money went.

Everything here is a pure function over plain values: the estimator takes
byte counts, and the aggregator takes any objects carrying ``stage``,
``cost_usd`` and ``cost_source`` (i.e. :class:`~education_pipeline.daemon.
jobs.Job` records) without importing the daemon.
"""

from __future__ import annotations

from typing import Iterable, Sequence

#: Bytes of UTF-8 text per token. A deliberately crude average that holds
#: well enough for English prose; the estimate it feeds is labelled as an
#: estimate precisely because this is an approximation.
BYTES_PER_TOKEN = 4

#: PLACEHOLDER prices in **USD per million tokens**, blended across input and
#: output tokens (one number per model, not a prompt/completion split). These
#: are not vendor price sheets and are not kept current: they exist so the
#: estimate path has something to multiply by, and so operators can see the
#: shape of a workspace's spend. Replace them with real numbers -- or prefer a
#: provider that reports its own cost -- before trusting any figure derived
#: from this table.
#:
#: Keys are **provider model identifiers**: the id the provider CLI is actually
#: invoked with (``ModelOption.argv_model``, falling back to the option id when
#: a catalog declares none). They are *not* catalog option ids, which are
#: project-local labels a workspace is free to rename -- pricing those would
#: both miss a renamed model and mis-price an unrelated one that happened to
#: borrow a familiar name.
PRICE_TABLE: dict[str, float] = {
    # claude-code provider (argv_model of the shipped catalog's options)
    "claude-fable-5": 30.0,
    "claude-opus-4-8": 30.0,
    "claude-sonnet-5": 6.0,
    "claude-haiku-4-5": 1.5,
    # codex provider
    "gpt-5.6-sol": 12.0,
    "gpt-5.6-terra": 6.0,
    "gpt-5.6-luna": 1.5,
}


def estimate_cost_usd(prompt_bytes: int, response_bytes: int, model_id: str) -> dict:
    """A rough USD cost for one stage execution, from byte counts.

    ``model_id`` is a *provider* model identifier (see :data:`PRICE_TABLE`),
    not a catalog option id. Returns ``{"usd": float, "source": "estimate"}``
    for a model listed in :data:`PRICE_TABLE`, and ``{"usd": None, "source":
    None}`` for any model the table does not price -- an unknown model yields
    *no number*, never a misleading zero. More bytes never cost less.
    """

    price_per_million = PRICE_TABLE.get(model_id)
    if price_per_million is None:
        return {"usd": None, "source": None}
    tokens = (max(prompt_bytes, 0) + max(response_bytes, 0)) / BYTES_PER_TOKEN
    return {"usd": tokens / 1_000_000 * price_per_million, "source": "estimate"}


def _collapse(sources: Iterable[str | None]) -> str | None:
    """One label for a set of cost sources: the shared one, or ``"mixed"``."""

    distinct = {source for source in sources if source}
    if not distinct:
        return None
    if len(distinct) == 1:
        return next(iter(distinct))
    return "mixed"


def summarize_job_costs(jobs: Iterable, stages: Sequence[str] = ()) -> dict:
    """Per-stage and whole-run cost totals over a topic's job records.

    Every job whose ``cost_usd`` is known contributes, whatever its status:
    a failed retry still spent money. ``stages`` seeds the result so stages
    that never ran are reported as known-nothing (``jobs: 0``) instead of
    being absent; any stage seen in ``jobs`` is added on top.

    Jobs whose cost is *not* known -- records written before costs were
    tracked, or a model the price table does not price -- are counted rather
    than quietly dropped: every stage entry carries ``unpriced_jobs``, and the
    run carries both ``unpriced_jobs`` and ``complete`` (``True`` exactly when
    nothing is missing). The subtotal is still reported, so a caller can show
    what is known while saying plainly that it is partial. A run with no jobs
    at all is ``complete`` with a ``run_usd`` of ``None``: nothing is missing
    because nothing was spent through a provider.

    Totals are raw floats -- rounding is a presentation concern. A stage (or
    run) with no known cost at all reports ``None``, never ``0.0``.
    """

    totals: dict[str, dict] = {
        stage: {"usd": None, "source": None, "jobs": 0, "unpriced_jobs": 0}
        for stage in stages
    }
    seen_sources: dict[str, list[str | None]] = {}
    for job in jobs:
        stage = job.stage
        entry = totals.setdefault(
            stage, {"usd": None, "source": None, "jobs": 0, "unpriced_jobs": 0}
        )
        entry["jobs"] += 1
        usd = getattr(job, "cost_usd", None)
        if usd is None:
            entry["unpriced_jobs"] += 1
            continue
        entry["usd"] = usd if entry["usd"] is None else entry["usd"] + usd
        seen_sources.setdefault(stage, []).append(getattr(job, "cost_source", None))
    for stage, sources in seen_sources.items():
        totals[stage]["source"] = _collapse(sources)
    known = [entry["usd"] for entry in totals.values() if entry["usd"] is not None]
    unpriced = sum(entry["unpriced_jobs"] for entry in totals.values())
    return {
        "stages": totals,
        "run_usd": sum(known) if known else None,
        "run_source": _collapse(entry["source"] for entry in totals.values()),
        "unpriced_jobs": unpriced,
        "complete": unpriced == 0,
    }


def latest_stage_costs(jobs: Iterable) -> dict:
    """The most recently observed cost per stage, over any job records.

    Answers a different question from :func:`summarize_job_costs`: not "what
    has this run spent" but "what did this stage last actually cost", which
    is what the plan editor shows beside a stage's model choice. One entry
    per stage that has at least one job with a known cost::

        {"draft": {"usd": 0.4, "source": "provider", "observed_at": "..."}}

    A stage whose jobs all ran without a determinable cost is *absent*: there
    is no observation to report, and reporting ``None`` would invite callers
    to render it as a figure. Recency is the job's ``ended_at`` (falling back
    to ``created_at``, then the id -- all sort chronologically), so a retry
    supersedes the attempt before it.
    """

    latest: dict[str, tuple[tuple[str, str], dict]] = {}
    for job in jobs:
        usd = getattr(job, "cost_usd", None)
        if usd is None:
            continue
        observed_at = getattr(job, "ended_at", None) or getattr(job, "created_at", None)
        key = (observed_at or "", getattr(job, "id", ""))
        previous = latest.get(job.stage)
        if previous is not None and key <= previous[0]:
            continue
        latest[job.stage] = (
            key,
            {
                "usd": usd,
                "source": getattr(job, "cost_source", None),
                "observed_at": observed_at or None,
            },
        )
    return {stage: entry for stage, (_, entry) in sorted(latest.items())}
