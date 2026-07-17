# First-Run and Course-Management — Post-Milestone Audit Ledger

- **Recorded:** 2026-07-16
- **Source of truth:** Wave 0–5 closeout records in
  [`docs/superpowers/plans/2026-07-16-first-run-course-management.md`](../plans/2026-07-16-first-run-course-management.md)
- **Purpose:** preserve accepted or deferred closeout items for a fresh,
  independent post-milestone audit. This ledger does not replace that audit.

## Closeout disposition

All five spec deliverables landed test-first across six waves, each closed
with the suite gates recorded in the Wave Log. The final gate ran the full
four suites (pytest, vitest, Playwright, `npm run build`) plus the local
equivalent of the CI `packaging-smoke` job against the real built wheel.

## Accepted limitations

### The `archived_course` guard lives at the daemon adapter layer

Mutating `/v1` routes and provider enqueue refuse writes to an archived
course with `archived_course`, but direct `RunStore` calls (and therefore
direct CLI commands such as `advance` or `approve` against an archived run)
are not guarded. The cockpit is the archiving surface and the CLI has no
archive/unarchive commands, so a CLI user can only reach that state by
archiving in the cockpit first; nothing corrupts — the flag is presentation
metadata and a later unarchive changes nothing on disk.

**Revisit when:** the CLI grows archive/unarchive commands, or archiving
acquires semantics beyond library presentation (e.g. compaction).

### `last_activity` scans the run directory per list request

`GET /v1/topics` computes each course's `last_activity` with a recursive
mtime scan of the run directory on every poll. Run directories are small
(tens of files) and the cockpit polls at 10s, so this is currently
negligible; there is no caching layer to invalidate.

**Revisit when:** workspaces hold hundreds of courses or run directories
grow large enough that list latency becomes visible in the cockpit.

### Reveal on Linux opens the containing directory

`xdg-open` cannot select a file, so the Linux reveal opens the containing
directory instead of highlighting the file (macOS `open -R` and Windows
`explorer /select,` do highlight). The `EP_REVEAL_OPENER` override exists
for tests and headless setups and is invoked as `$EP_REVEAL_OPENER <path>`.

**Revisit when:** a portable file-highlighting convention emerges, or user
feedback shows directory-opening is confusing.

### First-run TTY prompt is a single free-text question

The interactive first-run flow asks one question (workspace directory, with
`~/EducationPipeline` as the accept-default), rather than a multi-choice
menu. Non-interactive invocations never prompt and exit with
`workspace_unselected` per spec §3.2.

**Revisit when:** the P2 release milestone designs install/onboarding docs
and can user-test the prompt wording.

## Recommended independent audit

A fresh post-milestone task should review the complete first-run commit set
and this ledger read-only. It should confirm: the reveal endpoint's
enum-target and realpath-containment behavior (including symlink escapes and
that user input never reaches the spawned command line); the archived-course
write-guard coverage across every mutating route; registry corruption
handling; wheel bundling reproducibility and the packaging-smoke job; error
envelope stability (`detail` key, append-only codes); welcome-panel
accessibility; and that no generated runs, real profiles, or workspace
artifacts were committed. It should report only concrete, reproducible
findings and should not reopen the accepted limitations unless a stated
revisit condition is now true.
