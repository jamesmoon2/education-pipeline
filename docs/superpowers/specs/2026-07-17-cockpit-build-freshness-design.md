# Cockpit build freshness for source checkouts — design

**Date:** 2026-07-17
**Status:** Approved

## Problem

A `git pull` in a source checkout updates cockpit *source* (`web/src`) but
not the built bundle (`web/dist`) the daemon serves. Restarting the daemon
re-reads the same stale files, so users see old UI and have no signal
telling them why. Release-wheel users are unaffected (wheels bundle
`education_pipeline/_webdist/`); the trap springs only on source
checkouts. Existing docs make it worse: `docs/troubleshooting.md` says to
build "once", and nothing detects a *stale* (as opposed to *missing*)
build.

Audience is split roughly evenly between wheel installs and source
checkouts, so the fix must keep the wheel path silent while giving
checkouts real staleness protection.

## Decision

Detect staleness and **warn clearly on both surfaces (CLI and cockpit)
without acting**. Never run npm behind the user's back; offer an explicit
opt-in `--rebuild` flag instead. This matches the project ethos (no
hidden actions, explicit approval) and needs no new dependencies.

## Design

### 1. Detection primitive

New pure function in `education_pipeline/daemon/` (next to `static.py`):

```python
cockpit_build_status(web_dir: Path) -> Literal["ok", "stale", "missing"]
```

- `missing` — `web/dist/index.html` absent.
- `stale` — newest mtime across build inputs is newer than
  `web/dist/index.html`. Build inputs: `web/src/**`, `web/index.html`,
  `web/package.json`, `web/package-lock.json`, `web/tsconfig*.json`,
  `web/vite.config.*`.
- `ok` — otherwise.

Scope guard: the check runs only when `default_web_dist()` resolved to
the repo's `web/dist` **and** `web/src` exists (a dev checkout). For
packaged `_webdist` or an `$EP_WEB_DIST` override the status is `ok` and
no warning surface activates — wheel users never see any of this.

Rationale for mtime over a git-SHA stamp: needs no git, catches both
`git pull` and uncommitted local edits, standard library only. Because
the outcome is only ever a warning, a rare false positive is harmless.

### 2. CLI surface (`education-pipeline ui`)

- On `stale` or `missing`, print a loud block before launching:
  the status, the consequence ("you may be seeing old UI"), and the
  exact fix (`cd web && npm run build`). Then continue with the existing
  build (or, for `missing`, the existing `web_assets_missing` behavior).
- New opt-in flag `education-pipeline ui --rebuild`: runs
  `npm run build` in `web/` (via `shutil.which("npm")`), streams output,
  and launches on success. Every build stays user-initiated. If npm is
  absent, fail with a clear message naming the manual fix.

### 3. Cockpit surface (banner)

- The daemon includes the build status (and a build identifier, e.g. the
  dist `index.html` mtime) in an existing `/v1` meta/health response —
  no new endpoint.
- The React app renders a dismissible banner on `stale`: "You may be
  viewing an outdated cockpit build — rebuild with `npm run build`."
- Dismissal is stored keyed to the build identifier, so a subsequent
  rebuild clears the dismissal and a *newly* stale build re-shows the
  banner.

### 4. Documentation

- **README** and **docs/install-and-first-course.md**: a short "Keeping
  a source checkout current" note — after any `git pull` that touches
  `web/`, rebuild the cockpit; wheels bundle a prebuilt cockpit and
  never need this. Make the wheel-vs-source distinction unmissable.
- **docs/troubleshooting.md**: fix the misleading "build once" wording
  (rebuild after any pull touching `web/`); add a top-level entry "I
  pulled changes but the cockpit looks the same" → stale build → fix;
  document the `ui` staleness warning and `--rebuild`.

### 5. Testing (TDD, per repo convention)

- **pytest**: `cockpit_build_status` (ok/stale/missing; wheel and
  `$EP_WEB_DIST` skip paths); `ui` warning output on stale/missing;
  `--rebuild` invokes npm and handles npm-absent; meta response carries
  the status field.
- **vitest**: banner renders on `stale`, hidden on `ok`; dismiss works;
  dismissal resets when the build identifier changes.
- **Playwright + axe**: banner is accessible and dismissible in the
  running cockpit.

## Rejected alternatives

- **Auto-rebuild (silent or prompted)** — hidden action, needs node at
  runtime, surprising delays. Replaced by explicit `--rebuild`.
- **Git-SHA build stamping** — requires git at runtime, misses
  uncommitted edits, more moving parts than mtime for the same warning.
- **Bundled dev-server mode** — out of scope; `npm run dev` already
  serves contributors doing active UI work.
