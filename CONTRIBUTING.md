# Contributing to education-pipeline

Thanks for your interest in contributing. This project is a local-first,
prompt-first toolkit for building interactive education guides. The engine and
its supported surface (the CLI) stay small, dependency-free, and well tested.

## Ground rules

- **Keep the package dependency-free.** The runtime uses only the Python
  standard library. `pytest` is the only development dependency. Do not add a
  runtime dependency without discussion in an issue first.
- **Package code only.** Generated runs, private topics, tuned prompt libraries,
  and real learner profiles belong in a user workspace, never in this repo. See
  `docs/extraction-manifest.md` for the boundary, and note the ignored
  directories in `.gitignore` (`runs/`, `topics/`, `profiles/`, `queue/`).
- **Tests come before behavior changes.** Add or update tests in the same change
  that alters stage behavior.

## Development setup

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

Supported Python versions are 3.11 and 3.12, matching CI.

## Making a change

1. Open an issue describing the change (bug or proposal) before large work.
2. Create a branch off `main`.
3. Write or update tests first, then the implementation.
4. Run the full suite locally:
   ```bash
   python3 -m pytest
   ```
5. Sanity-check the CLI still drives a run:
   ```bash
   education-pipeline --help
   ```
6. Open a pull request. Keep the diff focused; describe what changed and why.

## Style

- Match the surrounding code: standard-library idioms, small pure functions,
  explicit file artifacts, no hidden global state.
- Prefer deterministic, file-based behavior. Stages that call a model produce a
  prompt on disk; deterministic steps (finalize, export) do not call a model.
- Keep public docs and prompt templates domain-neutral where possible.

## Reporting security issues

Please do not file public issues for security or privacy concerns. See
[`SECURITY.md`](SECURITY.md) for how to report and for the tool's trust model.
