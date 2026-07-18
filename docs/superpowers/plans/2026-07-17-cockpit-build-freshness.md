# Cockpit Build Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a stale/missing cockpit build in source checkouts and warn on both the CLI and in the cockpit — never rebuilding without an explicit `--rebuild` — so users who `git pull` are told why the UI looks old.

**Architecture:** A pure mtime-based status primitive in `education_pipeline/daemon/static.py` feeds three surfaces: the `/v1/health` payload (daemon), a stderr warning + opt-in `--rebuild` flag in `run_ui` (CLI), and a dismissible React banner (cockpit). Wheel installs and `$EP_WEB_DIST` overrides always report `ok` and stay silent.

**Tech Stack:** Python 3.11+ stdlib only (runtime), pytest, React 18 + TypeScript, vitest, Playwright + @axe-core.

**Spec:** `docs/superpowers/specs/2026-07-17-cockpit-build-freshness-design.md`

## Global Constraints

- **Standard library only at runtime** for the Python package; `pytest` is the sole dev dependency. No new runtime dependencies.
- **TDD**: every task writes its failing test first, per repo convention.
- **Never run npm behind the user's back**: builds happen only under the explicit `--rebuild` flag.
- **Warnings never block**: a stale build warns and continues; only `--rebuild` failures exit non-zero.
- **Error codes are append-only**, lowercase snake_case, added to `ERROR_CATALOG` in `education_pipeline/errors.py`.
- **CLI output is plain ASCII** (Windows consoles run cp1252; no `⚠` glyphs).
- Wheel installs (packaged `_webdist`) and `$EP_WEB_DIST` overrides must report `ok` — no warning surface may activate for them.
- Run Python tests from repo root: `python3 -m pytest tests/<file> -k <fragment>`. Web tests from `web/`: `npm run test`, `npm run e2e`.

---

### Task 1: Build-status primitives in `static.py`

**Files:**
- Modify: `education_pipeline/daemon/static.py` (append after `default_web_dist`, ~line 64)
- Test: `tests/test_static.py` (append)

**Interfaces:**
- Consumes: existing module constants `_REPO_WEB_DIST`, `_PACKAGED_WEB_DIST`.
- Produces (used by Tasks 2–4):
  - `cockpit_build_status(web_dir: Path) -> str` — `"ok" | "stale" | "missing"`, pure, testable on tmp dirs.
  - `repo_web_dir() -> Path | None` — the repo `web/` dir when this is a dev checkout (`web/src` exists), else `None`.
  - `cockpit_build_report(dist: Path | None) -> dict` — `{"status": str, "build_id": str | None}`; returns `{"status": "ok", "build_id": None}` unless `dist` is the dev-checkout `web/dist` with no `$EP_WEB_DIST` override.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_static.py` (it already imports from `education_pipeline.daemon.static`; extend that import):

```python
import os

from education_pipeline.daemon import static as static_mod
from education_pipeline.daemon.static import (
    cockpit_build_report,
    cockpit_build_status,
    repo_web_dir,
)


def _make_web_dir(tmp_path):
    """A minimal dev checkout web/ dir: src/ input and dist/ output."""
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "src" / "App.tsx").write_text("export {}", encoding="utf-8")
    (web / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (web / "package.json").write_text("{}", encoding="utf-8")
    (web / "dist").mkdir()
    (web / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return web


def _set_mtime(path, *, ns):
    os.utime(path, ns=(ns, ns))


def test_build_status_ok_when_dist_newer(tmp_path):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "src" / "App.tsx", ns=1_000)
    _set_mtime(web / "dist" / "index.html", ns=2_000)
    assert cockpit_build_status(web) == "ok"


def test_build_status_stale_when_src_newer(tmp_path):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=2_000)
    assert cockpit_build_status(web) == "stale"


def test_build_status_stale_when_config_input_newer(tmp_path):
    web = _make_web_dir(tmp_path)
    (web / "vite.config.ts").write_text("export default {}", encoding="utf-8")
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=500)
    _set_mtime(web / "vite.config.ts", ns=2_000)
    assert cockpit_build_status(web) == "stale"


def test_build_status_missing_without_dist_index(tmp_path):
    web = _make_web_dir(tmp_path)
    (web / "dist" / "index.html").unlink()
    assert cockpit_build_status(web) == "missing"


def test_repo_web_dir_requires_src(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    assert repo_web_dir() == web
    # Without web/src (a wheel layout) there is no dev checkout.
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", tmp_path / "elsewhere" / "dist")
    assert repo_web_dir() is None


def test_build_report_stale_for_dev_checkout(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=2_000)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    report = cockpit_build_report(web / "dist")
    assert report["status"] == "stale"
    assert report["build_id"] == "1000"


def test_build_report_silent_for_non_checkout_dist(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    # A packaged _webdist (any dist that is not the repo fallback) is silent.
    other = tmp_path / "webdist"
    other.mkdir()
    assert cockpit_build_report(other) == {"status": "ok", "build_id": None}
    assert cockpit_build_report(None) == {"status": "ok", "build_id": None}


def test_build_report_silent_under_env_override(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=2_000)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.setenv("EP_WEB_DIST", str(web / "dist"))
    assert cockpit_build_report(web / "dist") == {"status": "ok", "build_id": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_static.py -k "build_status or repo_web_dir or build_report" -v`
Expected: FAIL — `ImportError: cannot import name 'cockpit_build_status'`

- [ ] **Step 3: Implement in `static.py`**

Append after `default_web_dist` (keep the module's docstring/comment style):

```python
def _newest_input_mtime_ns(web_dir: Path) -> int | None:
    """Newest mtime across the cockpit's build inputs (spec §1)."""

    candidates: list[Path] = [
        web_dir / "index.html",
        web_dir / "package.json",
        web_dir / "package-lock.json",
    ]
    candidates.extend(web_dir.glob("tsconfig*.json"))
    candidates.extend(web_dir.glob("vite.config.*"))
    src = web_dir / "src"
    if src.is_dir():
        candidates.extend(p for p in src.rglob("*") if p.is_file())
    newest: int | None = None
    for path in candidates:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def cockpit_build_status(web_dir: Path) -> str:
    """``ok``/``stale``/``missing`` for a dev checkout's built cockpit.

    ``stale`` means some build input under ``web_dir`` is newer than
    ``web_dir/dist/index.html``. mtime (not a git SHA) so it needs no git
    and catches uncommitted edits; the outcome is only ever a warning, so
    a rare false positive is harmless.
    """

    try:
        built_ns = (web_dir / "dist" / "index.html").stat().st_mtime_ns
    except OSError:
        return "missing"
    newest = _newest_input_mtime_ns(web_dir)
    if newest is not None and newest > built_ns:
        return "stale"
    return "ok"


def repo_web_dir() -> Path | None:
    """The repo ``web/`` dir when running from a dev checkout, else None.

    A wheel install has no ``web/src`` next to the package, so this is the
    scope guard that keeps every freshness surface silent for wheels.
    """

    web_dir = _REPO_WEB_DIST.parent
    return web_dir if (web_dir / "src").is_dir() else None


def cockpit_build_report(dist: Path | None) -> dict:
    """Freshness payload for ``dist``: ``{"status", "build_id"}``.

    Anything other than the dev-checkout fallback — packaged ``_webdist``,
    an ``$EP_WEB_DIST`` override, or no dist at all — reports ``ok`` so
    wheel users never see a warning. ``build_id`` identifies the current
    build (dist index.html mtime) so the cockpit can key banner dismissal
    to it.
    """

    if os.environ.get("EP_WEB_DIST"):
        return {"status": "ok", "build_id": None}
    web_dir = repo_web_dir()
    if web_dir is None or dist is None or Path(dist) != _REPO_WEB_DIST:
        return {"status": "ok", "build_id": None}
    status = cockpit_build_status(web_dir)
    try:
        build_id = str((web_dir / "dist" / "index.html").stat().st_mtime_ns)
    except OSError:
        build_id = None
    return {"status": status, "build_id": build_id}
```

Note: `os` is already imported at the top of `static.py`.

The test sets mtimes in whole nanoseconds (`ns=1_000`), so `build_id == "1000"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_static.py -v`
Expected: all PASS (new tests and the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/static.py tests/test_static.py
git commit -m "feat(daemon): cockpit build-freshness status primitives"
```

---

### Task 2: `/v1/health` carries `cockpit_build`

**Files:**
- Modify: `education_pipeline/daemon/server.py` (the `/v1/health` branch in `_api_get_routes`, ~line 320)
- Test: `tests/test_server.py` (extend `test_health_ok`, ~line 225; add one stale test)

**Interfaces:**
- Consumes: `cockpit_build_report(dist)` from Task 1; `context.web_dist` on `DaemonContext`.
- Produces: `/v1/health` JSON gains `"cockpit_build": {"status": "ok"|"stale"|"missing", "build_id": str|null}` — consumed by the cockpit banner (Task 5) and its e2e fake (Task 6).

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, extend the existing `test_health_ok` and add a stale-path test next to it. Follow the file's `_req(server, "GET", path)` helper and `server` fixture already in use at line 225:

```python
def test_health_ok(server):
    status, body = _req(server, "GET", "/v1/health")
    assert status == 200
    assert body["ok"] is True
    # Freshness is always present; the test server's tmp dist is not the
    # repo dev-checkout fallback, so it reports ok/None.
    assert body["cockpit_build"] == {"status": "ok", "build_id": None}
```

(Keep any other assertions the current `test_health_ok` makes.) Then add:

```python
def test_health_reports_stale_dev_checkout(tmp_path, monkeypatch):
    from education_pipeline.daemon import static as static_mod

    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "src" / "App.tsx").write_text("export {}", encoding="utf-8")
    (web / "dist").mkdir()
    (web / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    import os as _os

    _os.utime(web / "dist" / "index.html", ns=(1_000, 1_000))
    _os.utime(web / "src" / "App.tsx", ns=(2_000, 2_000))
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.delenv("EP_WEB_DIST", raising=False)

    srv, _thread = _start_server(tmp_path, monkeypatch, web_dist=web / "dist")
    try:
        status, body = _req(srv.server_port, "GET", "/v1/health")
        assert status == 200
        assert body["cockpit_build"]["status"] == "stale"
        assert body["cockpit_build"]["build_id"] == "1000"
    finally:
        srv.shutdown()
```

Adapt the boot/teardown lines to exactly match how a nearby test uses `_start_server` (see the test at ~line 213 that calls `_req(srv.server_port, ...)`); the `_start_server` signature already accepts `web_dist=`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -k "health" -v`
Expected: `test_health_ok` FAILS with `KeyError: 'cockpit_build'`; the new test FAILS likewise.

- [ ] **Step 3: Implement**

In `education_pipeline/daemon/server.py`, add `cockpit_build_report` to the existing `from education_pipeline.daemon.static import ...` line, and change the health branch (~line 320):

```python
if self.path.startswith("/v1/health"):
    return self._send(
        200,
        {
            "version": context.version,
            "started_at": None,
            "ok": True,
            "cockpit_build": cockpit_build_report(context.web_dist),
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -k "health" -v`
Expected: all PASS. Then run the whole file: `python3 -m pytest tests/test_server.py` — no regressions.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): report cockpit build freshness on /v1/health"
```

---

### Task 3: `education-pipeline ui` warns on a stale build

**Files:**
- Modify: `education_pipeline/ui.py` (add a `build_report` seam to `UiDeps`; warn in `run_ui`)
- Test: `tests/test_ui.py` (append)

**Interfaces:**
- Consumes: `cockpit_build_report` from Task 1.
- Produces: `UiDeps.build_report: Callable[[Path | None], dict]` (default `cockpit_build_report`); stderr warning lines beginning `warning [cockpit_build_stale]:` and `fix:`. Task 4 inserts its rebuild step *before* this warning check.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui.py`, using the file's existing `make_deps` helper:

```python
def test_stale_build_warns_but_launches(tmp_path, capsys):
    deps, calls = make_deps(
        tmp_path,
        build_report=lambda dist: {"status": "stale", "build_id": "1000"},
    )
    assert run_ui(str(tmp_path / "ws"), deps=deps) == 0
    err = capsys.readouterr().err
    assert "warning [cockpit_build_stale]" in err
    assert "npm run build" in err
    assert "--rebuild" in err
    assert calls["opened"]  # launch was not blocked


def test_fresh_build_prints_no_warning(tmp_path, capsys):
    deps, calls = make_deps(tmp_path)
    assert run_ui(str(tmp_path / "ws"), deps=deps) == 0
    assert "cockpit_build_stale" not in capsys.readouterr().err
```

The second test relies on the default `build_report` being the real `cockpit_build_report`, which reports `ok` for the fake tmp dist — no `make_deps` change needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ui.py -k "stale_build or fresh_build" -v`
Expected: FAIL — `TypeError: UiDeps.__init__() got an unexpected keyword argument 'build_report'`

- [ ] **Step 3: Implement**

In `education_pipeline/ui.py`:

Extend the import from static:

```python
from education_pipeline.daemon.static import cockpit_build_report, default_web_dist
```

Add the field to `UiDeps` (after `web_dist`):

```python
    build_report: Callable = cockpit_build_report
```

In `run_ui`, replace the current web-dist check block:

```python
    if deps.web_dist() is None:
        _print_error("web_assets_missing")
        return 1
```

with:

```python
    dist = deps.web_dist()
    if dist is None:
        _print_error("web_assets_missing")
        return 1
    if deps.build_report(dist)["status"] == "stale":
        print(
            "warning [cockpit_build_stale]: the built cockpit is older than "
            "its source; the browser may show old UI",
            file=sys.stderr,
        )
        print(
            "fix: rebuild with `cd web && npm run build`, or relaunch with "
            "`education-pipeline ui --rebuild`",
            file=sys.stderr,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ui.py -v`
Expected: all PASS (new and pre-existing).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/ui.py tests/test_ui.py
git commit -m "feat(ui): warn on a stale cockpit build at launch"
```

---

### Task 4: opt-in `education-pipeline ui --rebuild`

**Files:**
- Modify: `education_pipeline/errors.py` (append three catalog entries)
- Modify: `education_pipeline/ui.py` (`_default_npm_build`, `UiDeps` seams, rebuild step in `run_ui`)
- Modify: `education_pipeline/cli.py` (`ui` subparser ~line 223; `_cmd_ui` ~line 736)
- Test: `tests/test_ui.py` (append)

**Interfaces:**
- Consumes: `repo_web_dir()` from Task 1; the warning block position from Task 3 (rebuild runs *before* the `dist = deps.web_dist()` line so a never-built checkout can bootstrap).
- Produces: `run_ui(workspace, *, no_browser=False, rebuild=False, deps=None)`; `UiDeps.npm_build: Callable[[Path], int | None]` (None ⇒ npm missing) and `UiDeps.repo_web_dir: Callable[[], Path | None]`; error codes `cockpit_rebuild_unavailable`, `npm_missing`, `cockpit_build_failed` in `ERROR_CATALOG`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui.py`:

```python
def test_rebuild_runs_npm_then_launches(tmp_path):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    built = []
    deps, calls = make_deps(
        tmp_path,
        repo_web_dir=lambda: web_dir,
        npm_build=lambda d: built.append(d) or 0,
    )
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 0
    assert built == [web_dir]
    assert calls["opened"]


def test_rebuild_outside_checkout_errors(tmp_path, capsys):
    deps, calls = make_deps(tmp_path, repo_web_dir=lambda: None)
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 1
    assert "cockpit_rebuild_unavailable" in capsys.readouterr().err
    assert not calls["ensure"]  # no daemon was started


def test_rebuild_without_npm_errors(tmp_path, capsys):
    deps, calls = make_deps(
        tmp_path,
        repo_web_dir=lambda: tmp_path / "web",
        npm_build=lambda d: None,
    )
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 1
    assert "npm_missing" in capsys.readouterr().err


def test_rebuild_failure_stops_launch(tmp_path, capsys):
    deps, calls = make_deps(
        tmp_path,
        repo_web_dir=lambda: tmp_path / "web",
        npm_build=lambda d: 2,
    )
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 1
    assert "cockpit_build_failed" in capsys.readouterr().err
    assert not calls["ensure"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ui.py -k "rebuild" -v`
Expected: FAIL — unexpected keyword argument `repo_web_dir`.

- [ ] **Step 3: Implement**

`education_pipeline/errors.py` — append inside the `ERROR_CATALOG` list (append-only, before the closing `]`), matching the `_entry` style of neighbors:

```python
        _entry(
            "cockpit_rebuild_unavailable",
            "--rebuild needs a source checkout containing web/src.",
            "Packaged installs already bundle the cockpit; run "
            "`education-pipeline ui` without --rebuild.",
        ),
        _entry(
            "npm_missing",
            "npm was not found on PATH.",
            "Install Node.js (which provides npm), or build manually with "
            "`cd web && npm run build`.",
        ),
        _entry(
            "cockpit_build_failed",
            "The cockpit build (npm run build) failed.",
            "Fix the reported build errors in web/, then rerun.",
        ),
```

`education_pipeline/ui.py` — add imports `shutil`, `subprocess`, and `repo_web_dir` (extend the existing static import). Add:

```python
def _default_npm_build(web_dir: Path) -> int | None:
    """Run `npm run build` in ``web_dir``; None when npm is not installed."""

    npm = shutil.which("npm")
    if npm is None:
        return None
    return subprocess.call([npm, "run", "build"], cwd=web_dir)
```

Extend `UiDeps`:

```python
    repo_web_dir: Callable = repo_web_dir
    npm_build: Callable = _default_npm_build
```

(Name collision note: the dataclass field default referencing the imported function of the same name works because the import is module-level; keep the field names exactly as shown.)

Change the `run_ui` signature:

```python
def run_ui(
    workspace: str | None,
    *,
    no_browser: bool = False,
    rebuild: bool = False,
    deps: UiDeps | None = None,
) -> int:
```

Insert the rebuild step in `run_ui` immediately **before** the `dist = deps.web_dist()` line from Task 3 (after the workspace-findings block):

```python
    if rebuild:
        web_dir = deps.repo_web_dir()
        if web_dir is None:
            _print_error("cockpit_rebuild_unavailable")
            return 1
        code = deps.npm_build(web_dir)
        if code is None:
            _print_error("npm_missing")
            return 1
        if code != 0:
            _print_error("cockpit_build_failed")
            return 1
```

`_print_error` already prints `error [<code>]: <summary>` + `fix: <remediation>` from the catalog, which is what the tests assert.

`education_pipeline/cli.py` — in the `ui` subparser block (~line 223), after the `--no-browser` argument:

```python
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="rebuild the cockpit (npm run build in web/) before launching; "
        "source checkouts only",
    )
```

And in `_cmd_ui` (~line 736), pass it through:

```python
    return run_ui(workspace, no_browser=args.no_browser, rebuild=args.rebuild)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ui.py -v` — all PASS.
Run: `python3 -m pytest` — full suite green (the CLI smoke test in CI covers `--help` parse).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/errors.py education_pipeline/ui.py education_pipeline/cli.py tests/test_ui.py
git commit -m "feat(ui): opt-in --rebuild flag rebuilds the cockpit before launch"
```

---

### Task 5: cockpit banner (types, component, mount, styles)

**Files:**
- Modify: `web/src/api/types.ts` (append)
- Create: `web/src/components/BuildFreshnessBanner.tsx`
- Test: `web/src/components/BuildFreshnessBanner.test.tsx`
- Modify: `web/src/App.tsx` (mount inside `<main>`)
- Modify: `web/src/styles.css` (append `.build-banner` rules)

**Interfaces:**
- Consumes: `/v1/health` shape from Task 2 via the existing `api<T>(path)` helper in `web/src/api/client.ts`.
- Produces: `CockpitBuild` and `HealthPayload` types; `<BuildFreshnessBanner />` rendered at the top of `<main className="workspace">`; localStorage key `"ep-cockpit-build-dismissed"` storing the dismissed `build_id`.

- [ ] **Step 1: Add the types**

Append to `web/src/api/types.ts`:

```ts
export interface CockpitBuild {
  status: "ok" | "stale" | "missing";
  build_id: string | null;
}

export interface HealthPayload {
  version: string;
  ok: boolean;
  cockpit_build: CockpitBuild;
}
```

- [ ] **Step 2: Write the failing component tests**

Create `web/src/components/BuildFreshnessBanner.test.tsx`. Before writing, open one existing test that mocks the api module (e.g. `web/src/components/JobsPanel.test.tsx`) and mirror its mocking idiom exactly; the shape below is the target behavior:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: apiMock,
}));

import BuildFreshnessBanner from "./BuildFreshnessBanner";

function healthWith(status: string, buildId: string | null = "b1") {
  return {
    version: "test",
    ok: true,
    cockpit_build: { status, build_id: buildId },
  };
}

describe("BuildFreshnessBanner", () => {
  beforeEach(() => {
    apiMock.mockReset();
    localStorage.clear();
  });

  it("shows when the build is stale", async () => {
    apiMock.mockResolvedValue(healthWith("stale"));
    render(<BuildFreshnessBanner />);
    expect(await screen.findByRole("status")).toHaveTextContent(/older than its source/i);
  });

  it("stays hidden when the build is ok", async () => {
    apiMock.mockResolvedValue(healthWith("ok"));
    render(<BuildFreshnessBanner />);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("dismisses and stays dismissed for the same build", async () => {
    apiMock.mockResolvedValue(healthWith("stale", "b1"));
    render(<BuildFreshnessBanner />);
    await userEvent.click(await screen.findByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(localStorage.getItem("ep-cockpit-build-dismissed")).toBe("b1");
  });

  it("re-appears for a different (newer) stale build", async () => {
    localStorage.setItem("ep-cockpit-build-dismissed", "b1");
    apiMock.mockResolvedValue(healthWith("stale", "b2"));
    render(<BuildFreshnessBanner />);
    expect(await screen.findByRole("status")).toBeInTheDocument();
  });

  it("never blocks the app when health fails", async () => {
    apiMock.mockRejectedValue(new Error("down"));
    render(<BuildFreshnessBanner />);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `web/`): `npm run test -- BuildFreshnessBanner`
Expected: FAIL — cannot resolve `./BuildFreshnessBanner`.

- [ ] **Step 4: Implement the component**

Create `web/src/components/BuildFreshnessBanner.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CockpitBuild, HealthPayload } from "../api/types";

const STORAGE_KEY = "ep-cockpit-build-dismissed";

/**
 * Source-checkout freshness notice: shown when the daemon reports the
 * built cockpit is older than its source (spec: cockpit-build-freshness).
 * Advisory only — health failures and non-stale statuses render nothing.
 */
export default function BuildFreshnessBanner() {
  const [build, setBuild] = useState<CockpitBuild | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<HealthPayload>("/v1/health")
      .then((health) => {
        if (!cancelled) setBuild(health.cockpit_build);
      })
      .catch(() => {
        // Advisory banner: never surface an error for a health probe.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (build === null || build.status !== "stale") return null;
  const key = build.build_id ?? "unknown";
  if (dismissed || localStorage.getItem(STORAGE_KEY) === key) return null;

  return (
    <div className="build-banner" role="status">
      <p>
        This cockpit build is older than its source — you may be seeing old
        UI. Rebuild with <code>cd web &amp;&amp; npm run build</code> (or
        relaunch with <code>education-pipeline ui --rebuild</code>), then
        reload this page.
      </p>
      <button
        type="button"
        onClick={() => {
          localStorage.setItem(STORAGE_KEY, key);
          setDismissed(true);
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `web/`): `npm run test -- BuildFreshnessBanner`
Expected: all 5 PASS.

- [ ] **Step 6: Mount and style**

In `web/src/App.tsx`: add `import BuildFreshnessBanner from "./components/BuildFreshnessBanner";` and render it as the first child of `<main className="workspace">`, above `<Routes>`:

```tsx
      <main className="workspace">
        <BuildFreshnessBanner />
        <Routes>
```

In `web/src/styles.css`, append (reuse existing custom properties where the file defines suitable ones — check how warnings/notices are colored elsewhere in the file and prefer those tokens over these fallbacks):

```css
/* Source-checkout build-freshness banner */
.build-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.6rem 1rem;
  margin-bottom: 1rem;
  border: 1px solid #b45309;
  border-radius: 6px;
  background: #fef3c7;
  color: #78350f;
}
.build-banner code {
  font-family: inherit;
  font-weight: 600;
}
.build-banner button {
  flex: none;
}
```

- [ ] **Step 7: Full web gate**

Run (from `web/`): `npm run test` (all unit tests) then `npm run build` (tsc + vite).
Expected: both green.

- [ ] **Step 8: Commit**

```bash
git add web/src/api/types.ts web/src/components/BuildFreshnessBanner.tsx web/src/components/BuildFreshnessBanner.test.tsx web/src/App.tsx web/src/styles.css
git commit -m "feat(web): dismissible stale-build banner driven by /v1/health"
```

---

### Task 6: e2e coverage (banner + axe)

**Files:**
- Create: `web/e2e/build-banner.spec.ts`

**Interfaces:**
- Consumes: `bootDaemon` from `web/e2e/helpers/daemon.ts`; the health shape from Task 2; banner selectors from Task 5.
- Produces: e2e proof the banner shows on stale, dismisses, and passes axe. (The real daemon under e2e always reports `ok` because `bootDaemon` sets `EP_WEB_DIST`; the stale state is faked via `page.route` interception of `/v1/health`.)

- [ ] **Step 1: Write the spec**

Before writing, open an existing spec that uses axe (grep `AxeBuilder` under `web/e2e/`) and mirror its import and scan pattern, plus `bootDaemon` teardown from e.g. `library.spec.ts`. Target content:

```ts
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

let handle: DaemonHandle;

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-build-banner-");
});

test.afterAll(async () => {
  handle.daemon.kill();
});

const staleHealth = {
  version: "test",
  ok: true,
  cockpit_build: { status: "stale", build_id: "e2e-build-1" },
};

test("stale build shows an accessible, dismissible banner", async ({ page }) => {
  await page.route("**/v1/health", (route) => route.fulfill({ json: staleHealth }));
  await page.goto(handle.baseURL);

  const banner = page.getByRole("status").filter({ hasText: /older than its source/i });
  await expect(banner).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);

  await banner.getByRole("button", { name: /dismiss/i }).click();
  await expect(banner).toBeHidden();

  // Dismissal is keyed to the build id and survives reload.
  await page.reload();
  await expect(
    page.getByRole("status").filter({ hasText: /older than its source/i }),
  ).toBeHidden();
});

test("fresh build shows no banner", async ({ page }) => {
  await page.goto(handle.baseURL);
  await expect(
    page.getByRole("status").filter({ hasText: /older than its source/i }),
  ).toBeHidden();
});
```

Adjust `afterAll` teardown to exactly match the sibling specs (some remove the workspace dir too — copy what `library.spec.ts` does with `handle.ws`).

- [ ] **Step 2: Run the spec**

Run (from `web/`, after `npm run build`): `npx playwright test e2e/build-banner.spec.ts`
Expected: 2 PASS.

- [ ] **Step 3: Run the full e2e suite**

Run (from `web/`): `npm run e2e`
Expected: green — the always-`ok` report under `EP_WEB_DIST` means no other spec sees the banner.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/build-banner.spec.ts
git commit -m "test(e2e): stale-build banner visibility, dismissal, and axe"
```

---

### Task 7: documentation

**Files:**
- Modify: `README.md` (install section, ~lines 82–90)
- Modify: `docs/install-and-first-course.md` (near its `npm run build` instruction)
- Modify: `docs/troubleshooting.md` (line ~39 wording; "Common first-run problems"; error-code table)

**Interfaces:** none — prose only, but command names must match Task 4 exactly (`education-pipeline ui --rebuild`).

- [ ] **Step 1: README**

In the Install section, directly after the source-checkout install lines (`python3 -m pip install -e ".[dev]"` / `(cd web && npm ci && npm run build)`), insert:

```markdown
> **Keeping a source checkout current:** `git pull` updates the cockpit's
> *source*, not the built bundle the daemon serves. After any pull that
> touches `web/`, rebuild with `(cd web && npm run build)` — or launch
> with `education-pipeline ui --rebuild`. If you skip this, `ui` warns
> and the cockpit shows a banner. Release wheels bundle a prebuilt
> cockpit and never need this.
```

- [ ] **Step 2: install-and-first-course.md**

Find the insertion point: `grep -n "npm run build" docs/install-and-first-course.md`. Immediately after that build instruction, insert the same call-out as Step 1 (verbatim), so both entry docs tell one story.

- [ ] **Step 3: troubleshooting.md**

Three edits:

1. Fix the misleading wording at ~line 39: the sentence currently says a checkout should "build once with `npm run build`". Reword to:

```markdown
a source checkout does not. In a checkout, build with `npm run build`
in `web/` — and rebuild after any `git pull` that touches `web/`, or
launch with `education-pipeline ui --rebuild`.
```

2. Add a new entry at the top of "Common first-run problems":

```markdown
**I pulled changes but the cockpit looks the same.** The daemon serves
the built bundle in `web/dist`, and `git pull` only updates source.
`education-pipeline ui` prints a `cockpit_build_stale` warning and the
cockpit shows a banner when this happens. Rebuild with
`(cd web && npm run build)` (or `education-pipeline ui --rebuild`) and
hard-reload the browser. Restarting the daemon alone never fixes this.
```

3. Append three rows to the error-code reference table, matching its format:

```markdown
| `cockpit_rebuild_unavailable` | --rebuild needs a source checkout containing web/src. | Packaged installs already bundle the cockpit; run `education-pipeline ui` without --rebuild. |
| `npm_missing` | npm was not found on PATH. | Install Node.js (which provides npm), or build manually with `cd web && npm run build`. |
| `cockpit_build_failed` | The cockpit build (npm run build) failed. | Fix the reported build errors in web/, then rerun. |
```

- [ ] **Step 4: Verify docs consistency**

Run: `grep -rn "build once" docs/ README.md` — expected: no matches.
Run: `grep -rn "ui --rebuild" README.md docs/install-and-first-course.md docs/troubleshooting.md` — expected: at least one match per file.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/install-and-first-course.md docs/troubleshooting.md
git commit -m "docs: source checkouts must rebuild the cockpit after pulls"
```

---

## Final verification

- [ ] `python3 -m pytest` — full Python suite green
- [ ] `cd web && npm run test && npm run build && npm run e2e` — full web gate green
- [ ] Manual smoke: `touch web/src/App.tsx`, run `education-pipeline ui --no-browser` from the checkout → stale warning prints; `(cd web && npm run build)` → warning gone.
