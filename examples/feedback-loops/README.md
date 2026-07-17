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
| `responses/draft.guide.json` | The draft-stage response: the full course as canonical guide JSON (schema 1.1, personalized). |
| `responses/qa.md` | The QA-stage review. This run is clean, so it finds nothing blocking. |
| `responses/repair.guide.json` | The repair-stage response — identical to the draft, since QA required no changes. |
| `export/guide.html` | The exported interactive course: one offline HTML file. |
| `export/guide.report.json` | The export's sidecar quality report: gate open, zero findings. |

## What it demonstrates

- **All six interaction types** the runtime supports: rich text, callouts,
  knowledge checks, worked reveals, scenarios, and reflections.
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
printed response path instead of calling a model:

```bash
mkdir -p /tmp/example-ws && cd /tmp/example-ws
education-pipeline topic import path/to/examples/feedback-loops/topic.toml
education-pipeline profile import path/to/examples/feedback-loops/profile.toml
education-pipeline profile attach example-learner feedback-loops
education-pipeline advance feedback-loops     # writes the spec prompt
# save responses/spec.md to the printed path, then:
education-pipeline approve feedback-loops spec
# ... repeat for outline, draft, qa, repair ...
education-pipeline export feedback-loops --format html
```

Everything in this directory is synthetic and public by design. Real
learner profiles and generated runs belong in your local workspace, never
in this repository.
