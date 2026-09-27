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

### The route fallback is its own component (T60)

- The plan named one `ErrorBoundary` in two placements. The route fallback UI
  lives in `RouteErrorFallback.tsx`, and the app-level UI in
  `AppErrorFallback.tsx`, which keeps the `App.tsx` diff small.
- The theme select has a visible "Theme" label bound by `htmlFor`, rather than
  an `aria-label`. Its accessible name is the same.

### The shortcuts button sits after the rail footer, not inside it (T61)

- Decision 7 put the "Keyboard shortcuts" button "in the rail footer". It is a
  DOM sibling that follows `.rail-footer` instead.
- `.rail-footer` is `display: none` below 48rem, so a button inside it would
  vanish on narrow screens. The on/off switch would then be unreachable there
  once shortcuts were turned off.
- At 600px the button shows in the top bar.

### `r` follows the library's default order (T61)

"Library order" means the default view: newest activity first, with archived
courses hidden. A sort the user picks on the library page does not change it.
`r` also skips approvals that name no stage, as `GlobalJobActivity` does.
Escape closes the overlay even when shortcuts are off, because a dialog must
always be closable.

## Accepted limitations

- **Theme select hidden on narrow screens (T60).** It sits inside
  `.rail-footer`, which is hidden below 48rem (`styles.css:353`). An explicit
  choice is still applied at boot.
- **Possible light flash before the script runs (T60).** The theme is stamped
  by the module script before the first React render. There is no inline
  `<script>` in `index.html`, so an explicit dark choice can show the default
  background for one frame while the bundle loads.
- **No cross-tab theme sync (T60).** Another open tab picks up a change on its
  next load.
- **Render errors only (T60).** React boundaries do not see errors in event
  handlers or async code. `ErrorNotice` already covers API failures.
- **contentEditable is unit-tested only as a plain object (T61).** jsdom has
  no `isContentEditable`.
- **`/` from another page (T61).** It navigates to the library and waits up to
  10 s for "Filter courses" to mount before giving up quietly.
