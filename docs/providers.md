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
claude -p --output-format json --tools "" --strict-mcp-config [--model <argv_model>] [extra_args]
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
codex exec [--model <argv_model>] --sandbox read-only --skip-git-repo-check [extra_args] -
```

Instructions arrive on stdin; the final message on stdout becomes the stage
response. `--sandbox read-only` keeps the run from writing to your
filesystem.

## Choosing models per stage

Two workspace files (editable by hand or through the cockpit, live-reloaded
either way) control what runs:

- `<workspace>/config/model-catalog.toml` — the models each provider
  offers. Per model: `id`/`label`/`description` (project-local alias),
  `quality` (relative guidance only — never a price claim),
  `default_effort`, `argv_model` (what is actually passed to `--model`),
  and `extra_args` (extra CLI flags, e.g. `["--reasoning", "high"]`).
- `<workspace>/config/model-plan.toml` — which provider/model/effort each
  stage uses, with "recommended" defaults you can reset to.

`config/model-catalog.example.toml` and `config/model-plan.example.toml` in
the repository show the full shape. Model names change over time by design:
update `argv_model` in your catalog rather than expecting the product to
hard-code current names.

## Running a stage through a provider

```bash
education-pipeline -C ./ws run <topic> --wait   # execute exactly the next stage
education-pipeline -C ./ws jobs <topic>          # job list
education-pipeline -C ./ws logs <job-id> -f      # follow output
```

`run` never auto-approves: it executes the next stage's prompt, saves the
response, and stops for your review. The first `run` auto-starts the
loopback-only daemon (opt out with `--no-autostart`).

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
