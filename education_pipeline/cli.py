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
from pathlib import Path
from typing import Sequence

from education_pipeline.config import ConfigError
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


def _print_next(next_action) -> None:
    stage = f" ({next_action.stage})" if next_action.stage else ""
    print(f"Next: {next_action.action}{stage} - {next_action.detail}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
