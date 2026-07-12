# Model-Plan Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user configures and executes a mixed-provider run entirely from the cockpit — recommended defaults or per-stage provider/model/effort overrides, with availability display, weak-config warnings, manual as a first-class choice, and the effective configuration persisted as run provenance — while hand-edited TOML still works.

**Architecture:** TOML files stay the source of truth (`<workspace>/config/model-catalog.toml` + `model-plan.toml`); a narrow emitter in `config.py` makes them writable. The daemon re-reads config per request via a `ConfigSource` abstraction. Per-run overrides are a sparse JSON file in the run dir, overlaid at each stage execution. New `/v1/config/*` and `/v1/runs/{topic}/plan` routes feed three cockpit surfaces: a Settings page, a per-run plan editor, and a New-run wizard.

**Tech Stack:** Python 3.11+ stdlib only (pytest dev-only), React 18 + TypeScript + Vite, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-07-11-model-plan-configuration-design.md` — read it first, every wave.

## Global Constraints

- **Stdlib only at runtime.** No new Python runtime dependencies. `tomllib` is read-only; the plan-TOML emitter is hand-written in `config.py`.
- **Strict TDD.** Every behavior change starts with a failing test committed alongside the fix.
- **Frozen surfaces untouched:** guide schema, `guide_runtime/assets/`, validation rules, prompt bytes, canonical fixture and its normalized SHA-256 (`99fde906…b07`). If a task appears to require touching one, STOP and escalate to the owner.
- **Suite baselines at plan start:** pytest 404, vitest 79, Playwright e2e 38. No regressions; additions only.
- **Never commit** generated runs, real learner profiles, or tuned prompt libraries.
- **Quality ordering** for weak-config warnings: `fast < strong < premium`; a model with no `quality` never warns; warning stages are exactly `spec`, `outline`, `repair`.
- Commands: pytest from repo root (`python3 -m pytest`); web commands from `web/` (`npm test -- --run`, `npm run build`, `npm run e2e`).

---

## Execution & Handoff Protocol (read me first, every session)

This plan is executed **one wave per manager session**. Context is cleared between waves; this file plus git history is the entire handoff state.

**On session start (every wave manager):**
1. Read this plan top to bottom, plus the spec.
2. Check the **Wave Log** below. Run `git log --oneline -5` and `git status`.
   - If HEAD equals the last recorded gate commit and the tree is clean: **trust the recorded suite counts — do not re-run the full suites.** Start your wave's first task directly.
   - If the tree is dirty or HEAD has moved past the gate commit: run `python3 -m pytest` and (if web files changed) `cd web && npm test -- --run` before starting, and investigate any failure before writing new code.
3. Work only your wave's tasks, in order, checking off steps in this file as you go.

**On wave completion (exit gate, every wave):**
1. Run the full gate: `python3 -m pytest`, then in `web/`: `npm test -- --run`, `npm run build`, `npm run e2e`.
2. Record in the **Wave Log**: date, gate commit SHA, suite counts, and one line of anything the next wave must know (deviations, discovered constraints).
3. Commit the updated plan file itself (`docs: record wave N gate`).
4. Report the handoff prompt for the next wave (verbatim from the wave's **Handoff** block) to the owner, then stop.

**Wave Log** (append one row per completed wave; never edit prior rows):

| Wave | Date | Gate commit | pytest | vitest | e2e | Notes for next wave |
|------|------|-------------|--------|--------|-----|---------------------|
| — | — | — | 404 | 79 | 38 | Baselines at plan start |

---

## File Structure

| File | Responsibility |
|------|----------------|
| `education_pipeline/export.py` (modify) | Wave 0: link-scheme allowlist; CSP meta on legacy HTML document |
| `education_pipeline/daemon/server.py` (modify) | Wave 0: CSP header on cockpit HTML. Waves 1–4: new routes |
| `education_pipeline/config.py` (modify) | Weak-config warnings, plan emitter, override overlay |
| `education_pipeline/daemon/__init__.py` (modify) | `ConfigSource` abstraction (fresh per-request/per-job loads) |
| `education_pipeline/daemon/read_api.py` (modify) | Config/plan read payload builders |
| `education_pipeline/daemon/write_api.py` (modify) | Global-plan PUT, run-overrides PUT, structured topic create |
| `education_pipeline/daemon/jobs.py` (unchanged interfaces) | JobRunner keeps taking `(catalog, plan)`; factory now loads fresh |
| `education_pipeline/runs.py` (modify) | Plan-overrides file I/O; `record_stage_provenance` |
| `education_pipeline/topics.py` (modify) | `emit_topic_toml` for the New-run form |
| `web/src/api/client.ts` + `types.ts` (modify) | New endpoints and payload types |
| `web/src/components/PlanStageRow.tsx` (create) | One stage's provider/model/effort selectors + warning (shared by Settings, run editor, wizard) |
| `web/src/pages/SettingsPage.tsx` (create) | Global defaults + availability |
| `web/src/components/RunPlanPanel.tsx` (create) | Per-run overrides + effective command preview |
| `web/src/pages/NewRunPage.tsx` (create) | Topic form/TOML → profile → plan review wizard |
| `web/src/App.tsx` (modify) | Routes `/settings`, `/new` |

---

# Wave 0 — Audit hardening + baseline

Independent of everything else. Lands as its own PR/commit series.

### Task 0.1: URL-scheme allowlist in the legacy Markdown renderer

**Files:**
- Modify: `education_pipeline/export.py` (`_render_inline_text`, ~line 196)
- Test: `tests/test_export.py`

**Interfaces:**
- Produces: `render_html_body(markdown_text)` never emits an `<a href>` whose scheme is outside `http:`/`https:`/`mailto:`/relative. Unsafe links degrade to `label (href)` plain text.

- [ ] **Step 1: Write the failing tests**

```python
def test_javascript_links_are_neutralized():
    html = render_html_body("[x](javascript:alert(1))")
    assert "javascript:" not in html.lower()
    assert "<a " not in html
    assert "x" in html


def test_scheme_check_defeats_case_and_whitespace_tricks():
    for href in ("JaVaScRiPt:alert(1)", "java\tscript:alert(1)", " javascript:alert(1)", "data:text/html,x", "vbscript:x"):
        html = render_html_body(f"[x]({href})")
        assert "<a " not in html, href


def test_safe_links_still_render():
    html = render_html_body("[docs](https://example.com/a) and [rel](./page.md) and [mail](mailto:a@b.c)")
    assert '<a href="https://example.com/a">docs</a>' in html
    assert '<a href="./page.md">rel</a>' in html
    assert '<a href="mailto:a@b.c">mail</a>' in html
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_export.py -k link -v` → the first two FAIL (live `javascript:` href today).

- [ ] **Step 3: Implement**

In `export.py`, replace the single-line `_LINK_RE.sub(r'<a href="\2">\1</a>', escaped)` with a function sub:

```python
_SAFE_LINK_SCHEMES = ("http:", "https:", "mailto:")


def _href_is_safe(href: str) -> bool:
    compact = "".join(href.split()).lower()
    if compact.startswith(_SAFE_LINK_SCHEMES):
        return True
    head = compact.split("#", 1)[0].split("?", 1)[0]
    return ":" not in head  # relative URL: no scheme at all


def _render_link(match: "re.Match[str]") -> str:
    label, href = match.group(1), match.group(2)
    if not _href_is_safe(href):
        return f"{label} ({href})"
    return f'<a href="{href}">{label}</a>'
```

and in `_render_inline_text`: `escaped = _LINK_RE.sub(_render_link, escaped)`.

- [ ] **Step 4: Verify** — `python3 -m pytest tests/test_export.py -v` → all pass.
- [ ] **Step 5: Commit** — `git commit -m "fix(export): allowlist URL schemes in legacy Markdown links"`

### Task 0.2: CSP on the legacy HTML export

**Files:**
- Modify: `education_pipeline/export.py` (`render_markdown_to_html`, ~line 54)
- Test: `tests/test_export.py`

**Interfaces:**
- Produces: legacy export documents carry `<meta http-equiv="Content-Security-Policy" ...>` in `<head>`.

- [ ] **Step 1: Failing test**

```python
def test_legacy_export_document_carries_csp():
    html = render_markdown_to_html("# T", title="T")
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html
```

- [ ] **Step 2: Verify it fails**, then implement: inside the `<head>` block of `render_markdown_to_html`, add

```python
'<meta http-equiv="Content-Security-Policy" '
"content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:;\">\n"
```

(The legacy export has no scripts, no remote assets; `'none'` default is correct. Do NOT touch the guide export path in `guides/` — frozen surface.)

- [ ] **Step 3: Verify + commit** — `python3 -m pytest tests/test_export.py -v`; `git commit -m "feat(export): add CSP to legacy HTML export"`

### Task 0.3: CSP header on the cockpit shell

**Files:**
- Modify: `education_pipeline/daemon/server.py` (`_static_get`, ~line 180)
- Test: `tests/test_server.py` (follow its existing daemon-request helpers)

**Interfaces:**
- Produces: every `text/html` static response carries a `Content-Security-Policy` header.

- [ ] **Step 1: Failing test** — in `tests/test_server.py`, using the file's existing pattern for issuing GETs against a built server with a stub `web_dist` containing an `index.html`:

```python
def test_cockpit_html_carries_csp_header(...):  # reuse the module's server fixture pattern
    status, headers, _ = <existing request helper>("/", ...)
    assert status == 200
    csp = headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
```

Also assert JSON API responses do NOT get the header (scope it to HTML only).

- [ ] **Step 2: Verify fail, then implement** — in `_static_get`, after `send_header("Cache-Control", ...)`:

```python
if static.content_type.startswith("text/html"):
    self.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'",
    )
```

`script-src` includes `'unsafe-inline'` deliberately: the guide preview renders via a sandboxed `srcdoc` iframe (`GuidePreviewFrame.tsx`, `sandbox="allow-scripts"`), and srcdoc documents inherit the parent CSP — a bare `'self'` would kill the inline guide runtime in previews. The header still forbids all remote script/style/img/connect origins, which is the actual F1 exfiltration concern on a loopback app.

- [ ] **Step 3: Full check** — `python3 -m pytest tests/test_server.py -v`, then `cd web && npm run e2e` (all 38 must pass — this is the "CSP didn't break preview" gate from the spec; if a preview e2e fails, the fix is adjusting the header per the srcdoc note above, never removing the sandbox).
- [ ] **Step 4: Commit** — `git commit -m "feat(daemon): serve cockpit HTML with a Content-Security-Policy"`

### Task 0.4: `.gitignore` drift (audit F2)

- [ ] **Step 1:** The working tree already has the intended change (adds `.education-pipeline/`). Clean the stray blank lines so `git diff --check` is quiet, keep the `.education-pipeline/` entry, and commit:

```bash
git add .gitignore && git diff --check && git commit -m "chore: ignore workspace .education-pipeline/ state"
```

### Wave 0 exit gate

- [ ] Run the full gate (pytest / vitest / build / e2e), record counts + gate SHA in the Wave Log, commit the plan file. Expected: pytest 404 + ~6 new, vitest 79, e2e 38.

**Handoff → Wave 1** (give this to the next manager verbatim):

> Read `docs/superpowers/plans/2026-07-11-model-plan-configuration.md` and its spec, follow the Execution & Handoff Protocol, and execute **Wave 1** (tasks 1.1–1.4). Wave 0 is done — verify via the Wave Log + `git log` shortcut instead of re-running suites. Your wave adds read-only `/v1` config endpoints; it must not add any write path.

---

# Wave 1 — Read API for providers / catalog / plan

### Task 1.1: Weak-config warning helper in `config.py`

**Files:**
- Modify: `education_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `REASONING_STAGES: frozenset[str]`; `weak_stage_warning(catalog: ModelCatalog, stage_plan: StageModelPlan) -> str | None`.

- [ ] **Step 1: Failing tests**

```python
def _catalog_with_quality(quality):
    return parse_model_catalog({"providers": [{"id": "p", "models": [{"id": "m", "label": "M", "quality": quality}]}]})


def test_weak_warning_fires_for_fast_model_on_reasoning_stage():
    catalog = _catalog_with_quality("fast")
    stage = StageModelPlan(stage="outline", recommendation="premium_reasoning", provider="p", model="m")
    assert weak_stage_warning(catalog, stage) is not None


def test_no_warning_for_strong_premium_unset_quality_or_non_reasoning_stage():
    strong = _catalog_with_quality("strong")
    stage = StageModelPlan(stage="outline", recommendation="premium_reasoning", provider="p", model="m")
    assert weak_stage_warning(strong, stage) is None
    unset = parse_model_catalog({"providers": [{"id": "p", "models": [{"id": "m", "label": "M"}]}]})
    assert weak_stage_warning(unset, stage) is None
    fast = _catalog_with_quality("fast")
    qa = StageModelPlan(stage="qa", recommendation="fast_cheap_check", provider="p", model="m")
    assert weak_stage_warning(fast, qa) is None
```

- [ ] **Step 2: Verify fail, implement** in `config.py`:

```python
REASONING_STAGES = frozenset({"spec", "outline", "repair"})
_QUALITY_RANK = {"fast": 0, "strong": 1, "premium": 2}


def weak_stage_warning(catalog: ModelCatalog, stage_plan: StageModelPlan) -> str | None:
    """A human-readable warning when a below-'strong' model is chosen for a reasoning-heavy stage."""

    if stage_plan.stage not in REASONING_STAGES or stage_plan.provider is None or stage_plan.model is None:
        return None
    provider = catalog.providers.get(stage_plan.provider)
    option = provider.models.get(stage_plan.model) if provider is not None else None
    if option is None or option.quality is None:
        return None
    if _QUALITY_RANK.get(option.quality, _QUALITY_RANK["strong"]) < _QUALITY_RANK["strong"]:
        return (
            f"stage {stage_plan.stage!r} is reasoning-heavy; "
            f"{option.label} is rated {option.quality!r} — consider a strong or premium model"
        )
    return None
```

- [ ] **Step 3: Verify + commit** — `python3 -m pytest tests/test_config.py -v`; `git commit -m "feat(config): catalog-driven weak-configuration warnings"`

### Task 1.2: `ConfigSource` — fresh config loads per request/job

**Files:**
- Modify: `education_pipeline/daemon/__init__.py`, `education_pipeline/daemon/server.py` (DaemonContext)
- Test: `tests/test_daemon_serve.py` (new tests), plus mechanical updates wherever tests construct `DaemonContext(catalog=..., plan=...)`

**Interfaces:**
- Produces:

```python
class WorkspaceConfigSource:
    def __init__(self, root: str | Path) -> None: ...
    def catalog_path(self) -> Path      # workspace file or packaged example fallback
    def plan_path(self) -> Path         # ditto
    def load(self) -> tuple[ModelCatalog, ModelPlan]   # re-reads from disk every call
    def plan_sha256(self) -> str        # sha256 of plan_path() bytes
    def write_plan(self, toml_text: str) -> None       # Wave 2 fills this in; stub raising NotImplementedError now


class StaticConfigSource:
    """Test double: fixed in-memory catalog/plan; write_plan re-parses into itself."""
    def __init__(self, catalog: ModelCatalog, plan: ModelPlan) -> None: ...
```

- `DaemonContext` **replaces** its `catalog: ModelCatalog` and `plan: ModelPlan` fields with `config: <either source>`. `enqueue_stage` calls `self.config.load()` to resolve the stage plan (fresh read per enqueue).

- [ ] **Step 1: Failing test** — in `tests/test_daemon_serve.py`:

```python
def test_workspace_config_source_rereads_after_disk_edit(tmp_path):
    cfg = tmp_path / "config"; cfg.mkdir()
    (cfg / "model-catalog.toml").write_text('[[providers]]\nid = "manual"\nlabel = "Manual"\n')
    (cfg / "model-plan.toml").write_text('provider = "manual"\n')
    source = WorkspaceConfigSource(tmp_path)
    _, plan1 = source.load()
    assert plan1.stage("draft").model is None
    (cfg / "model-plan.toml").write_text('provider = "manual"\n[stages.draft]\nmodel = "x"\n')
    # invalid model must raise (catalog has none), so use a catalog-less-model provider: models list empty → any model name passes
    _, plan2 = source.load()
    assert plan2.stage("draft").model == "x"
    assert source.plan_sha256() != ""
```

- [ ] **Step 2: Verify fail, implement.** `WorkspaceConfigSource` reuses the existing fallback logic (move the body of `load_workspace_config` into it; keep `load_workspace_config(root)` as a thin wrapper delegating to it for compatibility). `plan_sha256` = `hashlib.sha256(self.plan_path().read_bytes()).hexdigest()`.

- [ ] **Step 3: Thread it through.** In `serve()`: build `config = WorkspaceConfigSource(root)`; pass `config=config` to `DaemonContext`; the worker factory becomes:

```python
def _runner_for(job):
    catalog, plan = config.load()
    return JobRunner(store, runs, catalog, plan, timeout=timeout, force=bool(job.metadata.get("force")))

worker = Worker(store, _runner_for)
```

In `server.py`, `DaemonContext.enqueue_stage` starts with `_, plan = self.config.load()` and uses that local `plan`. Update every test that constructs `DaemonContext(...)` to pass `config=StaticConfigSource(catalog, plan)` (grep: `rg "DaemonContext\(" tests education_pipeline`).

- [ ] **Step 4: Full pytest** — `python3 -m pytest` → green (this task touches many test call sites; do not proceed with any red).
- [ ] **Step 5: Commit** — `git commit -m "refactor(daemon): load model catalog/plan freshly per request via ConfigSource"`

### Task 1.3: `GET /v1/config/providers`, `/v1/config/catalog`, `/v1/config/plan`

**Files:**
- Modify: `education_pipeline/daemon/read_api.py`, `education_pipeline/daemon/server.py` (`_api_get_routes`)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces (payload builders in `read_api.py`):

```python
def providers_payload(catalog: ModelCatalog) -> dict
# {"providers": [{"id", "label", "description", "executable", "available", "reason"}]}
# One entry per catalog provider; availability via providers.get_runner(id).is_available().
# A catalog provider with no registered runner → available False, reason "no runner registered for ...".
# An unavailable executable runner → reason "<id> CLI not found on PATH".
# "manual" is available whenever present in the catalog; ensure reason is None when available.

def catalog_payload(catalog: ModelCatalog) -> dict
# {"providers": [{"id", "label", "description", "models": [{"id", "label", "description", "quality", "default_effort"}]}]}

def plan_payload(catalog: ModelCatalog, plan: ModelPlan, plan_sha256: str) -> dict
# {"provider": ..., "plan_sha256": ..., "stages": [
#    {"stage", "provider", "model", "effort", "recommendation", "warning"}  # warning from weak_stage_warning
#  ]}  — stages in STAGE_ORDER, all eight (finalize/export show recommendation "local_only", provider as planned).
```

- [ ] **Step 1: Failing tests** in `tests/test_server.py` (use its existing authed-GET helper):

```python
def test_config_providers_reports_availability(...):
    payload = <GET /v1/config/providers>
    by_id = {p["id"]: p for p in payload["providers"]}
    assert by_id["manual"]["available"] is True and by_id["manual"]["executable"] is False

def test_config_plan_includes_sha_and_warnings(...):
    payload = <GET /v1/config/plan>
    assert len(payload["plan_sha256"]) == 64
    stages = {s["stage"]: s for s in payload["stages"]}
    assert set(stages) == set(STAGE_ORDER)
```

Add one test with a `StaticConfigSource` whose plan pins a `quality = "fast"` model on `outline` and assert `stages["outline"]["warning"]` is a non-empty string. (`StaticConfigSource.plan_sha256()` returns the sha of the emitted/held plan text — give it a deterministic value like sha of `repr(plan)` until Wave 2 makes it real.)

- [ ] **Step 2: Implement** the three builders in `read_api.py` (import `get_runner` from `education_pipeline.providers`; catch `ConfigError` from `get_runner` for the no-runner case). Wire routes in `_api_get_routes` **before** the `/v1/runs/...` matches:

```python
if self.path == "/v1/config/providers":
    catalog, _ = context.config.load()
    return self._send(200, read_api.providers_payload(catalog))
if self.path == "/v1/config/catalog":
    catalog, _ = context.config.load()
    return self._send(200, read_api.catalog_payload(catalog))
if self.path == "/v1/config/plan":
    catalog, plan = context.config.load()
    return self._send(200, read_api.plan_payload(catalog, plan, context.config.plan_sha256()))
```

- [ ] **Step 3: Verify + commit** — `python3 -m pytest tests/test_server.py -v`; `git commit -m "feat(daemon): read endpoints for provider availability, catalog, and plan"`

### Task 1.4: `GET /v1/runs/{topic}/plan` — effective plan + command preview

**Files:**
- Modify: `education_pipeline/daemon/read_api.py`, `server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces:

```python
def run_plan_payload(catalog: ModelCatalog, plan: ModelPlan, plan_sha256: str, runs: RunStore, topic_id: str) -> dict
# plan_payload(...) plus, per stage: "source": "default"  (Wave 3 adds "override")
# and "command": list[str] | None — argv the daemon would spawn, None for manual/local/unresolvable.
```

Command preview logic (private helper in `read_api.py`):

```python
def _stage_command(catalog, stage_plan, runs, topic_id):
    provider_id = stage_plan.provider
    if provider_id in (None, "manual") or stage_plan.stage not in SUPPORTED_STAGES:
        return None
    try:
        runner = get_runner(provider_id)
        if not runner.executable:
            return None
        provider = catalog.require_provider(provider_id)
        if stage_plan.model is not None:
            model = provider.models.get(stage_plan.model)
            if model is None:
                return None
        else:
            model = ModelOption(id="", label="")
        prompt_path = runs.stage_paths(topic_id, stage_plan.stage).prompt_path
        return list(runner.build_invocation(model, stage_plan, prompt_path).argv)
    except ConfigError:
        return None
```

- [ ] **Step 1: Failing test** — run-scoped plan for an initialized run returns per-stage `source: "default"` and a non-null `command` for an executable-provider stage (use the codex/claude-code provider ids the packaged example catalog defines; check `config/model-catalog.example.toml` for exact ids) and `command: null` for a manual stage. 404 for an unknown topic (reuse `read_api.require_run`).
- [ ] **Step 2: Implement + route** (`^/v1/runs/([^/?]+)/plan$` in `_api_get_routes`, placed before the bare `^/v1/runs/([^/?]+)$` match).
- [ ] **Step 3: Verify + commit** — `git commit -m "feat(daemon): per-run effective plan endpoint with command preview"`

### Wave 1 exit gate

- [ ] Full gate; record in Wave Log; commit plan file.

**Handoff → Wave 2:**

> Read `docs/superpowers/plans/2026-07-11-model-plan-configuration.md` + spec, follow the Execution & Handoff Protocol, execute **Wave 2** (tasks 2.1–2.4). Waves 0–1 are done (see Wave Log). Wave 2 makes the global plan writable (TOML emitter + SHA-guarded PUT) and builds the Settings page over the Wave-1 read endpoints.

---

# Wave 2 — Global plan writes + Settings surface

### Task 2.1: `emit_model_plan_toml` in `config.py`

**Files:**
- Modify: `education_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `emit_model_plan_toml(plan: ModelPlan) -> str` such that `parse_model_plan(tomllib.loads(emit_model_plan_toml(p)), catalog) == p` for any valid plan.

- [ ] **Step 1: Failing round-trip test**

```python
def test_emit_model_plan_toml_round_trips():
    catalog = parse_model_catalog({"providers": [
        {"id": "claude-code", "models": [{"id": "opus", "label": "Opus"}]},
        {"id": "codex", "models": [{"id": "gpt", "label": "GPT"}]},
        {"id": "manual"},
    ]})
    plan = parse_model_plan({
        "provider": "claude-code",
        "stages": {
            "draft": {"provider": "codex", "model": "gpt", "effort": "high"},
            "qa": {"provider": "manual"},
            "outline": {"model": "opus", "recommendation": "premium_reasoning"},
        },
    }, catalog=catalog)
    text = emit_model_plan_toml(plan)
    assert parse_model_plan(tomllib.loads(text), catalog=catalog) == plan


def test_emit_escapes_special_characters():
    plan = parse_model_plan({"provider": 'we"ird\\id'}, catalog=None)
    assert parse_model_plan(tomllib.loads(emit_model_plan_toml(plan))) == plan
```

- [ ] **Step 2: Implement**

```python
def emit_model_plan_toml(plan: ModelPlan) -> str:
    """Serialize a ModelPlan back to model-plan.toml. Narrow by design: this
    schema only ever holds strings, so JSON string escaping (valid TOML
    basic-string syntax) covers every value."""

    def q(value: str) -> str:
        return json.dumps(value)

    lines = [f"provider = {q(plan.provider)}", ""]
    for stage_name in STAGE_ORDER:
        stage = plan.stages[stage_name]
        body: list[str] = []
        if stage.provider is not None and stage.provider != plan.provider:
            body.append(f"provider = {q(stage.provider)}")
        if stage.model is not None:
            body.append(f"model = {q(stage.model)}")
        if stage.effort is not None:
            body.append(f"effort = {q(stage.effort)}")
        if stage.recommendation != DEFAULT_STAGE_RECOMMENDATIONS[stage_name]:
            body.append(f"recommendation = {q(stage.recommendation)}")
        if body:
            lines.append(f"[stages.{stage_name}]")
            lines.extend(body)
            lines.append("")
    return "\n".join(lines)
```

(add `import json` to the module imports.)

- [ ] **Step 3: Verify + commit** — `git commit -m "feat(config): TOML emitter for model plans"`

### Task 2.2: `WorkspaceConfigSource.write_plan` + `PUT /v1/config/plan`

**Files:**
- Modify: `education_pipeline/daemon/__init__.py` (write_plan), `write_api.py`, `server.py` (`_api_put_routes`)
- Test: `tests/test_daemon_serve.py`, `tests/test_write_api.py`, `tests/test_server.py`

**Interfaces:**
- Produces:

```python
# daemon/__init__.py — replaces the NotImplementedError stub:
def write_plan(self, toml_text: str) -> None:
    # ALWAYS writes <root>/config/model-plan.toml (creating config/ if needed),
    # even when reads currently fall back to the packaged example.
    # Atomic: tempfile in the same dir + os.replace (copy JobStore.save's pattern).

# write_api.py:
def update_global_plan(config, body: dict) -> dict
    # body: {"base_sha256": str, "provider": str, "stages": {stage: {"provider"?, "model"?, "effort"?}}}
    # 1. base_sha256 != config.plan_sha256() → ConflictError("stale_content", "the model plan changed on disk; reload settings")
    # 2. catalog, _ = config.load(); plan = parse_model_plan({"provider": ..., "stages": ...}, catalog=catalog)  # ConfigError → 400
    # 3. config.write_plan(emit_model_plan_toml(plan))
    # 4. return read_api.plan_payload(catalog, plan, config.plan_sha256())
```

- Route: `PUT /v1/config/plan` in `_api_put_routes` → `write_api.update_global_plan(context.config, self._read_body())`.
- `StaticConfigSource.write_plan` re-parses the text and swaps its held plan; its `plan_sha256()` becomes `hashlib.sha256(held_text.encode()).hexdigest()` (initialize held_text via `emit_model_plan_toml` at construction so SHA guards are testable without disk).

- [ ] **Step 1: Failing tests** — (a) write_plan creates `config/model-plan.toml` atomically and a subsequent `load()` reflects it even when the workspace previously used the packaged fallback; (b) PUT with correct SHA updates the plan and the response carries the new sha; (c) PUT with a stale SHA → 409 `stale_content`; (d) PUT referencing an unknown model → 400 and the file is untouched.
- [ ] **Step 2: Implement, verify, commit** — `git commit -m "feat(daemon): SHA-guarded global model-plan writes"`

### Task 2.3: API client + types for config endpoints

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/client.ts`
- Test: `web/src/api/client.test.ts`

**Interfaces:**
- Produces (types.ts):

```typescript
export interface ProviderAvailability { id: string; label: string; description: string; executable: boolean; available: boolean; reason: string | null; }
export interface CatalogModel { id: string; label: string; description: string; quality: string | null; default_effort: string | null; }
export interface CatalogProvider { id: string; label: string; description: string; models: CatalogModel[]; }
export interface PlanStage { stage: string; provider: string | null; model: string | null; effort: string | null; recommendation: string; warning: string | null; source?: "default" | "override"; command?: string[] | null; }
export interface PlanPayload { provider: string; plan_sha256: string; stages: PlanStage[]; }
export interface StageOverride { provider?: string; model?: string; effort?: string; }
```

- Produces (client.ts, following the file's existing `api`/`apiPut` helpers):

```typescript
export const getConfigProviders = () => api<{ providers: ProviderAvailability[] }>("/v1/config/providers");
export const getConfigCatalog = () => api<{ providers: CatalogProvider[] }>("/v1/config/catalog");
export const getConfigPlan = () => api<PlanPayload>("/v1/config/plan");
export const putConfigPlan = (baseSha256: string, provider: string, stages: Record<string, StageOverride>) =>
  apiPut<PlanPayload>("/v1/config/plan", { base_sha256: baseSha256, provider, stages });
export const getRunPlan = (topicId: string) => api<PlanPayload>(`/v1/runs/${topicId}/plan`);
```

- [ ] **Step 1:** Failing client tests (mock fetch per `client.test.ts`'s existing pattern: assert URL, method, and body shape for `putConfigPlan`). **Step 2:** implement. **Step 3:** `cd web && npm test -- --run` green; commit `feat(web): API client for config endpoints`.

### Task 2.4: Settings page

**Files:**
- Create: `web/src/components/PlanStageRow.tsx`, `web/src/pages/SettingsPage.tsx`
- Modify: `web/src/App.tsx` (route + nav link)
- Test: `web/src/pages/SettingsPage.test.tsx`, `web/src/components/PlanStageRow.test.tsx`

**Interfaces:**
- Produces: `PlanStageRow` — the single shared stage editor used by Settings (Wave 2), the run panel (Wave 3), and the wizard (Wave 4):

```typescript
export interface PlanStageRowProps {
  stage: PlanStage;
  catalog: CatalogProvider[];
  providers: ProviderAvailability[];
  onChange(stage: string, override: StageOverride | null): void; // null = "Use recommended"
}
```

Behavior: provider `<select>` (options = catalog providers + always `manual`; unavailable providers stay listed but render `(unavailable)` in the label with `title={reason}`); model `<select>` filtered to the chosen provider's models, each labeled `label — quality` when quality is set; effort `<select>` with `default/low/medium/high` where default means "unset"; a per-row "Use recommended" button calling `onChange(stage.stage, null)`; `stage.warning` rendered in a `role="alert"` element when present. Local-only stages (`finalize`, `export`) render as static text, no selectors.

- `SettingsPage`: loads providers+catalog+plan on mount; renders availability list (id, label, available ✓/✗ + reason) and one `PlanStageRow` per stage; tracks dirty overrides in state; Save → `putConfigPlan(plan.plan_sha256, provider, dirtyStages)`; on 409 `stale_content` shows "Plan changed on disk — reload" with a reload button (match `ResponseEditor.tsx`'s existing stale-content UX); "Use recommended (all stages)" button clears every stage override in the payload.

- [ ] **Step 1: Failing component tests** (vitest + testing-library, mock the client module like `RunBoardPage.test.tsx` does): (a) renders a row per model-powered stage and static rows for finalize/export; (b) an unavailable provider option shows its reason; (c) weak warning text appears under a stage whose payload carries `warning`; (d) Save calls `putConfigPlan` with only the edited stages; (e) a 409 from save surfaces the reload affordance.
- [ ] **Step 2: Implement.** Route in `App.tsx`: `<Route path="/settings" element={<SettingsPage />} />` plus a nav `<Link to="/settings">Settings</Link>` alongside the existing header links.
- [ ] **Step 3:** `npm test -- --run` and `npm run build` green. Commit `feat(web): Settings page for global model-plan defaults`.

### Wave 2 exit gate

- [ ] Full gate; Wave Log; commit plan file. Manual smoke (optional but encouraged): `npm run dev` against a live daemon, edit a default, verify `config/model-plan.toml` changed on disk, hand-edit it back, reload Settings, see the hand edit.

**Handoff → Wave 3:**

> Read `docs/superpowers/plans/2026-07-11-model-plan-configuration.md` + spec, follow the Execution & Handoff Protocol, execute **Wave 3** (tasks 3.1–3.5): per-run overrides, execution-time resolution, provenance, and the run plan editor UI. Waves 0–2 done per Wave Log. Reuse `PlanStageRow` from Wave 2 — do not build a second stage editor.

---

# Wave 3 — Per-run overrides, resolution at execution, provenance

### Task 3.1: Override storage + overlay

**Files:**
- Modify: `education_pipeline/runs.py` (override file I/O), `education_pipeline/config.py` (overlay)
- Test: `tests/test_runs.py`, `tests/test_config.py`

**Interfaces:**
- Produces (runs.py):

```python
def plan_overrides_path(self, topic_id: str) -> Path      # run_dir/model-plan-overrides.json
def read_plan_overrides(self, topic_id: str) -> dict      # {} when absent; {"stages": {stage: {"provider"?, "model"?, "effort"?}}}
def write_plan_overrides(self, topic_id: str, overrides: dict) -> None  # atomic; writes {} as an empty file-delete? NO — write the JSON as-is; empty dict just means no overrides
```

- Produces (config.py):

```python
def apply_overrides(plan: ModelPlan, overrides: Mapping[str, Any], catalog: ModelCatalog | None = None) -> ModelPlan:
    """Overlay sparse per-run overrides onto a plan. Implementation: rebuild the
    raw mapping (provider + per-stage dicts from `plan`), deep-merge
    overrides["stages"], and re-run parse_model_plan(..., catalog=catalog) so
    every existing validation rule applies to the merged result."""
```

- [ ] **Step 1: Failing tests** — overlay changes only the overridden stage; unknown stage/model in overrides raises `ConfigError`; `read_plan_overrides` returns `{}` for a fresh run and survives a daemon-restart round-trip (write → new RunStore → read).
- [ ] **Step 2: Implement, verify, commit** — `git commit -m "feat(runs): sparse per-run model-plan overrides with validated overlay"`

### Task 3.2: Resolve fresh at enqueue + execution

**Files:**
- Modify: `education_pipeline/daemon/server.py` (`enqueue_stage`), `education_pipeline/daemon/__init__.py` (runner factory)
- Test: `tests/test_daemon_serve.py`

**Interfaces:**
- Consumes: `apply_overrides`, `read_plan_overrides` from Task 3.1.
- Produces: `enqueue_stage` and the worker's `_runner_for(job)` both compute `plan = apply_overrides(loaded_plan, runs.read_plan_overrides(topic_id), catalog)` before use. Job records therefore carry the *effective* provider/model/effort at creation, and the runner re-resolves at execution (covers queued-then-edited windows).

- [ ] **Step 1: Failing test** — write overrides pinning `draft` to a different provider, call `enqueue_stage`, assert the created Job's provider/model/effort match the override, not the global plan.
- [ ] **Step 2: Implement, verify, commit** — `git commit -m "feat(daemon): resolve effective plan (global + run overrides) at enqueue and execution"`

### Task 3.3: Stage provenance

**Files:**
- Modify: `education_pipeline/runs.py` (`record_stage_provenance`), `education_pipeline/daemon/jobs.py` (success path), `education_pipeline/daemon/write_api.py` (`ingest_response`), `education_pipeline/daemon/read_api.py` (`run_status_payload`)
- Test: `tests/test_runs.py`, `tests/test_job_runner.py`, `tests/test_write_api.py`

**Interfaces:**
- Produces (runs.py):

```python
def record_stage_provenance(self, topic_id: str, stage: str, *, provider: str,
                            model: str | None, effort: str | None,
                            source: str, job_id: str | None = None) -> None:
    """Append {stage, provider, model, effort, source, job_id, recorded_at}
    to manifest["stage_provenance"] (created as [] when missing). Append-only;
    re-running a stage appends a new entry. Uses the module's existing
    manifest read/write helpers; legacy manifests without the key stay valid."""
```

- Call sites: `JobRunner.execute` success path (right beside the existing `append_manifest_event` call) with `source` = `"override"` if the job's stage was overridden else `"default"` — thread that through job.metadata: set `job.metadata["plan_source"]` in `enqueue_stage` (Task 3.2 knows which stages were overridden); `write_api.ingest_response` records `provider="manual", model=None, effort=None, source="manual"` after a successful ingest.
- `read_api.run_status_payload` gains `"stage_provenance": manifest.get("stage_provenance", [])`.

- [ ] **Step 1: Failing tests** — (a) `record_stage_provenance` appends and preserves prior entries; (b) a successful `JobRunner.execute` (reuse `tests/fake_provider.py` fixtures already used by `test_job_runner.py`) leaves a provenance entry with the job's id; (c) POST response ingest records a `manual` entry; (d) run status payload surfaces the list and omits nothing on legacy manifests.
- [ ] **Step 2: Implement, verify, commit** — `git commit -m "feat(runs): record effective provider/model/effort as stage provenance"`

### Task 3.4: `PUT /v1/runs/{topic}/plan` + `source` in the run-plan payload

**Files:**
- Modify: `education_pipeline/daemon/write_api.py`, `read_api.py` (Task 1.4's `run_plan_payload` now overlays overrides and sets `source`), `server.py`
- Test: `tests/test_write_api.py`, `tests/test_server.py`

**Interfaces:**
- Produces:

```python
def update_run_plan(runs: RunStore, config, topic_id: str, body: dict) -> dict
    # body: {"overrides": {stage: {"provider"?, "model"?, "effort"?} | None}}
    # None/null clears that stage's override. Merge into the stored overrides dict,
    # validate the merged result via apply_overrides(plan, merged, catalog) BEFORE writing,
    # write via runs.write_plan_overrides, return the refreshed run_plan_payload.
```

- Route: `PUT ^/v1/runs/([^/?]+)/plan$` in `_api_put_routes`.
- `run_plan_payload` change: load overrides, `effective = apply_overrides(plan, overrides, catalog)`, per-stage `source = "override"` when the stage appears in overrides else `"default"`; warnings and command computed from the *effective* stage plan.

- [ ] **Step 1: Failing tests** — set an override → GET shows `source: "override"` + changed command; clear with `null` → back to `default`; invalid model in the body → 400 and stored overrides unchanged.
- [ ] **Step 2: Implement, verify, commit** — `git commit -m "feat(daemon): per-run plan override endpoint"`

### Task 3.5: Run plan editor + pre-run preview + provenance display

**Files:**
- Create: `web/src/components/RunPlanPanel.tsx`
- Modify: `web/src/pages/RunBoardPage.tsx`, `web/src/api/client.ts` (`putRunPlan`), `web/src/api/types.ts` (`StageProvenance`)
- Test: `web/src/components/RunPlanPanel.test.tsx`, extend `web/src/pages/RunBoardPage.test.tsx`

**Interfaces:**
- Produces:

```typescript
// client.ts
export const putRunPlan = (topicId: string, overrides: Record<string, StageOverride | null>) =>
  apiPut<PlanPayload>(`/v1/runs/${topicId}/plan`, { overrides });
// types.ts
export interface StageProvenance { stage: string; provider: string; model: string | null; effort: string | null; source: string; job_id: string | null; recorded_at: string; }
```

- `RunPlanPanel` (collapsible section on `RunBoardPage`, near the existing JobsPanel): fetches `getRunPlan` + `getConfigCatalog` + `getConfigProviders`; renders `PlanStageRow` per model-powered stage with `source === "override"` rows visually tagged ("overridden"); edits call `putRunPlan` immediately per row change (no batch-save — run overrides are low-stakes and per-stage); shows the **next stage's** effective line prominently: `Next: draft — codex / gpt-5.4 / high` plus the `command` argv rendered in a `<code>` block when non-null ("runs locally as: …"), and "manual — you run the prompt yourself" when provider is manual.
- Provenance display: `RunBoardPage` reads `stage_provenance` from the run status payload it already fetches and renders, on each completed stage's card/row, the latest entry for that stage: `ran on {provider}{model ? ` / ${model}` : ""}{effort ? ` / ${effort}` : ""} ({source})`.

- [ ] **Step 1: Failing tests** — (a) panel renders rows from `getRunPlan` and tags overridden rows; (b) changing a row's model fires `putRunPlan` with `{stage: {…}}`; (c) "Use recommended" fires `putRunPlan` with `{stage: null}`; (d) next-stage command preview renders the argv; (e) RunBoardPage shows a provenance line for a stage present in `stage_provenance`.
- [ ] **Step 2: Implement.** **Step 3:** `npm test -- --run` + `npm run build` green; commit `feat(web): per-run plan editor with command preview and provenance display`.

### Wave 3 exit gate

- [ ] Full gate; Wave Log; commit plan file.

**Handoff → Wave 4:**

> Read `docs/superpowers/plans/2026-07-11-model-plan-configuration.md` + spec, follow the Execution & Handoff Protocol, execute **Wave 4** (tasks 4.1–4.2): structured topic creation and the New-run wizard replacing the empty-board TOML dead end. Waves 0–3 done per Wave Log. The wizard's plan-review step embeds `RunPlanPanel`/`PlanStageRow` from Wave 3 — build no new editor.

---

# Wave 4 — New-run entry point

### Task 4.1: Structured topic creation

**Files:**
- Modify: `education_pipeline/topics.py` (`emit_topic_toml`), `education_pipeline/daemon/write_api.py` (`create_topic`), `education_pipeline/daemon/server.py` (branch the existing `POST /v1/topics` route)
- Test: `tests/test_topics.py`, `tests/test_write_api.py`, `tests/test_server.py`

**Interfaces:**
- Produces (topics.py):

```python
def emit_topic_toml(topic: Topic) -> str:
    """Serialize a Topic to TOML. String fields via json.dumps (valid TOML
    basic strings); tuple fields as TOML arrays of quoted strings; omit
    None/empty fields; always emit id, title, schema_version."""
```

- Produces (write_api.py):

```python
def create_topic(topics: TopicStore, body: dict, *, overwrite: bool = False) -> dict
    # body: {"id": str, "title": str, "brief"?: str, "audience"?: str, "goals"?: [str], ...}
    # Validates id via the existing artifact-id rules by round-tripping through
    # save_topic_toml(id, emit_topic_toml(Topic(...)), overwrite=...). Returns {"id", "title"}.
```

- Route change in `_api_post_routes` for `POST /v1/topics`: if `"toml" in body` → existing `import_topic`; else → `create_topic`. Both keep the `already_exists` conflict behavior.

- [ ] **Step 1: Failing tests** — emit/parse round-trip for a Topic with goals + special characters; POST without `toml` creates the topic file and a follow-up GET `/v1/topics/{id}` returns it; duplicate id without overwrite → 409; missing `title` → 400.
- [ ] **Step 2: Implement, verify, commit** — `git commit -m "feat(daemon): create topics from structured fields"`

### Task 4.2: New-run wizard + empty-state replacement

**Files:**
- Create: `web/src/pages/NewRunPage.tsx`
- Modify: `web/src/App.tsx` (route `/new`), `web/src/pages/TopicListPage.tsx` (empty state → prominent "New run" link; keep an "Import TOML" secondary affordance using the existing `ImportForm`), `web/src/api/client.ts` (`createTopic`)
- Test: `web/src/pages/NewRunPage.test.tsx`, update `TopicListPage.test.tsx`
- E2E: `web/e2e/new-run.spec.ts` (create)

**Interfaces:**
- Produces:

```typescript
// client.ts
export const createTopic = (fields: { id: string; title: string; brief?: string; audience?: string; goals?: string[] }, overwrite = false) =>
  apiPost<{ id: string; title: string }>("/v1/topics", { ...fields, overwrite });
```

- `NewRunPage` — three sequential sections on one page (not a multi-route wizard; keep it minimal per the spec's non-goals):
  1. **Topic**: radio "Describe it" (fields: id, title, brief, audience, goals as one-per-line textarea) vs "Paste TOML" (reuses `ImportForm`'s import call). Submit creates the topic.
  2. **Profile**: `<select>` from `getProfiles()` + attach via the existing `postAttachProfile`-equivalent client call (see `AttachProfileControl.tsx` for the call in use); skippable.
  3. **Model plan review**: after topic creation + advance-to-run-init (drive the same call `RunBoardPage`'s primary action uses to initialize a run — read `PrimaryAction.tsx` for it), embed `RunPlanPanel` for the new topic, then a "Go to run board" link to `/topics/{id}`.
- `TopicListPage` empty state: replace the bare import form with "Create your first course →" linking `/new`, import form demoted below it.

- [ ] **Step 1: Failing vitest tests** — form submit calls `createTopic` with parsed fields; TOML mode calls the import client; empty TopicListPage shows the `/new` link.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: E2E** — `web/e2e/new-run.spec.ts` (copy the daemon-fixture bootstrapping from `smoke.spec.ts`): from an empty workspace, click through New run → describe a topic → skip profile → see the plan review with per-stage rows → land on the run board. Include an `@axe-core` accessibility pass on `/new` matching the pattern in the existing specs.
- [ ] **Step 4:** Full web gate (`npm test -- --run`, `npm run build`, `npm run e2e`); commit `feat(web): new-run wizard replacing the paste-TOML empty state`.

### Wave 4 exit gate

- [ ] Full gate; Wave Log; commit plan file.

**Handoff → Wave 5:**

> Read `docs/superpowers/plans/2026-07-11-model-plan-configuration.md` + spec, follow the Execution & Handoff Protocol, execute **Wave 5** (tasks 5.1–5.3): acceptance e2e, regression coverage, docs/PRD closeout. Waves 0–4 done per Wave Log. Wave 5 adds coverage and docs only — production code changes are allowed solely to fix defects the new tests expose.

---

# Wave 5 — Acceptance + closeout

### Task 5.1: Mixed-provider acceptance e2e

**Files:**
- Create: `web/e2e/model-plan.spec.ts`
- Possibly modify: the e2e daemon fixture (see how `full-run.spec.ts` boots its workspace) to (a) write a workspace `config/model-catalog.toml` defining `claude-code`, `codex`, and `manual`, and (b) prepend a stub-executables dir to the daemon process `PATH` containing fake `claude` and `codex` scripts modeled on `tests/fake_provider.py` (each reads stdin, emits a valid stage response on stdout, exits 0).

**Interfaces:**
- Consumes: everything shipped in Waves 1–4.

- [ ] **Step 1:** Write the spec covering, in one flow and **without ever editing TOML in the UI-driven path**:
  1. Settings shows both stub providers as available.
  2. Set a weak (quality `fast`) model on `outline` in the run plan editor → the warning renders.
  3. Configure: recommended defaults + one per-stage override (draft → the second provider) + `qa` set to manual.
  4. Drive the run: provider stages via the run button (stub CLIs respond), manual stage via the existing response paste flow.
  5. Assert each completed stage shows the expected provenance line, including `(override)` on draft and `manual` on qa.
- [ ] **Step 2:** Make it pass; commit `test(e2e): mixed-provider run configured entirely in the cockpit`.

### Task 5.2: TOML hand-edit regression tests

**Files:**
- Test: `tests/test_server.py`

- [ ] **Step 1:** Two pytest cases against a real `WorkspaceConfigSource` workspace: (a) hand-write `config/model-plan.toml`, GET `/v1/config/plan` reflects it; (b) PUT via the API, then `tomllib.loads` the file directly and assert the edit landed and the file re-parses under `load_model_plan` with the catalog — i.e., UI edits produce a file an advanced user can keep editing.
- [ ] **Step 2:** Commit `test(daemon): TOML round-trip regression for plan edits`.

### Task 5.3: Docs, PRD status, closeout

- [ ] Update `docs/product-requirements.md` §10: mark "P0 — Finish model-plan configuration" complete with a one-line pointer to this plan.
- [ ] Update `README`/cockpit docs where the paste-TOML flow was documented, describing Settings, the run plan editor, and New run. Keep everything domain-neutral.
- [ ] Verify the frozen-surface guard: `git log --oneline --stat -- education_pipeline/guide_runtime education_pipeline/guides` since the Wave 0 gate commit shows no changes; canonical fixture SHA unchanged.
- [ ] Run the final full gate; record final counts in the Wave Log; commit `docs: close model-plan-configuration milestone`.
- [ ] Write the post-milestone audit + next-milestone proposal per the pattern of `docs/superpowers/specs/2026-07-11-interactive-guide-v1-post-milestone-audit.md` (separate doc, separate commit).

---

## Self-review notes (kept for executors)

- `StaticConfigSource` must exist from Task 1.2 with a working `plan_sha256()`; Task 2.2 upgrades it to hold emitted text. If Task 1.2's interim SHA choice fights a test in 2.2, fix it in 2.2 — the interface (`plan_sha256() -> 64-hex-str`) is the contract, not the interim value.
- `enqueue_stage` sets `job.metadata["plan_source"]` (Task 3.2) and `JobRunner` reads it (Task 3.3). If you land 3.3 before 3.2 you will have no source value — the tasks are ordered; keep them ordered.
- The packaged example catalog (`config/model-catalog.example.toml`) defines the provider/model ids several tests lean on — read it before writing test fixtures.
