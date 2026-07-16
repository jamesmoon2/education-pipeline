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

### Learner profiles and personalization

The cockpit's **Profiles** page supports structured create, edit, duplicate,
privacy preview, and run attachment. Attaching a profile snapshots its current
canonical contents into the run, so later profile edits do not silently change
an in-progress course. New personalized guide runs use the backward-compatible
interactive-guide 1.1 source contract and keep their outcome-to-learner trace
local to the workspace.

On a run board, **Personalization fit** shows safe goal, facet, exclusion,
and evidence summaries next to the repair or final preview. Evidence links can
reveal and focus the corresponding module or outcome inside the sandboxed
preview. The optional personalization audit can be prepared, run through a
configured provider or pasted manually, reviewed, approved, rerun, and
re-exported; it never becomes a prerequisite for validation, finalization, or
export.

Private profile values, goal text, exclusion reasons, source annotations,
private traces, raw audit responses, prompts, and provider output remain local.
Exported HTML and `guide.report.json` are assembled from the public guide
projection and contain only allowlisted, deterministic personalization
findings and provenance. A changed guide makes its trace, audit, and prior
export visibly stale; regenerate or rerun the affected artifact before relying
on its evidence. Real profiles and all generated personalization artifacts must
stay in the workspace, never in this public repository.

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

### Release gates

Export refuses (with a `ConfigError`) while blocking findings remain in the
final-phase validation report. Findings come from the guide validator plus
computed static checks derived from the exact assembled export document
(render success, packaged-runtime asset match, control labeling, heading
order) and privacy screening against the attached profile's private values.
Validation is deterministic: identical inputs always produce identical
report bytes, and `validate`/`finalize`/`export` never call a model.

Every export also writes a sidecar quality report, `guide.report.json`, next
to `guide.html` — canonical, timestamp-free JSON that is byte-identical on
re-export of unchanged content. It carries `quality_report_schema_version`,
the `gate` decision (`open`, `effective_blocking`), the full `report`, the
`waivers` actually applied (plus rejected/orphaned and staleness), and
`export` fingerprints (file hash, runtime version, runtime asset hashes).
Its hash is recorded in the run manifest's `exported` event.

Five CLI commands manage the gate:

```bash
education-pipeline -C ./workspace validate systems-thinking --phase final
education-pipeline -C ./workspace findings systems-thinking --phase final --blocking
education-pipeline -C ./workspace report systems-thinking
education-pipeline -C ./workspace waive systems-thinking <finding-id> --reason "..."
education-pipeline -C ./workspace unwaive systems-thinking <finding-id>
```

All five commands share one exit-code contract: `0` = open/success, `1` =
gate blocked, `2` = usage/config error (nonexistent run, bad `--phase`, no
report on disk yet) — so a script can always tell "no such run" apart from
"gate blocked" by exit code alone.

- `validate <topic> [--phase draft|final]` runs deterministic validation and
  reports the gate (exit 0 if open, 1 if blocked, 2 on a usage/config error
  such as a nonexistent run).
- `findings <topic> [--phase] [--blocking]` lists a validation report's
  findings as tab-separated `severity  rule_id  stage  path  message` (exit 0
  on success — listing is not a gate; exits 2 if no report exists yet — run
  `validate` first — or the run doesn't exist).
- `report <topic>` prints the export sidecar quality report verbatim if one
  exists, otherwise the final validation report; its exit code tracks
  `gate.open` (0 open, 1 blocked), or 2 on a usage/config error (nonexistent
  run, or no final report exists yet).
- `waive <topic> <finding-id> --reason "..." [--phase]` and
  `unwaive <topic> <finding-id> [--phase]` record or remove a waiver. Usage
  errors (bad finding id, non-waivable rule, empty reason) exit 2, distinct
  from the gate's blocked exit 1.

Waivers are hash-bound to the validated content's `guide_sha256` and require
a recorded reason; only rules marked waivable can be waived. If the content
changes after waiving, the waiver set goes stale and is dropped — a stale
waiver can only close a gate, never open one — and removing the last waiver
deletes the waivers file.

`report` reflects the **export-time** gate state frozen in the sidecar, while
`validate` recomputes the **current** state; the two can disagree after
content changes without a re-export. `findings` and `report` warn on stderr
when the on-disk report is stale.

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
