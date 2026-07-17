# Privacy and local trust

Education Pipeline is a fully local application. This page consolidates
what stays on your machine, what can leave it, and how the local pieces
protect themselves. The author-time trust model (what the pipeline does and
does not defend against) lives in [`SECURITY.md`](../SECURITY.md).

## What stays local

Everything. There is no hosted service, no account, no telemetry, and the
engine never phones home. A run lives entirely in your workspace directory
as plain files:

- **Learner profiles** (`profiles/<id>.toml`) and the per-run snapshot
  (`runs/<topic>/inputs/profile.toml`) are private by default.
- **Prompts, responses, and job logs** under `runs/<topic>/` — including
  everything a provider CLI printed.
- **Personalization traces, audit responses, and validation reports** —
  the private trace is hash-bound to the guide and never exported.

Only two things ever leave the workspace, and both are explicit actions:

1. **Running a provider stage** sends that stage's prompt (topic + the
   profile context used for tailoring) to whatever service the provider
   CLI is signed into — the same content you would paste by hand in manual
   mode. See [`docs/providers.md`](providers.md).
2. **Sharing an exported guide** — see the export boundary below.

## The export boundary

`export` assembles the distributable `guide.html` (and its sidecar
`guide.report.json`) from the guide's **public projection** — an
allowlist, not a redaction pass:

- Private profile values, goal text, exclusion reasons, and source
  annotations are structurally absent from the projection, not filtered
  out of it.
- Deterministic privacy screening additionally blocks export while any
  exact private profile value appears in guide content
  (`privacy.exact_private_value`), unless you record a reasoned waiver.
- The sidecar quality report carries only allowlisted, deterministic
  findings and content hashes — no timestamps, no profile values.
- A learner's reading progress in an exported guide lives only in their
  browser's `localStorage`, with a built-in reset control.

The shipped example demonstrates the boundary end to end: its synthetic
profile's private values are asserted absent from the export on every CI
run (`tests/test_example_project.py`).

## How the local daemon protects itself

The cockpit talks to a local daemon that holds write access to your
workspace. Its defenses, all covered by tests:

- **Loopback only.** The daemon binds strictly to `127.0.0.1` on an
  ephemeral port. It is never reachable from another machine.
- **Per-daemon token.** Every request must carry an `X-EP-Token` header;
  the comparison is constant-time. Requests without the token get `401`.
- **DNS-rebinding defense.** The `Host` header must be `127.0.0.1` or
  `localhost`; anything else gets `400 bad_host`. No CORS headers are ever
  sent, so a malicious web page cannot read responses cross-origin.
- **Connection info at rest.** The token, port, and pid are written to
  `<workspace>/.education-pipeline/daemon.json` with `0600` permissions —
  readable only by your user account. Treat that file like a local
  credential; it is runtime state, not data (safe to delete when the
  daemon is stopped, excluded from backups).
- **Single owner.** Daemon discovery claims the workspace atomically, so
  two daemons never fight over one workspace.

## What the pipeline does not defend against

At author time **you** are the trust boundary (see `SECURITY.md`): saved
model responses are reviewed and approved by you, not sandboxed. The guide
runtime is maintained application code — models produce structured JSON
content only, never executable code — and validation blocks structurally
invalid or privacy-leaking content from being packaged. But a determined
author can waive waivable findings; waivers are recorded, hash-bound, and
listed in the sidecar report so that decision is always visible.

## Keeping private data out of the public repository

If you develop against a checkout of this repository: generated runs, real
topics, profiles, and queues belong in a separate workspace directory.
Root-level `runs/`, `topics/`, `profiles/`, and `queue/` are gitignored and
CI fails if any private workspace artifact is ever tracked.
