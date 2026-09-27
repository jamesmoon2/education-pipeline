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
| T60 | Error boundary, theme toggle, wizard reducer | A route-level boundary keeps the rail usable and offers "Try again" and "Back to the library". An app-level boundary offers "Reload". A theme select (system, light or dark) stamps or clears `data-theme` and persists per browser. `NewRunPage` form and lifecycle state live in one pure reducer, and the existing NewRunPage unit tests and the new-run and blueprints e2e pass with zero edits. There are unit tests for each part and one e2e case for theme persistence and axe in dark. | - [ ] |
| T61 | Keyboard shortcuts | The key map in decision 4 works, under the rules in decisions 5–8. A `?` overlay lists the keys and carries an on/off switch. A new `keyboard.spec.ts` walks library → course → stage by keyboard, proves typing in inputs triggers nothing, proves `a` never approves, and runs axe with the overlay open. The pure key resolver has unit tests. | - [ ] |
| T62a | Events endpoint (daemon) | `GET /v1/events` behaves as decisions 9–12 and the design note describe. Server tests cover Host and token rejection, the `hello` and `change` frames, a CLI-style out-of-process write being noticed, coalescing, the stream cap, heartbeat and lifetime, and shutdown releasing streams. | - [ ] |
| T62b | Events in the cockpit | One stream per tab, owned at App level. A `useEvents` hook and `usePolling` integration mean pollers stop while the stream is up and resume when it is down. A vitest proves that one change notice costs the board at most one request per mounted resource it names, and zero requests when idle. e2e: a board updates after a CLI-side change with the stream up. | - [ ] |
| T63 | Preview bridge, both ways | The runtime reports the current section in preview mode only. The run board stops remounting the preview on unrelated mutations, and it restores the reviewer's section when the guide HTML does change. The schema and origin rules are decisions 15–16. e2e covers the round trip in the real cockpit iframe and proves an exported guide posts nothing. The example export is rebuilt. | - [ ] |

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
