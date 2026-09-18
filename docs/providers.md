# Providers: setup, authentication, and configuration

Every model-powered stage can run three ways: through the **Claude Code**
CLI, through the **Codex** CLI, or **manually** (you copy the prompt into
any model and save the response back). Manual mode is a first-class path,
not a fallback — the pipeline works end to end with no provider installed.

The engine never calls a hosted API itself and never embeds an API key. A
"provider" is a local command-line tool on your machine; the daemon runs it
with your prompt on stdin and reads the response from stdout. Provider
authentication is therefore whatever the tool itself uses — the pipeline
neither sees nor stores those credentials.

## The three providers

| Provider id | Executable required | Availability check |
| --- | --- | --- |
| `manual` | none | always available |
| `claude-code` | `claude` on your `PATH` | `which claude` |
| `codex` | `codex` on your `PATH` | `which codex` |

The cockpit's Settings page shows each provider as detected or unavailable
with an explanation; a stage configured for an unavailable provider fails
with `provider_unavailable` and can always be switched to manual.

### Manual (`manual`)

Nothing to install or authenticate. `advance` writes the stage prompt to
`runs/<topic>/prompts/`, you run it in any model interface you like, save
the output to the printed response path, and `approve` the stage.

### Claude Code (`claude-code`)

1. Install the Claude Code CLI so `claude` is on your `PATH`
   (see https://code.claude.com/docs — npm, native installer, or your
   platform's package).
2. Authenticate once by running `claude` interactively and completing the
   login it offers (Claude subscription or Claude Console/API credentials).
   The pipeline reuses whatever login the CLI holds.
3. Verify: `claude -p "say ok"` should print a response without prompting.

What the adapter actually runs:

```
claude -p --output-format json --tools "" --strict-mcp-config [--model <argv_model>] [--effort <low|medium|high>] [extra_args]
```

The prompt is piped via stdin. `--tools ""` removes every built-in tool from
the session, and `--strict-mcp-config` (with no `--mcp-config` supplied)
keeps any MCP servers you have configured out of it too: the model can only
generate text — it cannot read or edit files or reach external tools during
a stage run. (Plan mode is deliberately not used here: it would make the
model produce a plan instead of the stage content.) The JSON envelope's
`result` field becomes the stage response; reported cost and session id are
kept as job metadata.

### Codex (`codex`)

1. Install the Codex CLI so `codex` is on your `PATH`
   (see https://developers.openai.com/codex).
2. Authenticate once by running `codex` interactively and completing its
   sign-in (ChatGPT account or API key, per the CLI's own docs).
3. Verify: `echo "say ok" | codex exec -` should print a response.

What the adapter actually runs:

```
codex exec [--model <argv_model>] --sandbox read-only --skip-git-repo-check [-c model_reasoning_effort="<low|medium|high>"] [extra_args] -
```

Instructions arrive on stdin; the final message on stdout becomes the stage
response. `--sandbox read-only` keeps the run from writing to your
filesystem.

Both `--effort` and the `model_reasoning_effort` config override appear only
when the stage's plan sets an effort; with no effort configured the CLI keeps
its own default. `extra_args` are appended last, so a flag you configure in
the catalog wins over the plan-derived one.

## Choosing models per stage

Two workspace files (editable by hand or through the cockpit, live-reloaded
either way) control what runs:

- `<workspace>/config/model-catalog.toml` — the models each provider
  offers. Per model: `id`/`label`/`description` (project-local alias),
  `quality` (relative guidance only — never a price claim),
  `default_effort`, `argv_model` (what is actually passed to `--model`),
  and `extra_args` (extra CLI flags, e.g. `["--reasoning", "high"]`).
- `<workspace>/config/model-plan.toml` — which provider/model/effort each
  stage uses, with "recommended" defaults you can reset to. A stage may also
  set `timeout_seconds` (a positive number) to cap how long that stage's
  provider job may run before the daemon fails it as a timeout; stages without
  one use the daemon-wide default of 1800 seconds.

`config/model-catalog.example.toml` and `config/model-plan.example.toml` in
the repository show the full shape. Model names change over time by design:
update `argv_model` in your catalog rather than expecting the product to
hard-code current names.

## Running a stage through a provider

```bash
education-pipeline -C ./ws run <topic> --wait   # execute exactly the next stage
education-pipeline -C ./ws jobs <topic>          # job list
education-pipeline -C ./ws logs <job-id> -f      # follow output
education-pipeline -C ./ws cancel <job-id>       # cancel one job
```

`run` never auto-approves: it executes the next stage's prompt, saves the
response, and stops for your review. The first `run` auto-starts the
loopback-only daemon (opt out with `--no-autostart`).

### Drafting a course module by module

An interactive-guide run drafts in units: one course *skeleton*, then one job
per module. `run <topic>` enqueues whichever is next — the skeleton on its
own, or every outstanding module as one **batch**:

```bash
education-pipeline -C ./ws run <topic> --wait                 # skeleton, then the batch
education-pipeline -C ./ws run <topic> --modules m1,m2        # just those modules
education-pipeline -C ./ws run <topic> --modules m1 --force   # re-draft one module
education-pipeline -C ./ws cancel --batch <batch-id>          # stop a whole fan-out
education-pipeline -C ./ws status <topic>                     # "draft: 3 of 8 modules"
```

`--modules` applies to the draft stage only, and re-running a module that
already has a response needs `--force`. `--wait` on a batch prints one line
per module, so a partial failure names exactly which modules to re-run rather
than costing the whole draft again. At most `parallelism` module jobs run at
once (`parallelism` in `config/model-plan.toml`, 1–4, default 2).

## Running to the next judgment

```bash
education-pipeline -C ./ws run <topic> --until approval
```

This keeps taking the steps that need no judgment — writing the next stage
prompt, running the configured provider and waiting for the job, assembling a
module-by-module draft, running validation — and stops at the first step that
does. It prints one line per step, then one line for where the run now stands.

What it never does: **approve, finalize or export.** It stops at the first
gate instead — a stage waiting for your approval, findings waiting for
review, a finished run waiting to be finalized or exported — and it also
hands back when the stage's provider is `manual` or the model plan cannot be
read, leaving the prompt on disk for you to run yourself. It cannot be
combined with `--stage` or `--modules` (usage error, exit 2), since those ask
for one specific job instead.

Exit codes: `0` when it reached a judgment point (including a manual
hand-back), `1` when a step failed or the run was still moving when the step
budget ran out, `2` for the usage error above.

To do this for several courses one after another, queue them:

```bash
education-pipeline -C ./ws queue add <topic>      # queue a course (or re-queue it)
education-pipeline -C ./ws queue list             # topic, status, where it stopped
education-pipeline -C ./ws queue remove <topic>
education-pipeline -C ./ws queue run              # drive each pending course, in order
```

`queue run` drives one course at a time, recording each one's stop in
`<workspace>/queue/courses.json` as it lands, and exits `1` if any course
stopped on a failure. A course interrupted mid-run stays `running` in that
file and is picked up again by the next `queue run`.

## Privacy notes

- Stage prompts include your topic and the private learner-profile context
  needed for tailoring. Running a provider sends that prompt to whatever
  service the CLI is signed into — the same content you would paste
  manually. If that is not acceptable for a given profile, use manual mode
  with a local model.
- Availability detection is a `PATH` lookup only; no course content is sent
  to check whether a provider works.
- Provider stdout/stderr is captured into local job logs under the
  workspace; logs never leave your machine.
