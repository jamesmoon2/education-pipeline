# First-Run and Course-Management Experience Implementation Plan

**Goal:** Turn the cockpit into an application a non-developer can launch with
one command and manage courses in: an `education-pipeline ui` launcher over a
user-level workspace registry and setup validation, first-run onboarding,
course-library management (filter/archive/duplicate/reveal), and a stable
error-code catalog with user-directed recovery actions.

**Architecture:** Launcher-first, six waves in dependency order: (0) workspace
registry + `validate_workspace` + `workspace check` CLI, (1) error-code
catalog + envelope migration + cockpit `ErrorNotice`, (2) the `ui` launcher
with bundled cockpit assets and a CI packaging smoke, (3) enriched topic list
+ archive/unarchive + duplicate + reveal-in-files, (4) welcome panel, empty
states, and New Course wizard polish, (5) acceptance, docs, and closeout.
Each wave is independently shippable and lands as thin additive layers on
existing surfaces.

**Tech Stack:** Python 3.11+ standard library only, pytest; React 18 +
TypeScript, Vite, vitest, Playwright; file-backed local workspace artifacts.

**Spec:**
`docs/superpowers/specs/2026-07-12-first-run-course-management-design.md`
(its §9 out-of-scope list and §10 decision log are binding).

## Global Constraints

- `education_pipeline/` remains **standard library only at runtime**. Cockpit
  asset bundling is a build-time step only.
- Strict TDD in every task: write and observe a failing focused test before
  implementation, then drive it green.
- Do not modify the guide schema, guide runtime assets, validation rules,
  stage prompt bytes, or the canonical acceptance fixture.
- The workspace registry is consulted **only** by `ui`; every other CLI
  command keeps its `-C/--workspace` = cwd behavior unchanged (spec §3.1).
- `/v1/reveal` is the first daemon route that spawns an OS process: the
  enum-target and realpath-containment tests from spec §5.5 are
  non-negotiable. User input never reaches the spawned command line.
- Archiving is a manifest flag under the existing manifest lock; nothing
  moves on disk. Preserve the `RunStore._manifest_write_lock` contract: it is
  non-reentrant; take it once and call only `_locked` primitives inside it.
- Error codes are append-only and live in one Python module
  (`education_pipeline/errors.py`). Unmapped failures surface as `internal`.
- A parallel branch owns the blueprint-pedagogy milestone: do not touch
  blueprint-related code or specs. Wizard changes stay structural (steps,
  navigation, confirm preview) so a blueprint-selection step slots in later.
- Never commit generated runs, real learner profiles, workspace artifacts,
  Playwright output, or the built `_webdist/` (gitignored package data).
- `web/`: `npm run build` is the type/lint gate; there is no eslint/prettier.
- All new writes are atomic (temp file in the target directory +
  `os.replace`).

## Wave Protocol

- A wave **closes** by running the four-suite gate (`python3 -m pytest`,
  `cd web && npm run test -- --run`, `npm run e2e`, `npm run build`) or — for
  waves that cannot affect a given suite — the suites it touches, and
  recording results in the Wave Log below. The full four-suite gate runs at
  Waves 3, 4, and 5 close.
- Each wave lands as one or more scoped commits with clear messages; the Wave
  Log row records commits, suite counts, and deviations the next wave must
  know about.

### Wave Log

| Wave | Status | Commits | pytest | vitest | e2e | build | Notes for the next wave |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | **complete** | code HEAD `28bf6aa` | 973 | 210 | (per prior log: 53) | clean | Fresh pytest/vitest run 2026-07-16; e2e/build counts inherited from the personalization Wave Log gate on the same HEAD. |
| 0 — Registry + validation | **complete** | `c02bd12` | 1009 (+1 skip as root) | n/a | n/a | n/a | Registry surface frozen: `load_registry`, `record_workspace`, `last_used_workspace`, `registry_path` (XDG). `validate_workspace`/`fix_workspace` + `WorkspaceFinding(code, severity, message, remediation, auto_fixable)`. `workspace check` exits 1 only on remaining blockers. `not_writable` test skips as root. |
| 1 — Error catalog | pending | — | — | — | — | — | — |
| 2 — `ui` launcher | pending | — | — | — | — | — | — |
| 3 — Course library | pending | — | — | — | — | — | — |
| 4 — Onboarding + wizard | pending | — | — | — | — | — | — |
| 5 — Acceptance + closeout | pending | — | — | — | — | — | — |

## File Structure

| Area | Files |
| --- | --- |
| Registry | `education_pipeline/registry.py` (new), `tests/test_registry.py` (new) |
| Workspace validation | `education_pipeline/workspace.py`, `tests/test_workspace.py`, `education_pipeline/cli.py`, `tests/test_cli.py` |
| Error catalog | `education_pipeline/errors.py` (new), `daemon/server.py`, `client.py`, `cli.py`, `tests/test_errors.py` (new), `tests/test_server.py`, `tests/test_client.py` |
| ErrorNotice | `web/src/components/ErrorNotice.tsx` (new) + test, `web/src/api/client.ts`, `web/src/api/types.ts`, migrated pages |
| `ui` launcher | `education_pipeline/ui.py` (new), `cli.py`, `daemon/static.py`, `tests/test_ui.py` (new), `tests/test_static.py` |
| Asset bundling | `scripts/build_webdist.py` (new), `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml` (packaging-smoke job), `tests/test_packaging.py` |
| Library API | `education_pipeline/runs.py` (archive flag), `daemon/read_api.py` (enriched list, workspace payload), `daemon/write_api.py` (archive/duplicate/reveal + guard), `daemon/reveal.py` (new), `daemon/server.py` |
| Library cockpit | `web/src/pages/TopicListPage.tsx` + test, `web/src/components/WelcomePanel.tsx` (new) + test, `web/src/api/{client,types}.ts` |
| Wizard | `web/src/pages/NewRunPage.tsx` + test, `web/src/App.tsx` |
| Acceptance | `web/e2e/first-run.spec.ts` (new), `web/e2e/library.spec.ts` (new) |
| Docs/closeout | `README.md`, `docs/product-requirements.md` §10, post-milestone audit ledger under `docs/superpowers/specs/` |

---

# Wave 0 — Workspace registry, validation, and `workspace check`

**Outcome:** a durable user-level registry of known workspaces and a tested
`validate_workspace` findings engine exposed via `education-pipeline
workspace check [--fix]`.

### Task 0.1: User-level workspace registry

- Create `education_pipeline/registry.py`: `registry_path()` honoring
  `$XDG_CONFIG_HOME` (default `~/.config/education-pipeline/workspaces.json`
  on every platform), `load_registry() -> Registry`,
  `record_workspace(path)` (adds + sets `last_used`, atomic write),
  `last_used_workspace() -> Path | None`.
- Shape: `{"workspaces": ["<abs path>", …], "last_used": "<abs path>"}`.
- Corrupt/unreadable file ⇒ treated as empty with a printed warning to
  stderr — never a crash. RED tests first: round trip, ordering/dedup,
  corruption, XDG override, atomicity (no partial file on failure).

### Task 0.2: `validate_workspace` findings engine

- `workspace.validate_workspace(root) -> list[WorkspaceFinding]` with the
  structured finding shape (severity, code, message, remediation,
  auto-fixable). Checks per spec §3.3: `missing_subdir` (blocking,
  auto-fixable, one per missing `runs/`/`topics/`/`profiles/`),
  `not_writable` (blocking), `path_is_file` (blocking),
  `stale_daemon_record` (warning, auto-fixable), `unrecognized_layout`
  (blocking, non-empty dir that is not a workspace; **not** auto-fixed).
- `fix_workspace(root)` applies only the auto-fixable findings (scaffold
  dirs, remove stale `daemon.json`) and returns remaining findings.
- An empty or brand-new directory is scaffoldable: `missing_subdir` findings
  only. A directory containing any workspace marker (`runs/`, `topics/`,
  `profiles/`, `.education-pipeline/`) is a workspace.

### Task 0.3: `education-pipeline workspace check` CLI

- New subcommand printing findings (severity, code, message, remediation);
  exit 0 when no blocking findings remain, 1 otherwise; `--fix` applies
  auto-fixes first. Registry is NOT consulted (cwd/-C semantics unchanged).

**Close:** pytest green; commit per task.

---

# Wave 1 — Error catalog, envelope migration, ErrorNotice

**Outcome:** every daemon error response is
`{"error": {"code", "message", "detail"}}` with a stable catalog code; the
cockpit maps codes to recovery actions through one `ErrorNotice` component;
the CLI prints catalog remediation for proxied daemon errors.

### Task 1.1: Catalog module + daemon envelope migration

- `education_pipeline/errors.py`: `ERROR_CATALOG` mapping code →
  `(summary, remediation)` for the spec §7.1 codes (`stale_content`,
  `not_found`, `invalid_request`, `workspace_invalid`,
  `workspace_unselected`, `provider_unavailable`, `job_conflict`,
  `archived_course`, `validation_blocked`, `web_assets_missing`,
  `reveal_unsupported`, `internal`) plus the pre-existing daemon codes that
  remain (`already_exists`, `not_ready`, `stale_validation`,
  `finding_not_waivable`, `guide_not_renderable`, `invalid_guide_json`,
  `unauthorized`, `bad_host`). Codes are append-only.
- Server `_error` emits `detail` (renamed from `details`); code migrations:
  `bad_request` → `invalid_request`, `job_active` → `job_conflict`,
  `ui_unavailable` → `web_assets_missing`. Unmapped exceptions stay
  `internal` (existing `_last_resort`). A test asserts every code the server
  can emit is in the catalog.

### Task 1.2: CLI remediation for proxied daemon errors

- `DaemonClient` surfaces the envelope code; `DaemonError` carries it; the
  CLI prints `error: <message>` plus the catalog remediation line when the
  code is known.

### Task 1.3: Cockpit `ErrorNotice` + `daemon_unreachable`

- `ApiRequestError` gains `detail`; network-level fetch failures synthesize
  code `daemon_unreachable` (recovery: "start `education-pipeline ui`").
- `ErrorNotice` maps code → plain-language explanation + recovery action
  (Retry / Reload latest / Open Settings / Unarchive / daemon instructions),
  raw message + detail behind a "details" disclosure; unknown codes render
  the generic fallback. Existing `error.message` renderings migrate to it.

**Close:** pytest + vitest + build green; commit per task.

---

# Wave 2 — `education-pipeline ui` launcher and asset bundling

**Outcome:** `pip install` + `education-pipeline ui` yields a working
cockpit: workspace resolution (flag → registry → first-run flow),
validation/scaffolding, daemon reuse-or-start, URL print, browser open.

### Task 2.1: `default_web_dist` lookup order + packaging

- Lookup order: `$EP_WEB_DIST` override → packaged
  `education_pipeline/_webdist/` → repo-relative `web/dist/` → `None`.
- `scripts/build_webdist.py` (stdlib): `npm run build` then a clean copy of
  `web/dist/` → `education_pipeline/_webdist/`. `_webdist/` gitignored and
  declared as package data in `pyproject.toml`.

### Task 2.2: `ui` orchestration

- `education_pipeline/ui.py` with injectable seams (daemon ensurer, browser
  opener, TTY prompt IO) so pytest drives every path with fakes:
  1. resolve workspace: `--workspace` → registry `last_used` → first-run
     selection (interactive TTY: create `~/EducationPipeline` or enter a
     path; non-TTY: exit with `workspace_unselected` + instructions);
  2. validate/scaffold via Wave 0 (`--fix`-style auto-scaffold only for a
     directory the user just chose to create; otherwise stop and print
     findings, error `workspace_invalid`);
  3. ensure daemon (reuse live discovery record, else start);
  4. missing web dist ⇒ error `web_assets_missing` with recovery message;
  5. print the cockpit URL always; open browser unless `--no-browser`.
- Registers/updates the registry (`last_used`) on success. Idempotent.

### Task 2.3: CI packaging smoke

- CI job: build cockpit, run `scripts/build_webdist.py`, build the wheel,
  install into a clean venv, run `education-pipeline ui --no-browser`
  against a temp workspace, assert the served cockpit index responds 200,
  then daemon stop.

**Close:** pytest green; CLI smoke (`education-pipeline ui --help`); commit
per task.

---

# Wave 3 — Course library: enriched list, archive, duplicate, reveal

**Outcome:** the library manages the course lifecycle: enriched list
payload, archive/unarchive behind the manifest lock with a write guard,
duplicate-from-brief, and workspace-confined reveal-in-files, with the
cockpit UI for filtering/sorting and all four actions.

### Task 3.1: Enriched `/v1/topics` payload

- Per-course additions computed server-side: `last_activity` (ISO-8601 UTC
  mtime of the newest run artifact), `archived` (manifest flag; absent run ⇒
  `false`), `profile_id` (attached snapshot's embedded id), `completion`
  (`{stages_approved, stages_total, exported}` over required stages).

### Task 3.2: Archive/unarchive + `archived_course` write guard

- `RunStore.archive_run` / `unarchive_run` set `archived` + timestamp in the
  run manifest under `_manifest_write_lock`; `is_archived` reader. Nothing
  moves on disk.
- `POST /v1/runs/{topic}/archive` and `/unarchive`; topic with no run ⇒ 404.
- Mutating write actions (advance, ingest/edit response, approve, enqueue
  run, prepare audit, validate, waivers, finalize, export, attach profile)
  on an archived course ⇒ 409 `archived_course`. Read endpoints still work.
  Lock-contention test included.

### Task 3.3: Duplicate from brief

- `POST /v1/topics/{id}/duplicate`: new topic id `<id>-copy` (then
  `-copy-2`, …), copies the topic definition with the embedded id replaced;
  optional `attach_profile: true` re-attaches the source run's profile via a
  **fresh** snapshot; copies no run artifacts.

### Task 3.4: Reveal in files

- `education_pipeline/daemon/reveal.py`: pure `resolve_reveal_target(...)`
  (enum `run`/`export`/`topic` → concrete path) + `realpath` containment
  check inside the workspace (symlink escapes rejected), and a thin
  `open_in_file_manager(path)` invoking the platform opener (`open -R` /
  `xdg-open` / `explorer /select,`), overridable via `EP_REVEAL_OPENER` for
  tests. `POST /v1/reveal` with `{"target", "topic_id"}`; opener failure or
  unsupported platform ⇒ `reveal_unsupported` with the resolved path in
  `detail`. Enum-target and symlink-escape tests are non-negotiable.

### Task 3.5: Library cockpit

- `TopicListPage`: enriched columns; client-side filter by status, learner,
  archived (hidden by default), free text over id/title; sort by last
  activity (default), title, completion; Archive/Unarchive, Duplicate, and
  Reveal actions (reveal failure falls back to showing the path with a copy
  button); errors through `ErrorNotice`.

**Close:** full four-suite gate; commit per task.

---

# Wave 4 — Welcome panel, empty states, New Course flow polish

**Outcome:** first-run onboarding per spec §4 and the wizard as the complete
happy path per spec §6, structurally ready for a later blueprint step.

### Task 4.1: `GET /v1/workspace`

- Read-only `{path, counts: {topics, runs, profiles}, first_run}`
  (`first_run` = zero runs).

### Task 4.2: Welcome panel + empty states

- `WelcomePanel` on the library page when `first_run` and not dismissed
  (localStorage; "Show welcome" control in Settings re-opens it): the three
  PRD §6.1 facts, detected provider availability with manual mode
  first-class, one primary CTA → New Course wizard. No multi-step tour.
- Run board / jobs panels get short purposeful empty states.

### Task 4.3: Wizard polish

- Steps become: **Learner** (existing profile or "none", link out to
  import) → **Topic + brief** (existing form) → **Model plan review**
  (read-only effective-plan summary, "adjust in Settings" link) →
  **Confirm** (learner/topic pairing, estimated stages, selected plan).
  Create happens at Confirm; the user lands on the run board with the next
  action highlighted. Blueprint remains the existing simple field; step
  structure keeps room for a blueprint step (other branch).

**Close:** full four-suite gate; commit per task.

---

# Wave 5 — Acceptance, docs, closeout

- New Playwright coverage per spec §8: first-run welcome → create course →
  run board next action; archive → hidden by default → filter shows →
  unarchive; duplicate → new course at spec; reveal fallback path shows a
  copyable path.
- Docs: README/user docs for `ui`, the registry location, and
  troubleshooting via error codes.
- PRD §10 "P1 — First-run and course-management experience" → Delivered
  with closeout evidence links; post-milestone audit ledger under
  `docs/superpowers/specs/` following the personalization audit format.
- Final four-suite gate with counts recorded in the Wave Log; push branch.
