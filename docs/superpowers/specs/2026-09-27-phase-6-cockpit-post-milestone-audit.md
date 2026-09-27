# Phase 6 Cockpit Polish — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-27. Opened with the phase.
- **Source of truth:** the thread closeout log in
  [`docs/superpowers/plans/2026-09-27-phase-6-cockpit.md`](../plans/2026-09-27-phase-6-cockpit.md).
- **Purpose:** keep a record of the decisions that departed from the
  opportunity map, and of the accepted limitations, from the Phase 6 threads,
  so that a later audit can check them independently. This ledger is not that
  audit.

## Closeout disposition

(Written at phase close.)

## Decisions that departed from or refined the map text

### T62 splits into T62a and T62b (at open)

The map sizes T62 as L and hands the daemon to Opus and the hook to Sonnet.
The plan splits it before any code, into T62a (daemon) and T62b (cockpit).
Each half gets its own red and green commits. The two halves share only the
wire format, and together they would pass the phase's ~800-line split
threshold.

### Approving by keyboard takes two keys (at open)

The map lists "Approve" among the shortcuts. The plan binds `a` to *focus* the
primary approve button, and Enter confirms. A single stray keystroke must never
approve, because approval is the product's deliberate judgment gate and nothing
auto-approves.

### The events stream is read with `fetch`, not `EventSource` (at open)

The map says "SSE, loopback and token-guarded like everything else".
`EventSource` cannot send the `X-EP-Token` header. The stream therefore keeps
the `text/event-stream` wire format, and the cockpit reads it with `fetch` and
a `ReadableStream`, so there is still exactly one credential and one auth rule.
A query-string token and a cookie were both rejected (plan decision 9).

### Change detection is a stat-only scan (at open)

The map says "emitting run, job and workspace change notices". The CLI writes
the workspace directly from another process (`cli.py:120`), so a notification
bus inside the daemon would miss those writes. Notices come from a stat-only
fingerprint scan that runs only while a stream is open.

## Accepted limitations

(Added per thread.)
