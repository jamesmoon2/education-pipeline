# Phase 6 Cockpit Polish — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-27. Opened with the phase.
- **Source of truth:** the thread closeout log in
  [`docs/superpowers/plans/2026-09-27-phase-6-cockpit.md`](../plans/2026-09-27-phase-6-cockpit.md).
- **Purpose:** keep a record of the decisions that departed from the
  opportunity map, and of the accepted limitations, from the Phase 6 threads,
  so that a later audit can check them independently. This ledger is not that
  audit.

## Closeout disposition

The phase ran as five map threads: T60, T61, T62a, T62b and T63. T62 was split
before any code was written. Around them ran the T62 design note and its
adversarial review, one found-bug fix (rail toast contrast), one flaky unit
test fixed at its source, and two characterization test addenda (T60 and T63).
Each addendum pinned behaviour that an implementer had reported as unpinned.

Every behaviour change followed strict TDD. One Opus subagent wrote the
failing tests and a different Opus subagent made them pass without editing
tests. The manager reviewed diffs, checked each red set before green started,
and ruled on every open question.

Parallel work:

- T60 and T61 ran in parallel worktrees.
- T62a ran alongside the T62b red step.
- T63 followed T62b, because both touch `RunBoardPage` and the preview.

Mutations:

- 35 were tried across green steps and addenda, and all were caught: T60 8,
  T61 5, T62a 5, T62b 6 plus 3 on the toast fix, and T63 8.
- Each red writer also ran its tests against a throwaway implementation out
  of tree: T60 8 breakages, T61 5, T62a 11, T62b 33 mutants.
- The CI round-1 Windows fix added 2 more, both caught, for 37 in the phase.

| Gate | Baseline at open (`6675b40`) | At close (`26126b7`) |
| --- | --- | --- |
| pytest | 2619 passed, 1 skipped | 2667 passed, 1 skipped |
| vitest | 634 | 938 |
| Playwright full suite | 162 | 176 |

Code under `education_pipeline/` and `web/src`, tests excluded, changed by
+2292 / −165 across 30 files. `runtime.js` grew from 2383 to 2425 lines.
The largest new modules are `daemon/events.py` (456 lines), the cockpit's
`hooks/useEvents.tsx` (292) and `ShortcutsProvider.tsx` (385).

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

### The results page stays out of the preview bridge (T63)

The page's fallback id `results_page` fails `GUIDE_ID_PATTERN`, and the page
is not a guide section. The runtime never reports it, and it ignores a
preview-show that names it. A reload restores the last real section instead.
Two e2e cases pin both gates.

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
  mtimes (for example FAT, or some network mounts), an in-place edit that
  keeps the same size inside one mtime tick can go unnoticed. The 300 s
  lifetime reconnect resyncs everything, so staleness is bounded at 5
  minutes. Polling had no such gap. Windows is not a special case: records
  come from `os.stat(path, follow_symlinks=False)`, which there returns the
  real file index as `st_ino` and live timestamps, not the directory
  listing's lazily updated copy (`DirEntry.stat()`, with `st_ino` 0) that
  once made untouched runs look changed on the windows-latest CI job.
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
- **The preview is refreshed by mutations only (T63, manager ruling 2).** An
  out-of-process change to the approved guide (for example, a CLI approve)
  leaves the preview showing the previous HTML until the reviewer's next
  cockpit mutation. This is unchanged from before the phase. Now that the
  position survives a reload, making the preview driven by notices is a cheap
  follow-up.
- **No loading line on refresh (T63).** A refetch no longer shows "Loading
  guide preview…". On a refetch error, or when there is no approved repair,
  the preview is cleared, as the remount used to do.
- **A remounted board restores nothing (T63).** The remembered section lives
  in run-board page state, so navigating away from the board and back starts
  the preview at its boot section.

## After PR review (CI round 1 on PR #43)

The first CI run on `7db0a44` failed two checks. Both were root-caused and
fixed before the next push, and neither was re-run.

### `test (windows-latest, py3.12)`: 14 events tests (fixed red/green)

- **Symptom.** Topics nobody touched showed up as `run` changes between two
  fingerprint scans. Ubuntu passed.
- **Root cause.** `_record` built each record from `os.scandir`'s
  `DirEntry.stat()`.
  - On Windows, CPython fills that from the `WIN32_FIND_DATAW` listing
    (`Modules/posixmodule.c`, `DirEntry_from_find_data`). The listing is the
    copy of the metadata held in the parent directory's index, and NTFS
    updates it lazily. Microsoft's FindFirstFile documentation warns that it
    "may not be current".
  - A directory created just before the baseline scan could therefore report
    a stale timestamp once and the live one on the next pass.
  - On POSIX, `DirEntry.stat()` is an `lstat` anyway.
- **Red** (`bd02e74`). `test_fingerprint_does_not_trust_the_listings_stat_copy`
  reproduces the Windows behaviour on Linux: `scandir` entries whose first
  `stat()` is stale. It failed with the CI pattern. A positive control in the
  same test checks that real changes are still reported.
- **Green** (`8d3d9bd`). Every record now comes from
  `os.stat(path, follow_symlinks=False)`, which costs the same on POSIX.
  - Mutations: going back to `entry.stat` was caught, and so was
    `follow_symlinks=True`.
  - Side effect: records now carry the real file index on Windows, so the
    `st_ino = 0` limitation above no longer applies.

### `e2e (guide + mixed-run acceptance)`: `full-run.spec.ts:155` (test race, fixed in the test)

- **Symptom.** A strict-mode violation in the module paste loop: two "Save"
  buttons, one of them disabled.
- **Root cause.** Each paste editor keeps its Save disabled until its request
  lands, then closes. The spec opened the next editor straight after
  clicking Save. There are two ways in:
  - **A, predates the PR.** A module save is still in flight when the next
    module's editor opens. Holding the module POST for 300 ms fails it 5/5 at
    the PR head and 5/5 at the merge base `6675b40`.
  - **B, new with the events stream.** The module rows appear from a notice
    while the skeleton's own POST is still in flight. Holding the skeleton
    POST for 1.5 s fails it 5/5 at the PR head and 0/5 at the base.
  - Under load, the burst of refetches after a notice raised the median
    module-POST latency from 64 ms to 116 ms on one CPU. That widened path A.
- **Why the product is right.** Two open editors, one of them saving, is
  intended: the rows are independent, and the daemon serializes the writes.
- **Fix** (`f585de2`, test only). The spec waits for each editor to close
  before moving on. It uses no sleep and no longer timeout.
- **Evidence.** Both held-response variants now pass 10/10. Unloaded and
  loaded runs gave 0/40, the loaded full suite passed 176/176, and the merged
  head passed 10/10 on repeat.
- **Observed, not acted on.** At the merge base only, a heavily loaded
  40-run probe twice timed out waiting for a paste editor to open. It never
  reproduced at the PR head.

Gates on the fixed head `17007a3`: pytest 2668 passed, 1 skipped; `--help`
clean; build clean; vitest 938; full Playwright 176/176.

## CI round 2 on PR #43

On `c02d0ee`, 9 of 10 checks were green, including e2e, which confirms the
paste-loop fix. Windows pytest dropped from 14 failures to 2.

- **The remaining 2 were a test-helper portability bug.**
  - `_replace_same_size_with_new_mtime` read text and wrote text back.
  - The helpers `_write` and `_append` write in text mode, so on Windows each
    `\n` is stored as `\r\n`.
  - `read_text()` folds those back to `\n`, and `atomic_write_text` writes
    `\n` verbatim. The file shrank by one byte per line, 38 → 36 and 43 → 40,
    so the helper's own "same size" precondition failed before the code under
    test ran.
- **Fix** (`7349263`, test only). The helper copies bytes with
  `atomic_write_bytes(path, path.read_bytes())`.
- **Evidence.** A Linux simulation that forces CRLF on every text-mode write
  in both events test files fails exactly the two CI tests with the old
  helper, and passes all 49 with the new one.
- **Sweep.** No other test depends on size after a text-mode write.

