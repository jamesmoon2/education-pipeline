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

### Change detection lists directories as well as stats files (T62 design)

- Decision 11 said "stat-only". Finding new topics and jobs needs directory
  listings (`os.scandir`), and directory mtimes alone miss in-place edits.
- The shipped rule: no file *content* is ever read. The scan stats every
  entry in a run tree and every `job.json`, and it skips job logs.
- The per-job nudge from `JobStore.save` lowers latency only. Correctness
  rests on the scan.

### Dead peers are found by a liveness check, not the heartbeat (T62 design)

Decision 12 said a heartbeat surfaces a dead peer within one interval. On TCP,
the first write after the peer closes still succeeds, so a heartbeat needs two
intervals. Each stream checks its socket for EOF every second instead, and
the 15 s heartbeat only keeps proxies and the client watchdog alive.

### Six files in T62a, not four (T62a)

Emitting a new error code trips the error-catalog test, and cataloguing it
trips the troubleshooting-doc test. So `errors.py` and
`docs/troubleshooting.md` gained an `events_capacity` entry.

### Rail toast contrast fixed as a found bug (T62b)

This was not map scope. Rail toasts had set a white background without a text
colour, inside a rail whose text colour is near-white, so they were unreadable
in the light theme. It predates the phase. It is fixed with its own red/green
pair inside T62b's branch before the merge, so the phase head never carried an
intermittent axe failure. The fix is one line: `.toast` now takes
`--ep-color-text`.

### A flaky unit test fixed at its source (T62b)

`GlobalJobActivity.test.tsx` counted polls on real timers against `waitFor`'s
1 s default. It now advances fake timers. The timeout was not lengthened.

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
- **Filesystems whose mtimes can hide a change (T62a).** On coarse or cached
  mtimes (for example FAT, or some network mounts), or on Windows where
  `st_ino` is 0, an in-place edit that keeps the same size inside one mtime
  tick can go unnoticed. The 300 s lifetime reconnect resyncs everything, so
  staleness is bounded at 5 minutes. Polling had no such gap.
- **Scan cost grows with job history (T62a).** Every `job.json` is stat'ed on
  each pass, about 26 ms for 1,500 jobs in this container. The interval
  stretches to 10× the last pass, so a large workspace slows the scan rather
  than the daemon.
- **A plan edit sends `topics`, not `run{t}` (T62 design, manager ruling 3).**
  A run board open in another tab shows the previous parallelism figure until
  the next `run{t}` notice or the 5-minute resync.
- **Symlinked run directories are not followed (T62a).**
- **A client that stops reading holds a slot (T62a).** A peer that stays
  connected but stops reading keeps its stream slot until the 300 s lifetime
  ends it. Loopback socket buffers never fill at notice rates, so the write
  timeout does not fire first.
- **A shown tab can fetch twice (T62b, manager ruling 2).** When a hidden tab
  is shown again, each poller fetches once on the resume and once on the new
  stream's `hello`.
- **A notice in the same chunk as `hello` is dropped (T62b).** A notice that
  arrives in the same network chunk as `hello`, before React re-renders, is
  not delivered on its own. The `hello` resync, which starts after it, covers
  it.
- **React `act()` warnings in two unit tests (T62b).** They dispatch
  `visibilitychange` outside `act`, so they log warnings. They do not fail.
