"""Rebuild the exported guide for the shipped synthetic example project.

Drives a real guide-v1 run — spec → outline → draft → qa → repair →
validate → finalize → export — in a throwaway workspace, using only the
committed sources under ``examples/feedback-loops/``, then copies the
resulting ``guide.html`` and ``guide.report.json`` into the example's
``export/`` directory.

Engine exports are byte-deterministic, so rebuilding from unchanged sources
reproduces the committed artifacts exactly; ``tests/test_example_project.py``
pins that. Run from the repository root:

    python3 scripts/build_example.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from education_pipeline import ProfileStore, RunStore, TopicStore  # noqa: E402

EXAMPLE_DIR = REPO_ROOT / "examples" / "feedback-loops"
TOPIC_ID = "feedback-loops"
PROFILE_ID = "example-learner"


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
        "draft": (responses / "draft.guide.json").read_text(encoding="utf-8"),
        "qa": (responses / "qa.md").read_text(encoding="utf-8"),
        "repair": (responses / "repair.guide.json").read_text(encoding="utf-8"),
    }
    prompt_writers = {
        "spec": runs.write_topic_spec_prompt,
        "outline": runs.write_outline_prompt,
        "draft": runs.write_draft_prompt,
        "qa": runs.write_qa_prompt,
        "repair": runs.write_repair_prompt,
    }

    for stage in ("spec", "outline", "draft", "qa", "repair"):
        result = prompt_writers[stage](TOPIC_ID)
        result.response_path.write_text(stage_bodies[stage], encoding="utf-8")
        runs.approve_stage(TOPIC_ID, stage)
        if stage == "draft":
            runs.validate_run(TOPIC_ID, "draft")

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
