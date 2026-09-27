# Events Endpoint (`GET /v1/events`) — Design

- **Date:** 2026-09-27
- **Status:** Draft for adversarial review (plan: T62 is reviewed before any code)
- **Plan:** [`../plans/2026-09-27-phase-6-cockpit.md`](../plans/2026-09-27-phase-6-cockpit.md), threads T62a (daemon) and T62b (cockpit), binding decisions 9–14 and 20
- **Anchors:** verified at `ee671cf` (branch `claude/gifted-davinci-slrab7`)

## Summary

One authenticated `text/event-stream` route tells the cockpit *that* something changed, never *what*. A daemon-wide hub runs a stat-only scan of the workspace while at least one stream is open. It publishes idempotent notices (`run` per topic, `jobs`, `topics`) into a coalescing pending set per subscriber. While the stream is up, pollers stop and refetch only on a notice that names them. While it is down, they poll exactly as today. No engine behaviour or existing route changes.

## 1. Wire format

The stream is UTF-8 with LF line endings. Each `data:` line holds one JSON object, written with `json.dumps(..., sort_keys=True, separators=(",", ":"))`, so it is always a single line. *Review:* `ensure_ascii` stays at its default `True`, so every control character, CR and LF included, is escaped. Frame injection would have to get past two layers: the escaping, and the `is_artifact_id` gate on every topic id (`workspace.py:22`, which `fullmatch`es `[A-Za-z0-9][A-Za-z0-9._-]*`, so no CR, LF or `:` ever reaches a frame). `job_saved(t)` applies the same gate. There are no `id:` or `retry:` fields, because a reconnect resyncs instead of resuming.

```
event: hello
data: {"heartbeat_seconds":15,"lifetime_seconds":300,"protocol":1}

event: change
data: {"kind":"run","topic":"intro-statistics"}

event: change
data: {"kind":"jobs"}

event: change
data: {"kind":"topics"}

: keepalive

```

`hello` is always the first frame. It is written after the subscriber is registered and the baseline fingerprint exists (§4). A client that gets `protocol != 1` treats the stream as unsupported. One wake may write several `change` frames in a single `sendall`, ordered `topics`, then `jobs`, then `run` by topic id.

| On-disk change (relative to the workspace) | Notices |
| --- | --- |
| Anything under `runs/<t>/` except `runs/<t>/jobs/`, including `runs/<t>/` appearing or vanishing | `run{t}` |
| A job directory under `runs/<t>/jobs/` added, removed, or its record replaced (`JobStore.save`, `jobs.py:212`) | `jobs` **and** `run{t}` |
| `runs/<t>/inputs/profile.toml` (attach) | `run{t}` **and** `topics` |
| `topics/<t>.toml` added, removed or changed | `topics` **and** `run{t}` |
| `topics/`, `profiles/`, `config/` (the dirs and their other direct children) | `topics` |
| `runs/*/jobs/*/output.log` appends, `.education-pipeline/`, `queue/` | none |

- **Job pairing.** Run status embeds the job-derived fields `continuation`, `draft_progress` and `cost` (`read_api.py:488-493`), and `{"kind":"jobs"}` carries no topic (decision 10). So each job change also sends `run{t}`, which carries the topic.
- **Attach pairing.** `/v1/profiles` counts run snapshots (`read_api.py:197`, `workspace.py:340-355`), so an attach also sends `topics`.
- **Topic pairing.** *Review:* added. `/v1/runs/{t}` reads the live topic TOML, not only the run tree: `_calibration_context` loads `topics/<t>.toml` for its time budget (`runs_reports.py:950-967`), and that context feeds `_status_final_report` (`runs.py:880`, `runs_reports.py:803-852`) and the `gate_result` that `_validation_summary` runs when a waiver set exists. A topic edit (`PUT /v1/topics/{t}`, CLI or hand edit) must therefore reach the `{run: t}` pollers, and `topics` alone does not name them. `<t>` is the file stem, and it must pass `is_artifact_id`.
- **Plan edits.** *Review:* `draft_progress.parallelism` in `/v1/runs/{t}` is read from `config/model-plan.toml` (`read_api.py:600-628`), but a plan edit sends only `topics`. The worker reads `parallelism` only at start (`daemon/__init__.py:162-164`), so the board's figure lags until the next `run{t}` or the lifetime resync. This is accepted (§8.9), because a `run` notice for every topic on each plan edit costs more than it is worth.
- **Topic ids.** `<t>` is only ever a `runs/` child directory whose name passes `workspace.is_artifact_id` (`workspace.py:624`). Other names are ignored.
- **Archive.** Archiving is a manifest flag flip (`runs.py:988-1016`), so it reports as `run{t}`.
- **Deletion.** A deleted run directory reports `run{t}` once, and the refetch then gets the existing 404. A deleted topic TOML reports `topics`.

## 2. HTTP framing (`protocol_version = "HTTP/1.1"`, `server.py:581`)

- **Route.** `if self.path == "/v1/events": return self._events_stream()` is the first line of `_api_get_routes` (`server.py:766`). The match is exact, so a query string gets the ordinary 404.
- **Headers.** `200` with `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-store` and `Connection: close`. There is no `Content-Length` and no `Transfer-Encoding`.
- **Close-delimited, not chunked.**
  - A close-delimited body is valid HTTP/1.1 (RFC 9112 §6.3 item 8). A stream connection is never reused, so chunking would add an encoder and a terminal chunk for nothing.
  - `send_header("Connection", "close")` already sets `close_connection = True` (stdlib), and the method sets it again in `finally`.
  - After `do_GET` returns, `handle()` exits and `shutdown_request` closes the socket. EOF is the client's only end-of-stream signal.
- **Errors after the status line.** The `do_GET` arms for `NotFoundError` and `ConfigError` (`server.py:706-714`) would write a *second* status line. So once `send_response(200)` has run, `_events_stream` catches everything itself:
  - `OSError` (`BrokenPipeError`, `ConnectionResetError`, or `TimeoutError` from a blocked `sendall`) is a normal end and is not logged.
  - Anything else goes to `self._last_resort(exc)`. Because `_response_started` is set (`server.py:586-590,637`), that only logs the exception type.
- **Write timeout.** The existing 30 s `handler.timeout` (`server.py:74,574`) bounds every `sendall`. Idle waits happen on a `Condition`, never on the socket.
  - *Review, corrected:* a peer that stays connected but stops reading does **not** end its stream after 30 s. On loopback, the kernel buffers hold far more than one lifetime of frames (about 20 keepalives of 13 bytes, plus change frames of about 50 bytes each). So `sendall` never blocks, and the readability check does not see a silent reader. `LIFETIME_SECONDS` is the real bound: such a peer, which must hold the token, keeps one slot for at most 300 s. The 30 s timeout matters only when a buffer is actually full.
  - A client that half-closes its write side after the request (`shutdown(SHUT_WR)`) reads as gone and loses its stream within about 1 s. Browsers, Node's http client (Vite's proxy) and `http.client` never do this.
- **Over capacity.** The answer is `_error(503, "events_capacity", "event stream limit reached; poll instead")`, the standard envelope (`server.py:617-622`), on an ordinary keep-alive connection.

## 3. The fingerprint

`workspace_fingerprint(root) -> dict[str, tuple]` is pure.

- **Calls.** It uses only `os.scandir` and `DirEntry.stat(follow_symlinks=False)`, plus one `os.stat(…, follow_symlinks=False)` per `job.json` (*Review:* see `jobs:<t>`). It never opens, reads or parses a file. Directory listings are unavoidable, because they are how new topics and jobs are discovered.
- **Symlinks and races.** Symlinks are recorded, never followed. An entry that vanishes mid-scan is skipped, and its absence is then a change.
- **Values.** Each value is a sorted tuple of `(relpath, st_mtime_ns, st_size, st_ino)`.

| Key | Stat'ed | Why it catches the writes that matter |
| --- | --- | --- |
| `run:<t>` | `runs/<t>` and every dir and file below it, recursively, except the `jobs/` subtree | Every package write is `mkstemp` beside the target plus `os.replace` (`atomic_io.py:76,87`). That adds and renames directory entries, so the file gets a new inode and the parent directory's mtime moves. Stat'ing files, not only directories, also catches an in-place human edit of an existing response, which leaves the directory alone. |
| `jobs:<t>` | `runs/<t>/jobs/`, each job **directory** entry, and each job's `job.json` (one `os.stat`). `output.log` is never stat'ed. | `JobStore.save` is always atomic, so every save gives `job.json` a new inode and bumps its job dir's mtime. *Review:* `job.json` is stat'ed as well, because two saves inside one mtime tick leave the directory's `(mtime, size, ino)` unchanged. `JobRunner.execute` saves "running" and then the re-stamped provider back to back (`jobs.py:442-462`), so without it the scan could miss the second save. `output.log` appends change only that file, so the 1 s log tail never becomes a notice. |
| `attach:<t>` | `runs/<t>/inputs/profile.toml`, from the same walk | Profile attachment counts. |
| `topics` | `topics/`, `profiles/`, `config/` and their direct children | Hand edits of `model-plan.toml` are caught whether done in place or by replace. |
| `topic:<t>` | `topics/<t>.toml`, from the same listing | *Review:* added for the topic pairing (§1). |

`diff_fingerprints(old, new)` maps changed, added and removed keys to notices per §1. *Review:* the `announced_jobs` parameter and its skip are gone. See "Nudge".

- **Cost.** One pass is O(files and directories in the run trees + job directories and their `job.json` + topics/profiles/config children), with zero reads.
  - Measured in this container: 50 runs and 1,500 jobs (5,650 entries) took **23.6 ms** per pass.
  - *Review, re-measured:* on a synthetic workspace, stat'ing the 1,500 `job.json` files as well took a pass from 18 ms to 26 ms (6,950 entries).
  - For comparison, `GET /v1/topics` already walks every file of every run on each call (`runs.py:1018-1042`), and `GET /v1/jobs` parses every job record (`jobs.py:221-236`). The rail polls both of these today.
- **Interval.** `SCAN_INTERVAL_SECONDS = 1.0`. The next wait is `max(1.0, 10 × last pass)`, so scanning never uses more than 10 % of a core.
- **Start and stop.**
  - On 0→1 subscribers, `subscribe()` computes the baseline on the handler thread, under `_scan_lock`, *before* `hello`. It then bumps `_scan_gen` and starts the daemon thread `ep-events-scan` for that generation.
  - On 1→0 nothing is joined. The thread exits at its next wake, when it finds no subscribers or a newer generation. A quick 1→0→1 simply starts a fresh generation.
  - *Review:* a pass checks its generation (and `_closed`) **after** it takes `_scan_lock`, and exits if either is stale. A thread from the old generation can pass the check before a 0→1 `subscribe()` bumps the generation and then block on `_scan_lock`. Without this second check it would run one extra pass once the lock came free. That pass would be harmless, but the test for scanning only while subscribed would flake. The thread sleeps on a `Condition` or `Event` that `close()` signals, not in `time.sleep`.
- **Nudge.** `JobStore` gains `on_saved: Callable[[Job], None] | None = None`, like `Worker.on_finished` (`jobs.py:868`).
  - `save()` calls it after the replace, inside a `try/except` that logs only the exception type, so a hook can never fail a save.
  - `serve()` wires it to `hub.job_saved(t)`. That call publishes `jobs` and `run{t}` immediately, under `_lock` only and without any stat, so worker threads never block. On a closed hub, or for a `t` that fails `is_artifact_id`, it does nothing. This matters because `worker.stop()` can still save after `events.close()`.
  - *Review, changed:* the nudge is **latency only**. The `_announced` set, and the scan's skip of `jobs:<t>` for announced topics, are removed. Two reasons:
    1. The skip could lose a notice. Take a save for `t`, then the client's refetch, then a non-save change to `runs/<t>/jobs/` (a pruned or hand-deleted job dir, or a first `output.log` creation that `last_activity` reads), all between two passes. The next pass then skips `jobs:<t>`, and nothing ever reports the second change.
    2. It made job correctness rest on the nudge. Decision 11 says correctness rests on the scan.
  - Now that `job.json` is stat'ed, the scan alone sees every save. The cost is one duplicate `jobs` and `run{t}` for each burst of saves, at most one pass later, which the client's `dirty` flag absorbs.
  - Correctness rests on the scan (decision 11). Duplicate notices can happen and are harmless. Lost notices cannot, within §8.1's limits.

## 4. Hub and threading (`education_pipeline/daemon/events.py`, new)

| Constant | Value | Reason |
| --- | --- | --- |
| `MAX_STREAMS` | 4 | Browsers allow 6 HTTP/1.1 connections per host across all tabs. Hidden tabs drop their stream (§6), and 4 always leaves 2 connections for requests. |
| `HEARTBEAT_SECONDS` | 15 | Sent only after 15 s with no other write. The client watchdog is 3× this. |
| `LIFETIME_SECONDS` | 300 | Bounds a leaked stream and any change the scan cannot see (§8), for one resync every 5 min. |
| `LIVENESS_SECONDS` | 1.0 | The longest single wait. After each wait, a zero-timeout `select` on the socket checks whether the peer has left. |
| `SCAN_INTERVAL_SECONDS` | 1.0 | Stretched as described in §3. |

- **State.**
  - `_lock`, with `_changed = threading.Condition(_lock)`.
  - `_subscribers: set[_Subscriber]`. Each subscriber has `pending: dict[str, dict]`, keyed `"topics"`, `"jobs"` or `"run:<t>"`. The dict is insertion-ordered and bounded at 2 + the number of topics. A key that is already pending is not re-added, which loses nothing because notices are idempotent.
  - `_closed`, `_scan_gen`, `_fingerprint`, and `_scan_lock`. Lock order is always `_scan_lock`, then `_lock`.
  - *Review, lock rules made explicit:*
    - `JobStore.save`, and so `job_saved`, already runs under `Worker._lock` (`enqueue`, `cancel`: `jobs.py:926-941,953-964`), under the workspace lock (`execute`: `jobs.py:442-445`; `enqueue_stage`: `server.py:203`), and under `DaemonContext._chain_lock` (`server.py:249,306-309`). So `_lock` must be a **leaf** lock. Under it the hub does no socket I/O, no filesystem I/O and no callbacks, and it never takes another lock.
    - `_scan_lock` is taken only by the scanner thread and by `subscribe()`, never on a worker path.
    - Frames are written only after `wait()` has returned and released both locks.
    - The hub never takes the workspace lock or `Worker._lock`. That leaves no cycle.
- **API.**
  - `subscribe() -> _Subscriber | None` returns `None` at the cap or once the hub is closed. It runs under `_scan_lock`, so it never interleaves with a pass.
  - `unsubscribe(sub)`.
  - `wait(sub, timeout) -> list[dict] | None` drains the pending set. If it is empty, it makes one `Condition.wait` and returns `[]` on timeout, or `None` once the hub is closed.
  - `job_saved(t)`, `scan_once()`, `close()`, `hello_payload()`, and the `stream_count` and `scanning` properties.
  - A scan pass holds `_scan_lock` across list, diff and publish. Publishing merges into every pending set, then calls `notify_all()`.
- **Handler loop.**
  1. Subscribe, send the headers and write `hello`.
  2. Set `deadline = now + 300` and `beat = now + 15`.
  3. Loop:
     - Call `wait(sub, min(deadline, beat, now + 1) - now)`.
     - `None`: end.
     - Notices: write the frames and reset `beat`.
     - Otherwise, if `now ≥ beat`: write `: keepalive` and reset `beat`.
     - A readable socket ends the stream. The stream is receive-only, so readable means EOF or stray bytes.
     - `now ≥ deadline`: end.
  4. `finally: unsubscribe(sub)`. *Review:* the `try` opens on the line after `subscribe()` returns, before `send_response(200)`, so a failure while writing the headers or `hello` still frees the slot.
- **Dead peers.** A clean close (tab closed, reload, abort, or Vite tearing down the upstream) is seen within about 1 s. A heartbeat alone is slower: on loopback, the first write after a peer closes succeeds and draws an RST, and only the second write raises.
- **Shutdown.**
  - Today `serve()`'s `finally` (`daemon/__init__.py:203-206`) runs `server.shutdown()`, `worker.stop()` and the discovery removal. `server.shutdown()` ends only the accept loop, and nothing signals the handler threads, which are daemon threads (`ThreadingHTTPServer.daemon_threads`).
  - `serve()` builds `events = EventHub(root)` beside `JobStore` and passes it as `DaemonContext(events=...)`. It sets `store.on_saved = lambda job: events.job_saved(job.topic_id)`.
  - The `finally` becomes `events.close(); server.shutdown(); worker.stop(); …`.
  - `close()` sets `_closed`, bumps `_scan_gen` and calls `notify_all()`. Every stream's `wait` then returns `None`, its handler returns and its socket closes. Any later `subscribe()` gets 503.
- **Default hub.** `DaemonContext.events: EventHub | None = None`, and `__post_init__` builds a default hub. So `_start_server` (`tests/test_server.py:50`) and `test_worker_safety.py`'s context keep working unedited. A hub starts no thread until something subscribes.
- **Test hooks.**
  - Every constant is a keyword argument: `EventHub(root, *, max_streams, heartbeat_seconds, lifetime_seconds, liveness_seconds, scan_interval_seconds, clock=time.monotonic)`.
  - `scan_interval_seconds=None` starts no scanner, and tests call `scan_once()` themselves.
  - `clock` feeds the deadlines. Waits are real, so endpoint tests use small real values (heartbeat 0.05 s, lifetime 0.4 s) with generous bounds.
  - Tests swap `context.events` through `server_with_context` (`tests/test_server.py:119`).
  - Both fingerprint functions are pure.
  - *Review:* endpoint tests build their hub with small values and `close()` it in teardown. `_start_server` never closes the default hub, and a stream left open would keep a scanner walking a deleted `tmp_path` for the rest of the session.
  - *Review, CI:* CI runs pytest on Windows and macOS too (`.github/workflows/ci.yml:23-30`). On Windows, `DirEntry.stat` reports `st_ino = 0`, and mtimes can repeat within a coarse tick. So every fingerprint test that expects a notice must change the entry's size, or set its mtime explicitly with `os.utime(ns=…)`. None may rely on a new inode or on time passing. `test_in_place_edit_of_response_file_is_noticed` changes the size and also has a same-size variant that uses `os.utime`.

## 5. Auth and security

- **Same path as every `/v1` GET.** `_do_get_dispatch` checks `_host_ok` (400 `bad_host`, `server.py:592,719-720`), then `_authed` with `compare_digest` (401 `unauthorized`, `:598,730-731`). Both run *before* `subscribe()`, so an unauthenticated connection never takes a slot and stays bounded by the 30 s read timeout. There is no query token, no cookie and no second credential.
- **What it reveals.** Topic ids that pass `is_artifact_id`, which `/v1/topics` already shows the same token holder, plus the timing of changes. It never reveals paths, job ids, profile data or content, and it echoes nothing from the request.
- **DNS rebinding.** The bind is loopback-only, and a rebinding page's `Host` is refused.
- **Cross-origin reads.** No `Access-Control-Allow-*` header is ever sent. `X-EP-Token` makes a cross-origin fetch non-simple, and the handler has no `do_OPTIONS` (the stdlib answers 501), so the preflight fails and the GET is never sent. The static CSP `connect-src 'self'` (`server.py:760`) already permits the same-origin fetch.
- **Vite dev proxy.**
  - `vite.config.ts:11` proxies `/v1` with `{ target }` only, so `Host: localhost:5173` reaches the daemon and passes `_host_ok`, which strips the port.
  - The http-proxy bundled with Vite 5.4.21 pipes responses unbuffered, with no compression on proxied routes.
  - It destroys the upstream response when the browser's response closes, and aborts `proxyReq` on `aborted` (`node_modules/vite/dist/node/chunks/dep-BK3b2jBa.js:61247,61810-61815`). Dev reloads and StrictMode's double effect (`main.tsx:8`) therefore free their slot within about 1 s.
  - e2e never goes through the proxy.

## 6. Client (T62b)

- **Opening the stream.** `client.ts` gains `openEventStream(signal)`. It sends `GET /v1/events` with `X-EP-Token`, `Accept: text/event-stream` and `cache: "no-store"`, using the memoized token (`client.ts:86-106`). On 401 it clears the memo, so the next attempt picks up a restarted daemon's token.
  - *Review:* that rationale is weak. A restarted daemon binds a new ephemeral port, so a daemon-served page cannot reach it anyway, and Vite reads the proxy port once, at startup (`vite.config.ts:6-16`). Clearing the memo is harmless and cheap, so it stays, but no test should claim it recovers a restart.
- **`web/src/hooks/useEvents.tsx`** exports:
  - `EventsProvider`, wrapped by `App.tsx` around `.app-shell`, so the rail and every route share **one stream per tab**.
  - `useEvents(): { up, epoch, subscribe }`.
  - The `ChangeNotice` type and `noticeMatches(filter, notice)`.
  - A pure `createSseParser(onEvent)`. It reads `resp.body.getReader()` through a `TextDecoder` with `{stream: true}`, accepts LF, CRLF and CR, and joins multi-line `data`. It ignores comments, `id`, `retry`, unknown events and bad JSON, and it never throws.
- **Default context.** Without a provider the context is `{up: false}`, so every existing test and page behaves as it does today.
- **Behaviour.**
  - `up` holds from `hello` until the reader ends, and each `hello` bumps `epoch`.
  - A hidden tab aborts its stream, and a visible one reconnects at once. Pollers already skip hidden ticks (`usePolling.ts:40,69-75`).
  - A watchdog aborts after 3 × `heartbeat_seconds` with no bytes.
  - *Review:* a second watchdog runs from the request's start until `hello`, with a fixed 15 s. It covers a daemon that accepts but never answers, where `fetch` would otherwise stay pending for good.
  - *Review:* backoff jitter comes from an injectable `random` (default `Math.random`), so the vitest can assert the exact delays.
  - The state is mirrored to `document.documentElement.dataset.events` for e2e.

| Attempt outcome | Next attempt |
| --- | --- |
| Stream lived ≥ 10 s after `hello` (e.g. lifetime end) | 250–1000 ms, and backoff resets |
| Network error, EOF before `hello`, **EOF < 10 s after `hello`**, other 5xx, **other 4xx** (e.g. 400 `bad_host`), either watchdog | 1, 2, 4, 8, 16, then 30 s (cap), ±20 % jitter. *Review:* the bold cases were unassigned. Without the short-lived one, a daemon that closes right after `hello` would get a reconnect, and a full resync, every ≤1 s. |
| 503 `events_capacity` | 30 s |
| 401 | Memo cleared, then the backoff row |
| 404 (older daemon), no `ReadableStream`/`body`, `protocol != 1` | None: polling for the life of the page |

**`usePolling(fetcher, intervalMs, options?: { events?: NoticeFilter })`**, where `NoticeFilter = { run?: string | "*"; jobs?: true; topics?: true }`:

- Without `events`, or while `!up`, behaviour is exactly today's.
- On `up` the timer chain stops.
- Each `epoch` (resync) and each matching notice asks for one fetch. A request while this instance's fetch is in flight sets one `dirty` flag, worth exactly one follow-up fetch.
- Stream-driven fetches keep the payload-key bail-out. Only mount, `refresh()` and an interval change reset `lastKey`.
- On `up → down` the chain restarts with an immediate tick.
- *Review:* the filter is compared **by value** (a stable key such as `JSON.stringify(filter)`) or held in a ref. Every call site passes a fresh literal on each render, and that must never restart the chain or reset `lastKey`.
- *Review:* **when a stream-driven fetch fails while `up`**, that instance re-arms its own interval timer until one fetch succeeds, and then stops again. Today a transient failure heals on the next tick. Two examples: a Windows sharing violation that outlasts `_read_job_record`'s retries (`jobs.py:133-144`), and a 400 while a hand edit of a TOML file is half written. Without this rule the error would stick until the next notice or the 300 s resync. An idle, healthy page still makes zero requests.
- *Review, accepted:* after a hidden tab is shown, each instance fetches twice, once for `usePolling`'s own visibility tick (the stream is down at that moment) and once for the `hello` resync. That is one extra fetch per show.
- `JobLogView`'s 1 s tail (`JobLogView.tsx:49-63`) is untouched.

| Call site | Endpoint | Filter |
| --- | --- | --- |
| `RunBoardPage.tsx:163`, `StageViewerPage.tsx:72` | `/v1/runs/{t}` | `{ run: t }` |
| `RunBoardPage.tsx:171` | `/v1/jobs?topic={t}` | `{ run: t }` (every job save under t emits `run{t}`) |
| `RunBoardPage.tsx:70`, `ModuleRepairControl.tsx:37`, `StageViewerPage.tsx:71` | personalization, repair modules, stage | `{ run: t }` |
| `GlobalJobActivity.tsx:55` | `/v1/jobs` | `{ jobs: true }` |
| `GlobalJobActivity.tsx:56`, `TopicListPage.tsx:99` | `/v1/topics` | `{ run: "*", topics: true }` |
| `TopicListPage.tsx:100`, `NewRunPage.tsx:121`, `ProfilesPage.tsx:8` | `/v1/profiles` | `{ topics: true }` |

**"At most one request per change", as the test asserts it.**

- A *change* is one delivered `change` frame.
- A *mounted resource* is one mounted `usePolling` instance, so the rail's `/v1/topics` and the library's count as two.
- The vitest mounts `EventsProvider`, `GlobalJobActivity` and `RunBoardPage(t)`. The client module is mocked, with `openEventStream` yielding a controllable `ReadableStream`. It then checks:
  1. After `hello`, each instance has fetched exactly once.
  2. 120 s of fake time with **a `: keepalive` comment every 15 s** and no `change` frames costs **zero** calls. *Review:* as first written ("no frames"), this contradicted the 45 s watchdog. The watchdog would abort, `up → down` would restart every chain, and the calls would not be zero.
  3. One `change run t` costs exactly one call for each `{run: t}` instance and one for the rail's `/v1/topics`, and zero for the rail's `/v1/jobs`.
  4. `change run other` costs the board zero calls.
  5. Three frames during an unresolved fetch cost exactly one follow-up per instance.
  6. Ending the stream resumes the intervals.
  7. *Review:* a stream-driven fetch that rejects is retried on that instance's interval until it succeeds, and then costs zero calls again.

## 7. Test plan and size

**T62a, `tests/test_events.py`:** `test_fingerprint_opens_no_files`; `test_atomic_replace_in_run_tree_notices_that_topic_only`; `test_in_place_edit_of_response_file_is_noticed`; `test_job_record_save_notices_jobs_and_its_run`; `test_job_record_rewrite_within_one_dir_mtime_tick_is_noticed` (*Review:* added; restores the dir's mtime with `os.utime` and changes `job.json`'s size); `test_job_log_append_is_not_noticed`; `test_topics_profiles_and_plan_changes_notice_topics`; `test_topic_toml_change_notices_topics_and_that_run` (*Review:* added); `test_profile_snapshot_attach_notices_run_and_topics`; `test_run_directory_created_or_removed_notices_run`; `test_non_artifact_names_under_runs_are_ignored`; `test_notice_order_topics_jobs_then_runs`; `test_pending_notices_coalesce_per_subscriber`; `test_subscribe_past_cap_returns_none`; `test_scanner_runs_only_while_subscribed`; `test_job_saved_publishes_now` (*Review:* was `…_and_scan_does_not_repeat_it`; the skip is gone); `test_job_saved_on_closed_hub_or_bad_id_is_a_no_op` (*Review:* added); `test_job_store_save_calls_on_saved_and_survives_a_failing_hook`; `test_close_wakes_waiters_and_refuses_new_subscribers`; `test_polled_reads_produce_no_notices` (every polled GET payload runs between two passes); `test_scan_error_does_not_kill_the_scanner`.

**T62a, `tests/test_events_endpoint.py`:** `test_events_rejects_bad_host`; `test_events_rejects_missing_and_wrong_token`; `test_events_query_string_token_is_not_accepted`; `test_events_headers_and_hello_frame`; `test_events_change_after_cli_advance_out_of_process` (a real `python -m education_pipeline -C ws advance g` subprocess); `test_events_burst_coalesces_to_one_frame_per_notice`; `test_events_cap_answers_503_envelope`; `test_events_heartbeat_comment_when_idle`; `test_events_stream_ends_at_max_lifetime`; `test_events_client_disconnect_frees_the_slot`; `test_events_hub_close_releases_open_streams`; `test_serve_shutdown_releases_streams` (a real `daemon.serve` thread, then `POST /v1/shutdown`).

**T62b:**

- `useEvents.test.tsx`: the parser cases, `noticeMatches`, every backoff row, the watchdog, and hide/show. *Review:* the parser cases include a CRLF split across two chunks (a CR at the end of one chunk and an LF at the start of the next must end one line, not two), and a multi-byte UTF-8 character split across chunks.
- `usePolling.test.ts`: additions only. Existing cases stay unedited.
- `RunBoardPage.events.test.tsx`: the §6 budget test.
- `client.test.ts`: the header is sent, a query token never is, and a 401 clears the memo.
- `web/e2e/events.spec.ts`:
  1. Create a run through the CLI, as `library.spec.ts:26-30` does, and open the board.
  2. Wait for `data-events="up"`, **then for the response of the post-`hello` resync's `/v1/runs/{t}`**. *Review:* the resync fetch can start after the attribute flips, and without this wait it lands inside the counting window and makes the test flaky.
  3. Assert **zero** `/v1/runs/{t}` requests over 6 s, which is longer than the 5 s poll.
  4. Run the CLI `advance`.
  5. The board's next action changes within 3 s.

| Half | Non-test lines | Non-test files | Tests |
| --- | --- | --- | --- |
| T62a | ~300: `events.py` ~220 (new), `server.py` ~60, `daemon/__init__.py` ~8, `jobs.py` ~8 | 4 | 2 files, ~650 lines |
| T62b | ~360: `useEvents.tsx` ~200 (new), `usePolling.ts` ~50, `client.ts` ~30, `App.tsx` ~5, 7 call-site files ~20 | 11 | 4 files + 1 e2e, ~500 lines |

Both halves stay under ~800 lines. T62b is one file under the 12-file threshold, which is why the parser, the notice type and the matcher share `useEvents.tsx` instead of getting their own modules.

*Review, size check:* T62a is realistic at about 330–400 lines, with the `job.json` stat and topic pairing adding under 20. T62b's `useEvents.tsx` is more likely 250–300 than 200 once the pre-`hello` watchdog, the injectable jitter and the parser's CR handling are in, and `usePolling.ts` gains the failure re-arm. That still puts T62b under 800 lines, but at 11 of 12 files it has no slack. The cut is fixed now so the green agent does not improvise one: if T62b would touch a 12th non-test file, the `/v1/profiles` call sites in `NewRunPage.tsx:121` and `ProfilesPage.tsx:8` stay on plain polling and move to a follow-up, T62c. That frees two files. `TopicListPage.tsx` stays in T62b for its `/v1/topics` poller. These 30 s polls are the cheapest in the table.

## 8. Open risks

1. **Timestamps the scan cannot see.** Coarse or cached mtimes (FAT's 2 s, SMB or NFS attribute caching) can hide a change. On Windows, `DirEntry.stat` reports `st_ino = 0`, so a same-size replace within one timestamp tick is invisible. The 300 s lifetime resync bounds the staleness, where polling bounded it at 5–10 s. This is accepted for local-disk workspaces.
2. **Scan cost grows with job history.** Nothing prunes old job directories, and the 10 % stretch caps CPU, not latency.
3. **`/v1/topics` refetch rate.** The rail and the library refetch it on any `run` notice, so an active batch can drive this most expensive read to about 1/s, against 0.1/s today. If that measures badly, the lever is a per-instance minimum gap, which is not in T62.
4. **Lagging `last_activity`.** It includes `output.log` mtimes (`runs.py:1025`), which are deliberately unwatched, so it can lag during a running job until that job's next save.
5. **A GET that writes into a watched tree would loop:** notice, refetch, write, notice. A check in this session found no writes from the polled payloads, on a spec-stage guide run and a legacy run. That is not every state, so `test_polled_reads_produce_no_notices` guards it.
   - *Review, extended:* the review re-ran the check over HTTP against a real `build_server`. It compared `lstat` of every path in the workspace, `.education-pipeline/` included, before and after two rounds of 87 GETs. Those GETs were every polled route plus manifest, plan, validation, waivers and downloads, over four runs:
     - a guide run at finalize-ready;
     - a guide run finalized and exported;
     - a guide run with its outline approved and a profile attached;
     - a legacy run.
   - The diff was empty. `read_api.py` has no write call at all. `_PARALLELISM_CACHE` (`read_api.py:597`) and `RunStore`'s memo live in memory only.
6. **More than 4 visible cockpit tabs.** The extra tabs fall back to polling, by design.
7. **jsdom.** `ReadableStream` and `TextDecoder` come from Node 22's globals. *Review, resolved:* a scratch vitest (2.1.9, jsdom 24.1.3, Node 22.22.2) confirmed that `ReadableStream`, `TextDecoder`, `Response(stream).body.getReader()` and `AbortController` all exist, and that a stream read resolves under `vi.useFakeTimers()`. The budget test can hand `openEventStream`'s mock a `Response` over a `ReadableStream` whose controller the test holds.
8. **Existing e2e now runs on notices,** arriving in about 1 s or less, instead of polls. The phase's full Playwright gate on the merged head is the check.
9. **Plan edits reach run boards late.** *Review:* added. See the §1 "Plan edits" note. `draft_progress.parallelism` can lag a plan edit until the next `run{t}` or the lifetime resync.
10. **Symlinked run directories.** *Review:* added. `runs/<t>` as a symlink is recorded and not followed, so changes inside it are invisible to the scan until the lifetime resync. `RunStore` itself would follow it. This is accepted, because the engine never creates such links.

## Where this note sharpens decisions 9–14

- **11:** Discovering new topics and jobs needs directory listings, so "stat-only" is read as "no file contents". Directory mtimes alone miss in-place edits, so files are stat'ed too.
- **12:** A heartbeat surfaces a dead peer on the *second* write after the close, not within one interval. The 1 s readability check closes that gap. The browser's connection pool, not the daemon's threads, sets the cap.
- **10:** The §1 pairings exist because `jobs` carries no topic, profiles depend on run snapshots, and run status depends on the live topic TOML.
- **11 (review):** The `JobStore.save` nudge is latency only. The scan stats `job.json`, so job correctness rests on the scan as the decision requires.

None of decisions 9–14 is unworkable.

## Review record (adversarial review, 2026-09-27, before red)

Checked against `server.py` (the whole GET path), `daemon/__init__.py`, `jobs.py`, `read_api.py`, `atomic_io.py`, `workspace.py`, `runs_reports.py`, `usePolling.ts`, `client.ts`, `vite.config.ts` and Vite 5.4.21's bundled http-proxy. Every inline *Review:* mark above is a change made in this pass.

**Verified, no change:**

- Auth order. `_do_get_dispatch` runs the Host check, then splits off the query, then checks `/v1/` and then the token, all before `_api_get_routes` (`server.py:718-733`). So every spelling of the route is authenticated before any match:
  - a query string, a trailing slash and `//v1/events` get 404 after auth;
  - an absolute-form target falls to `_static_get`;
  - `HEAD` and `OPTIONS` get the stdlib 501.
- `send_header("Connection","close")` sets `close_connection`.
- `_SocketWriter` does an unbuffered `sendall`.
- The `_last_resort` behaviour after `send_response`.
- The Vite proxy's `Host` pass-through, its unbuffered pipe, and its destroy on close (`dep-BK3b2jBa.js:61247,61810-61815`).
- Every line anchor the note cites.

**Findings folded in:**

- **BLOCKER:** the §6 budget test 2 ("no frames for 120 s") contradicted the 45 s watchdog. Fixed.
- **BLOCKER:** the `_announced` skip could drop a notice, and it put job correctness on the nudge against decision 11. Fixed: `job.json` is stat'ed and the skip is removed.
- **SHOULD:**
  - `topics/<t>.toml` must also notice `run{t}`;
  - scanner generation re-check under `_scan_lock`;
  - lock rules made explicit (`_lock` is a leaf);
  - `try/finally` scope in the handler;
  - the write-timeout claim corrected;
  - Windows- and macOS-safe fingerprint tests;
  - `usePolling` compares its filter by value and re-arms after a failed fetch;
  - the reconnect table made total, plus a pre-`hello` watchdog;
  - the e2e counting window waits for the resync;
  - the T62b cut fixed in advance.
- **NIT:**
  - `ensure_ascii` stated;
  - the 401 rationale;
  - parser split-CRLF and split-UTF-8 cases;
  - injectable jitter;
  - teardown closes the hub;
  - the double fetch on tab show accepted;
  - risks 9 and 10.

**Optional for green:** the handler class may set `disable_nagle_algorithm = True`, so that 13-byte keepalives are not held back by Nagle and delayed ACK in the tight-timing endpoint tests. It changes nothing on the wire for other routes.

**For the manager:**

1. Keep `MAX_STREAMS = 4`, knowing that four visible tabs leave only two browser connections for every other request.
2. Keep "hidden tab drops its stream", which costs one extra fetch per show, instead of holding slots in background tabs.
3. Accept the plan-edit lag (§8.9).

## Manager rulings (2026-09-27, before red)

1. **`MAX_STREAMS = 4` stays.** A browser holds at most 6 HTTP/1.1
   connections per host, so four streams leave two for the page's own
   requests. The fifth concurrent stream gets 503 `events_capacity`, and that
   tab polls.
2. **A hidden tab drops its stream.** Showing the tab again costs one resync
   fetch. `usePolling` already does the same today, since it ticks at once when
   a tab becomes visible.
3. **The lag in `draft_progress.parallelism` after a plan edit is accepted.**
   A plan edit sends `topics` and not `run{t}`. The lag is visible only when a
   second tab shows a run board while the first edits Settings, and it lasts
   at most until the next `run{t}` notice or the 300 s lifetime resync. It is
   recorded as a limitation in the Phase 6 audit ledger.
