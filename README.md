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

## Repository Boundary

Generated runs, private topics, tuned prompt libraries, and real learner
profiles belong in user workspaces, not in this public package repository.

See `docs/extraction-manifest.md` for the extraction boundary.
