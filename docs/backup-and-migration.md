# Backing up and moving your workspace

Everything the pipeline knows about your courses lives in one workspace
directory as plain files — there is no database, no hidden state, and no
cloud copy. Backing up means copying a directory; migrating means moving
it.

## What a workspace contains

```
<workspace>/
  topics/       course briefs (<topic-id>.toml)
  profiles/     learner profiles (<profile-id>.toml)   ← private
  runs/         one directory per course: manifest, prompts, responses,
                approvals, validation reports, waivers, final/ exports,
                inputs/profile.toml snapshot, job logs                ← private
  queue/        provider job records
  config/       model-plan.toml, model-catalog.toml (your model choices)
  .education-pipeline/   runtime state (daemon.json) — do NOT back up
```

A run is resumable from the workspace alone: the manifest plus the stage
artifacts fully determine the next action. Profile snapshots under
`runs/<topic>/inputs/` are self-contained, so an in-progress course stays
consistent even if you later edit or delete the profile it came from.

## Backup

1. Stop the daemon first so nothing is mid-write:
   `education-pipeline -C <workspace> daemon stop`
2. Copy the workspace directory with any tool you trust (`cp -a`, rsync,
   your OS backup, a synced folder).
3. Exclude `.education-pipeline/` — it holds only the live daemon's
   connection record (`daemon.json`, including its access token). It is
   recreated on the next start and is stale by definition in a backup.

Treat backups as **private data**: profiles and run artifacts contain
learner details and everything your models generated.

## Restoring or moving to a new machine or path

1. Copy the workspace directory to its new location.
2. Point the tool at it: `education-pipeline ui --workspace <new-path>`
   (or `-C <new-path>` for any other command). `ui` records the new
   location in the user-level registry for next time.
3. Run `education-pipeline workspace check --fix` — it validates the
   layout and removes a stale daemon record left over from the old
   machine.
4. Reinstall and re-authenticate any provider CLIs (`claude`, `codex`) on
   the new machine; the workspace's `config/model-catalog.toml` carries
   your model choices, but provider logins are per-machine (see
   [`docs/providers.md`](providers.md)).

Nothing inside the workspace stores absolute paths to itself, so moving it
does not corrupt runs.

## The one file outside the workspace

The workspace **registry** — the list `education-pipeline ui` uses to find
your workspaces — lives in your user configuration directory, not in the
workspace: `$XDG_CONFIG_HOME/education-pipeline/workspaces.json`
(default `~/.config/education-pipeline/workspaces.json` on every
platform). It is a convenience cache, safe to lose: if it is missing or
mentions old paths, `ui --workspace <path>` re-registers the workspace,
and a corrupt registry is treated as empty with a warning. Only `ui`
consults it; every other command uses `-C`/`--workspace` or the current
directory.

## Exported guides

`runs/<topic>/final/guide.html` is self-contained and offline — you can
copy just that one file anywhere, and it keeps working with no daemon,
Node, or network. Its sidecar `guide.report.json` records the quality-gate
state and content hashes for provenance; keep the pair together if you
care about traceability. A reader's progress lives in their own browser's
`localStorage`, never in the file, so copying a guide never carries
someone's progress with it.
