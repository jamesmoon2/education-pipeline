# Troubleshooting

Every error the daemon, CLI, or cockpit reports carries a stable code from
`education_pipeline/errors.py`. The cockpit's error notices and the CLI map
those codes to the recovery actions below, so what you see on screen and
what this page says always match (`tests/test_troubleshooting_doc.py`
enforces that).

## Error-code reference

| Code | What happened | What to do |
| --- | --- | --- |
| `stale_content` | The content changed on disk since it was loaded. | Reload the latest version, then re-apply your edits. |
| `not_found` | The requested course, stage, or resource does not exist. | Return to the course library and pick a current course. |
| `invalid_request` | The request was not valid. | Fix the highlighted input and try again. |
| `workspace_invalid` | The workspace failed setup validation. | Run `education-pipeline workspace check --fix` and follow the findings. |
| `workspace_unselected` | No workspace is selected. | Pass --workspace PATH, or run `education-pipeline ui` in a terminal to choose one. |
| `provider_unavailable` | The configured model provider is not available. | Open Settings → providers, or switch the stage to manual mode. |
| `job_conflict` | Another job is already running for this course. | Wait for the running job to finish, or cancel it first. |
| `archived_course` | This course is archived, so write actions are refused. | Unarchive the course first. |
| `validation_blocked` | Deterministic validation is blocking this action. | Open the findings at the responsible stage and resolve or waive them. |
| `web_assets_missing` | The built cockpit assets were not found. | Run `npm run build` in web/, or install a packaged release. |
| `reveal_unsupported` | The system file manager could not be opened. | Copy the shown path and open it manually. |
| `internal` | Something went wrong inside the daemon. | Retry; if it keeps failing, report an issue with the daemon log. |
| `daemon_unreachable` | The local daemon is not reachable. | Start it with `education-pipeline ui` (or `daemon start`), then retry. |
| `already_exists` | The target already exists. | Retry with overwrite/force if replacing it is intended. |
| `not_ready` | A prerequisite step has not completed yet. | Perform the named prerequisite step first. |
| `stale_validation` | The validation report no longer matches the current guide. | Re-run validation, then retry this action. |
| `finding_not_waivable` | This finding cannot be waived. | Resolve the finding at its stage instead. |
| `guide_not_renderable` | The guide content is not renderable under the guide contract. | Fix the guide JSON at the responsible stage and revalidate. |
| `invalid_guide_json` | The guide text is not valid JSON. | Fix the JSON syntax and try again. |
| `unauthorized` | The request token is missing or invalid. | Reload the cockpit page to refresh the session token. |
| `bad_host` | The request Host header is not allowed. | Access the cockpit via 127.0.0.1 or localhost only. |
| `cockpit_rebuild_unavailable` | --rebuild needs a source checkout containing web/src. | Packaged installs already bundle the cockpit; run `education-pipeline ui` without --rebuild. |
| `npm_missing` | npm was not found on PATH. | Install Node.js (which provides npm), or build manually with `cd web && npm run build`. |
| `cockpit_build_failed` | The cockpit build (npm run build) failed. | Fix the reported build errors in web/, then rerun. |

## Common first-run problems

**`education-pipeline ui` says the cockpit assets are missing
(`web_assets_missing`).** Packaged release wheels bundle the built cockpit;
a source checkout does not. In a checkout, build once with `npm run build`
in `web/`. The CLI works either way — only the browser cockpit needs the
built assets.

**The cockpit page loads but every request fails (`unauthorized`).** The
cockpit authenticates to the daemon with a per-daemon token. Reload the
page; if that does not help, stop and restart with
`education-pipeline daemon stop` then `education-pipeline ui`.

**A provider stage refuses to run (`provider_unavailable`).** The provider's
CLI is not on your `PATH` or is not signed in. See
[`docs/providers.md`](providers.md) for install and authentication steps —
or switch the stage to manual mode and paste the prompt into any model
yourself.

**The daemon seems stuck or a stale daemon is recorded.** Run
`education-pipeline workspace check` — a `stale_daemon_record` finding means
a previous daemon exited without cleaning up; `--fix` removes the record.
`education-pipeline daemon status` shows whether a live daemon serves the
workspace, and `daemon stop` shuts it down.

## Workspace check findings

`education-pipeline workspace check [--fix]` validates the workspace layout
and reports findings by name:

- `missing_subdir` — a required directory (`runs/`, `topics/`, `profiles/`)
  is absent; `--fix` creates it.
- `unrecognized_layout` — the directory does not look like a workspace at
  all; pick the right directory or let first-run setup scaffold a new one.
- `not_writable` / `path_is_file` — permissions or a file where a directory
  should be; fix by hand (the tool never deletes your data).
- `stale_daemon_record` — leftover connection info from a dead daemon;
  `--fix` removes it safely.

## Validation gate problems

When `validate`, `finalize`, or `export` refuse with blocking findings, the
loop is always the same: read the findings at the responsible stage
(`education-pipeline findings <topic> --blocking`), edit or regenerate that
stage's content, re-approve, revalidate. Findings that are waivable can be
recorded with `waive` and a reason; waivers are hash-bound to the exact
content, so any later edit makes them stale and the gate closes again. A
stale report never opens a gate in your favor. See
[`docs/interactive-guides.md`](interactive-guides.md) for the full
findings-and-waivers workflow.

## Exit codes for scripting

The gate commands (`validate`, `findings`, `report`, `waive`, `unwaive`)
share one contract: `0` = open/success, `1` = gate blocked, `2` =
usage/config error (nonexistent run, bad flag, missing report). A script can
always tell "no such run" apart from "gate blocked" by exit code alone.
