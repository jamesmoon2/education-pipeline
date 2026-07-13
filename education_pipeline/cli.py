"""Command-line interface for driving education-pipeline runs.

A thin, dependency-free wrapper over the library API. It exposes the same
workspace stores and run driver that a GUI would sit on, so power users can run
the whole lifecycle from a terminal:

    education-pipeline topic import topic.toml
    education-pipeline advance systems-thinking      # writes the next prompt
    # ...save the model response to the printed path...
    education-pipeline approve systems-thinking spec
    education-pipeline export systems-thinking --format html
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence

from education_pipeline.client import DaemonClient, DaemonError, daemon_status, ensure_daemon
from education_pipeline.config import ConfigError
from education_pipeline.daemon import lifecycle
from education_pipeline.daemon.jobs import TERMINAL_STATUSES
from education_pipeline.export import EXPORT_FORMATS
from education_pipeline.profiles import load_learner_profile
from education_pipeline.runs import ContentContract, RunStore
from education_pipeline.topics import load_topic
from education_pipeline.workspace import ProfileStore, TopicStore


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns a process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except DaemonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="education-pipeline", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workspace",
        "-C",
        default=".",
        help="workspace directory holding profiles/, topics/, and runs/ (default: current dir)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    topic = sub.add_parser("topic", help="manage topic artifacts").add_subparsers(
        dest="topic_command", required=True
    )
    topic.add_parser("list", help="list stored topic ids").set_defaults(func=_cmd_topic_list)
    p = topic.add_parser("import", help="import a topic TOML file")
    p.add_argument("file")
    p.set_defaults(func=_cmd_topic_import)
    p = topic.add_parser("show", help="print a stored topic's TOML")
    p.add_argument("topic_id")
    p.set_defaults(func=_cmd_topic_show)

    profile = sub.add_parser("profile", help="manage learner profiles").add_subparsers(
        dest="profile_command", required=True
    )
    profile.add_parser("list", help="list stored profile ids").set_defaults(func=_cmd_profile_list)
    p = profile.add_parser("import", help="import a learner profile TOML file")
    p.add_argument("file")
    p.set_defaults(func=_cmd_profile_import)
    p = profile.add_parser("attach", help="attach a profile snapshot to a topic run")
    p.add_argument("profile_id")
    p.add_argument("topic_id")
    p.set_defaults(func=_cmd_profile_attach)

    p = sub.add_parser("create", help="create a topic run directory")
    p.add_argument("topic_id")
    p.add_argument(
        "--legacy-markdown",
        action="store_true",
        help="create a legacy Markdown run instead of interactive_guide 1.0",
    )
    p.set_defaults(func=_cmd_create)

    p = sub.add_parser("status", help="show a run's progress and next step")
    p.add_argument("topic_id")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("advance", help="perform the run's next machine step")
    p.add_argument("topic_id")
    p.set_defaults(func=_cmd_advance)

    p = sub.add_parser("approve", help="approve a stage's saved response")
    p.add_argument("topic_id")
    p.add_argument("stage")
    p.set_defaults(func=_cmd_approve)

    p = sub.add_parser("finalize", help="assemble the approved draft into the final guide")
    p.add_argument("topic_id")
    p.set_defaults(func=_cmd_finalize)

    p = sub.add_parser("export", help="export the finalized guide to a distributable format")
    p.add_argument("topic_id")
    p.add_argument("--format", "-f", default="html", choices=EXPORT_FORMATS)
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("validate", help="run deterministic validation and report the gate")
    p.add_argument("topic_id")
    p.add_argument("--phase", default="final", choices=["draft", "final"])
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("findings", help="list a validation report's findings")
    p.add_argument("topic_id")
    p.add_argument("--phase", default="final", choices=["draft", "final"])
    p.add_argument("--blocking", action="store_true", help="show only blocking findings")
    p.set_defaults(func=_cmd_findings)

    p = sub.add_parser("report", help="print the export sidecar quality report, or the final report")
    p.add_argument("topic_id")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("waive", help="waive a waivable blocking finding to open the gate")
    p.add_argument("topic_id")
    p.add_argument("finding_id")
    p.add_argument("--reason", required=True, help="reason the finding is being waived")
    p.add_argument("--phase", default="final", choices=["draft", "final"])
    p.set_defaults(func=_cmd_waive)

    p = sub.add_parser("unwaive", help="remove a previously recorded waiver")
    p.add_argument("topic_id")
    p.add_argument("finding_id")
    p.add_argument("--phase", default="final", choices=["draft", "final"])
    p.set_defaults(func=_cmd_unwaive)

    p = sub.add_parser("run", help="enqueue the next-stage provider run for a topic")
    p.add_argument("topic_id")
    p.add_argument("--stage", default=None, help="override the stage to run")
    p.add_argument("--wait", action="store_true", help="block until the job is terminal")
    p.add_argument("--force", action="store_true", help="override the no-clobber refusal")
    p.add_argument("--no-autostart", dest="autostart", action="store_false")
    p.set_defaults(func=_cmd_run, autostart=True)

    p = sub.add_parser("jobs", help="list jobs (optionally for one topic)")
    p.add_argument("topic_id", nargs="?", default=None)
    p.set_defaults(func=_cmd_jobs)

    p = sub.add_parser("job", help="show one job's full record")
    p.add_argument("job_id")
    p.set_defaults(func=_cmd_job)

    p = sub.add_parser("logs", help="print or follow a job's output log")
    p.add_argument("job_id")
    p.add_argument("-f", "--follow", action="store_true")
    p.set_defaults(func=_cmd_logs)

    p = sub.add_parser("cancel", help="cancel a queued or running job")
    p.add_argument("job_id")
    p.set_defaults(func=_cmd_cancel)

    daemon = sub.add_parser("daemon", help="manage the run daemon").add_subparsers(
        dest="daemon_command", required=True
    )
    daemon.add_parser("start", help="start the run daemon").set_defaults(func=_cmd_daemon_start)
    daemon.add_parser("stop", help="stop the run daemon").set_defaults(func=_cmd_daemon_stop)
    daemon.add_parser("status", help="show daemon status").set_defaults(func=_cmd_daemon_status)

    return parser


def _root(args: argparse.Namespace) -> Path:
    return Path(args.workspace)


def _cmd_topic_import(args: argparse.Namespace) -> int:
    topic = load_topic(args.file)
    TopicStore(_root(args)).import_topic(topic.id, args.file, overwrite=True)
    print(f"imported topic {topic.id}")
    return 0


def _cmd_topic_list(args: argparse.Namespace) -> int:
    ids = TopicStore(_root(args)).list_topic_ids()
    print("\n".join(ids) if ids else "(no topics)")
    return 0


def _cmd_topic_show(args: argparse.Namespace) -> int:
    print(TopicStore(_root(args)).read_topic_toml(args.topic_id), end="")
    return 0


def _cmd_profile_import(args: argparse.Namespace) -> int:
    profile = load_learner_profile(args.file)
    ProfileStore(_root(args)).import_profile(profile.id, args.file, overwrite=True)
    print(f"imported profile {profile.id}")
    return 0


def _cmd_profile_list(args: argparse.Namespace) -> int:
    ids = ProfileStore(_root(args)).list_profile_ids()
    print("\n".join(ids) if ids else "(no profiles)")
    return 0


def _cmd_profile_attach(args: argparse.Namespace) -> int:
    attachment = ProfileStore(_root(args)).attach_profile_to_topic(
        args.profile_id, args.topic_id, overwrite=True
    )
    print(f"attached profile {attachment.profile_id} to {attachment.topic_id}")
    print(f"  snapshot: {attachment.snapshot_path}")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    store = RunStore(_root(args))
    if args.legacy_markdown:
        run = store.create_run(
            args.topic_id, content_contract=ContentContract.legacy_markdown()
        )
        print(f"created run {args.topic_id} (legacy_markdown)")
    else:
        run = store.create_run(args.topic_id)
        print(f"created run {args.topic_id} (interactive_guide 1.0)")
    print(run)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    status = RunStore(_root(args)).run_status(args.topic_id)
    finalized = "yes" if status.finalized else "no"
    print(f"Run: {status.topic_id}   (finalized: {finalized})")
    for stage in status.stages:
        print(f"  {stage.stage:8s} {stage.state}")
    _print_next(status.next_action)
    return 0


def _cmd_advance(args: argparse.Namespace) -> int:
    result = RunStore(_root(args)).advance(args.topic_id)
    print(f"Performed: {result.performed or 'nothing (waiting on you)'}")
    _print_next(result.status.next_action)
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    runs = RunStore(_root(args))
    approved_path = runs.approve_stage(args.topic_id, args.stage)
    print(f"approved {args.stage}: {approved_path}")
    _print_next(runs.run_status(args.topic_id).next_action)
    return 0


def _cmd_finalize(args: argparse.Namespace) -> int:
    final_path = RunStore(_root(args)).finalize_run(args.topic_id)
    print(f"finalized: {final_path}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    export_path = RunStore(_root(args)).export_run(args.topic_id, format=args.format)
    print(f"exported ({args.format}): {export_path}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    runs = RunStore(_root(args))
    result = runs.validate_and_gate(args.topic_id, args.phase)
    state = "open" if result.gate_open else "blocked"
    parts = [
        f"validate ({args.phase}): gate {state}; "
        f"{result.effective_blocking} blocking finding(s) remain"
    ]
    if result.stale:
        parts.append("stale waivers were ignored")
    if result.rejected_finding_ids:
        parts.append(
            "non-waivable or empty-reason waivers were rejected: "
            + ", ".join(result.rejected_finding_ids)
        )
    print("; ".join(parts))
    return 0 if result.gate_open else 1


def _warn_if_report_stale(runs: RunStore, topic_id: str, phase: str) -> None:
    """Print a staleness warning to stderr when the on-disk report for
    ``phase`` no longer matches its approved source.

    Read commands (``findings``, ``report``) still print whatever is on
    disk rather than refusing outright -- unlike gate/write commands
    (``validate``, ``finalize``, export), which fail closed via
    ``report_state`` (see ``RunStore._export_guide_v1``) because they would
    otherwise act on stale content. A read command has no such side effect,
    so a clear warning keeps the output usable while making the staleness
    visible, instead of silently disagreeing with a freshly recomputed gate.
    """

    if runs.report_state(topic_id, phase) == "stale":
        print(
            f"warning: {phase} validation report for {topic_id!r} is stale "
            "(the approved source changed since this report was written); "
            "run `validate` again for current results",
            file=sys.stderr,
        )


def _cmd_findings(args: argparse.Namespace) -> int:
    import json

    runs = RunStore(_root(args))
    report_path = (
        runs.draft_report_path(args.topic_id)
        if args.phase == "draft"
        else runs.final_report_path(args.topic_id)
    )
    if not report_path.is_file():
        raise ConfigError(
            f"no {args.phase} validation report for {args.topic_id!r}; run `validate` first"
        )
    _warn_if_report_stale(runs, args.topic_id, args.phase)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    findings = report.get("findings", [])
    if args.blocking:
        findings = [f for f in findings if f.get("blocking")]
    # Pre-v2 reports (written before findings carried a stage) have no
    # finding["stage"]; fall back to the phase-derived stage the cockpit
    # uses (see web's findingHref): draft-phase -> draft, final-phase ->
    # repair.
    default_stage = "draft" if args.phase == "draft" else "repair"
    for finding in findings:
        stage = finding.get("stage", default_stage)
        print(
            f"{finding['severity']}\t{finding['rule_id']}\t{stage}\t"
            f"{finding['path']}\t{finding['message']}"
        )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    import json

    runs = RunStore(_root(args))
    export_report_path = runs.export_report_path(args.topic_id)
    if export_report_path.is_file():
        _warn_if_report_stale(runs, args.topic_id, "final")
        text = export_report_path.read_text(encoding="utf-8")
        data = json.loads(text)
        gate_open = bool(data.get("gate", {}).get("open"))
    else:
        report_path = runs.final_report_path(args.topic_id)
        if not report_path.is_file():
            raise ConfigError(
                f"no final validation report for {args.topic_id!r}; run `validate` first"
            )
        _warn_if_report_stale(runs, args.topic_id, "final")
        text = report_path.read_text(encoding="utf-8")
        gate_open = runs.gate_result(args.topic_id, "final").gate_open
    print(text, end="")
    return 0 if gate_open else 1


def _cmd_waive(args: argparse.Namespace) -> int:
    """Waive a blocking finding so the gate can open.

    Exit codes deliberately diverge from ``validate``/``report``: this is an
    action command (0 = the waiver was recorded), not a gate-status probe,
    so a still-blocked gate after waiving one of several blockers is not a
    failure. An empty reason or a finding that doesn't exist / isn't
    waivable is a usage error (2), caught here rather than left to `main`'s
    generic ``ConfigError`` handler -- which returns 1 -- so usage errors
    stay distinct from the gate's blocked-exit-1 convention.
    """

    runs = RunStore(_root(args))
    try:
        result = runs.record_waiver(args.topic_id, args.phase, args.finding_id, args.reason)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    state = "open" if result.gate_open else "blocked"
    print(
        f"waive ({args.phase}): {args.finding_id} waived; gate {state}; "
        f"{result.effective_blocking} blocking finding(s) remain"
    )
    return 0


def _cmd_unwaive(args: argparse.Namespace) -> int:
    """Remove a previously recorded waiver, potentially closing the gate again."""

    runs = RunStore(_root(args))
    try:
        result = runs.remove_waiver(args.topic_id, args.phase, args.finding_id)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    state = "open" if result.gate_open else "blocked"
    print(
        f"unwaive ({args.phase}): {args.finding_id} waiver removed; gate {state}; "
        f"{result.effective_blocking} blocking finding(s) remain"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    root = _root(args)
    try:
        client = ensure_daemon(root, autostart=args.autostart)
        job = client.enqueue(args.topic_id, stage=args.stage, force=args.force)
    except DaemonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"enqueued job {job['id']} ({job['stage']})")
    if not args.wait:
        return 0
    while True:
        job = client.get_job(job["id"])
        if job["status"] in TERMINAL_STATUSES:
            break
        time.sleep(0.25)
    log_path = job.get("response_path") or "(see logs)"
    print(f"job {job['id']} {job['status']}")
    if job["status"] == "succeeded":
        print(f"response: {log_path}")
        return 0
    if job.get("error"):
        print(f"error: {job['error']}", file=sys.stderr)
    print(f"log: education-pipeline -C {args.workspace} logs {job['id']}", file=sys.stderr)
    return 1


def _cmd_jobs(args: argparse.Namespace) -> int:
    client = ensure_daemon(_root(args), autostart=False)
    jobs = client.list_jobs(args.topic_id)
    if not jobs:
        print("(no jobs)")
        return 0
    for job in jobs:
        print(f"{job['id']}  {job['status']:11s}  {job['topic_id']}/{job['stage']}")
    return 0


def _cmd_job(args: argparse.Namespace) -> int:
    import json

    client = ensure_daemon(_root(args), autostart=False)
    print(json.dumps(client.get_job(args.job_id), indent=2))
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    client = ensure_daemon(_root(args), autostart=False)
    offset = 0
    while True:
        chunk, offset = client.get_log(args.job_id, offset)
        if chunk:
            print(chunk, end="")
        if not args.follow:
            break
        if client.get_job(args.job_id)["status"] in TERMINAL_STATUSES and not chunk:
            break
        time.sleep(0.25)
    return 0


def _cmd_cancel(args: argparse.Namespace) -> int:
    client = ensure_daemon(_root(args), autostart=False)
    job = client.cancel(args.job_id)
    print(f"job {job['id']} {job['status']}")
    return 0


def _cmd_daemon_start(args: argparse.Namespace) -> int:
    root = _root(args)
    status = daemon_status(root)
    if status["running"]:
        print(f"daemon already running (pid {status['pid']}, port {status['port']})")
        return 0
    client = ensure_daemon(root, autostart=True)
    health = client.health()
    print(f"daemon started (version {health['version']})")
    record = lifecycle.read_discovery(root) or {}
    if record.get("port"):
        print(f"cockpit: http://127.0.0.1:{record['port']}/")
    return 0


def _cmd_daemon_stop(args: argparse.Namespace) -> int:
    root = _root(args)
    status = daemon_status(root)
    if not status["running"]:
        print("daemon not running")
        lifecycle.remove_discovery(root)
        return 0
    try:
        ensure_daemon(root, autostart=False).shutdown()
    except DaemonError:
        pass
    print("daemon stopped")
    return 0


def _cmd_daemon_status(args: argparse.Namespace) -> int:
    status = daemon_status(_root(args))
    if not status["running"]:
        print("daemon: stopped")
        return 0
    warn = "  [version mismatch: restart the daemon]" if status["version_mismatch"] else ""
    print(f"daemon: running  pid={status['pid']}  port={status['port']}  "
          f"version={status['version']}{warn}")
    print(f"cockpit: http://127.0.0.1:{status['port']}/")
    return 0


def _print_next(next_action) -> None:
    stage = f" ({next_action.stage})" if next_action.stage else ""
    print(f"Next: {next_action.action}{stage} - {next_action.detail}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
