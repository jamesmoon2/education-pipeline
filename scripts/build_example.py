"""Rebuild the exported guide for the shipped synthetic example project.

Drives a real guide-v1 run — spec → outline → draft → qa → factcheck →
repair → validate → finalize → export — in a throwaway workspace, using only the
committed sources under ``examples/feedback-loops/``, then copies the
resulting ``guide.html`` and ``guide.report.json`` into the example's
``export/`` directory.

Engine exports are byte-deterministic, so rebuilding from unchanged sources
reproduces the committed artifacts exactly; ``tests/test_example_project.py``
pins that. Run from the repository root:

    python3 scripts/build_example.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from education_pipeline import ProfileStore, RunStore, TopicStore  # noqa: E402

EXAMPLE_DIR = REPO_ROOT / "examples" / "feedback-loops"
TOPIC_ID = "feedback-loops"
PROFILE_ID = "example-learner"


def _drive_draft_stage(runs: RunStore, topic_id: str, responses: Path) -> None:
    """Drive the draft stage through the per-module unit path.

    Design: ``docs/superpowers/specs/2026-09-18-per-module-drafting-design.md``
    decisions 1-9. ``write_draft_prompt`` also writes the skeleton prompt;
    ingesting the skeleton response writes the module prompts; ingesting the
    last outstanding module response assembles the stage response
    automatically -- ``assemble_draft`` is only called explicitly as a
    belt-and-suspenders check in case it did not.
    """

    runs.write_draft_prompt(topic_id)

    skeleton_text = (responses / "draft.skeleton.json").read_text(encoding="utf-8")
    runs.ingest_draft_unit(topic_id, "skeleton", skeleton_text)

    module_order = [module["id"] for module in json.loads(skeleton_text)["modules"]]
    modules_dir = responses / "draft.modules"
    for module_id in module_order:
        module_text = (modules_dir / f"{module_id}.json").read_text(encoding="utf-8")
        runs.ingest_draft_unit(topic_id, "module", module_text, module_id=module_id)

    progress = runs.draft_progress(topic_id)
    if progress.assembled is None or not progress.assembled.ok:
        result = runs.assemble_draft(topic_id)
        if not result.ok:
            raise RuntimeError(
                f"failed to assemble the draft for {topic_id!r}: {result.error}"
            )


def build_export(example_dir: Path, workspace: Path) -> tuple[bytes, bytes]:
    """Drive a full run in ``workspace`` from the example sources.

    Returns ``(guide_html_bytes, guide_report_json_bytes)``.
    """

    responses = example_dir / "responses"
    workspace.mkdir(parents=True, exist_ok=True)

    topic_toml = (example_dir / "topic.toml").read_text(encoding="utf-8")
    TopicStore(workspace).save_topic_toml(TOPIC_ID, topic_toml)

    profile_toml = (example_dir / "profile.toml").read_text(encoding="utf-8")
    profiles = ProfileStore(workspace)
    profiles.save_profile_toml(PROFILE_ID, profile_toml)
    profiles.attach_profile_to_topic(PROFILE_ID, TOPIC_ID)

    runs = RunStore(workspace)
    runs.create_run(TOPIC_ID)

    stage_bodies = {
        "spec": (responses / "spec.md").read_text(encoding="utf-8"),
        "outline": (responses / "outline.md").read_text(encoding="utf-8"),
        "qa": (responses / "qa.md").read_text(encoding="utf-8"),
        "factcheck": (responses / "factcheck.md").read_text(encoding="utf-8"),
        "repair": (responses / "repair.guide.json").read_text(encoding="utf-8"),
    }
    prompt_writers = {
        "spec": runs.write_topic_spec_prompt,
        "outline": runs.write_outline_prompt,
        "qa": runs.write_qa_prompt,
        "factcheck": runs.write_factcheck_prompt,
        "repair": runs.write_repair_prompt,
    }

    for stage in ("spec", "outline"):
        result = prompt_writers[stage](TOPIC_ID)
        result.response_path.write_text(stage_bodies[stage], encoding="utf-8")
        runs.approve_stage(TOPIC_ID, stage)

    _drive_draft_stage(runs, TOPIC_ID, responses)
    runs.approve_stage(TOPIC_ID, "draft")
    runs.validate_run(TOPIC_ID, "draft")

    for stage in ("qa", "factcheck", "repair"):
        result = prompt_writers[stage](TOPIC_ID)
        result.response_path.write_text(stage_bodies[stage], encoding="utf-8")
        runs.approve_stage(TOPIC_ID, stage)

    runs.validate_run(TOPIC_ID, "final")
    runs.finalize_run(TOPIC_ID)
    export_path = runs.export_run(TOPIC_ID, format="html")
    report_path = runs.export_report_path(TOPIC_ID)
    return export_path.read_bytes(), report_path.read_bytes()


def main() -> int:
    export_dir = EXAMPLE_DIR / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ep-example-") as tmp:
        html, report = build_export(EXAMPLE_DIR, Path(tmp) / "workspace")
    (export_dir / "guide.html").write_bytes(html)
    (export_dir / "guide.report.json").write_bytes(report)
    print(f"wrote {export_dir / 'guide.html'} ({len(html)} bytes)")
    print(f"wrote {export_dir / 'guide.report.json'} ({len(report)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
