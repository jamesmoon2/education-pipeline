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
from education_pipeline.runs import RunStore
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
    return 0


def _print_next(next_action) -> None:
    stage = f" ({next_action.stage})" if next_action.stage else ""
    print(f"Next: {next_action.action}{stage} - {next_action.detail}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
