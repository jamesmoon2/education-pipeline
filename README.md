# education-pipeline

Local-first, prompt-first tooling for building interactive education guides.

`education-pipeline` is intended to turn a topic, learner profile, model plan,
and teaching contract into prompt artifacts, deterministic QA reports, and
self-contained static HTML guides. The project is designed so models generate
course content only; the guide shell, runtime, design system, and validation
logic stay in maintained source code.

## Status

This repository is being extracted as a fresh public project from a private
education-content factory. It intentionally starts with no generated courses,
private prompts, learner profiles, or run artifacts.

The pipeline engine, CLI, local provider daemon, browser-based cockpit, and
the interactive-guide v1 output (versioned schema, deterministic validation
with waivers, and a maintained offline runtime) are implemented. See
[`docs/product-requirements.md`](docs/product-requirements.md) for the
authoritative whole-product direction and prioritized roadmap.

## Workflow

```text
profile -> spec -> outline -> approve -> draft -> qa -> repair -> finalize -> export
```

Key principles:

- local files first
- prompt-first and provider-flexible
- explicit outline approval before long-form generation
- configurable model plan per stage
- learner/profile context without publishing private details by default
- static HTML output

## Command-Line Interface

A dependency-free CLI (also available as `python -m education_pipeline`) drives a
run end to end from a local workspace. It writes each stage's prompt to disk,
tells you where to save the model's response, and gates each stage on your
approval, so a run can be resumed at any time from the workspace alone.

```bash
education-pipeline -C ./workspace topic import topic.toml
education-pipeline -C ./workspace advance systems-thinking   # writes the next prompt
# ...run that prompt in your model, save the response to the printed path...
education-pipeline -C ./workspace approve systems-thinking spec
education-pipeline -C ./workspace advance systems-thinking   # writes the next prompt
# ...repeat through outline, draft, qa, repair; advance finalizes automatically...
education-pipeline -C ./workspace status systems-thinking
education-pipeline -C ./workspace export systems-thinking --format html
```

Commands: `topic`/`profile` (`import`, `list`, `attach`, `show`), and
`status`, `advance`, `approve`, `finalize`, `export`. The local browser cockpit
runs over the same API; the CLI remains the supported power-user surface and an
end-to-end way to verify the engine.

### Configuring and starting runs from the cockpit

The cockpit's **Settings** page (`/settings`) shows provider availability and
lets you set global per-stage provider/model/effort defaults, with
weak-configuration warnings and a one-click "Use recommended" reset. Each run
board has a **plan editor** (the `RunPlanPanel` next to the jobs panel) for
per-stage overrides on top of those defaults, saved immediately, with a
command preview and provenance display so you can see exactly what will run
and why. The **New-run wizard** (`/new`) walks through a structured topic
form (or a TOML paste, for hand-authored topics), an optional learner
profile, and a model-plan review before creating the run.

Hand-editing `<workspace>/config/model-plan.toml` (and
`model-catalog.toml`) directly remains fully supported and takes effect
without restarting the daemon; the cockpit and the TOML files read and write
the same underlying configuration.

### Executing a stage through a provider

Instead of copying a prompt into a model UI, run it through a configured
provider (Claude Code or Codex):

    education-pipeline -C ./ws run systems-thinking --wait   # runs the next stage
    education-pipeline -C ./ws jobs systems-thinking          # list jobs
    education-pipeline -C ./ws logs <job-id> -f               # follow output
    education-pipeline -C ./ws daemon status                  # daemon health

`run` executes exactly the run's next stage and stops for your approval; it
never auto-approves. The first `run` auto-starts a local, loopback-only daemon
(opt out with `--no-autostart`); stop it with `daemon stop`.

## Interactive Guides

New runs default to the `interactive_guide` 1.0 content contract: draft and
repair produce canonical guide JSON, deterministic validation (with reviewable
findings and exact-hash waivers) gates finalization, and `export --format html`
writes one self-contained interactive course that works offline from a `file:`
URL — no daemon, Node, or network needed. Existing Markdown runs are read as
legacy and never mutated; pass `create --legacy-markdown` to start a new one.
Learner progress lives only in the reader's browser `localStorage`, with a
built-in reset control.

See [`docs/interactive-guides.md`](docs/interactive-guides.md) for the guide
workflow, artifact layout, validation findings and waivers, preview isolation,
progress storage, and export/privacy boundaries.

## Repository Boundary

Generated runs, private topics, tuned prompt libraries, and real learner
profiles belong in user workspaces, not in this public package repository.

See `docs/extraction-manifest.md` for the extraction boundary.

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

The public config examples live in `config/`. Keep generated runs, private
topics, tuned prompt libraries, and real learner profiles outside this package
repository.

`config/learner-profile.example.toml` is a synthetic fixture showing the learner
profile schema. Real profiles should stay in a local workspace such as
`profiles/<profile-id>.toml`, not in this package repo.
