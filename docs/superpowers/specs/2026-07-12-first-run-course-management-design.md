# First-Run and Course-Management Experience — Design

**Date:** 2026-07-12
**Status:** Approved design, pending implementation plan
**PRD anchor:** `docs/product-requirements.md` §10 "P1 — First-run and
course-management experience" (also §6.1–§6.3, §7.1, §7.11, §8)

## 1. Summary

This milestone turns the cockpit from a developer tool that assumes a
checked-out repo, a hand-started daemon, and a `cwd` workspace into an
application a
non-developer can launch with one command and manage courses in. Five
deliverables:

1. an `education-pipeline ui` launcher (one-step entry point);
2. workspace selection, first-run creation, and setup validation;
3. first-run onboarding (welcome panel + purposeful empty states);
4. course-library management: filtering, archive/unarchive, duplicate,
   reveal-in-files;
5. a stable error-code catalog with user-directed recovery actions in the
   cockpit.

The guided New Course flow already delivered in the model-plan-configuration
milestone (Wave 4 wizard) is polished and integrated, not rebuilt. Profile
*editing* UI belongs to the personalization milestone; blueprint
recommendation depth belongs to the blueprint-pedagogy milestone. This spec
deliberately excludes both.

**Approach:** launcher-first. `education-pipeline ui` is the orchestration
spine; everything else lands as thin additive layers on existing surfaces
(new `/v1` endpoints, an enriched topic-list payload, an error-envelope
refactor, and cockpit work built on the existing `TopicListPage` /
`NewRunPage`). Each layer ships independently and the first-run story is
testable end-to-end early.

## 2. `education-pipeline ui` launcher

New CLI subcommand:

```
education-pipeline ui [--workspace PATH] [--no-browser]
```

Behavior, in order:

1. **Resolve workspace.** `--workspace` wins; otherwise the user-level
   workspace registry (§3) supplies the last-used workspace; otherwise the
   first-run selection flow (§3) runs.
2. **Validate/scaffold** the workspace via `validate_workspace` (§3).
   Blocking findings stop the launch with recovery instructions.
3. **Ensure daemon.** Reuse a live daemon for that workspace via the existing
   discovery record (`.education-pipeline/daemon.json` + staleness check in
   `daemon/lifecycle.py`); otherwise start one bound to the workspace.
4. **Serve the cockpit.** The daemon's existing `static.py` serves the built
   web assets; `default_web_dist()` gains a lookup order (§2.1).
5. **Open the browser** at the daemon URL using the existing token handoff
   pattern, via stdlib `webbrowser`. Always print the URL to stdout so
   headless/remote terminals still work; `--no-browser` skips the open.

`ui` is idempotent: run twice, the second invocation finds the live daemon
and just reopens/prints the URL.

### 2.1 Cockpit asset bundling

The built cockpit ships inside the wheel so `pip install` yields a working
`ui` with no Node toolchain:

- A release/CI step runs `npm run build` and copies `web/dist/` to
  `education_pipeline/_webdist/` before building the wheel;
  `_webdist/` is included as package data and **gitignored**.
- `default_web_dist()` lookup order: packaged `education_pipeline/_webdist/`
  → repo-relative `web/dist/` (dev checkout) → none.
- If no dist exists, `ui` fails with error code `web_assets_missing` and a
  recovery message ("run `npm run build` in `web/`, or install a packaged
  release"). The daemon API remains fully usable without assets.
- A `scripts/` helper performs the build-and-copy deterministically; a CI
  job builds the wheel, installs it into a clean venv, and smoke-tests
  `education-pipeline ui --no-browser` serving the cockpit index.

No runtime dependency is added; bundling is a build-time step only.

## 3. Workspace registry, selection, and setup validation

### 3.1 User-level registry

A small JSON file records known workspaces across sessions:

- **Location:** `$XDG_CONFIG_HOME/education-pipeline/workspaces.json`,
  defaulting to `~/.config/education-pipeline/workspaces.json` on every
  platform. One stdlib path convention everywhere (no
  `~/Library/Application Support` split); documented in the user docs.
- **Shape:** `{"workspaces": ["<abs path>", …], "last_used": "<abs path>"}`.
- **Durability:** written atomically (temp file + rename). A corrupt or
  unreadable file is treated as empty with a printed warning — never a
  crash.
- **Scope:** consulted **only** by `ui`. Every other CLI command keeps its
  current `-C/--workspace` = cwd behavior unchanged.

### 3.2 First-run selection

When `ui` has no `--workspace` and no usable registry entry:

- **Interactive TTY:** offer to create `~/EducationPipeline` (default) or
  enter an existing directory path. The chosen workspace is scaffolded,
  registered, and set as `last_used`.
- **Non-interactive (no TTY):** exit with error code `workspace_unselected`
  and instructions to pass `--workspace`. Never prompt, never guess.

### 3.3 Setup validation

New `workspace.validate_workspace(root) -> list[Finding]` reusing the
structured finding shape (severity, code, message, remediation) from the
release-gates work. Checks:

| Code | Severity | Remediation |
| --- | --- | --- |
| `missing_subdir` (`runs/`, `topics/`, `profiles/`) | blocking, auto-fixable | scaffold the directory |
| `not_writable` | blocking | fix permissions / choose another directory |
| `path_is_file` | blocking | choose a directory |
| `stale_daemon_record` | warning, auto-fixable | remove stale `daemon.json` |
| `unrecognized_layout` (non-empty dir that is not a workspace) | blocking | explicit confirmation required before scaffolding into it |

Exposed two ways:

- new CLI subcommand `education-pipeline workspace check` (prints findings,
  exit code reflects blockers; `--fix` applies the auto-fixable ones);
- run automatically by `ui` before daemon start (auto-fixes scaffolding for
  a directory the user just chose to create; stops with findings otherwise).

## 4. First-run onboarding in the cockpit

### 4.1 Workspace read endpoint

New `GET /v1/workspace` returning `{path, counts: {topics, runs, profiles},
first_run: bool}` (`first_run` = zero runs). Read-only; powers the welcome
panel and the Settings workspace display.

### 4.2 Welcome panel

Shown on the library page when `first_run` is true and the user has not
dismissed it (dismissal persisted in browser `localStorage`; re-openable via
a "Show welcome" control in Settings). Content:

- the three PRD §6.1 facts, stated plainly: everything is stored locally;
  model work uses a supported local provider or a manual copy/paste loop;
  course quality improves with good learner context and gate review;
- detected provider availability (existing config/provider endpoints), with
  manual mode presented as a first-class choice;
- one primary CTA: **Create your first course** → the New Course wizard.

No multi-step tour.

### 4.3 Empty states

- Library page: existing empty state upgraded to the same CTA treatment plus
  a secondary "Import topic…" path (already present).
- Run board and jobs panels: short purposeful empty states ("No jobs yet —
  the next action is …") instead of blank regions.

## 5. Course library

### 5.1 Enriched list payload

`GET /v1/topics` (which already joins run status) adds per-course:

- `last_activity` — mtime of the newest run artifact/event, ISO-8601;
- `archived` — bool from the run manifest (absent run ⇒ `false`);
- `profile_id` — attached learner profile, if any;
- `completion` — `{stages_approved, stages_total, exported: bool}`.

Computed server-side so the UI stays presentation-only.

### 5.2 Filtering and sorting

Client-side over the enriched payload: filter by status, learner, archived
(hidden by default), and free-text over topic id/title; sort by last
activity (default), title, or completion. No new query-param API surface.

### 5.3 Archive / unarchive

- `POST /v1/runs/{topic}/archive` and `POST /v1/runs/{topic}/unarchive` set
  `archived: true|false` plus a timestamp in the run manifest, under the
  existing manifest lock. Nothing moves on disk; exports and artifacts are
  untouched; unarchive is a pure flag flip.
- Archived courses are hidden by default behind a library filter toggle.
- Mutating write actions (advance, approve, edit, run, finalize, export) on
  an archived course are rejected with error code `archived_course`
  ("unarchive first"). Read endpoints still work.
- A topic with no run yet cannot be archived (404).

Future "compact archived run" (zip working artifacts, keep exports) is
explicitly **out of scope**.

### 5.4 Duplicate

`POST /v1/topics/{id}/duplicate` — "start a new run from an existing
brief":

- creates a new topic id `<id>-copy` (numeric suffix `-copy-2`, … on
  collision) copying the topic definition/brief;
- optional request flag re-attaches the same learner profile via a **fresh**
  snapshot;
- copies **no** run artifacts — the duplicate starts at spec. Byte-level run
  cloning is out of scope.

### 5.5 Reveal in files

`POST /v1/reveal` with `{"target": "run"|"export"|"topic",
"topic_id": …}`:

- the target is an **enum of known locations**, never a free path;
- the daemon resolves the concrete path, `realpath`-checks it is inside the
  workspace (rejecting symlink escapes), then invokes the platform opener
  (`open -R` on macOS, `xdg-open` on Linux, `os.startfile`/`explorer
  /select` on Windows);
- opener failure or unsupported platform returns error code
  `reveal_unsupported` **with the resolved path in `detail`**, and the UI
  falls back to showing the path with a copy button.

This is the first daemon endpoint that spawns an OS process on request;
path validation and escape tests carry the security weight, and the enum
design keeps user input out of the command entirely.

## 6. New Course flow polish

The existing Wave-4 wizard becomes the complete happy path (no rebuild):

1. **Learner** — pick an existing profile or "none", with a link out to
   import; no profile editing UI (personalization milestone).
2. **Topic + brief** — the existing structured form.
3. **Model plan review** — read-only summary of the effective plan using the
   existing plan panel, with an "adjust in Settings" link.
4. **Confirm** — the PRD §6.3 preview: learner/topic pairing, estimated
   stages, selected model plan.

On create, the user lands on the run board with the next action highlighted
(existing `PrimaryAction`). Blueprint selection remains the existing simple
field; no recommendation engine (blueprint-pedagogy milestone).

## 7. Error catalog and recovery actions

### 7.1 API contract

Every daemon error response becomes:

```json
{"error": {"code": "<stable-slug>", "message": "<human text>", "detail": {}}}
```

Initial catalog:

| Code | Typical recovery action |
| --- | --- |
| `stale_content` | Reload latest version (keep local edits per §7.6 PRD) |
| `not_found` | Return to library |
| `invalid_request` | Fix highlighted input |
| `workspace_invalid` | Show findings + fix instructions |
| `workspace_unselected` | Pass/choose a workspace (CLI) |
| `provider_unavailable` | Open Settings → providers; offer manual mode |
| `job_conflict` | Show running job; offer cancel/wait |
| `archived_course` | Offer Unarchive |
| `validation_blocked` | Link to findings at the responsible stage |
| `web_assets_missing` | Build or install packaged release (CLI) |
| `reveal_unsupported` | Show path + copy button |
| `internal` | Retry; report issue |

`daemon_unreachable` is synthesized client-side on fetch failure (recovery:
"start `education-pipeline ui`" instructions). Existing handlers migrate to
the envelope; anything unmapped gets `internal` so nothing breaks. The
catalog lives in one Python module; codes are append-only and stable.

### 7.2 Cockpit

One `ErrorNotice` component maps codes → plain-language explanation +
recovery button (Retry / Reload latest / Open Settings / Unarchive / daemon
instructions), with the raw message and `detail` behind a "details"
disclosure. Existing scattered `error.message` renderings migrate to it.
Unknown codes render the generic fallback.

### 7.3 CLI

Where the CLI proxies daemon errors it prints the same catalog's message +
remediation rather than raw payloads.

## 8. Testing

- **Python (pytest):** registry read/write/corruption; `validate_workspace`
  matrix incl. `--fix`; archive/unarchive under lock contention and the
  `archived_course` write guard; duplicate id-collision and fresh-snapshot
  behavior; reveal path resolution incl. symlink-escape attempts (opener
  stubbed); error-envelope shape across migrated handlers; `ui`
  orchestration with a fake daemon and fake browser opener.
- **Web (vitest):** library filtering/sorting; `ErrorNotice` code→action
  mapping incl. unknown-code fallback; welcome-panel show/dismiss/reopen
  logic.
- **E2E (Playwright):** first-run welcome → create course → run board next
  action; archive → hidden by default → filter shows → unarchive; duplicate
  → new course at spec; reveal fallback path (opener failure) shows copyable
  path.
- **Packaging smoke (CI):** build `web/dist`, package the wheel, install in
  a clean venv, run `education-pipeline ui --no-browser`, assert the cockpit
  index is served.

TDD throughout, per repo convention.

## 9. Out of scope

- Profile creation/editing UI and privacy classification (personalization
  milestone).
- Blueprint recommendation and blueprint-specific contracts
  (blueprint-pedagogy milestone).
- In-cockpit workspace switching (daemon stays one-workspace-per-process).
- Archived-run compaction; byte-level run cloning.
- Desktop-native wrappers, installers, and OS shortcuts (P2 release
  milestone covers install docs).
- Multi-workspace daemon, remote access, accounts (PRD non-goals).

## 10. Decision log

| Decision | Choice |
| --- | --- |
| Scope | All five PRD bullets in one spec |
| Cockpit assets | Bundled into the wheel at build time (`_webdist/`) |
| Workspace selection | User-level registry + last-used default + first-run creation prompt |
| Onboarding depth | Welcome panel + empty states; no guided tour |
| Archiving | Manifest flag, nothing moves on disk |
| Reveal in files | Daemon endpoint, enum targets, workspace-confined, path fallback |
| Error recovery | Stable error-code catalog in the API; cockpit maps codes to actions |
| New Course flow | Polish/integrate the Wave-4 wizard; no profile editing or blueprint engine |
| Overall shape | Launcher-first (Approach A) |
