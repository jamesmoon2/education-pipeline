"""Seed a demo workspace: one finished, exported course with a learner profile
(the shipped example), one mid-run course, one course with no run yet."""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2] if (Path(__file__).resolve().parents[2] / "education_pipeline").is_dir() else Path(os.environ["EP_REPO"])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from build_example import build_export, EXAMPLE_DIR  # noqa: E402
from education_pipeline import RunStore, TopicStore  # noqa: E402

ws = Path(sys.argv[1])
ws.mkdir(parents=True, exist_ok=True)
(ws / "config").mkdir(exist_ok=True)
(ws / "config" / "model-plan.toml").write_text('provider = "manual"\n', encoding="utf-8")

build_export(EXAMPLE_DIR, ws)

topics = TopicStore(ws)
topics.save_topic_toml(
    "ocean-carbon",
    'schema_version = 1\nid = "ocean-carbon"\ntitle = "The Ocean Carbon Cycle"\n'
    'brief = "How the ocean absorbs, stores and releases carbon, and why the pumps matter."\n'
    'audience = "a policy analyst comfortable with charts but new to earth science"\n'
    'goals = ["explain the solubility and biological pumps", "read a carbon flux diagram"]\n',
)
topics.save_topic_toml(
    "study-design",
    'schema_version = 1\nid = "study-design"\ntitle = "Designing Better Experiments"\n'
    'brief = "Controls, randomization, power and the mistakes that quietly ruin studies."\n',
)
runs = RunStore(ws)
runs.create_run("ocean-carbon")
r = runs.write_topic_spec_prompt("ocean-carbon")
r.response_path.write_text(
    "# Course spec: The Ocean Carbon Cycle\n\n"
    "## Who this is for\nA policy analyst who reads charts daily but has never studied earth science.\n\n"
    "## Outcomes\n1. Explain the solubility pump and the biological pump in plain words.\n"
    "2. Read a carbon flux diagram and identify the largest reservoirs and fluxes.\n"
    "3. Describe why ocean uptake slows as the surface warms.\n\n"
    "## Scope\nPhysical and biological uptake, storage timescales, and the feedbacks that matter for policy.\n\n"
    "```education-pipeline-contract+json\n"
    '{"contract_version": 1, "guide_schema_version": "1.0", "blueprint": "conceptual-foundations", "estimated_minutes": 20, '
    '"outcomes": [{"id": "pumps", "text": "Explain the solubility pump and the biological pump in plain words."}, '
    '{"id": "flux-diagram", "text": "Read a carbon flux diagram and identify the largest reservoirs and fluxes."}, '
    '{"id": "warming", "text": "Describe why ocean uptake slows as the surface warms."}], '
    '"required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"], '
    '"personalization_requirements": ["Use chart-reading examples."], '
    '"source_policy": "Sources required for factual claims that are not common knowledge."}\n'
    "```\n",
    encoding="utf-8",
)
runs.approve_stage("ocean-carbon", "spec")
r = runs.write_outline_prompt("ocean-carbon")
r.response_path.write_text(
    "# Outline\n\n1. Reservoirs and fluxes: the big picture\n2. The solubility pump\n"
    "3. The biological pump\n4. Timescales and feedbacks\n5. Reading a flux diagram (practice)\n\n"
    "```education-pipeline-outline+json\n"
    '{"contract_version": 1, "modules": {"pumps": {"outcome_ids": ["pumps"], "estimated_minutes": 10, '
    '"interaction_types": ["knowledge_check", "worked_reveal"]}, "reading-fluxes": {"outcome_ids": ["flux-diagram", "warming"], '
    '"estimated_minutes": 10, "interaction_types": ["knowledge_check", "scenario", "reflection"]}}}\n'
    "```\n",
    encoding="utf-8",
)
print("seeded", ws)
