# Phase 6 — Cockpit polish

**Goal:** Make the cockpit resilient, faster to drive and cheaper to keep open. After this phase:

- A render error on one page no longer blanks the app.
- The cockpit has its own theme choice.
- The new-course wizard's state is one reducer.
- The common review moves have single-key shortcuts that never approve by accident.
- One authenticated events stream replaces the run board's pollers, with polling kept as the fallback.
- The guide preview tells the cockpit where the reviewer is and keeps that place across refreshes.

No engine behaviour changes. The only daemon change is one new read route.

**Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`): tier-2 items J and K, and "Build plan · Phase 6". Threads are numbered as there. Line anchors are as of `6675b40` (post Phase 5, PR #42 merged).

**Method:** strict TDD.

- One Opus subagent writes the failing tests and commits `T6x red: …`. A different Opus subagent makes them pass without editing tests and commits `T6x green: …`. Every green agent tries at least two mutations, confirms the tests catch them, and reverts them.
- The manager reviews diffs, not transcripts. Before the green step starts, the manager checks that each red test fails for missing behaviour and not for a typo.
- T62 is size L and security-sensitive. One Opus subagent writes a design note, and a second reviews it adversarially against `daemon/server.py`, `read_api.py` and `jobs.py` before any code.
- A thread that grows past ~800 changed lines or 12 files (tests and generated files aside) is split.

Gates for every thread, before it is ticked:

- full pytest and `python3 -m education_pipeline --help`;
- `npm run build` and `npx vitest run`;
- the e2e specs the thread touches;
- `python3 scripts/build_example.py` whenever `runtime.js`, `runtime.css` or `document.py` changes, because the example export is byte-pinned.

The full Playwright suite runs on the merged head before the PR.

**Baseline at open (`6675b40`):**

| Gate | Result |
| --- | --- |
| pytest (Python 3.11) | 2619 passed, 1 skipped |
| `python3 -m education_pipeline --help` | clean |
| `npm run build` | clean |
| vitest | 634 |
| Playwright full suite | 162 |

About the Playwright count: the first baseline run passed 155 of 162, because the manager ran `npm run build` at the same time and the e2e daemon serves `web/dist`. All 7 failures were in the first minute. The three affected specs then passed 10/10 when run alone. The rule taken from this is decision 20.

**Audit ledger:** [`../specs/2026-09-27-phase-6-cockpit-post-milestone-audit.md`](../specs/2026-09-27-phase-6-cockpit-post-milestone-audit.md)
**T62 design note:** [`../specs/2026-09-27-events-endpoint-design.md`](../specs/2026-09-27-events-endpoint-design.md) (written at T62 open)

## Threads

| ID | Thread | Exit criteria | Status |
| --- | --- | --- | --- |
| T60 | Error boundary, theme toggle, wizard reducer | A route-level boundary keeps the rail usable and offers "Try again" and "Back to the library". An app-level boundary offers "Reload". A theme select (system, light or dark) stamps or clears `data-theme` and persists per browser. `NewRunPage` form and lifecycle state live in one pure reducer, and the existing NewRunPage unit tests and the new-run and blueprints e2e pass with zero edits. There are unit tests for each part and one e2e case for theme persistence and axe in dark. | - [x] |
| T61 | Keyboard shortcuts | The key map in decision 4 works, under the rules in decisions 5–8. A `?` overlay lists the keys and carries an on/off switch. A new `keyboard.spec.ts` walks library → course → stage by keyboard, proves typing in inputs triggers nothing, proves `a` never approves, and runs axe with the overlay open. The pure key resolver has unit tests. | - [x] |
| T62a | Events endpoint (daemon) | `GET /v1/events` behaves as decisions 9–12 and the design note describe. Server tests cover Host and token rejection, the `hello` and `change` frames, a CLI-style out-of-process write being noticed, coalescing, the stream cap, heartbeat and lifetime, and shutdown releasing streams. | - [ ] |
| T62b | Events in the cockpit | One stream per tab, owned at App level. A `useEvents` hook and `usePolling` integration mean pollers stop while the stream is up and resume when it is down. A vitest proves that one change notice costs the board at most one request per mounted resource it names, and zero requests when idle. e2e: a board updates after a CLI-side change with the stream up. | - [x] |
| T63 | Preview bridge, both ways | The runtime reports the current section in preview mode only. The run board stops remounting the preview on unrelated mutations, and it restores the reviewer's section when the guide HTML does change. The schema and origin rules are decisions 15–16. e2e covers the round trip in the real cockpit iframe and proves an exported guide posts nothing. The example export is rebuilt. | - [x] |

## Order and parallelism between threads

- **T60 and T61 run in parallel worktrees.** They touch mostly disjoint web files. Both touch `App.tsx` (the boundary around `<Routes>`, the theme select, the shortcuts provider and button) and `styles.css`, which only gets appended to. They merge in the order T60, then T61. T61 resolves the `App.tsx` overlap at its merge.
- **The T62 design note and its adversarial review run alongside T60 and T61.** They are documents only.
- **T62a runs once the review is folded in.** It is Python only and disjoint from the web threads, so it may overlap T60 and T61.
- **T62b follows the T61 merge**, because it adds a provider in `App.tsx`.
- **T63 follows T62b.** Both touch `RunBoardPage.tsx` and the preview components.
- **Worktrees are fully isolated, e2e included.** The e2e helper spawns `python3 -m education_pipeline.daemon` with `cwd` set to the checkout root (`web/e2e/helpers/daemon.ts:48-49`), so each worktree's e2e runs that worktree's Python.

## Decisions settled at open

### T60

1. **Error boundary: one component, two placements.**
   - `web/src/components/ErrorBoundary.tsx` is a class component with `resetKey` and `fallback(error, reset)` props.
   - **Route level.** It wraps `<Routes>` (`App.tsx:42-51`) with `resetKey={location.pathname}`. The rail (brand, nav, `GlobalJobActivity`) and the build banner stay outside it and usable, and navigating away clears the error.
   - **Route fallback.** It is `role="alert"`, with a heading, the error message inside a `<details>`, a "Try again" button that clears the boundary and re-renders the route, and a "Back to the library" link.
   - **App level.** The same component wraps `<App/>` in `main.tsx` as a last resort, with a "Reload the cockpit" button, for a throw in the rail itself.
   - **Out of scope.** Event-handler and async errors, which React boundaries never see. `ErrorNotice` already covers API failures.
2. **Theme: three states and no matchMedia.**
   - A native `<select aria-label="Theme">` in the rail footer offers "Match system" (the default), "Light" and "Dark".
   - **Storage.** An explicit choice is stored in localStorage `ep.theme` as `light` or `dark` and stamped on `document.documentElement.dataset.theme`. "Match system" removes both.
   - **Why no listener.** The existing CSS already does the rest: `:root[data-theme="dark"]` (`styles.css:58-79`), and the system block guarded by `:root:not([data-theme="light"])` (`styles.css:82-105`). So the cockpit needs no `matchMedia` listener and never duplicates a token.
   - **Timing.** The stored choice is applied synchronously in `main.tsx` before the first render.
   - **Failure handling.** Storage access never throws: if storage is blocked, the choice holds for the session. There is no cross-tab sync.
3. **Reducer: no behaviour change.**
   - `web/src/lib/newRunWizard.ts` exports a pure `wizardReducer`, `initWizardState(draft)` and `wizardDraft(state)`, which is the value `saveDraft` persists.
   - **What moves.** The 17 form and lifecycle `useState`s move into it: `initialDraft`, the restore note, `step`, `profileId`, `mode`, the six field states, `toml`, the blueprint choice, the time budget, `createdId`, `attached`, `creating` and `createError`.
   - **What stays.** The five remote-data states stay `useState`: `blueprints`, `blueprintsError`, `restoringBlueprints`, `plan` and `planError`.
   - The draft format (`DRAFT_VERSION` 1) does not change.
   - **The no-behaviour-change proof** is that `NewRunPage.test.tsx`, `newRunDraft.test.ts`, `new-run.spec.ts` and `blueprints.spec.ts` pass with zero edits.

### T61

4. **Key map.** Single keys, no modifiers.

   | Key | Action |
   | --- | --- |
   | `?` | Open or close the shortcuts overlay. Shift is allowed for this key only. |
   | `/` | Focus "Filter courses" (`TopicListPage.tsx:200-205`). From any other page it navigates to the library first. |
   | `n` | Open the stage the run's `next_action.stage` names. Run board and stage viewer only. |
   | `r` | Open the next course whose `run.next_action.action === "approve"`. The search starts after the current course, in library order, and wraps. It lands on the approve deep link (`?tab=response`, as `TopicListPage.tsx:84-90` builds it). When no course needs review, a polite live region says "No course needs review". |
   | `a` | Move focus to the page's primary approve button (`PrimaryAction.tsx:205` or `StageViewerPage.tsx:233`). It never activates the button. |
   | Escape | Close the overlay and restore focus. |

5. **Conflict rules.**
   - A key is ignored when Ctrl, Meta or Alt is held, so browser and OS shortcuts always win.
   - A key is ignored during IME composition, when the event was already `defaultPrevented`, and when the target is editable (input, textarea, select or contentEditable).
   - While any other modal dialog is open, every key is ignored. While the overlay is open, only `?` and Escape act.
   - **←/→ are not bound.** They belong to the exported guide (`runtime.js:2309-2330`), whose key events stay inside its sandboxed frame (`GuidePreviewFrame.tsx:84-95`), so the two maps cannot collide.
   - `/` means "go to search or navigation" in both the cockpit and the guide.
   - A handled key calls `preventDefault`, which also stops Firefox quick-find on `/`.
6. **Approving by keyboard takes two keys: `a`, then Enter.** Approval is a deliberate judgment gate, so a stray keystroke must never approve.
7. **WCAG 2.1.4 (single-character shortcuts).**
   - The overlay has a "Single-key shortcuts" checkbox, stored in localStorage `ep.shortcuts` (`off` when disabled).
   - A "Keyboard shortcuts" button in the rail footer opens the overlay even when shortcuts are off, so they can always be turned back on.
   - The overlay is `role="dialog"` with `aria-modal="true"` and an accessible name. Focus moves into it on open and is restored on close.
8. **Shape.**
   - One document-level `keydown` listener is installed by a `ShortcutsProvider` at App level.
   - Pages register their page-scoped handlers (`n` and `a`) through a hook.
   - The decision "which action does this key event mean here" is a pure function in `web/src/lib/shortcuts.ts`, so unit tests can drive it without a DOM.

### T62

9. **Transport and auth.**
   - `GET /v1/events` streams `text/event-stream` behind the same Host check and `_authed` `X-EP-Token` guard as every `/v1` route (`server.py:592,598,718-733`).
   - The cockpit reads it with `fetch` and a `ReadableStream`, sending the header, instead of `EventSource`, which cannot send custom headers.
   - **No query-string token.** It would reach access logs, history and the dev proxy's logs.
   - **No cookie.** It would be a second credential, which every write route would then have to reason about for CSRF.
   - Exactly one auth rule stays.
10. **Events are notices, not payloads.**
    - `hello` is sent on connect.
    - `change` carries `{"kind":"run","topic":"<id>"}`, `{"kind":"jobs"}` or `{"kind":"topics"}`. `topics` covers the topic list, profiles and the model plan.
    - Heartbeats are SSE comment lines.
    - The client refetches over the existing routes, so the stream never carries course content.
11. **Change source: a stat-only scan.** A daemon-wide hub computes a fingerprint from `stat` calls only (no reads, parses or validation). It runs while at least one stream is open and stops when none are. The CLI writes the workspace directly (`cli.py:120`), and a bus inside the daemon would miss those writes. `JobStore.save` (`jobs.py:212`) may add an immediate nudge, but correctness rests on the scan.
12. **Backpressure and thread cost.** `ThreadingHTTPServer` spends one thread per open stream, and there is no cap (`server.py:552`).
    - **Pending notices.** Each subscriber holds a pending set keyed by notice. Coalescing is lossless because notices are idempotent.
    - **Stream cap.** Concurrent streams have a fixed limit. Past it, the route answers 503 with the standard error envelope, and that client polls.
    - **Dead peers.** A heartbeat surfaces dead peers within one interval. Writes use the existing 30 s socket timeout (`server.py:74`).
    - **Lifetime.** A stream has a maximum lifetime, after which the client reconnects.
    - **Shutdown.** The hub wakes and releases every stream on daemon shutdown.
    - The numbers are set by the design note and its review.
13. **Fallback.**
    - While the stream is down (refused, 503, network error or unsupported), every poller runs exactly as today.
    - While it is up, the pollers stop. Each notice then costs at most one refetch per mounted resource that the notice names.
    - Every (re)connect triggers one resync.
    - `JobLogView`'s 1 s log tail stays as it is. A log tail is not a change notice.
14. **Split up front.** T62 lands as T62a (daemon) and T62b (cockpit), each with its own red and green commits. It is size L, and the two halves share only the wire format.

### T63

15. **Message schema.**
    - **Frame → cockpit:** `{"type":"education-pipeline:preview-position","id":"<section id>","initial":<bool>}`. It is posted on every section change, with `initial` true for the boot position. It is posted only when `data-guide-mode="preview"`.
    - **Cockpit → frame:** `{"type":"education-pipeline:preview-show","id":"<section id>"}`.
    - **Validation.** Key sets are exact, as the evidence message's are (`runtime.js:979-980`). Ids must match `GUIDE_ID_PATTERN`, and an id that is not a section of the current guide is ignored.
16. **Origin.**
    - The frame is a `sandbox="allow-scripts"` srcDoc with an opaque origin. Its `event.origin` is `"null"`, and no targetOrigin except `"*"` can address it (the evidence bridge already posts with `"*"`, `GuidePreviewFrame.tsx:42-53`).
    - **Identity is checked by source.** The cockpit accepts a message only when `event.source === iframe.contentWindow`. The runtime accepts one only when `event.source === window.parent`, as its evidence listener does (`runtime.js:978`).
    - **Why `"*"` is acceptable.** Both payloads carry only a section id the cockpit already holds.
    - An exported guide never posts.
17. **Mount.**
    - Mutations stop remounting the preview. The `key={previewGeneration}` remount goes (`RunBoardPage.tsx:80-85,120`); a mutation now only refetches.
    - The iframe stays keyed by its HTML, so it reloads only when the rendered guide changes.
    - The run board remembers the last non-initial section the frame reported, and it holds that in page state, not in a module global. When an `initial` report differs from the remembered section, the board posts `preview-show`.
18. **No runtime version bump.** `RUNTIME_VERSION` versions the document and progress-store contract, and T63 does not change it. The new messages are inert outside preview mode. The example export is rebuilt.

### Phase

19. **Branches.**
    - Thread branches `p6/t6x-<slug>` merge into the phase branch `claude/gifted-davinci-slrab7` with `--no-ff`.
    - Only the phase branch is pushed, after each thread.
    - Red commits reach it through the merges.
20. **Build and e2e never overlap in one checkout.** The e2e daemon serves `web/dist` (`web/e2e/helpers/daemon.ts:9`), so `npm run build` during a Playwright run breaks the run. Each worktree builds its own `dist`.

## Anchors at open

- **App shell:**
  - `web/src/App.tsx:15-39` (rail), `:40-51` (`main`, banner, `Routes`).
  - `web/src/main.tsx:8` (`BrowserRouter` with v7 future flags).
  - react-router-dom ^6.26.
- **Theme:**
  - `web/src/styles.css:11-56` (light), `:58-79` (forced dark), `:82-105` (system dark).
  - The only theme writer today is the guide runtime's `applyTheme` (`runtime.js:2236-2240`).
- **Storage keys in use:**
  - `ep.welcome.dismissed` (`WelcomePanel.tsx:6`).
  - `ep-cockpit-build-dismissed` (`BuildFreshnessBanner.tsx:5`).
  - sessionStorage `ep.newrun.draft` (`newRunDraft.ts:8`).
- **Wizard:**
  - `web/src/pages/NewRunPage.tsx:46-99`: 22 `useState`.
  - `NewRunPage.tsx:64-69`: 6 `useId`.
  - `NewRunPage.tsx:162`: the ref `blueprintsGeneration`.
  - Effects at `:109-118` (persist, deps `:103-107`), `:124-137` and `:201-208`.
  - `newRunDraft.ts:10,46-76,78-110`.
- **Keys:**
  - The only cockpit key handler today is `InfoTip.tsx:26-28`.
  - Approve buttons: `PrimaryAction.tsx:181-222`, `StageViewerPage.tsx:233,255` (gates at `:130-132` and `:150-153`).
  - Next action: `types.ts:8-25` (`NextAction`) and `:255-265` (`TopicSummary`).
  - Labels: `labels.ts:10,22`.
  - Filter input: `TopicListPage.tsx:200-205`.
  - Guide keys: `runtime.js:2302-2330,2367`.
- **Daemon:**
  - `server.py:552` (`_LoopbackHTTPServer`), `:581` (HTTP/1.1), `:74,574` (30 s handler timeout).
  - Checks: `:592` `_host_ok`, `:598` `compare_digest`, `:600-606` `_send`.
  - Error handling: `:625-659` `_last_resort`, `:661` `_guard`.
  - Routing: `:718-733` GET dispatch, `:722-728` `/v1/session`, `:766-918` GET routes, `:756-762` static CSP (`connect-src 'self'`).
  - Lifecycle: `daemon/__init__.py:179,186,195-206`.
  - Jobs: `jobs.py:212` (`JobStore.save`, every job write), `:868,987` (`on_finished`).
  - CLI writes: `cli.py:120` (`_guarded_mutation`, out of process).
- **Pollers:**

  | Call site | Endpoint | Interval |
  | --- | --- | --- |
  | `RunBoardPage.tsx:163` | `/v1/runs/{t}` | 5 s |
  | `RunBoardPage.tsx:171` | `/v1/jobs?topic=` | 2 s |
  | `RunBoardPage.tsx:70` | `/v1/runs/{t}/personalization` | 5 s |
  | `GlobalJobActivity.tsx:55` | `/v1/jobs` | 5 s |
  | `GlobalJobActivity.tsx:56` | `/v1/topics` | 10 s |
  | `TopicListPage.tsx:99` | `/v1/topics` | 10 s |
  | `TopicListPage.tsx:100`, `NewRunPage.tsx:121`, `ProfilesPage.tsx:8` | `/v1/profiles` | 30 s |
  | `StageViewerPage.tsx:71` | `/v1/runs/{t}/stages/{s}` | 5 s |
  | `StageViewerPage.tsx:72` | `/v1/runs/{t}` | 5 s |
  | `ModuleRepairControl.tsx:37` | `/v1/runs/{t}/repair/modules` | 10 s |

  `usePolling.ts:18,69-75` is the hook they share. `JobLogView.tsx:49-63` runs its own 1 s tail.
- **Client:**
  - `client.ts:86-106` (token from `GET /v1/session`, memoized), `:117-121` (header), `:69-82` (unreachable).
  - `vite.config.ts:6-16` (proxy reads the port only).
- **Preview:**
  - `GuidePreviewFrame.tsx:42-53` (evidence post, `"*"`), `:84-95` (sandbox, srcDoc, keyed by HTML).
  - `RunBoardPage.tsx:80-85,120,180-183,260` (the remount chain).
  - `runtime.js:967-996` (listener), `:752-838` (`Nav`, `show`), `:120-130` (storage probe fails in the sandbox), `:944-949` (boot restore).
- **Tests:**
  - `tests/test_server.py:50` (`_start_server`), `:110,118,182` (fixtures), `:194,336,818` (HTTP helpers), `:350,356,396,403` (auth and Host).
  - `tests/test_worker_safety.py:290` (a raw socket).
  - `web/e2e/new-run.spec.ts:43,94,106`, `web/e2e/blueprints.spec.ts:86`.
  - `web/e2e/guide-runtime.spec.ts:93-229` (bridge) and `:695-744` (keys).
  - `web/e2e/personalization.spec.ts:328-339` (cockpit iframe).
  - `web/src/test/setup.ts` (jest-dom only; no `matchMedia` mock).

## Closeout log

(One entry per thread as it lands: commits, diff size, red/green counts, mutations, gates, accepted limitations.)

- **T60** landed in a parallel worktree (red `c9af03d`, green `05b6835`, tests `d75d6fd`, merged `1bbc316`).
  - **Changes:** 10 production files, +528 / −109.
    - New: `ErrorBoundary.tsx`, `RouteErrorFallback.tsx`, `AppErrorFallback.tsx`, `ThemeToggle.tsx`, `lib/theme.ts` and `lib/newRunWizard.ts`.
    - `App.tsx` wraps `<Routes>` in the boundary keyed by pathname.
    - `main.tsx` stamps the stored theme before `createRoot` and wraps `<App/>` in the last-resort boundary.
    - `NewRunPage.tsx` goes from 22 `useState` to one `useReducer` plus the five remote-data states.
    - `styles.css` +40, appended.
  - **Tests.**
    - **Red:** 98 vitest cases and 1 e2e case, across 9 files. They fail on missing modules, missing elements, or the source guard counting 22 `useState` calls against at most 5. The red writer checked the tests against a throwaway implementation, which passed all 98 and was caught by 8 deliberate breakages.
    - **Green:** it edited no tests.
    - **Characterization addendum:** a separate test writer added 4 cases, because the implementer reported that three behaviour-changing mutants passed every test. They pin `startOver` clearing a pasted TOML draft back to "Describe it", and landing on the blueprint step after a double-click or a Back-during-load. The page's original step change was absolute. All 4 pass against the pre-refactor page (`c9af03d`) too, so the refactor's "no behaviour change" claim rests on evidence.
  - **Mutations:** 8, all caught.
    - Green: the boundary ignoring `resetKey` (3 failures), "system" stamping light (5), `startOver` keeping the title (3), `createFailure` dropping the retry markers (2), and `main.tsx` skipping the theme (1).
    - Addendum: `startOver` keeping `toml`, keeping `mode`, and a relative `next` in place of `goToStep("blueprint")`.
  - **Gates on the merge:** pytest 2619 passed, 1 skipped; `--help` clean; build clean; vitest 738; e2e `cockpit-shell`, `new-run`, `blueprints` and `smoke` 10/10. The implementer also ran the full Playwright suite in the worktree: 163/163.
  - **Accepted:** see the ledger (the theme select is hidden below 48rem, a possible light flash before the script runs, no cross-tab sync, and render errors only).
- **T61** landed in a parallel worktree (red `a16fb9c`, green `6c4578a`, merged `bbaf70f`).
  - **Changes:** 8 production files, +658 / −27.
    - `lib/shortcuts.ts` (pure `resolveShortcut`, `nextCourseNeedingReview`, `nextActionHref`, `compareLibraryOrder`).
    - `components/ShortcutsProvider.tsx` (one bubble-phase listener, `usePageShortcut`, the overlay, the rail button and the live region).
    - Page registrations: `a` in `PrimaryAction.tsx` and `StageViewerPage.tsx`, `n` in `RunBoardPage.tsx` and `StageViewerPage.tsx`.
    - `TopicListPage.tsx` now imports the shared deep-link and library-order helpers instead of keeping local copies. This is pure code motion.
    - `styles.css` +86, appended.
  - **Tests.**
    - **Red:** 72 cases (41 resolver, 10 provider, 19 App, 2 e2e). Each "does nothing" case also proves the key acts somewhere else, so none of them pass vacuously. The red writer checked them against a throwaway implementation, and 5 deliberate breakages were caught.
    - **Green:** it edited no tests.
  - **Mutations:** 5, all caught: dropping the editable-target check (8 failures), `a` clicking on the run board, `a` clicking on the stage viewer, ignoring the enabled flag (4), and a capture-phase listener (1).
  - **Merge:** `App.tsx` and `styles.css` conflicted with T60, as planned. The resolution keeps both import sets and both appended CSS blocks. The shortcuts button goes after T60's rail-footer `div`. `useLocation` moves into the new inner `AppShell`, where the route boundary now renders.
  - **Gates on the merge:** pytest 2619 passed, 1 skipped; `--help` clean; build clean; vitest 808; e2e `keyboard`, `cockpit-shell`, `smoke`, `approve-continue`, `library`, `editor` and `new-run` 15/15. axe is clean with the overlay open.
  - **Found on the way:** `GlobalJobActivity.test.tsx:287` polls every 30 ms on real timers and waits for four calls inside `waitFor`'s 1 s default. It failed once while four agents were loading the machine, and passed alone. The root cause is a count that depends on wall-clock throughput. The fix is fake-timer advancement, not a longer timeout, and it is assigned to T62b's red step, which rewrites that component's polling.
  - **Unreproduced:** one pytest failure in T61's worktree under the same load was not captured, and T61 changes no Python. Three later full runs were clean. Every gate run since then uses `-rf`, so a recurrence will be named.
- **T62 design** (`a7c0774` draft, `2359ee4` reviewed). An Opus writer drafted `docs/superpowers/specs/2026-09-27-events-endpoint-design.md` from decisions 9–14, and a second Opus reviewed it adversarially against `server.py`, `read_api.py` and `jobs.py`, editing in place (33 marks and a review record).
  - **Blocker 1, fixed:** the budget test as written could never pass, because the note's own 45 s idle watchdog would restart the stream. The budget test now sends a keepalive every 15 s.
  - **Blocker 2, fixed:** skipping job directories that the nudge had already announced could drop a later non-save change under `jobs/`, and it made correctness depend on the nudge. The scan now stats every `job.json`.
  - **Should-fixes:** topic edits also notify `run{t}`, because run status reads the topic file live. The scanner re-checks its generation under `_scan_lock`. The hub lock is a written leaf-lock rule. The handler's `try` opens right after `subscribe`. Fingerprint tests must be portable to the macOS and Windows CI.
  - **Manager rulings:** keep `MAX_STREAMS = 4`, which is under the browser's 6-per-host limit; a hidden tab drops its stream; the parallelism figure may lag a plan edit (ledger).
- **T62a** landed in a parallel worktree (red `037a972`, green `22d5866`, merged `651a151`).
  - **Changes:** 6 non-test files, +534.
    - New module `daemon/events.py` (456 lines): `EventHub`, the pure `workspace_fingerprint` and `diff_fingerprints`, `encode_frame` and `pump`.
    - `server.py` +50: `_events_stream` as the first arm of `_api_get_routes`, so it is reached only after `_host_ok` and `_authed`, with the 503 `events_capacity` envelope at the cap.
    - `daemon/__init__.py` +9: the hub is wired, and `events.close()` runs first on shutdown.
    - `jobs.py` +11: `JobStore.on_saved`. A failing hook logs its type and never fails a save.
    - The `events_capacity` entry in `errors.py` and a row in `docs/troubleshooting.md`, which the existing catalog and doc tests require. The note had missed these two files.
  - **Values:** `MAX_STREAMS` 4, heartbeat 15 s, lifetime 300 s, a 1 s peer-liveness check (a per-stream `selectors` poll, which avoids `select`'s 1024-descriptor limit), a scan every 1 s stretched to 10× the last pass, and `TCP_NODELAY` on stream sockets only.
  - **Locks:** `_scan_lock` is always taken before `_lock`. `_lock` is a leaf: no I/O, logging or other lock under it. The manager checked that the scan's filesystem pass runs outside `_lock`.
  - **Tests.**
    - **Red:** 48 cases in `tests/test_events.py` and `tests/test_events_endpoint.py`. 45 failed on import and 3 on missing hooks, routes or catalog. Every auth-rejection case (bad Host, missing or wrong token, query-string token, other methods, absolute form) asserts that `subscribe` is never called, so an unauthenticated connection never takes a slot or a thread.
    - The red writer ran them against a throwaway prototype out of tree: 11 mutations were caught, and the files ran 8 times in a row plus 6 concurrent runs under CPU load.
    - **Correction to the review record:** `//v1/events` is collapsed to `/v1/events` by the stdlib, rather than getting a 404. The test asserts only that it never streams without the token.
  - **Mutations (green):** 5, all caught.
    - Route before `_authed`: 2 tests, which time out because the unauthenticated client gets a live stream.
    - Coalescing dropped: 1.
    - `unsubscribe` outside `finally`: 3.
    - `job.json` not stat'ed: 1.
    - `events.close()` removed from `serve()`: 2.
  - **Evidence:** the two new files passed 5 runs in a row and 4 concurrent copies.
  - **Curl smoke on a real daemon:** 401 without a token or with a wrong one. With the token, 200 with the three headers and a byte-exact `hello`. An append to `topics/demo.toml` sent `topics`, then `run{demo}`.
  - **Gates on the merge:** pytest 2667 passed, 1 skipped; `--help` clean; build clean; vitest 808; e2e `smoke`, `approve-continue` and `full-run` 7/7.
- **T62b** landed in a parallel worktree (flake fix `18191e4`, red `2aba908`, phase merged in at `e3db87c`, green `9b10ace`, fix red `b6cdd93`, fix green `aeaac55`, merged `03dafac`).
  - **Changes:** 11 non-test files, +423 / −21.
    - New `hooks/useEvents.tsx` (292 lines). It holds `createSseParser`, `EventsProvider` (the reconnect table, the 15 s pre-hello and 3× heartbeat idle watchdogs, hidden-tab drop and `<html data-events>`) and `useEvents`.
    - `usePolling.ts` +84 / −6: an optional `{events}` filter, held in a ref. While the stream is up the chain stops. The poller then fetches once per `hello` and once per matching notice, with one fetch in flight and one queued, and a failed fetch re-arms the interval until one succeeds.
    - `client.ts` +20: `openEventStream`, which sends the memoized `X-EP-Token` and clears the memo only on 401.
    - `App.tsx` gains `EventsProvider`, and seven call sites each change by 1–6 lines.
    - `JobLogView` is unchanged.
  - **Flake fixed at the source first.** `GlobalJobActivity.test.tsx` "forgets a job the payload drops" now advances fake timers one 30 ms interval at a time. Under 4 and 8 CPU hogs it failed 1/20 and 2/20 before the change, and 0/20 at both loads after it.
  - **Tests.**
    - **Red:** 120 cases.
      - `useEvents.test.tsx` 45 (the parser, including CRLF split across chunks; the reconnect table with exact jittered delays; the watchdogs; hidden tabs).
      - `usePolling.events.test.tsx` 14.
      - `RunBoardPage.events.test.tsx` 9 (the budget test).
      - `callSites.events.test.tsx` 40 (8 call sites × idle and 4 notice kinds).
      - `App.events.test.tsx` 3 and `client.test.ts` +9.
      - `e2e/events.spec.ts`: a CLI-side change updates an open board, with the counting window starting after the resync lands.
    - Existing assertions were not changed. The only edit to an existing test is a never-settling `openEventStream` stub in `AppShell.test.tsx`'s module mock.
    - The red writer ran the cases against a throwaway implementation: 33 mutants were each caught.
  - **Mutations (green):** 6, all caught: polling while up, no resync on `hello`, a 401 keeping the token memo, the filter compared by identity, no backoff reset after a long-lived stream, and a chunk-final CR not swallowing the next LF.
  - **Measured on a real daemon:** a run board idle for 30 s made **0** `/v1` requests with the stream up. With `/v1/events` forced to 404 it made **29** (`/v1/jobs` 20, `/v1/runs/{t}` 6, `/v1/topics` 3).
  - **Bug found on the way, fixed red/green.** Rail toasts were unreadable in the light theme: `#eef1f6` text on white, contrast 1.13. `.app-rail` sets a light text colour for the dark rail, and `.toast` set a white background without resetting `color`.
    - The bug predates the phase. It surfaced as `personalization.spec.ts:382` failing axe about 1 run in 8, because the job-save nudge lets the rail catch a short audit job while it is active and toast it. The 5 s poll almost never did.
    - At the default 720 px viewport, axe marks the toast "incomplete" rather than failing it, which is why the failure was intermittent.
    - **Red:** `cockpit-shell.spec.ts:146` raises a success and an error toast deterministically. It routes `/v1/events` to 404 and serves `/v1/jobs` from a test flag. At 1280×1600 it asserts that every node gets an axe verdict and that there are no contrast violations: 10/10 failed in light and 10/10 passed in dark.
    - **Green:** one line, `color: var(--ep-color-text)` inside `.toast`. 3 mutations were caught, `cockpit-shell` passed 30/30, and `personalization` passed 30/30 (it had failed about 1 in 8).
  - **Gates on the merge:** pytest 2667 passed, 1 skipped; `--help` clean; build clean; vitest 928; **full Playwright 168/168** in 1.6 min (3.8 min at baseline, on a contended run).
- **T63** landed in a worktree after T62b (red `3704b40`, green `34c78f9`, tests `7ab0329`, merged `26126b7`).
  - **Manager rulings at red:**
    1. The results page stays out of the bridge. Its fallback id `results_page` fails `GUIDE_ID_PATTERN`, and it is not a guide section.
    2. The preview stays refreshed by mutations, not by events notices. T62b pins it as a resource that notices do not drive.
  - **Changes:** 4 production files, +163 / −11, plus the regenerated example export (`guide.html` and `guide.report.json`).
    - **`runtime.js`** (+44 net, to 2425 lines). `Nav.show` reports a change to a different real section. `isSection` and `watchSections` are new. `installPreviewPositionBridge` does nothing outside `data-guide-mode="preview"`. It installs its preview-show listener before the boot report, with the evidence listener's guard style: source `window.parent`, the exact key set `{id,type}`, the id pattern, and a real section. `RUNTIME_VERSION` stays 1.2.
    - **`GuidePreviewFrame.tsx`.** A layout-effect listener accepts only `event.source === iframe.contentWindow`, with a non-null `contentWindow`. It sends `onSectionChange` for reports that are not initial. It answers an initial report that differs from `restoreSection` with preview-show and `"*"`. The iframe is still keyed by its HTML.
    - **`CanonicalGuidePreview.tsx`** refetches on `refreshGeneration` without clearing the document.
    - **`RunBoardPage.tsx`** drops the `key={previewGeneration}` remount. The remembered section is state in `RunBoardForTopic`.
  - **Tests.**
    - **Red:** 10 vitest cases, 4 runtime e2e cases in `guide-runtime.spec.ts` and 2 cockpit e2e cases in the new `preview-bridge.spec.ts`. Each negative case is paired with a positive control, so no case passes vacuously.
    - The cockpit e2e keeps the preview through "Run final validation" and "Finalize". A revised repair is approved out of process, which changes the HTML, and the frame restores to the reviewer's section.
    - The exported-guide guard covers the fixture export and the committed example.
    - **Characterization addendum:** 2 e2e cases pin ruling 1, which the implementer reported as unpinned (removing either gate passed every test). The results page, reached by either learner route, is never reported. A preview-show naming `results` is ignored, and a frame-side counter proves the page never became current, even briefly.
  - **Mutations:** 8, all caught.
    - Green (6): the frame's source check dropped, positions posted outside preview mode, the remount key restored, preview-show accepting any id inside a section, the runtime's `window.parent` check dropped, and the preview cleared on each refresh.
    - Addendum (2): the report's `isSection` gate removed, and preview-show's `isSection` gate removed.
  - **Repeats:** `preview-bridge.spec.ts` 20/20, the runtime bridge tests 100/100, and the addendum 20/20.
  - **Gates on the merge:** pytest 2667 passed, 1 skipped; `--help` clean; `build_example.py` leaves the tree clean; build clean; vitest 938; **full Playwright 176/176**.

## Phase closeout

Five map threads (T62 split into T62a and T62b), plus the T62 design note and its review, one found-bug fix (rail toast contrast), one flaky test fixed at its source, and two characterization addenda (T60, T63), on `claude/gifted-davinci-slrab7`.

- T60 and T61 ran in parallel worktrees and merged in that order. `App.tsx` and `styles.css` conflicted as planned.
- T62a (Python only) ran in a worktree alongside the T62b red step. The phase branch was merged into T62b before its green step, so its e2e ran against the real endpoint.
- T63 followed T62b.

Final gate on the branch head (`26126b7`):

| Gate | Result |
| --- | --- |
| pytest (Python 3.11) | 2667 passed, 1 skipped (baseline 2619) |
| `python3 -m education_pipeline --help` | clean |
| `python3 scripts/build_example.py` | no diff |
| `npm run build` | clean |
| vitest | 938 (baseline 634) |
| Playwright full suite | 176/176 (baseline 162) |

The diff against `main` at `6675b40` is 66 files, +10376 / −181, most of it tests. Production code under `education_pipeline/` and `web/src` changed by +2292 / −165 across 30 files. `runtime.js` went from 2383 to 2425 lines.

Shape after the phase:

- **Resilience.** A route that throws shows a recoverable fallback while the rail keeps working. A throw in the rail itself gets a last-resort reload.
- **Theme.** The cockpit has its own theme choice (system, light or dark), stamped before first render and kept per browser.
- **Keyboard.** `?`, `/`, `n`, `r` and `a`, with the documented conflict rules. Approving by keyboard takes two keys. An on/off switch meets WCAG 2.1.4.
- **Events.** One authenticated `text/event-stream` per tab replaces the pollers while it is up. A board idle for 30 s makes 0 requests, against 29 with polling. Polling remains the fallback. The stream carries notices only, never course content. Change detection sees CLI writes from other processes.
- **Preview.** The preview reports the reviewer's section, survives unrelated refreshes without reloading, and restores the section when the guide HTML changes.

Departures and accepted limitations are in the audit ledger.

