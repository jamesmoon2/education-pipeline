# Provider Run Daemon — Design

**Status:** Approved design, ready for implementation planning
**Date:** 2026-07-09
**Spec 1 of 2** toward a local GUI. Spec 2 (the HTML/JS frontend) builds on the
JSON API defined here.

## Purpose

Give `education-pipeline` a headless, resumable way to *execute* a stage's
compiled prompt through a model provider (Claude Code or Codex) and capture the
response — instead of the human copying the prompt into a model UI by hand.

This is the Phase 5 "model provider" work from
`docs/open-source-readiness-plan.md`. It is built **runner-first**: usable from
the CLI now, with a JSON API that the future browser GUI (Spec 2) consumes as a
second client. The engine (`RunStore`, `config`) stays synchronous and
provider-agnostic; only the new daemon spawns provider processes.

## Scope

In scope:

- A long-lived local **run daemon** that owns a job queue and executes provider
  runs.
- A small **JSON API over loopback HTTP**, token-authenticated, shared by the
  CLI now and the GUI later.
- **Pluggable provider adapters** for `claude-code` and `codex`; `manual` stays
  non-executable (prompt-only).
- **Durable, resumable jobs**: status and logs persisted under the workspace.
- New CLI commands: `run`, `jobs`, `job`, `logs`, `cancel`, `daemon`.

Out of scope (Spec 2 or later):

- The browser GUI / HTML frontend.
- Auto-approving or auto-chaining stages. One invocation runs exactly one stage
  and stops; every approval gate stays human.
- New model providers beyond Claude Code and Codex.

## Key Decisions

Locked in during brainstorming:

1. **Runner first, GUI second.** Build the execution engine + CLI now; the GUI
   is a later client of the same API.
2. **One stage per invocation, stop for approval.** The runner does the run's
   next machine step for exactly one stage: ensure prompt written → invoke
   provider → capture response → stop. It never auto-approves. This preserves
   every approval gate (notably the explicit outline gate).
3. **Background jobs via a long-lived daemon.** Chosen over a detached
   per-job supervisor specifically because the daemon becomes the single shared
   backend for both the CLI and the future GUI. Without the GUI on the roadmap
   this would be premature; with it, it is the right architecture.
4. **Loopback HTTP + token transport.** Not a Unix domain socket: CPython does
   not expose `socket.AF_UNIX` on Windows, and the project is classified
   "Operating System :: OS Independent." Loopback HTTP works everywhere and is
   the transport the GUI needs anyway, so we build one backend, not two.
5. **Claude Code + Codex adapters** implemented now behind a pluggable
   interface; `manual` is a non-executable no-op.
6. **Typed provider fields on `ModelOption`** (not freeform metadata) carry the
   concrete CLI mapping. The maintainer owns these; model names change rarely.

## Architecture

```
┌─────────────┐     JSON API      ┌──────────────────────────┐
│  CLI client │ ────────────────▶ │   run daemon (long-lived) │
│ (education- │                   │  ┌────────────────────┐   │
│  pipeline)  │ ◀──────────────── │  │ job queue + worker │   │
└─────────────┘                   │  └─────────┬──────────┘   │
┌─────────────┐                   │            ▼              │
│ future GUI  │ ────────────────▶ │  provider adapters        │
│ (Spec 2)    │                   │  (claude-code, codex,     │
└─────────────┘                   │   manual)                 │
                                  │            │ calls         │
                                  │            ▼               │
                                  │      RunStore / config     │
                                  └────────────┬──────────────┘
                                               ▼
                                   workspace files (runs/, jobs/)
```

- **Daemon**: the only component that spawns provider CLIs. Holds an in-memory
  job queue backed by disk, runs a worker loop, calls the existing synchronous
  `RunStore`/config code.
- **Clients** (CLI now, GUI later): thin. They hit the JSON API and otherwise
  read workspace files directly.
- **Persistence**: job state and logs live on disk, so history survives daemon
  restarts and a fresh client can read past runs without the daemon running.

### Suggested module layout

- `education_pipeline/daemon/__init__.py`
- `education_pipeline/daemon/server.py` — loopback HTTP server, routing, auth.
- `education_pipeline/daemon/jobs.py` — `Job` model, on-disk store, queue, worker.
- `education_pipeline/daemon/lifecycle.py` — discovery file, start/stop/status,
  stale detection, orphan reconciliation.
- `education_pipeline/providers/__init__.py` — `ProviderRunner` protocol +
  registry.
- `education_pipeline/providers/claude_code.py`, `providers/codex.py`,
  `providers/manual.py`.
- `education_pipeline/client.py` — CLI-side HTTP client for the daemon API.
- New CLI command handlers in `education_pipeline/cli.py`.

Final boundaries are the implementer's call as long as the daemon stays the sole
process-spawner and the engine stays daemon-agnostic.

## Transport & Security

- Bind strictly to `127.0.0.1` on an ephemeral port. Never `0.0.0.0`.
- On start, generate a random token (`secrets.token_urlsafe`); write it plus the
  port to `.education-pipeline/daemon.json` (mode `0600`): `{pid, port, token,
  started_at, version}`. Clients read this file to locate and authenticate. The
  file is written atomically (temp file + `os.replace`) so a client can never
  read a half-written record.
- Every request must present the token (header, e.g. `X-EP-Token`); reject
  otherwise. Compare with `secrets.compare_digest`, not `==`. This stops other
  local processes and stray browser tabs / random localhost pages from driving
  runs.
- Validate an `Origin`/`Host` allowlist so a future browser client is not
  vulnerable to DNS-rebinding.
- The token is **not** placed in provider child-process environments; providers
  inherit the user's normal environment (they need keychain/OAuth/env auth)
  minus daemon-internal variables.
- `version` in `daemon.json` is the installed package version. If a client's
  version differs from the daemon's, the client warns and suggests
  `daemon stop && daemon start` — a daemon left over from before an upgrade
  runs old code.
- **One daemon per workspace.** `daemon.json` lives under the workspace, so
  daemon scope is the workspace. The daemon validates every `topic_id`/`stage`
  in a request against the workspace's known topics (reusing the existing safe-id
  logic) so a request can never address paths outside the workspace.

### JSON API (v1)

Pinned now because the GUI (Spec 2) is a second client of the same contract.
All responses are JSON; errors are `{"error": {"code", "message"}}` with an
appropriate HTTP status.

| Method & path              | Purpose |
|----------------------------|---------|
| `GET  /v1/health`          | liveness + `{version, started_at}` |
| `POST /v1/jobs`            | enqueue: `{topic_id, stage?, force?}` → job record (or refusal) |
| `GET  /v1/jobs?topic=`     | list job records, newest first |
| `GET  /v1/jobs/{id}`       | one job record |
| `GET  /v1/jobs/{id}/log?offset=N` | log bytes from `offset`; returns next offset — clients tail by polling |
| `POST /v1/jobs/{id}/cancel`| cancel a queued or running job |
| `POST /v1/shutdown`        | graceful stop (used by `daemon stop`) |

No server push in v1: clients poll (`GET /jobs/{id}`, log offsets). Simple,
stdlib-only, and sufficient for both CLI `-f` and a GUI refresh loop.

## Job Model & Persistence

A **Job** is the durable record of one stage execution:

```
runs/<topic_id>/jobs/<job_id>/
    job.json      # written atomically on each state transition
    output.log    # combined stdout+stderr from the provider, streamed live
```

`job.json` fields: `id`, `topic_id`, `stage`, `provider`, `model`, `effort`,
`status`, `pid`, `created_at`, `started_at`, `ended_at`, `exit_code`,
`response_path`, `error`.

Job ids are `<UTC timestamp>-<short random suffix>` (e.g.
`20260709T183042Z-a3f9`) — sortable by creation, collision-safe, filesystem-safe.

Status lifecycle: `queued → running → succeeded | failed | canceled |
interrupted`. The last four are terminal.

Rules:

- **No duplicate active jobs**: enqueue refuses if a `queued` or `running` job
  already exists for the same `topic_id` + `stage` (double-submit from CLI + GUI
  must not launch two provider runs).
- **Per-job timeout**: configurable (default generous, e.g. 30 minutes). On
  expiry the process is terminated like a cancel and the job is `failed` with
  `error: "timeout"`. No job can wedge the single-worker queue forever.
- **Output caps**: `output.log` capture is capped (e.g. 10 MB, keep head +
  tail with a truncation marker); the parsed response has a sanity cap as well.
  A runaway provider can't fill the disk.

- On **success**, captured provider output is written to the stage's normal
  `response_path` via the existing `RunStore`, so an executed response is
  byte-for-byte indistinguishable from a hand-saved one. Existing
  `approve`/`advance`/`finalize`/`export` work unchanged.
- A `job` event is appended to the run manifest, consistent with the existing
  event log.
- Never write an **empty/whitespace** response — empty output is a failure.
- Never clobber an already-ingested response — a job refuses if a response
  exists unless explicitly forced.
- Every response write is atomic and gated on a clean provider exit, so a crash
  can never leave a half-written response that later gets approved.

## Provider Adapters

A pluggable interface isolates provider-specific logic. Adapters only *describe*
how to invoke; they never spawn — the daemon worker owns `subprocess`, log
streaming, and response capture.

```python
class ProviderRunner(Protocol):
    provider_id: str
    def is_available(self) -> bool: ...          # is the CLI on PATH?
    def build_invocation(self, model: ModelOption, plan: StageModelPlan,
                         prompt_path: Path) -> Invocation: ...
```

`Invocation` is a value object: `argv: list[str]`, `stdin: bytes | None`, `env`
overrides. A registry maps `provider_id → ProviderRunner`. The daemon resolves
the stage's provider and model alias from the `ModelPlan`/`ModelCatalog` and
passes the concrete `ModelOption` (which carries `argv_model`/`extra_args`) into
`build_invocation`, so adapters never touch config parsing themselves.

### Claude Code adapter

```
claude -p --output-format json --model <argv_model> [extra_args...]   < prompt.md
```

- Prompt fed via stdin (piped stdin capped at 10 MB; prompts are far under).
- Parse stdout as JSON; take the `.result` field (the assistant's final text).
  JSON also carries `total_cost_usd`, `session_id` — recorded in the job when
  available.
- Run with **tools disabled** (pure text generation; the model must not edit
  files) via a restrictive permission mode / empty allowed-tools.
- `--model` accepts an alias (`opus`/`sonnet`/`fable`/`haiku`) or a full id
  (`claude-opus-4-8`).
- **`--bare` default OFF.** `--bare` gives reproducible scripted runs but forces
  `ANTHROPIC_API_KEY` auth and skips OAuth/keychain, which breaks
  subscription/OAuth users. Default without it; opt in via config.

### Codex adapter

```
codex exec --model <argv_model> --sandbox read-only --skip-git-repo-check [extra_args...]   -   < prompt.md
```

- `codex exec` with `-` reads instructions from stdin; stdout is exactly the
  agent's final message (activity goes to stderr) — clean to capture.
- `--sandbox read-only` (pure generation, don't let it touch files) and
  `--skip-git-repo-check` (workspaces are not git repos).

### Manual adapter

`ManualRunner.is_available()` is true but it is **not executable**. Enqueuing a
manual-provider job returns a clear "manual provider — run the prompt yourself
and save the response" result instead of launching anything.

### Config change: typed fields on `ModelOption`

Add to `ModelOption` in `config.py`:

```python
argv_model: str | None = None     # concrete --model / -m value; None → provider default
extra_args: tuple[str, ...] = ()  # additional per-model CLI args (e.g. effort/reasoning flags)
```

The adapter composes `base_argv + ["--model", argv_model] + extra_args`.
Provider-specific effort/reasoning flags live in `extra_args`, so exact flag
spellings are user-editable config, not baked into the package. The example
catalog (`config/model-catalog.example.toml`) gets real values filled in
(e.g. `argv_model = "claude-opus-4-8"` for the premium alias).

**How effort is resolved (no per-adapter effort logic):** `StageModelPlan.effort`
is recorded on the job for provenance but is **not** translated to a CLI flag by
the adapter. Concrete reasoning/effort flags are expressed once, in the model
option's `extra_args`. A user who wants per-stage effort variation defines
distinct model aliases (e.g. `premium-high`, `premium-low`) and points stages at
them in the model plan. This keeps the invocation fully declarative and typed,
with no fragile effort-string-to-flag mapping in code.

## Daemon Lifecycle & Crash Recovery

- **Discovery file**: `.education-pipeline/daemon.json` as above. `daemon start`
  refuses if a live daemon already owns the file.
- **Commands**: `daemon start` (spawn detached), `daemon status` (PID alive +
  token works), `daemon stop` (graceful: stop accepting, finish or cancel the
  in-flight job per flag, exit, remove the file). Jobs still `queued` at stop
  stay `queued` on disk and resume when a daemon next starts.
- **Auto-start**: a `run` call auto-starts the daemon if none is live; opt out
  with `--no-autostart`. Two concurrent auto-starts must not race: the starter
  claims `daemon.json` with an exclusive create (`O_EXCL`; stale files are
  removed first), and the loser detects the winner's file and uses that daemon.
  After spawning, the client waits for `/v1/health` before enqueueing, with a
  bounded startup timeout.
- **Stale detection**: if `daemon.json` exists but the PID is dead, clients
  treat it as stale and a new daemon may replace it.
- **Orphan reconciliation**: on startup the daemon inspects jobs left over from
  a previous life. Jobs still `queued` (never started) are **re-enqueued** FIFO
  — resumable by design. Jobs left `running` are marked `interrupted`, with a
  note, and **no** partial response is written. If the recorded `pid` is still
  alive it is terminated best-effort — but only after a sanity check that it
  plausibly is our child (guard against PID reuse; if unsure, don't kill, just
  mark `interrupted` and log).
- **Concurrency**: default worker concurrency is 1 (one provider call at a time;
  predictable, avoids hammering the model), configurable. Extra jobs sit
  `queued` and start FIFO.

## CLI Surface

New command groups, all thin clients of the daemon API:

```
education-pipeline -C ./ws run <topic>                 # enqueue next-stage job → prints job id
education-pipeline -C ./ws run <topic> --wait          # block until terminal; exit 0 only on success
education-pipeline -C ./ws run <topic> --stage draft   # override stage (default: run_status.next_action)
education-pipeline -C ./ws jobs [<topic>]              # list jobs
education-pipeline -C ./ws job <job-id>                # one job's full record
education-pipeline -C ./ws logs <job-id> [-f]          # print/tail output.log (-f follows to terminal)
education-pipeline -C ./ws cancel <job-id>             # cancel queued/running job
education-pipeline -C ./ws daemon start|stop|status
```

**How `run` fits the existing flow.** `run <topic>` executes the stage named by
the current `run_status.next_action` — the same next-step logic the CLI already
uses. It enqueues *only* if that next action is a "run this stage's prompt" step.
If the run is instead waiting on a human **approve**, `run` refuses with a clear
message pointing at `approve`. The gate is structural: the runner physically
cannot skip an approval. After a job succeeds, the response lands in the normal
`response_path` and the existing `approve`/`advance`/`finalize`/`export`
commands take over unchanged. `--force` overrides the no-clobber refusal.

**Exit codes for scripting**: enqueue-only `run` exits 0 once the job is
accepted; `run --wait` exits 0 only if the job succeeded, non-zero otherwise
(and prints the terminal status + log path). `cancel` of an already-terminal
job is a no-op that says so, exit 0.

## Error Handling

Each maps to a terminal job status plus a clear message:

- **Provider unavailable** (`is_available()` false): fail immediately, name the
  missing binary and suggest installing it or selecting another provider. No
  process spawned.
- **Non-zero exit**: `failed`; stderr/stdout in `output.log`; `exit_code`
  recorded; no response written.
- **Empty/whitespace output**: `failed` (never poison approve/advance with an
  empty response).
- **Malformed JSON** (Claude `--output-format json`): `failed`, raw output
  preserved in the log.
- **Response already ingested**: `run` refuses up front unless `--force`.
- **Crash/orphan**: reconciled to `interrupted` on daemon restart.
- **Timeout**: terminated like a cancel; status `failed` with `error: "timeout"`.
- **Cancellation** (portable — the transport was chosen for Windows, so
  termination must be too): on POSIX, spawn with `start_new_session=True` and
  SIGTERM the process group, SIGKILL after a grace period. On Windows, spawn
  with `CREATE_NEW_PROCESS_GROUP` and use `Popen.terminate()`/`kill()` (no
  SIGTERM semantics). Both paths behind one `terminate_job()` helper; status
  `canceled`. Canceling a still-`queued` job just marks it `canceled` — nothing
  to kill.
- **No automatic retries** in v1. A failed job stays failed; the human
  inspects the log and re-runs. Retry policy, if ever, is a later spec.

## Testing Strategy

Deterministic and offline — no real model calls in CI.

- **Fake provider**: a tiny stub script the adapter is pointed at via config,
  echoing a canned response with configurable exit code and delay. Exercises the
  whole job lifecycle (success, failure, empty output, timeout, cancel) with
  zero network.
- **Provider adapters**: unit-test `build_invocation()` (argv, stdin,
  model/`extra_args` composition) for Claude Code and Codex without executing.
- **Daemon API**: start the daemon on an ephemeral port in a temp workspace,
  drive it through a test client (enqueue → poll → assert job record, that the
  response landed in `response_path`, and the manifest event).
- **Lifecycle/recovery**: start/stop, stale-file replacement, orphan
  reconciliation (simulate a dead PID → assert `interrupted`, no partial
  response; leftover `queued` jobs → assert re-enqueued and run), autostart
  race (two clients claim `daemon.json` → exactly one daemon).
- **Job guards**: duplicate enqueue for the same topic+stage refused; timeout
  (fake provider sleeps past a tiny configured timeout → `failed`,
  `error: "timeout"`, process gone); cancel of queued vs running vs terminal
  jobs; oversized output truncated at the cap.
- **CLI**: `run` refusing when the next action is an approval; `run --wait`
  exit codes; `manual` provider returning the do-it-yourself message.
- **Auth**: requests without the token are rejected (constant-time compare);
  `Origin`/`Host` allowlist enforced; requests naming a topic outside the
  workspace rejected.
- **Cross-platform**: process-termination helper unit-tested on the platform CI
  runs on; the POSIX/Windows split is isolated in one function so the Windows
  branch is small and testable on a Windows runner when available.
- **Real CLIs stay out of CI**: availability/e2e against actual `claude`/`codex`
  is an opt-in local check, never a CI dependency.

## Constraints Preserved

- **Dependency-free**: standard library only (`http.server`, `subprocess`,
  `socket`, `json`, `tomllib`, `secrets`). `pytest` remains the only dev
  dependency.
- **Local-first, resumable**: all job state on disk; a fresh session recovers
  history.
- **Human quality gate intact**: one stage per invocation, no auto-approval.
- **Content/runtime separation**: providers generate content only, with tools
  off / read-only sandbox.

## References

- Claude Code headless docs: https://code.claude.com/docs/en/headless
- Codex non-interactive mode: https://developers.openai.com/codex/noninteractive
- codex/docs/exec.md: https://github.com/openai/codex/blob/main/docs/exec.md
- `docs/open-source-readiness-plan.md` (Phase 5, Model Provider Settings)
- `docs/roadmap.md` (Phase 4, Model Plan UI)
