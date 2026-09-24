# Example project: Thinking in Feedback Loops

A complete, fully synthetic guide-v1 project — every artifact a real run
produces, from the topic brief to the exported offline guide. Use it to see
what the pipeline makes before running your own course, or as a reference
for what each stage's response looks like.

**To see the end result:** open [`export/guide.html`](export/guide.html) in
any browser. It is one self-contained file — it works offline from a
`file:` URL with no daemon, Node, or network. Learner progress stays in the
browser's `localStorage` and has a built-in reset control.

## What's here

| File | Role |
| --- | --- |
| `topic.toml` | The course brief: title, audience, goals, 15-minute time budget, and the `conceptual-foundations` blueprint. |
| `profile.toml` | A synthetic learner profile ("Rowan Vale" is not a real person). Private by default — tailors the course without being published. |
| `responses/spec.md` | The spec-stage model response, ending in the machine-readable contract block. |
| `responses/outline.md` | The outline-stage response with the module contract. |
| `responses/draft.skeleton.json` | The draft skeleton response: the whole course (header, outcomes, glossary, sources) with every module reduced to a sectionless stub, in the outline's authored order. |
| `responses/draft.modules/<module-id>.json` | One draft response per module — the full module object (sections and blocks) that replaces its stub. |
| `responses/qa.md` | The QA-stage review. This run is clean, so it finds nothing blocking. |
| `responses/repair.guide.json` | The repair-stage response — the assembled draft (skeleton + modules), unchanged, since QA required no changes. |
| `export/guide.html` | The exported interactive course: one offline HTML file. |
| `export/guide.report.json` | The export's sidecar quality report: gate open, zero findings. |

## What it demonstrates

- **Per-module drafting.** The draft stage runs as one skeleton call plus
  one call per module instead of a single whole-course call — see
  `responses/draft.skeleton.json` and `responses/draft.modules/`.
  `scripts/build_example.py` drives this the same way a real run does:
  `write_draft_prompt` (which also writes the skeleton prompt),
  `ingest_draft_unit` for the skeleton (which writes the module prompts),
  then `ingest_draft_unit` per module — the engine assembles the two into
  the stage's draft response automatically once every module is saved.
- **All six interaction types** the runtime supports: rich text, callouts,
  knowledge checks, worked reveals, scenarios, and reflections.
- **Diagrams (guide schema 1.2).** A flow diagram whose last connection
  closes a reinforcing loop (`growth-loop-flow`, drawn with a curved
  loop-back edge) and a comparison table (`intervention-comparison`). Both
  are plain JSON data in the module responses; the runtime draws the flow
  and keeps a text version of each in the page.
- **Personalization with privacy.** The guide serves two of the profile's
  three goals and records a reasoned exclusion for the third. None of the
  profile's private values (name, experience, goal text) appear in the
  export — `tests/test_example_project.py` asserts that on every CI run.
- **Deterministic quality gates.** `export/guide.report.json` is
  byte-reproducible, timestamp-free, and records the gate decision, runtime
  version, and content hashes.

## Reproduce it yourself

The export is rebuilt from these sources by driving a real run in a
temporary workspace:

```bash
python3 scripts/build_example.py
```

Rebuilding from unchanged sources reproduces `export/` byte-for-byte —
exports are deterministic by design.

To walk the same run manually with the CLI (the workflow you would use for
your own course), copy the sources into a fresh workspace and step through
it; at each `advance`, save the matching file from `responses/` to the
printed response path instead of calling a model. The draft stage takes
several rounds of `advance` — one for the skeleton prompt, one per module
prompt, then an automatic assembly — instead of a single response:

```bash
mkdir -p /tmp/example-ws && cd /tmp/example-ws
education-pipeline topic import path/to/examples/feedback-loops/topic.toml
education-pipeline profile import path/to/examples/feedback-loops/profile.toml
education-pipeline profile attach example-learner feedback-loops
education-pipeline advance feedback-loops     # writes the spec prompt
# save responses/spec.md to the printed path, then:
education-pipeline approve feedback-loops spec
education-pipeline advance feedback-loops     # writes the outline prompt
# save responses/outline.md, then approve outline
education-pipeline advance feedback-loops     # writes draft/skeleton/prompt.md
# save responses/draft.skeleton.json to the printed path, then:
education-pipeline advance feedback-loops     # writes draft/modules/<id>/prompt.md for each module
# save each responses/draft.modules/<id>.json to its printed path, then:
education-pipeline advance feedback-loops     # assembles the draft response
education-pipeline approve feedback-loops draft
# ... repeat for qa, repair ...
education-pipeline export feedback-loops --format html
```

Everything in this directory is synthetic and public by design. Real
learner profiles and generated runs belong in your local workspace, never
in this repository.
