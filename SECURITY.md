# Security Policy

## Trust model

`education-pipeline` is a **local authoring tool**, not a sandbox for running
untrusted content. Understanding this boundary is essential to using it safely.

- **Generated content is trusted at author time.** Model responses you save into
  a workspace are assembled into the final guide and, on export, injected into a
  self-contained HTML/JS page. The tool does not sandbox or sanitize that
  content against active markup or script. Only finalize and export guides whose
  model responses you have reviewed.
- **Do not point it at untrusted responses.** Treat saved responses the same way
  you would treat source code you are about to run and publish.
- **Learner profiles are private by default.** Profiles live in your local
  workspace (`profiles/`, and a snapshot under `runs/<topic-id>/inputs/`) and are
  never published into a final guide unless you explicitly include a
  non-sensitive summary. Keep real profiles out of this package repository.
- **No network or hosted-API dependency.** The engine is standard-library only
  and reads and writes local files. It does not phone home. Any model calls
  happen in whatever provider UI or command *you* run, outside this tool.

## Supported versions

This project is pre-1.0. Security fixes are applied to `main` and the latest
release.

## Reporting a vulnerability

If you discover a security or privacy issue (for example a way generated content
or a profile could leak into published output unexpectedly), please report it
privately rather than opening a public issue:

- Use GitHub's **private vulnerability reporting** ("Report a vulnerability" on
  the repository's Security tab), or
- Email the maintainer.

Please include a description, reproduction steps, and the impact. We aim to
acknowledge reports within a reasonable time and will coordinate a fix and
disclosure timeline with you.
