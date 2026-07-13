# Autonomous Wave Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan wave-by-wave. Steps use checkbox (`- [ ]`) syntax for tracking. Each wave runs in a **fresh session** with a **fresh manager**; the human clears context between waves and pastes the kickoff prompt printed by the previous wave's manager.

**Goal:** A deterministic local conductor (`tools/wave_runner.py`) that executes an entire wave plan unattended — fresh headless `claude` session per wave with the prescribed model/effort, three-layer usage-limit handling, liveness watchdog, and halt-plus-notify failure semantics.

**Architecture:** A stdlib-only `tools/waverunner/` package with one module per responsibility (plan parsing, JSON contract, session process management, recovery, pre-flight, notifications, status file, main loop) behind a thin `tools/wave_runner.py` CLI. Control flow rides on a final-message JSON contract emitted by each wave manager; the plan doc + Wave Log remain the human/recovery artifact. All tests run against a fake `claude` executable — no real tokens.

**Tech Stack:** Python 3.11+ stdlib only (`subprocess`, `threading`, `queue`, `json`, `urllib.request`, `dataclasses`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-13-autonomous-wave-runner-design.md`

## Global Constraints

- **Stdlib only** — the runner is dev tooling but follows the repo rule: no dependencies beyond the standard library; `pytest` is the sole dev dependency.
- Strict TDD: the failing test is written and observed to fail before implementation, in every task.
- **No real `claude` invocations in tests.** Every subprocess test uses the fake-claude harness (Task 1.1) selected via the `claude_bin` parameter. Zero tokens spent by the suite.
- All new file writes are atomic (temp file + `os.replace`).
- The runner **never re-runs test suites** — gates are the wave manager's job (trust-but-verify checks git/doc state only).
- Notifications are best-effort: a notify failure must never crash or halt the runner.
- Commit after every green test cycle; messages follow `type(scope): summary`.
- **Style (this code will be open-sourced — no slop):** self-documenting names; comments only for constraints the code cannot express (a contract, a deliberate trade-off) — never narration. No function or method takes more than three parameters (test-injection keywords like `_sleep`/`_post` excepted); past three, introduce a frozen dataclass parameter object or split the function. Small single-purpose functions over flags and nesting.
- **Wave gate for this plan:** full `python3 -m pytest` plus `python3 tools/wave_runner.py --help` smoke (this milestone never touches `web/`). The final wave additionally runs the four-suite gate once as milestone assurance.

---

## Wave Protocol (manager instructions — read first, every wave)

This plan executes as **four waves (0–3)**. Each wave is one independent session driven by a manager agent using `superpowers:subagent-driven-development` (fresh implementer subagent per task, spec review + code review per task).

### Trust the Wave Log — do not retest prior waves

- A wave **closes** by running this plan's gate (`python3 -m pytest`; `python3 tools/wave_runner.py --help` once it exists) and recording the results in the Wave Log below. The final wave also runs the four-suite gate (`python3 -m pytest`, `cd web && npm run test`, `npm run e2e`, `npm run build`) once.
- A wave **opens** by reading this plan and the Wave Log **and nothing else**. The recorded gate of the previous wave is canonical truth. **Do NOT re-run any test suite, re-verify prior waves' work, or re-read prior waves' diffs at session start.** Start dispatching your first task immediately. (Individual tasks still run their own narrow test files during TDD.)

### Wave-close checklist (the manager does this personally, in order)

1. Run the gate once; green (fix or dispatch fixes until green).
2. **Update this plan document itself:** tick every completed checkbox, fill in this wave's Wave Log row, and correct any later-wave instruction this wave invalidated. The Wave Log entry is the *only* handoff artifact.
3. Commit the plan-document update.
4. **Print to the terminal, for the human:** the next wave's manager model + effort recommendation (one-sentence rationale), and the verbatim kickoff prompt (template below).
5. Stop. Do not begin the next wave in this session.

### Kickoff prompt template

```
Read docs/superpowers/plans/2026-07-13-autonomous-wave-runner.md and execute Wave N
using superpowers:subagent-driven-development. The Wave Log records all prior waves'
gates — treat it as canonical truth and do NOT re-run or re-verify prior waves' tests
before starting. Dispatch Wave N's tasks per the plan, then run the wave-close checklist
in the Wave Protocol section (gate, update the plan doc, commit, print the next wave's
manager recommendation and kickoff prompt).
```

### Wave Log

| Wave | Status | Commits | pytest | smoke | Notes for the next wave |
| --- | --- | --- | --- | --- | --- |
| 0 — Core parsing + contract | not started | | | n/a (CLI lands in Wave 2) | |
| 1 — Process layer | not started | | | n/a | |
| 2 — Recovery, headroom, main loop | not started | | | | |
| 3 — Acceptance + closeout | not started | | | | four-suite gate this wave |

Baseline at plan time: pytest 592, vitest 127, e2e 41, build clean (commit `f4e4f39`).

**Wave 0 manager recommendation (initial):** Opus, medium — pure-function parsing and dataclasses with crisp tests; no cross-module design risk yet.

---

## File Structure

```
tools/
  wave_runner.py            # thin CLI entry (argparse, sys.path bootstrap, main())
  headroom.py               # standalone: prints usage-window headroom JSON (managers call it)
  waverunner/
    __init__.py
    plandoc.py              # parse plan markdown: waves, ticks, Wave Log, manager lines
    contract.py             # final-message JSON contract; outcome classification; limit/reset parsing
    kickoff.py              # synthesize kickoff prompts (fresh / continue / resume)
    status.py               # wave-runner-status.json load/save (atomic)
    preflight.py            # pre-run checks
    session.py              # subprocess launch, stream-json consumption, watchdog, log capture
    recovery.py             # fresh-vs-resume decision, reset wait
    notify.py               # macOS notification + ntfy push (best-effort)
    runner.py               # main loop state machine, trust-but-verify, multi-plan
tools/run_waves.sh          # caffeinate wrapper
tests/
  test_waverunner_plandoc.py
  test_waverunner_contract.py
  test_waverunner_kickoff_status.py
  test_waverunner_session.py      # uses fake claude
  test_waverunner_preflight.py
  test_waverunner_notify.py
  test_waverunner_recovery.py
  test_waverunner_headroom.py
  test_waverunner_runner.py       # main-loop unit tests, fake claude
  test_waverunner_e2e.py          # Wave 3: full scenario matrix through the CLI
  fake_claude/fake_claude.py      # the fake executable (Task 1.1)
```

Tests import the package via a small path shim at the top of each test file (`tools/` is not an installed package):

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
```

---

## Wave 0 — Core parsing + contract (no subprocesses)

### Task 0.1: Plan-document parsing (`plandoc.py`)

**Files:**
- Create: `tools/waverunner/__init__.py` (empty), `tools/waverunner/plandoc.py`
- Test: `tests/test_waverunner_plandoc.py`

**Interfaces:**
- Consumes: nothing (pure functions over markdown text).
- Produces:
  - `@dataclass(frozen=True) WaveInfo(number: int, closed: bool, tasks_total: int, tasks_done: int)`
  - `parse_waves(text: str) -> list[WaveInfo]` — waves are `## Wave N` sections; a wave is `closed` iff its Wave Log row's Status cell contains `complete`; task ticks are `- [x]`/`- [ ]` checkboxes inside the wave's section.
  - `first_open_wave(waves: list[WaveInfo]) -> WaveInfo | None`
  - `manager_line(text: str, wave: int) -> tuple[str, str] | None` — parses the structured recommendation line `**Wave N manager:** <model>, <effort>` (the playbook amendment in Task 0.4 makes this line mandatory); returns `(model, effort)` lowercased, `None` if absent.
  - `PlanDocError(ValueError)` — raised on a plan with no `## Wave` sections or no Wave Log table.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_waverunner_plandoc.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest
from waverunner import plandoc

PLAN = """# X Plan
### Wave Log
| Wave | Status | Commits |
| --- | --- | --- |
| 0 — Core | **complete** | `a..b` |
| 1 — Next | not started | |

**Wave 0 manager:** Opus, medium
**Wave 1 manager:** Fable, high

## Wave 0 — Core
- [x] **Step 1: do a thing**
- [x] **Step 2: do another**

## Wave 1 — Next
- [x] **Step 1: started**
- [ ] **Step 2: unfinished**
"""

def test_parse_waves_counts_and_status():
    waves = plandoc.parse_waves(PLAN)
    assert [w.number for w in waves] == [0, 1]
    assert waves[0].closed and not waves[1].closed
    assert (waves[1].tasks_total, waves[1].tasks_done) == (2, 1)

def test_first_open_wave():
    waves = plandoc.parse_waves(PLAN)
    assert plandoc.first_open_wave(waves).number == 1
    closed_doc = PLAN.replace("| 1 — Next | not started |", "| 1 — Next | **complete** |")
    assert plandoc.first_open_wave(plandoc.parse_waves(closed_doc)) is None

def test_manager_line():
    assert plandoc.manager_line(PLAN, 1) == ("fable", "high")
    assert plandoc.manager_line(PLAN, 7) is None

def test_malformed_plan_raises():
    with pytest.raises(plandoc.PlanDocError):
        plandoc.parse_waves("# no waves here\n")

def test_other_numeric_tables_do_not_poison_wave_log():
    poisoned = PLAN + "\n## Appendix\n| 0 | **complete** |\n| 1 | **complete** |\n"
    waves = plandoc.parse_waves(poisoned)
    # Wave 1 must still read as open despite the appendix table.
    assert not next(w for w in waves if w.number == 1).closed
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_waverunner_plandoc.py -v` → FAIL (`ModuleNotFoundError: waverunner`).

- [ ] **Step 3: Implement**

```python
# tools/waverunner/plandoc.py
"""Parse wave-plan markdown for control decisions (read-only)."""
from __future__ import annotations
import re
from dataclasses import dataclass

class PlanDocError(ValueError):
    pass

@dataclass(frozen=True)
class WaveInfo:
    number: int
    closed: bool
    tasks_total: int
    tasks_done: int

_WAVE_HEADING = re.compile(r"^## Wave (\d+)\b", re.M)
_LOG_HEADING = re.compile(r"^#{2,4} Wave Log\s*$", re.M)
_NEXT_HEADING = re.compile(r"^#{1,4} ", re.M)
_LOG_ROW = re.compile(r"^\|\s*(\d+)[^|]*\|\s*([^|]*)\|", re.M)
_MANAGER = re.compile(r"^\*\*Wave (\d+) manager:\*\*\s*(\w+),\s*(\w+)", re.M)
_TICKED = re.compile(r"^\s*- \[x\]", re.M)
_UNTICKED = re.compile(r"^\s*- \[ \]", re.M)

def _wave_log_section(text: str) -> str:
    """Rows are parsed ONLY inside the '### Wave Log' section — other tables
    with numeric first columns (task tables) must not poison the map."""
    m = _LOG_HEADING.search(text)
    if not m:
        raise PlanDocError("no 'Wave Log' heading found")
    rest = text[m.end():]
    nxt = _NEXT_HEADING.search(rest)
    return rest[:nxt.start()] if nxt else rest

def parse_waves(text: str) -> list[WaveInfo]:
    headings = list(_WAVE_HEADING.finditer(text))
    if not headings:
        raise PlanDocError("no '## Wave N' sections found")
    closed = {int(m.group(1)): "complete" in m.group(2).lower()
              for m in _LOG_ROW.finditer(_wave_log_section(text))}
    if not closed:
        raise PlanDocError("no Wave Log table rows found")
    waves = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[start:end]
        done = len(_TICKED.findall(section))
        total = done + len(_UNTICKED.findall(section))
        n = int(m.group(1))
        waves.append(WaveInfo(n, closed.get(n, False), total, done))
    return waves

def first_open_wave(waves: list[WaveInfo]) -> WaveInfo | None:
    for w in waves:
        if not w.closed:
            return w
    return None

def manager_line(text: str, wave: int) -> tuple[str, str] | None:
    for m in _MANAGER.finditer(text):
        if int(m.group(1)) == wave:
            return (m.group(2).lower(), m.group(3).lower())
    return None
```

- [ ] **Step 4: Run to verify pass** — same command → PASS (5 tests).
- [ ] **Step 5: Commit** — `git add tools/waverunner tests/test_waverunner_plandoc.py && git commit -m "feat(waverunner): plan-document parsing (waves, ticks, manager lines)"`

### Task 0.2: Final-message contract + outcome classification (`contract.py`)

**Files:**
- Create: `tools/waverunner/contract.py`
- Test: `tests/test_waverunner_contract.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) WaveResult(wave: int, status: str, gate: dict, next_wave: int | None, next_model: str | None, next_effort: str | None, notes: str)` — `status ∈ {"closed", "blocked", "parked"}`.
  - `parse_final_message(text: str) -> WaveResult` — raises `ContractViolation(ValueError)` on non-JSON, wrong types, unknown status, or missing keys (`gate`/`notes` may be absent for `blocked`/`parked`; default `{}` / `""`). Tolerates surrounding whitespace and a ```json fence.
  - `is_limit_message(text: str) -> bool` — matches usage-limit phrasing (case-insensitive: `usage limit`, `5-hour limit`, `rate limit.*resets`).
  - `parse_reset_time(text: str, now: datetime) -> datetime | None` — extracts `resets at H[:MM] am/pm` or `resets HH:MM`; returns the next such wall-clock time strictly after `now` (local tz), else `None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_waverunner_contract.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from datetime import datetime
import pytest
from waverunner import contract

GOOD = '{"wave": 2, "status": "closed", "gate": {"pytest": 600}, "next_wave": 3, "next_model": "fable", "next_effort": "high", "notes": "ok"}'

def test_parse_final_message_good():
    r = contract.parse_final_message(GOOD)
    assert (r.wave, r.status, r.next_wave, r.next_model, r.next_effort) == (2, "closed", 3, "fable", "high")
    assert r.gate == {"pytest": 600}

def test_parse_tolerates_json_fence_and_whitespace():
    fenced = "```json\n" + GOOD + "\n```\n"
    assert contract.parse_final_message(fenced).wave == 2

def test_parked_without_gate_ok():
    r = contract.parse_final_message('{"wave": 1, "status": "parked", "next_wave": 1, "next_model": null, "next_effort": null}')
    assert r.status == "parked" and r.gate == {} and r.notes == ""

@pytest.mark.parametrize("bad", [
    "I finished the wave, all green!",          # prose, not JSON
    '{"wave": "two", "status": "closed"}',       # wrong type
    '{"wave": 2, "status": "victorious"}',       # unknown status
    '{"status": "closed"}',                      # missing wave
])
def test_contract_violations(bad):
    with pytest.raises(contract.ContractViolation):
        contract.parse_final_message(bad)

def test_is_limit_message():
    assert contract.is_limit_message("5-hour limit reached ∙ resets at 3pm")
    assert contract.is_limit_message("You have hit your usage limit.")
    assert not contract.is_limit_message("error: connection reset by peer")

def test_parse_reset_time_rolls_to_tomorrow():
    now = datetime(2026, 7, 13, 16, 0)
    t = contract.parse_reset_time("limit reached ∙ resets at 3pm", now)
    assert (t.day, t.hour) == (14, 15)          # 3pm already past → tomorrow

def test_parse_reset_time_absent():
    assert contract.parse_reset_time("usage limit reached", datetime(2026, 7, 13, 16, 0)) is None
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_waverunner_contract.py -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# tools/waverunner/contract.py
"""The wave-manager final-message JSON contract and limit-message parsing."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

class ContractViolation(ValueError):
    pass

_STATUSES = {"closed", "blocked", "parked"}
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```\s*$", re.S)
_LIMIT = re.compile(r"usage limit|5-hour limit|rate limit.*reset", re.I)
_RESET = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)

@dataclass(frozen=True)
class WaveResult:
    wave: int
    status: str
    gate: dict = field(default_factory=dict)
    next_wave: int | None = None
    next_model: str | None = None
    next_effort: str | None = None
    notes: str = ""

def parse_final_message(text: str) -> WaveResult:
    body = text.strip()
    fence = _FENCE.match(body)
    if fence:
        body = fence.group(1)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContractViolation(f"final message is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractViolation("final message JSON is not an object")
    if not isinstance(data.get("wave"), int):
        raise ContractViolation("'wave' missing or not an int")
    if data.get("status") not in _STATUSES:
        raise ContractViolation(f"'status' must be one of {sorted(_STATUSES)}")
    gate = data.get("gate") or {}
    if not isinstance(gate, dict):
        raise ContractViolation("'gate' must be an object")
    nxt = data.get("next_wave")
    if nxt is not None and not isinstance(nxt, int):
        raise ContractViolation("'next_wave' must be an int or null")
    return WaveResult(
        wave=data["wave"], status=data["status"], gate=gate, next_wave=nxt,
        next_model=data.get("next_model"), next_effort=data.get("next_effort"),
        notes=data.get("notes") or "",
    )

def is_limit_message(text: str) -> bool:
    return bool(_LIMIT.search(text))

def parse_reset_time(text: str, now: datetime) -> datetime | None:
    m = _RESET.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
```

- [ ] **Step 4: Run to verify pass** → PASS (8 tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(waverunner): final-message JSON contract + limit/reset parsing"`

### Task 0.3: Kickoff synthesis + status file (`kickoff.py`, `status.py`)

**Files:**
- Create: `tools/waverunner/kickoff.py`, `tools/waverunner/status.py`
- Test: `tests/test_waverunner_kickoff_status.py`

**Interfaces:**
- Consumes: `WaveInfo` from Task 0.1.
- Produces:
  - `kickoff.kickoff_prompt(plan_path: str, wave: WaveInfo) -> str` — the playbook template with plan path and `wave.number` substituted; when `wave.tasks_done > 0` it prepends the continue-preamble: `"This wave was interrupted. The plan doc's checkboxes are canonical: {done}/{total} tasks are already complete — do NOT redo them."` Every prompt ends with the contract clause: `"Your final message must be exactly one JSON object: {\"wave\": N, \"status\": \"closed\"|\"blocked\"|\"parked\", \"gate\": {...}, \"next_wave\": ..., \"next_model\": ..., \"next_effort\": ..., \"notes\": \"...\"} — no prose before or after it."`
  - `status.RunnerStatus` dataclass: `plan: str, wave: int, session_id: str, attempt: int, state: str, detail: str, cumulative_cost_usd: float, updated_at: str`
  - `status.save(path: Path, s: RunnerStatus) -> None` (atomic: temp + `os.replace`), `status.load(path: Path) -> RunnerStatus | None` (`None` if missing or malformed — the status file is advisory, never fatal).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_waverunner_kickoff_status.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from waverunner import kickoff
from waverunner.plandoc import WaveInfo
from waverunner.status import RunnerStatus, save, load

def test_fresh_kickoff_mentions_plan_wave_and_contract():
    p = kickoff.kickoff_prompt("docs/plans/x.md", WaveInfo(2, False, 5, 0))
    assert "docs/plans/x.md" in p and "Wave 2" in p
    assert '"status"' in p and "final message must be exactly one JSON object" in p
    assert "interrupted" not in p

def test_continue_kickoff_carries_progress():
    p = kickoff.kickoff_prompt("docs/plans/x.md", WaveInfo(2, False, 5, 3))
    assert "3/5 tasks are already complete" in p and "interrupted" in p

def test_status_roundtrip_and_malformed(tmp_path):
    f = tmp_path / "wave-runner-status.json"
    s = RunnerStatus(plan="p.md", wave=1, session_id="u", attempt=1,
                     state="running", detail="", cumulative_cost_usd=1.25,
                     updated_at="2026-07-13T09:00:00")
    save(f, s)
    assert load(f) == s
    f.write_text("{not json", encoding="utf-8")
    assert load(f) is None
    assert load(tmp_path / "missing.json") is None
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement**

```python
# tools/waverunner/kickoff.py
"""Synthesize wave kickoff prompts (the runner replaces manager-printed prompts)."""
from __future__ import annotations

from .plandoc import WaveInfo

_CONTRACT = (
    'Your final message must be exactly one JSON object: '
    '{"wave": N, "status": "closed"|"blocked"|"parked", "gate": {...}, '
    '"next_wave": ..., "next_model": ..., "next_effort": ..., "notes": "..."} '
    '— no prose before or after it.'
)

_TEMPLATE = (
    "Read {plan} and execute Wave {wave} using superpowers:subagent-driven-development. "
    "The Wave Log records all prior waves' gates — treat it as canonical truth and do NOT "
    "re-run or re-verify prior waves' tests before starting. Dispatch Wave {wave}'s tasks "
    "per the plan, then run the wave-close checklist in the Wave Protocol section "
    "(gate, update the plan doc, commit). "
)

_CONTINUE = (
    "This wave was interrupted. The plan doc's checkboxes are canonical: "
    "{done}/{total} tasks are already complete — do NOT redo them. "
)

def kickoff_prompt(plan_path: str, wave: WaveInfo) -> str:
    prompt = ""
    if wave.tasks_done > 0:
        prompt += _CONTINUE.format(done=wave.tasks_done, total=wave.tasks_total)
    prompt += _TEMPLATE.format(plan=plan_path, wave=wave.number)
    return prompt + _CONTRACT
```

```python
# tools/waverunner/status.py
"""Advisory runner state for reboot recovery and human inspection."""
from __future__ import annotations
import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

@dataclass
class RunnerStatus:
    plan: str
    wave: int
    session_id: str
    attempt: int
    state: str
    detail: str
    cumulative_cost_usd: float
    updated_at: str

def save(path: Path, s: RunnerStatus) -> None:
    data = json.dumps(dataclasses.asdict(s), indent=2)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".status-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def load(path: Path) -> RunnerStatus | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunnerStatus(**data)
    except (OSError, ValueError, TypeError):
        return None
```

- [ ] **Step 4: Run to verify pass** → PASS (3 tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(waverunner): kickoff synthesis + advisory status file"`

### Task 0.4: Playbook amendments (docs only)

**Files:**
- Modify: `docs/superpowers/wave-plan-playbook.md`

**Interfaces:**
- Produces: the authoring conventions Waves 1–3 and all *future plans* rely on. No code.

- [ ] **Step 1: Amend the playbook.** Add a new section `## Runner mode (autonomous execution)` after "Execution model", containing exactly these rules:
  1. Plans intended for autonomous execution include a structured line per wave — `**Wave N manager:** <model>, <effort>` — which `tools/wave_runner.py` parses as the launch fallback; the closing manager's final-message JSON (`next_model`/`next_effort`) overrides it.
  2. Under the runner, the manager's **final message is exactly one JSON object** (reproduce the contract from the spec §2 verbatim); the wave-close "print kickoff prompt" step applies to human-driven runs only — the runner synthesizes kickoff prompts itself.
  3. **Ticking each task's checkboxes and committing after every task is mandatory** (it is what makes interrupted-wave recovery cheap and correct).
  4. **Pre-task headroom gate:** before dispatching each task, run `python3 tools/headroom.py`; if it reports `"low"`, checkpoint the plan doc, emit `"status": "parked"`, and exit cleanly. If it reports `"unknown"`, proceed.
- [ ] **Step 2: Verify** — `python3 -m pytest` (no regressions; docs-only) and proofread the section against spec §§2, 4.
- [ ] **Step 3: Commit** — `git commit -m "docs(playbook): runner mode — JSON contract, manager lines, mandatory per-task commits, headroom gate"`

- [ ] **Wave 0 close** — run the wave-close checklist.

**Wave 1 manager:** opus, high

---

## Wave 1 — Process layer

### Task 1.1: Fake-claude harness + session launcher (`session.py`)

**Files:**
- Create: `tests/fake_claude/fake_claude.py`, `tools/waverunner/session.py`
- Test: `tests/test_waverunner_session.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `@dataclass(frozen=True) SessionSpec(prompt: str, session_id: str, model: str, effort: str, resume: str | None = None, max_budget_usd: float | None = None, claude_bin: str = "claude")`
  - `build_command(spec: SessionSpec) -> list[str]` — fresh launch uses `-p <prompt> --session-id <id>`; `spec.resume` set uses `-p <prompt> -r <resume>` (no `--session-id`). Always: `--model`, `--effort`, `--output-format stream-json --verbose`, `--permission-mode auto`; `--max-budget-usd` only when given.
  - `@dataclass SessionOutcome(kind: str, exit_code: int | None, result_text: str, is_error: bool, cost_usd: float)` — `kind ∈ {"result", "stalled", "died"}`. `result_text` is the final `result` event's `result` field (empty for stalled/died); `cost_usd` from the result event's `total_cost_usd` (0.0 if absent).
  - `run_session(cmd: list[str], log_path: Path, stall_timeout_s: float) -> SessionOutcome` — spawns the process, appends every stdout line to `log_path` as it arrives (reader thread + `queue.Queue`), and: no line for `stall_timeout_s` → `terminate()`, 10 s grace, `kill()` → `kind="stalled"`; EOF with a `{"type": "result", ...}` line seen → `kind="result"`; EOF without one → `kind="died"`.
  - The fake executable: `tests/fake_claude/fake_claude.py`, driven by the env var `FAKE_CLAUDE_SCRIPT` naming a JSON file of directives: `{"mode": "result"|"hang"|"die", "result": "...", "is_error": false, "cost": 0.5, "delay_s": 0, "hang_after_lines": 2}`. In `result` mode it prints two assistant stream lines then the result event and exits 0; `hang` prints `hang_after_lines` lines then sleeps 3600 s; `die` prints one line and exits 1 without a result event. It records its argv to `FAKE_CLAUDE_ARGV_LOG` (one JSON line per invocation) so tests can assert flags.

- [ ] **Step 1: Write the fake executable** (test infrastructure first — it *is* the test double):

```python
# tests/fake_claude/fake_claude.py
"""Fake `claude` for wave-runner tests. Behavior via FAKE_CLAUDE_SCRIPT (JSON file)."""
import json
import os
import sys
import time

def main() -> int:
    argv_log = os.environ.get("FAKE_CLAUDE_ARGV_LOG")
    if argv_log:
        with open(argv_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\n")
    spec = json.loads(open(os.environ["FAKE_CLAUDE_SCRIPT"], encoding="utf-8").read())
    # Support a queue of behaviors: consume the head, leave the tail for the next call.
    if isinstance(spec, list):
        current, rest = spec[0], spec[1:]
        with open(os.environ["FAKE_CLAUDE_SCRIPT"], "w", encoding="utf-8") as fh:
            json.dump(rest if rest else [current], fh)
    else:
        current = spec
    time.sleep(current.get("delay_s", 0))
    mode = current.get("mode", "result")
    if mode == "hang":
        for i in range(current.get("hang_after_lines", 1)):
            print(json.dumps({"type": "assistant", "line": i}), flush=True)
        time.sleep(3600)
        return 0
    print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
    print(json.dumps({"type": "assistant", "message": "working"}), flush=True)
    if mode == "die":
        return 1
    print(json.dumps({
        "type": "result",
        "result": current.get("result", ""),
        "is_error": current.get("is_error", False),
        "total_cost_usd": current.get("cost", 0.0),
    }), flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_waverunner_session.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import json
import pytest
from waverunner import session

FAKE = str(Path(__file__).parent / "fake_claude" / "fake_claude.py")

@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    script = tmp_path / "script.json"
    argv_log = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))
    return script, argv_log

def _cmd():
    spec = session.SessionSpec("do wave 1", "uuid-1", "opus", "high",
                               claude_bin=sys.executable)
    base = session.build_command(spec)
    return [base[0], FAKE] + base[1:]  # claude_bin=python → fake script rides second

def test_build_command_fresh_and_resume():
    fresh = session.build_command(session.SessionSpec("p", "sid", "fable", "max"))
    assert fresh[:3] == ["claude", "-p", "p"]
    assert "--session-id" in fresh and "-r" not in fresh
    assert ["--model", "fable"] == fresh[fresh.index("--model"):fresh.index("--model") + 2]
    assert "--permission-mode" in fresh and "stream-json" in fresh
    resumed = session.build_command(
        session.SessionSpec("p", "sid", "fable", "max", resume="old-sid"))
    assert "-r" in resumed and "--session-id" not in resumed

def test_run_session_result(fake_env, tmp_path):
    script, _ = fake_env
    script.write_text(json.dumps({"mode": "result", "result": '{"ok": 1}', "cost": 0.25}))
    out = session.run_session(_cmd(), tmp_path / "wave.log", stall_timeout_s=30)
    assert (out.kind, out.exit_code, out.is_error) == ("result", 0, False)
    assert out.result_text == '{"ok": 1}' and out.cost_usd == 0.25
    assert '"type": "result"' in (tmp_path / "wave.log").read_text()

def test_run_session_stall_kills(fake_env, tmp_path):
    script, _ = fake_env
    script.write_text(json.dumps({"mode": "hang", "hang_after_lines": 2}))
    out = session.run_session(_cmd(), tmp_path / "wave.log", stall_timeout_s=1.5)
    assert out.kind == "stalled" and out.result_text == ""

def test_run_session_death_without_result(fake_env, tmp_path):
    script, _ = fake_env
    script.write_text(json.dumps({"mode": "die"}))
    out = session.run_session(_cmd(), tmp_path / "wave.log", stall_timeout_s=30)
    assert out.kind == "died" and out.exit_code == 1
```

- [ ] **Step 3: Run to verify failure** → FAIL (`session` has no attributes).

- [ ] **Step 4: Implement**

```python
# tools/waverunner/session.py
"""Launch one wave session and supervise its stream-json output."""
from __future__ import annotations
import json
import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SessionSpec:
    prompt: str
    session_id: str
    model: str
    effort: str
    resume: str | None = None
    max_budget_usd: float | None = None
    claude_bin: str = "claude"

@dataclass
class SessionOutcome:
    kind: str                  # "result" | "stalled" | "died"
    exit_code: int | None
    result_text: str
    is_error: bool
    cost_usd: float

def build_command(spec: SessionSpec) -> list[str]:
    cmd = [spec.claude_bin, "-p", spec.prompt]
    if spec.resume:
        cmd += ["-r", spec.resume]
    else:
        cmd += ["--session-id", spec.session_id]
    cmd += ["--model", spec.model, "--effort", spec.effort,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "auto"]
    if spec.max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(spec.max_budget_usd)]
    return cmd

def _reader(pipe, q: queue.Queue) -> None:
    for line in pipe:
        q.put(line)
    q.put(None)  # EOF sentinel

def run_session(cmd: list[str], log_path: Path, stall_timeout_s: float) -> SessionOutcome:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
    result_event = None
    with open(log_path, "a", encoding="utf-8") as log:
        while True:
            try:
                line = q.get(timeout=stall_timeout_s)
            except queue.Empty:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                return SessionOutcome("stalled", proc.returncode, "", True, 0.0)
            if line is None:
                break
            log.write(line)
            log.flush()
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                result_event = event
    exit_code = proc.wait()
    if result_event is None:
        return SessionOutcome("died", exit_code, "", True, 0.0)
    return SessionOutcome(
        "result", exit_code,
        str(result_event.get("result") or ""),
        bool(result_event.get("is_error", False)),
        float(result_event.get("total_cost_usd") or 0.0),
    )
```

- [ ] **Step 5: Run to verify pass** — `python3 -m pytest tests/test_waverunner_session.py -v` → PASS (4 tests; the stall test takes ~2 s by design).
- [ ] **Step 6: Commit** — `git commit -m "feat(waverunner): session launcher with stream-json watchdog + fake-claude harness"`

### Task 1.2: Pre-flight checks (`preflight.py`)

**Files:**
- Create: `tools/waverunner/preflight.py`
- Test: `tests/test_waverunner_preflight.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) PreflightSpec(repo_root: Path, expected_branch: str, claude_bin: str = "claude", min_free_gb: float = 5.0, process_patterns: tuple[str, ...] = ())`
  - `preflight_failures(spec: PreflightSpec) -> list[str]` — empty list means go. Composed of one helper per check, each `(spec) -> str | None` (`None` = pass): `_dirty_tree` (`git status --porcelain --untracked-files=no` — **tracked** changes only; stray untracked files must not kill an unattended run), `_wrong_branch`, `_claude_unavailable` (`--version` exits 0 within 30 s), `_low_disk` (`shutil.disk_usage` ≥ `min_free_gb`), and `_live_processes` (one `pgrep -f` per pattern; failure only when pgrep exits 0). Patterns default to empty — repo-specific patterns are the *caller's* knowledge (this repo's CLI passes `("playwright", "education-pipeline.*daemon")`; OSS users pass their own), and tests pass none so a developer's running daemon/Playwright can't flake the suite.

- [ ] **Step 1: Write the failing tests** — use `tmp_path` git repos and `sys.executable` stand-ins:

```python
# tests/test_waverunner_preflight.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import subprocess
from waverunner.preflight import PreflightSpec, preflight_failures

def _git_repo(tmp_path, branch="main", dirty=False):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=root, check=True)
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=root, check=True)
    if dirty:
        (root / "a.txt").write_text("changed")
    return root

def _spec(root, **overrides):
    defaults = dict(repo_root=root, expected_branch="main",
                    claude_bin=sys.executable, min_free_gb=0.001)
    return PreflightSpec(**{**defaults, **overrides})

def test_clean_repo_passes(tmp_path):
    assert preflight_failures(_spec(_git_repo(tmp_path))) == []

def test_untracked_files_do_not_fail(tmp_path):
    root = _git_repo(tmp_path)
    (root / "scratch-notes.md").write_text("untracked")
    assert preflight_failures(_spec(root)) == []

def test_dirty_tree_and_wrong_branch_reported(tmp_path):
    root = _git_repo(tmp_path, branch="feature", dirty=True)
    fails = preflight_failures(_spec(root))
    assert any("working tree" in f for f in fails)
    assert any("branch" in f for f in fails)

def test_missing_claude_reported(tmp_path):
    fails = preflight_failures(_spec(_git_repo(tmp_path),
                                     claude_bin="/nonexistent/claude"))
    assert any("claude" in f.lower() for f in fails)
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement**

```python
# tools/waverunner/preflight.py
"""Hard-fail checks before an unattended run starts."""
from __future__ import annotations
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PreflightSpec:
    repo_root: Path
    expected_branch: str
    claude_bin: str = "claude"
    min_free_gb: float = 5.0
    process_patterns: tuple[str, ...] = ()

def preflight_failures(spec: PreflightSpec) -> list[str]:
    checks = (_dirty_tree, _wrong_branch, _claude_unavailable, _low_disk,
              _live_processes)
    return [failure for check in checks if (failure := check(spec))]

def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)

def _dirty_tree(spec: PreflightSpec) -> str | None:
    porcelain = _run(["git", "status", "--porcelain", "--untracked-files=no"],
                     cwd=spec.repo_root)
    if porcelain.returncode != 0 or porcelain.stdout.strip():
        return "working tree is not clean (or not a git repo)"
    return None

def _wrong_branch(spec: PreflightSpec) -> str | None:
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                  cwd=spec.repo_root).stdout.strip()
    if branch != spec.expected_branch:
        return f"on branch {branch!r}, expected {spec.expected_branch!r}"
    return None

def _claude_unavailable(spec: PreflightSpec) -> str | None:
    try:
        if _run([spec.claude_bin, "--version"]).returncode != 0:
            return f"{spec.claude_bin} --version failed"
    except (OSError, subprocess.TimeoutExpired):
        return f"claude binary not runnable: {spec.claude_bin}"
    return None

def _low_disk(spec: PreflightSpec) -> str | None:
    free_gb = shutil.disk_usage(spec.repo_root).free / 1e9
    if free_gb < spec.min_free_gb:
        return f"only {free_gb:.1f} GB free (need {spec.min_free_gb})"
    return None

def _live_processes(spec: PreflightSpec) -> str | None:
    for pattern in spec.process_patterns:
        try:
            if _run(["pgrep", "-f", pattern]).returncode == 0:
                return f"live process matches {pattern!r} — clean up before running"
        except (OSError, subprocess.TimeoutExpired):
            continue  # pgrep unavailable: skip, never block on it
    return None
```

- [ ] **Step 4: Run to verify pass** → PASS (4 tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(waverunner): pre-flight checks"`

### Task 1.3: Notifications (`notify.py`)

**Files:**
- Create: `tools/waverunner/notify.py`
- Test: `tests/test_waverunner_notify.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass NotifyConfig(ntfy_topic: str | None = None, osascript: bool = True)` — built by the CLI from `--ntfy-topic` / `WAVE_RUNNER_NTFY_TOPIC`.
  - `notify(title: str, message: str, config: NotifyConfig, *, _post=None, _osascript=None) -> None` — sends the macOS notification via `osascript -e 'display notification ...'` and, when a topic is set, POSTs `message` to `https://ntfy.sh/<topic>` with a `Title` header (`urllib.request`, 10 s timeout). **Never raises**; failures print to stderr. `_post`/`_osascript` are injection points for tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_waverunner_notify.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from waverunner.notify import NotifyConfig, notify

def test_notify_calls_both_channels():
    posts, scripts = [], []
    cfg = NotifyConfig(ntfy_topic="my-topic")
    notify("Wave 2 closed", "pytest 600", cfg,
           _post=lambda url, data, headers: posts.append((url, data, headers)),
           _osascript=lambda text: scripts.append(text))
    assert posts and "my-topic" in posts[0][0] and b"pytest 600" == posts[0][1]
    assert posts[0][2]["Title"] == "Wave 2 closed"
    assert scripts and "Wave 2 closed" in scripts[0]

def test_notify_never_raises():
    def boom(*a, **k):
        raise RuntimeError("network down")
    notify("t", "m", NotifyConfig(ntfy_topic="x"), _post=boom, _osascript=boom)

def test_no_topic_skips_post():
    posts = []
    notify("t", "m", NotifyConfig(ntfy_topic=None),
           _post=lambda *a: posts.append(a), _osascript=lambda t: None)
    assert posts == []
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement**

```python
# tools/waverunner/notify.py
"""Best-effort human notifications: macOS banner + ntfy push. Never raises."""
from __future__ import annotations
import subprocess
import sys
import urllib.request
from dataclasses import dataclass

@dataclass
class NotifyConfig:
    ntfy_topic: str | None = None
    osascript: bool = True

def _default_post(url: str, data: bytes, headers: dict) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10).close()

def _default_osascript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)

def notify(title: str, message: str, config: NotifyConfig, *,
           _post=None, _osascript=None) -> None:
    post = _post or _default_post
    osa = _osascript or _default_osascript
    if config.osascript:
        try:
            escaped_msg = message.replace("\\", "\\\\").replace('"', '\\"')
            escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
            osa(f'display notification "{escaped_msg}" with title "{escaped_title}"')
        except Exception as exc:  # noqa: BLE001 — best-effort by contract
            print(f"[notify] osascript failed: {exc}", file=sys.stderr)
    if config.ntfy_topic:
        try:
            post(f"https://ntfy.sh/{config.ntfy_topic}",
                 message.encode("utf-8"), {"Title": title})
        except Exception as exc:  # noqa: BLE001
            print(f"[notify] ntfy push failed: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run to verify pass** → PASS (3 tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(waverunner): best-effort notifications (osascript + ntfy)"`

- [ ] **Wave 1 close** — run the wave-close checklist.

**Wave 2 manager:** fable, high

---

## Wave 2 — Recovery, headroom, main loop

### Task 2.1: Recovery decision + reset wait (`recovery.py`)

**Files:**
- Create: `tools/waverunner/recovery.py`
- Test: `tests/test_waverunner_recovery.py`

**Interfaces:**
- Consumes: `plandoc.parse_waves` / `WaveInfo` (Task 0.1).
- Produces:
  - `@dataclass(frozen=True) WaveStart(repo_root: Path, plan_path: Path, wave: int, sha: str, ticks: int)` — everything the runner must remember about the moment a wave launched. One snapshot serves both the recovery decision here and close verification in Task 2.3.
  - `snapshot_wave_start(repo_root: Path, plan_path: Path, wave: WaveInfo) -> WaveStart` — records `git rev-parse HEAD` and `wave.tasks_done`.
  - `wave_progressed(start: WaveStart) -> bool` — True iff either (a) `git rev-list --count <start.sha>..HEAD` > 0, or (b) the wave's ticked-checkbox count in the *working-tree* plan file now exceeds `start.ticks`. Progressed ⇒ recover with a **fresh** relaunch; not progressed ⇒ `--resume` (spec §4 Layer 1).
  - `wait_for_reset(reset_at: datetime | None, *, poll_interval_s: float = 1200, max_wait_s: float = 21600, _sleep=time.sleep, _now=datetime.now) -> None` — sleeps until `reset_at` + 60 s slack when known; unknown → sleeps `poll_interval_s` once (caller retries and comes back on the next failure). Total wait bounded by `max_wait_s` (raises `RecoveryTimeout` past it — 6 h means something else is wrong).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_waverunner_recovery.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import subprocess
from datetime import datetime, timedelta
import pytest
from waverunner import recovery

PLAN_ONE_TICK = """### Wave Log
| Wave | Status |
| --- | --- |
| 1 — X | not started |

## Wave 1 — X
- [x] **Step 1**
- [ ] **Step 2**
"""

def _repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    plan = root / "plan.md"
    plan.write_text(PLAN_ONE_TICK.replace("- [x]", "- [ ]", 1))  # zero ticks committed
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=root, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                         capture_output=True, text=True).stdout.strip()
    return root, plan, sha

def _start(root, plan, sha):
    return recovery.WaveStart(repo_root=root, plan_path=plan, wave=1,
                              sha=sha, ticks=0)

def test_no_progress_means_resume(tmp_path):
    root, plan, sha = _repo(tmp_path)
    assert recovery.wave_progressed(_start(root, plan, sha)) is False

def test_new_commit_means_fresh(tmp_path):
    root, plan, sha = _repo(tmp_path)
    (root / "work.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "task 1"], cwd=root, check=True)
    assert recovery.wave_progressed(_start(root, plan, sha)) is True

def test_working_tree_tick_means_fresh(tmp_path):
    root, plan, sha = _repo(tmp_path)
    plan.write_text(PLAN_ONE_TICK)  # one tick, uncommitted
    assert recovery.wave_progressed(_start(root, plan, sha)) is True

def test_snapshot_captures_head_and_ticks(tmp_path):
    from waverunner.plandoc import WaveInfo
    root, plan, sha = _repo(tmp_path)
    start = recovery.snapshot_wave_start(root, plan, WaveInfo(1, False, 2, 0))
    assert (start.sha, start.ticks, start.wave) == (sha, 0, 1)

def test_wait_for_reset_known_time():
    slept = []
    now = datetime(2026, 7, 13, 12, 0)
    recovery.wait_for_reset(now + timedelta(minutes=30),
                            _sleep=slept.append, _now=lambda: now)
    assert slept == [30 * 60 + 60]

def test_wait_for_reset_unknown_polls_once():
    slept = []
    recovery.wait_for_reset(None, poll_interval_s=7, _sleep=slept.append)
    assert slept == [7]

def test_wait_past_max_raises():
    now = datetime(2026, 7, 13, 12, 0)
    with pytest.raises(recovery.RecoveryTimeout):
        recovery.wait_for_reset(now + timedelta(hours=12), _sleep=lambda s: None,
                                _now=lambda: now)
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement**

```python
# tools/waverunner/recovery.py
"""Pick the cheap recovery mode and wait out usage-limit resets."""
from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import plandoc
from .plandoc import WaveInfo

class RecoveryTimeout(RuntimeError):
    pass

@dataclass(frozen=True)
class WaveStart:
    repo_root: Path
    plan_path: Path
    wave: int
    sha: str
    ticks: int

def snapshot_wave_start(repo_root: Path, plan_path: Path, wave: WaveInfo) -> WaveStart:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                         capture_output=True, text=True, timeout=30).stdout.strip()
    return WaveStart(repo_root, plan_path, wave.number, sha, wave.tasks_done)

def wave_progressed(start: WaveStart) -> bool:
    return _commits_since(start) > 0 or _ticks_now(start) > start.ticks

def _commits_since(start: WaveStart) -> int:
    count = subprocess.run(
        ["git", "rev-list", "--count", f"{start.sha}..HEAD"],
        cwd=start.repo_root, capture_output=True, text=True, timeout=30,
    )
    if count.returncode != 0:
        return 0
    return int(count.stdout.strip() or 0)

def _ticks_now(start: WaveStart) -> int:
    try:
        waves = plandoc.parse_waves(start.plan_path.read_text(encoding="utf-8"))
    except (OSError, plandoc.PlanDocError):
        return 0
    return next((w.tasks_done for w in waves if w.number == start.wave), 0)

def wait_for_reset(reset_at: datetime | None, *, poll_interval_s: float = 1200,
                   max_wait_s: float = 21600, _sleep=time.sleep, _now=datetime.now) -> None:
    if reset_at is None:
        _sleep(poll_interval_s)
        return
    seconds = (reset_at - _now()).total_seconds() + 60
    if seconds > max_wait_s:
        raise RecoveryTimeout(f"reset {seconds:.0f}s away exceeds max_wait {max_wait_s}s")
    if seconds > 0:
        _sleep(seconds)
```

- [ ] **Step 4: Run to verify pass** → PASS (7 tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(waverunner): recovery decision (fresh vs resume) + reset wait"`

### Task 2.2: Headroom spike + `tools/headroom.py`

**Files:**
- Create: `tools/headroom.py`
- Test: `tests/test_waverunner_headroom.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a standalone script managers run per the Task 0.4 playbook rule. Contract (fixed regardless of measurement outcome): prints exactly one JSON object `{"headroom": "ok"|"low"|"unknown", "detail": "<human sentence>"}` to stdout and exits 0 — **always**, including on any internal failure (fail-open to `"unknown"` per spec §4 Layer 3).

- [ ] **Step 1 (spike, timeboxed ~30 min): investigate measurement sources.** In order: (a) does the local `claude` expose usage programmatically (`claude --help` for a usage/status flag; check `~/.claude` for cached usage/rate-limit state written by recent sessions)? (b) transcript accounting: sum `usage` fields from today's `~/.claude/projects/<slug>/*.jsonl` entries newer than 5 h, compare against a configurable soft cap (env `WAVE_RUNNER_WINDOW_BUDGET_TOKENS`, unset ⇒ unknown). Pick the best option that works **without new dependencies and without an interactive prompt**; record the choice and rejected options in a comment block at the top of `headroom.py`. If nothing measurable exists, the deliverable is the fail-open stub — that is an acceptable spike outcome (Layer 1 covers misses).

- [ ] **Step 2: Write the failing contract tests** (they pin the interface, not the measurement):

```python
# tests/test_waverunner_headroom.py
import json
import subprocess
import sys
from pathlib import Path

HEADROOM = str(Path(__file__).resolve().parents[1] / "tools" / "headroom.py")

def _run(env_extra=None):
    import os
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run([sys.executable, HEADROOM], capture_output=True,
                          text=True, timeout=30, env=env)

def test_always_valid_json_and_zero_exit():
    out = _run()
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert data["headroom"] in {"ok", "low", "unknown"}
    assert isinstance(data["detail"], str)

def test_broken_home_fails_open(tmp_path):
    out = _run({"HOME": str(tmp_path)})  # no ~/.claude at all
    assert out.returncode == 0
    assert json.loads(out.stdout)["headroom"] == "unknown"
```

- [ ] **Step 3: Run to verify failure** → FAIL (file missing).
- [ ] **Step 4: Implement** per the spike outcome, with this exact skeleton guaranteeing the contract:

```python
# tools/headroom.py
"""Report usage-window headroom for the pre-task gate. Always exits 0 with JSON.

Spike outcome (fill in during Task 2.2):
- chosen source: ...
- rejected: ...
"""
import json
import sys

def measure() -> tuple[str, str]:
    """Return (headroom, detail). Replace body per spike outcome."""
    return "unknown", "no measurement source configured"

def main() -> int:
    try:
        headroom, detail = measure()
    except Exception as exc:  # noqa: BLE001 — fail open by contract
        headroom, detail = "unknown", f"measurement failed: {exc}"
    print(json.dumps({"headroom": headroom, "detail": detail}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run to verify pass** → PASS (2 tests).
- [ ] **Step 6: Commit** — `git commit -m "feat(tools): headroom gate script (spike outcome documented inline)"`

### Task 2.3: Main loop + CLI (`runner.py`, `tools/wave_runner.py`, `tools/run_waves.sh`)

**Files:**
- Create: `tools/waverunner/runner.py`, `tools/wave_runner.py`, `tools/run_waves.sh`
- Test: `tests/test_waverunner_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 0.1–2.2 (exact signatures as specified in their Interfaces blocks).
- Produces:
  - `@dataclass RunnerConfig(repo_root: Path, plans: list[Path], expected_branch: str = "main", claude_bin: str = "claude", stall_timeout_s: float = 1800, max_budget_usd: float | None = None, notify_config: NotifyConfig = ..., log_dir: Path = ..., default_model: str = "opus", default_effort: str = "high")`
  - `class Halt(Exception)` — the diagnosis of an anomaly that stops the whole run. Raised anywhere inside a wave, caught once in `run_plans`.
  - `run_plans(config: RunnerConfig) -> int` — exit code 0 = all plans complete, 2 = halted on anomaly (pre-flight refusal → 1 lives in the CLI). Thin: create one `_Run`, iterate plans, catch `Halt` → record + notify + return 2.
  - `class _Run` — holds the cross-wave state (`config`, injected `wait`, `cumulative_cost`, `carried: WaveResult | None`, `last_attempt`) so no method needs more than two parameters. Methods, each single-purpose:
    - `execute_plan(plan_path)` — `while (wave := first open wave)` → `_execute_wave`; then milestone notification.
    - `_execute_wave(plan_path, wave) -> WaveResult` — the per-wave loop: snapshot via `recovery.snapshot_wave_start`, `_launch`, then classify. `closed` → `_confirm_close` + `_announce_close` + return. `parked` → `_park` (raises `Halt` past `max_consecutive_parks`; notifies; waits; does **not** consume the attempt) then relaunch fresh. `blocked` / `ContractViolation` / second failure → raise `Halt`. First failure → `_wait_if_limit` (limit message ⇒ notify + wait until reset), then `wave_progressed(start)` ? relaunch fresh : relaunch with `resume=session_id`; consumes the wave's single recovery attempt.
    - `_launch(attempt: _Attempt) -> SessionOutcome` — builds the `SessionSpec` (kickoff prompt from the re-read `WaveInfo`), saves `state="running"` status, runs the session, accumulates cost. `_Attempt` is a frozen dataclass `(plan_path, wave: WaveInfo, model, effort, resume_id, session_id)`.
    - `_model_and_effort(plan_path, wave_number)` — carried JSON `next_model`/`next_effort` if set, else `manager_line`, else config defaults.
    - `_confirm_close(start: WaveStart)` — raises `Halt` unless the plan file appears in `git log <start.sha>..HEAD --name-only` **and** the working-tree Wave Log row for `start.wave` is `complete`. Never re-runs tests.
    - `record_halt(plan_path, reason)` — saves `state="halted"` status with the diagnosis + exact manual-resume command (`claude -r <session-id>`), notifies `"Wave runner HALTED"`.
  - `tools/wave_runner.py` — argparse CLI: `wave_runner.py PLAN [PLAN ...] [--branch main] [--claude-bin claude] [--stall-timeout 1800] [--max-budget-usd X] [--ntfy-topic T] [--log-dir .wave-runner-logs]`; maps onto `RunnerConfig`, runs pre-flight (exit 1 with the failure list printed), then `run_plans`.
  - `tools/run_waves.sh` — two lines: `#!/bin/sh` and `exec caffeinate -is python3 "$(dirname "$0")/wave_runner.py" "$@"`; `chmod +x`.

- [ ] **Step 1: Write the failing tests.** Drive `run_plans` with the fake claude (behavior-queue mode from Task 1.1) against a `tmp_path` git repo containing a two-wave plan fixture. To keep tests fast, inject waits: `run_plans` takes an internal `_wait=wait_for_reset` parameter tests replace with a recorder. **Simulating wave close:** the fake claude only prints JSON — it cannot edit the plan. Give the fake a `"touch_plan"` directive: when present, fake_claude ticks all `- [ ]` boxes in the named wave section of the plan file, marks the Wave Log row `**complete**`, and commits (it already runs inside the repo cwd). Extend `tests/fake_claude/fake_claude.py` with that directive in this task (it is test infrastructure, co-owned).

```python
# tests/test_waverunner_runner.py — core scenarios (complete file in repo)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import json
import subprocess
import uuid as uuidlib
import pytest
from waverunner import runner
from waverunner.notify import NotifyConfig

FAKE = str(Path(__file__).parent / "fake_claude" / "fake_claude.py")

TWO_WAVE_PLAN = """# Mini Plan
### Wave Log
| Wave | Status |
| --- | --- |
| 0 — A | not started |
| 1 — B | not started |

**Wave 0 manager:** opus, medium
**Wave 1 manager:** fable, high

## Wave 0 — A
- [ ] **Step 1: thing**

## Wave 1 — B
- [ ] **Step 1: other thing**
"""

def _closed(wave, nxt):
    return json.dumps({"wave": wave, "status": "closed", "gate": {"pytest": 1},
                       "next_wave": nxt, "next_model": "opus",
                       "next_effort": "low", "notes": f"wave {wave} ok"})

@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    plan = root / "plan.md"
    plan.write_text(TWO_WAVE_PLAN)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "plan"], cwd=root, check=True)
    script = tmp_path / "script.json"
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(tmp_path / "argv.jsonl"))
    notes = []
    cfg = runner.RunnerConfig(
        repo_root=root, plans=[plan], claude_bin=f"{sys.executable} {FAKE}",
        stall_timeout_s=5, log_dir=tmp_path / "logs",
        notify_config=NotifyConfig(osascript=False),
    )
    return root, plan, script, cfg, notes

def test_happy_path_two_waves(env, monkeypatch):
    root, plan, script, cfg, _ = env
    script.write_text(json.dumps([
        {"mode": "result", "result": _closed(0, 1), "touch_plan": {"path": "plan.md", "wave": 0}},
        {"mode": "result", "result": _closed(1, None), "touch_plan": {"path": "plan.md", "wave": 1}},
    ]))
    sent = []
    monkeypatch.setattr(runner, "notify", lambda t, m, c: sent.append((t, m)))
    assert runner.run_plans(cfg) == 0
    assert any("Wave 0 closed" in t for t, _ in sent)
    assert any("complete" in t.lower() or "milestone" in m.lower() for t, m in sent)

def test_blocked_halts_with_status(env, monkeypatch):
    root, plan, script, cfg, _ = env
    script.write_text(json.dumps([{"mode": "result", "result": json.dumps(
        {"wave": 0, "status": "blocked", "next_wave": None,
         "next_model": None, "next_effort": None, "notes": "gate red"})}]))
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg) == 2
    st = json.loads((root / "wave-runner-status.json").read_text())
    assert st["state"] == "halted" and "gate red" in st["detail"]

def test_limit_then_fresh_relaunch(env, monkeypatch):
    root, plan, script, cfg, _ = env
    # First call: limit error after ticking wave 0's boxes (progress, wave still open —
    # tick_only skips the Wave Log flip). Then a clean close of each wave.
    script.write_text(json.dumps([
        {"mode": "result", "result": "5-hour limit reached ∙ resets at 3am",
         "is_error": True, "touch_plan": {"path": "plan.md", "wave": 0, "tick_only": True}},
        {"mode": "result", "result": _closed(0, 1), "touch_plan": {"path": "plan.md", "wave": 0}},
        {"mode": "result", "result": _closed(1, None), "touch_plan": {"path": "plan.md", "wave": 1}},
    ]))
    waits = []
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg, _wait=lambda reset, **k: waits.append(reset)) == 0
    assert waits, "runner must wait for reset after a limit hit"
    argv = [json.loads(l) for l in (root.parent / "argv.jsonl").read_text().splitlines()]
    assert all("-r" not in a for a in argv), "progress ⇒ fresh relaunch, not resume"

def test_no_progress_limit_uses_resume(env, monkeypatch):
    root, plan, script, cfg, _ = env
    script.write_text(json.dumps([
        {"mode": "result", "result": "usage limit reached", "is_error": True},
        {"mode": "result", "result": _closed(0, 1), "touch_plan": {"path": "plan.md", "wave": 0}},
        {"mode": "result", "result": _closed(1, None), "touch_plan": {"path": "plan.md", "wave": 1}},
    ]))
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg, _wait=lambda *a, **k: None) == 0
    argv = [json.loads(l) for l in (root.parent / "argv.jsonl").read_text().splitlines()]
    assert any("-r" in a for a in argv), "no progress ⇒ --resume"

def test_second_failure_halts(env, monkeypatch):
    root, plan, script, cfg, _ = env
    script.write_text(json.dumps([
        {"mode": "die"}, {"mode": "die"},
    ]))
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg, _wait=lambda *a, **k: None) == 2

def test_contract_violation_halts(env, monkeypatch):
    root, plan, script, cfg, _ = env
    script.write_text(json.dumps([{"mode": "result", "result": "all done, great work!"}]))
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg) == 2

def test_park_loop_capped(env, monkeypatch):
    root, plan, script, cfg, _ = env
    parked = json.dumps({"wave": 0, "status": "parked", "next_wave": 0,
                         "next_model": None, "next_effort": None})
    cfg.max_consecutive_parks = 2
    script.write_text(json.dumps([{"mode": "result", "result": parked}] * 4))
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg, _wait=lambda *a, **k: None) == 2
    st = json.loads((root / "wave-runner-status.json").read_text())
    assert "parked" in st["detail"]

def test_verify_close_rejects_unchanged_plan(env, monkeypatch):
    root, plan, script, cfg, _ = env
    # Manager claims closed but never touched the plan doc.
    script.write_text(json.dumps([{"mode": "result", "result": _closed(0, 1)}]))
    monkeypatch.setattr(runner, "notify", lambda *a: None)
    assert runner.run_plans(cfg) == 2
```

Note the `claude_bin=f"{sys.executable} {FAKE}"` convention: the config's claude_bin may contain spaces (the fake needs `python3 fake_claude.py` as two argv entries), so `_Run._launch` builds the command as `shlex.split(config.claude_bin) + build_command(spec)[1:]` — the spec's own head is discarded in favor of the split binary.

- [ ] **Step 2: Extend `fake_claude.py` with `touch_plan`** (tick every `- [ ]` in the wave's section, flip its Wave Log row to `**complete**`, `git add -A && git commit -m "wave work"` in cwd). Complete directive handler:

```python
# added to fake_claude.py main(), before printing the result event
tp = current.get("touch_plan")
if tp:
    import re, subprocess
    path = tp["path"]
    text = open(path, encoding="utf-8").read()
    wave = tp["wave"]
    m = re.search(rf"^## Wave {wave}\b.*?(?=^## Wave |\Z)", text, re.M | re.S)
    section = m.group(0).replace("- [ ]", "- [x]")
    text = text[:m.start()] + section + text[m.end():]
    if not tp.get("tick_only"):  # tick_only simulates dying mid-wave with progress
        text = re.sub(rf"^\|\s*{wave}([^|]*)\|[^|]*\|", rf"| {wave}\1| **complete** |",
                      text, count=1, flags=re.M)
    open(path, "w", encoding="utf-8").write(text)
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "-c", "user.email=f@f", "-c", "user.name=fake",
                    "commit", "-qm", f"wave {wave} work"], check=True)
```

- [ ] **Step 3: Run to verify failure** → FAIL (`runner` missing).

- [ ] **Step 4: Implement `runner.py`.** The state machine, exactly as specified in Interfaces. Skeleton with the full control flow (implementer fills nothing in — this is the code):

```python
# tools/waverunner/runner.py
"""Main loop: execute wave plans unattended."""
from __future__ import annotations
import datetime as dt
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import contract, kickoff, plandoc, recovery, session
from .notify import NotifyConfig, notify
from .status import RunnerStatus, save as save_status

@dataclass
class RunnerConfig:
    repo_root: Path
    plans: list[Path]
    expected_branch: str = "main"
    claude_bin: str = "claude"
    stall_timeout_s: float = 1800
    max_budget_usd: float | None = None
    notify_config: NotifyConfig = field(default_factory=NotifyConfig)
    log_dir: Path = Path(".wave-runner-logs")
    default_model: str = "opus"
    default_effort: str = "high"
    max_consecutive_parks: int = 15  # ≈ one 5-h window at the 20-min poll

class Halt(Exception):
    """Diagnosis of an anomaly that stops the whole run."""

@dataclass(frozen=True)
class _Attempt:
    plan_path: Path
    wave: plandoc.WaveInfo
    model: str
    effort: str
    resume_id: str | None
    session_id: str

def run_plans(config: RunnerConfig, _wait=recovery.wait_for_reset) -> int:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    run = _Run(config, _wait)
    for plan_path in config.plans:
        try:
            run.execute_plan(plan_path)
        except Halt as halt:
            run.record_halt(plan_path, str(halt))
            return 2
    return 0

class _Run:
    def __init__(self, config: RunnerConfig, wait) -> None:
        self.config = config
        self.wait = wait
        self.cumulative_cost = 0.0
        self.carried: contract.WaveResult | None = None
        self.last_attempt: _Attempt | None = None

    def execute_plan(self, plan_path: Path) -> None:
        while (wave := self._first_open_wave(plan_path)) is not None:
            self.carried = self._execute_wave(plan_path, wave)
        notify(f"Plan complete: {plan_path.name}",
               f"All waves closed. Cumulative cost ${self.cumulative_cost:.2f}.",
               self.config.notify_config)

    def _execute_wave(self, plan_path: Path,
                      wave: plandoc.WaveInfo) -> contract.WaveResult:
        model, effort = self._model_and_effort(plan_path, wave.number)
        attempt_used = False
        parks = 0
        resume_id: str | None = None
        while True:
            attempt = _Attempt(plan_path, wave, model, effort,
                               resume_id, str(uuid.uuid4()))
            start = recovery.snapshot_wave_start(self.config.repo_root,
                                                 plan_path, wave)
            outcome = self._launch(attempt)
            if outcome.kind == "result" and not outcome.is_error:
                result = self._parse_result(outcome)
                if result.status == "blocked":
                    raise Halt(f"manager reported blocked: {result.notes}")
                if result.status == "parked":
                    parks = self._park(wave, parks)
                    wave = self._reread_wave(plan_path, wave)
                    resume_id = None
                    continue  # parking never consumes the recovery attempt
                self._confirm_close(start)
                self._announce_close(attempt, result)
                return result
            if attempt_used:
                raise Halt(f"second failure in wave {wave.number} "
                           f"(kind={outcome.kind})")
            attempt_used = True
            self._wait_if_limit(wave, outcome)
            resume_id = (None if recovery.wave_progressed(start)
                         else attempt.session_id)
            wave = self._reread_wave(plan_path, wave)

    def _launch(self, attempt: _Attempt) -> session.SessionOutcome:
        self.last_attempt = attempt
        self._save_status(attempt, "running", "")
        spec = session.SessionSpec(
            prompt=kickoff.kickoff_prompt(str(attempt.plan_path), attempt.wave),
            session_id=attempt.session_id, model=attempt.model,
            effort=attempt.effort, resume=attempt.resume_id,
            max_budget_usd=self.config.max_budget_usd)
        cmd = shlex.split(self.config.claude_bin) + session.build_command(spec)[1:]
        outcome = session.run_session(cmd, self._log_path(attempt),
                                      self.config.stall_timeout_s)
        self.cumulative_cost += outcome.cost_usd
        return outcome

    def _parse_result(self,
                      outcome: session.SessionOutcome) -> contract.WaveResult:
        try:
            return contract.parse_final_message(outcome.result_text)
        except contract.ContractViolation as exc:
            raise Halt(f"contract violation: {exc}") from exc

    def _park(self, wave: plandoc.WaveInfo, parks: int) -> int:
        parks += 1
        if parks > self.config.max_consecutive_parks:
            raise Halt(f"parked {parks} times in a row — "
                       "headroom gate looks stuck")
        notify(f"Wave {wave.number} parked ({parks})",
               "low headroom — waiting for the window to breathe",
               self.config.notify_config)
        self.wait(None)
        return parks

    def _wait_if_limit(self, wave: plandoc.WaveInfo,
                       outcome: session.SessionOutcome) -> None:
        if outcome.kind != "result" or not contract.is_limit_message(outcome.result_text):
            return
        reset_at = contract.parse_reset_time(outcome.result_text,
                                             dt.datetime.now())
        notify(f"Usage limit hit (wave {wave.number})",
               f"sleeping until {reset_at or 'unknown — polling'}",
               self.config.notify_config)
        self.wait(reset_at)

    def _confirm_close(self, start: recovery.WaveStart) -> None:
        log = subprocess.run(
            ["git", "log", "--name-only", f"{start.sha}..HEAD"],
            cwd=start.repo_root, capture_output=True, text=True, timeout=30)
        if start.plan_path.name not in log.stdout:
            raise Halt("plan document was not committed during the wave")
        waves = plandoc.parse_waves(start.plan_path.read_text(encoding="utf-8"))
        if not any(w.number == start.wave and w.closed for w in waves):
            raise Halt(f"Wave Log row for wave {start.wave} is not marked complete")

    def _announce_close(self, attempt: _Attempt,
                        result: contract.WaveResult) -> None:
        notify(f"Wave {attempt.wave.number} closed: {attempt.plan_path.name}",
               f"gate={result.gate} notes={result.notes} "
               f"cumulative=${self.cumulative_cost:.2f}",
               self.config.notify_config)

    def _model_and_effort(self, plan_path: Path,
                          wave_number: int) -> tuple[str, str]:
        if self.carried and self.carried.next_model and self.carried.next_effort:
            return self.carried.next_model, self.carried.next_effort
        line = plandoc.manager_line(plan_path.read_text(encoding="utf-8"),
                                    wave_number)
        return line or (self.config.default_model, self.config.default_effort)

    def _first_open_wave(self, plan_path: Path) -> plandoc.WaveInfo | None:
        waves = plandoc.parse_waves(plan_path.read_text(encoding="utf-8"))
        return plandoc.first_open_wave(waves)

    def _reread_wave(self, plan_path: Path,
                     fallback: plandoc.WaveInfo) -> plandoc.WaveInfo:
        return self._first_open_wave(plan_path) or fallback

    def record_halt(self, plan_path: Path, reason: str) -> None:
        if self.last_attempt is not None:
            resume_hint = f"manual resume: claude -r {self.last_attempt.session_id}"
            self._save_status(self.last_attempt, "halted",
                              f"{reason} | {resume_hint}")
        notify("Wave runner HALTED", f"{plan_path.name}: {reason}",
               self.config.notify_config)

    def _save_status(self, attempt: _Attempt, state: str, detail: str) -> None:
        save_status(self.config.repo_root / "wave-runner-status.json", RunnerStatus(
            plan=str(attempt.plan_path), wave=attempt.wave.number,
            session_id=attempt.session_id,
            attempt=1 if attempt.resume_id is None else 2,
            state=state, detail=detail,
            cumulative_cost_usd=self.cumulative_cost,
            updated_at=dt.datetime.now().isoformat(timespec="seconds")))

    def _log_path(self, attempt: _Attempt) -> Path:
        name = (f"{attempt.plan_path.stem}-wave{attempt.wave.number}"
                f"-{attempt.session_id[:8]}.log")
        return self.config.log_dir / name
```

- [ ] **Step 5: Run to verify pass** — `python3 -m pytest tests/test_waverunner_runner.py -v` → PASS (8 tests).

- [ ] **Step 6: Write the CLI + wrapper**

```python
# tools/wave_runner.py
"""CLI for the autonomous wave runner. See docs/superpowers/wave-plan-playbook.md."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from waverunner import preflight, runner  # noqa: E402
from waverunner.notify import NotifyConfig  # noqa: E402

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run wave plans unattended.")
    ap.add_argument("plans", nargs="+", type=Path)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--stall-timeout", type=float, default=1800)
    ap.add_argument("--max-budget-usd", type=float, default=None)
    ap.add_argument("--ntfy-topic",
                    default=os.environ.get("WAVE_RUNNER_NTFY_TOPIC"))
    ap.add_argument("--log-dir", type=Path, default=Path(".wave-runner-logs"))
    ap.add_argument("--skip-preflight", action="store_true",
                    help="for supervised debugging only")
    args = ap.parse_args(argv)

    repo_root = Path.cwd()
    if not args.skip_preflight:
        spec = preflight.PreflightSpec(
            repo_root=repo_root, expected_branch=args.branch,
            claude_bin=args.claude_bin.split()[0],
            process_patterns=("playwright", "education-pipeline.*daemon"))
        failures = preflight.preflight_failures(spec)
        if failures:
            print("Pre-flight refused to start:", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return 1
    config = runner.RunnerConfig(
        repo_root=repo_root, plans=args.plans, expected_branch=args.branch,
        claude_bin=args.claude_bin, stall_timeout_s=args.stall_timeout,
        max_budget_usd=args.max_budget_usd,
        notify_config=NotifyConfig(ntfy_topic=args.ntfy_topic),
        log_dir=args.log_dir)
    return runner.run_plans(config)

if __name__ == "__main__":
    sys.exit(main())
```

```sh
# tools/run_waves.sh
#!/bin/sh
exec caffeinate -is python3 "$(dirname "$0")/wave_runner.py" "$@"
```

`chmod +x tools/run_waves.sh`. Smoke: `python3 tools/wave_runner.py --help` prints usage, exit 0.

- [ ] **Step 7: Add gitignore entries** — append to `.gitignore`: `wave-runner-status.json` and `.wave-runner-logs/`.
- [ ] **Step 8: Run full new-module tests** — `python3 -m pytest tests/test_waverunner_*.py -v` → all PASS.
- [ ] **Step 9: Commit** — `git commit -m "feat(waverunner): main loop, CLI entry, caffeinate wrapper"`

- [ ] **Wave 2 close** — run the wave-close checklist (smoke now applies).

**Wave 3 manager:** fable, medium

---

## Wave 3 — Acceptance + closeout

### Task 3.1: End-to-end scenario matrix (`test_waverunner_e2e.py`)

**Files:**
- Create: `tests/test_waverunner_e2e.py`
- Test: itself.

**Interfaces:**
- Consumes: the CLI (`tools/wave_runner.py main(argv)`) + fake claude. These tests go through `main()` (not `run_plans`) to cover argument wiring and pre-flight integration.

- [ ] **Step 1: Write the scenario tests** (each builds a tmp git repo + plan fixture like Task 2.3's `env`, invokes `wave_runner.main([...])` with `--claude-bin "<python> <fake>" --skip-preflight` except the pre-flight scenarios, and monkeypatches `runner.notify` and `_wait` via `runner.run_plans` defaults — expose `_wait` through an env-var override `WAVE_RUNNER_TEST_NO_WAIT=1` checked in `run_plans` if monkeypatching through `main` proves awkward; prefer monkeypatch). Scenarios (spec Testing section, complete matrix):
  1. clean two-wave close through the CLI → exit 0, both Wave Log rows complete;
  2. limit-hit → fresh-relaunch recovery (progress made) → exit 0;
  3. limit-hit → resume recovery (no progress) → exit 0, `-r` in argv log;
  4. parked → relaunch → exit 0;
  5. blocked → exit 2, halted status file, notify fired;
  6. malformed final message → exit 2;
  7. verify-close mismatch (fake claims closed, never edits plan) → exit 2;
  8. stall (hang mode, `--stall-timeout 1`) → watchdog kill → recovery → exit 0;
  9. pre-flight failure (dirty tree, no `--skip-preflight`) → exit 1, nothing launched (argv log empty);
  10. two plans sequenced → exit 0, second plan's waves closed after first.
- [ ] **Step 2: Run** — `python3 -m pytest tests/test_waverunner_e2e.py -v` → all PASS (fix the code, not the scenario, on failure).
- [ ] **Step 3: Commit** — `git commit -m "test(waverunner): end-to-end scenario matrix through the CLI"`

### Task 3.2: Verify-at-build items + docs closeout

**Files:**
- Modify: `docs/superpowers/wave-plan-playbook.md`, `docs/superpowers/specs/2026-07-13-autonomous-wave-runner-design.md` (resolve the two verify-at-build notes), `CLAUDE.md` (one line under Commands: `tools/run_waves.sh PLAN` — run wave plans unattended)
- Create: `docs/superpowers/wave-runner.md` (operator guide)

- [ ] **Step 1: Verify `--max-budget-usd` under subscription auth.** Run a **single, tiny** real probe (the one deliberate token spend of this milestone): `claude -p "Reply with the word ok and nothing else." --model haiku --effort low --output-format json --max-budget-usd 0.01` — inspect whether `total_cost_usd` is populated and whether the budget flag errors under subscription. Record the finding in the spec's §4 note and, if the flag is inert, remove `--max-budget-usd` from the operator guide's recommended invocation (keep the plumbing).
- [ ] **Step 2: Verify limit-message phrasing.** Search the local install for the actual usage-limit error strings (`strings "$(command -v claude)" | grep -i "limit"` and/or recent session transcripts in `~/.claude/projects/`). If the real phrasing does not match `contract._LIMIT`/`_RESET`, update the regexes + tests in the same commit.
- [ ] **Step 3: Write the operator guide** `docs/superpowers/wave-runner.md`: prerequisites (allowlist calibration note: first run supervised, add `.claude/settings.json` permission rules for any `auto`-mode denial), invocation (`tools/run_waves.sh docs/superpowers/plans/<plan>.md --ntfy-topic <topic>`), what each notification means, reading `wave-runner-status.json` and the per-wave logs, manual-resume recipe after a halt, and the supervised-first-run checklist from the spec.
- [ ] **Step 4: Four-suite milestone gate** — `python3 -m pytest`; `cd web && npm run test && npm run e2e && npm run build` → all green (this milestone should not have touched web; the gate is assurance, not diagnosis).
- [ ] **Step 5: Commit** — `git commit -m "docs(waverunner): operator guide, verify-at-build findings, CLAUDE.md pointer"`

### Task 3.3: Open-source extraction (`wave-runner` standalone package)

**Files:**
- Create: `dist-oss/wave-runner/` (gitignored export directory — add `dist-oss/` to `.gitignore` in this task) containing: `waverunner/` (the package, copied), `wave_runner.py`, `headroom.py`, `run_waves.sh`, `tests/` (all `test_waverunner_*.py` + `fake_claude/`), `pyproject.toml`, `LICENSE` (MIT, copyright James Mooney), `README.md`, `.github/workflows/ci.yml`
- Create: `tools/export_oss.py` — the deterministic copier that assembles `dist-oss/wave-runner/` from the sources above (so the export is reproducible after future fixes, per this repo's extraction-manifest ethos)

**Interfaces:**
- Consumes: everything shipped in Waves 0–2; no repo-specific content may survive (grep the export for `education-pipeline` — only the README's "developed for" credit line may match).
- Produces: a directory that passes `python3 -m pytest` **from inside `dist-oss/wave-runner/`** with no reference to this repo.

- [ ] **Step 1: Write the failing test** — `tests/test_oss_export.py`: run `python3 tools/export_oss.py`, then assert the export contains the file list above, that `subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=export_dir)` exits 0, and that `grep -r "education-pipeline" dist-oss/wave-runner --include="*.py"` finds nothing.
- [ ] **Step 2: Run to verify failure** → FAIL (`export_oss.py` missing).
- [ ] **Step 3: Implement `export_oss.py`** (shutil.copytree with an explicit source list; rewrites the tests' `sys.path` shim from `parents[1] / "tools"` to `parents[1]` since the package sits at the export root). Write the README: what it does (one paragraph), the plan-format contract (wave headings, `### Wave Log`, `**Wave N manager:**` lines, checkbox discipline, final-message JSON — copied from the playbook's runner-mode section), quick start (`./run_waves.sh docs/plans/my-plan.md --ntfy-topic mytopic`), configuration table (flags + env vars), the three-layer budget design (three sentences), failure semantics, and the supervised-first-run/allowlist-calibration warning. `pyproject.toml`: `[project] name = "wave-runner" requires-python = ">=3.11"` + pytest dev extra. `ci.yml`: checkout + setup-python 3.11/3.12 + `pip install pytest` + `pytest -q`.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(oss): reproducible wave-runner OSS export"`
- [ ] **Step 6 (HUMAN step — the manager prints this instruction, never executes it):** create the public repo and push:
  `cd dist-oss/wave-runner && git init -b main && git add -A && git commit -m "wave-runner v0.1" && gh repo create wave-runner --public --source=. --push`

- [ ] **Wave 3 close** — run the wave-close checklist; this is the final wave, so print a **milestone summary** and a post-milestone-audit recommendation instead of a kickoff prompt. Include in the summary: the headroom spike outcome, both verify-at-build findings, the OSS publish command for the human, and the reminder that the first real run must be supervised (allowlist calibration).
