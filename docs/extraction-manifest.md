# Extraction Manifest

`education-pipeline` is a fresh public repo with no shared Git history from the
private `EducationContentGenerator` repo.

## Include

- Generic package code after review and sanitization.
- Generic shell/runtime code after token and asset license review.
- Domain-neutral prompt templates.
- Small fixture topics and sample outputs created specifically for public use.
- Tests, CI, documentation, and packaging metadata.

## Omit

- `runs/` from the private repo.
- Private technology/software topic libraries.
- Personally tuned prompt libraries.
- Real model responses, final generated guides, and queue artifacts.
- `.remember/` state.
- Private learner profiles or audience notes.

## Adapt

- Rename project-specific references to the public `education-pipeline` product.
- Move personal defaults into workspace-local configuration.
- Replace hard-coded model defaults with `config/model-plan.toml` and
  `config/model-catalog.toml`.
- Generalize authoring examples across multiple education domains.
