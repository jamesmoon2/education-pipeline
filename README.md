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

## Planned Workflow

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
`status`, `advance`, `approve`, `finalize`, `export`. A GUI over the same API is
planned; the CLI is the supported surface for power users and for verifying the
engine.

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
