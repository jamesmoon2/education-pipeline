# Events Endpoint (`GET /v1/events`) — Design

- **Date:** 2026-09-27
- **Status:** Draft for adversarial review (plan: T62 is reviewed before any code)
- **Plan:** [`../plans/2026-09-27-phase-6-cockpit.md`](../plans/2026-09-27-phase-6-cockpit.md), threads T62a (daemon) and T62b (cockpit), binding decisions 9–14 and 20
- **Anchors:** verified at `ee671cf` (branch `claude/gifted-davinci-slrab7`)

## Summary

One authenticated `text/event-stream` route tells the cockpit *that* something changed, never *what*. A daemon-wide hub runs a stat-only scan of the workspace while at least one stream is open. It publishes idempotent notices (`run` per topic, `jobs`, `topics`) into a coalescing pending set per subscriber. While the stream is up, pollers stop and refetch only on a notice that names them. While it is down, they poll exactly as today. No engine behaviour or existing route changes.

## 1. Wire format

The stream is UTF-8 with LF line endings. Each `data:` line holds one JSON object, written with `json.dumps(..., sort_keys=True, separators=(",", ":"))`, so it is always a single line. There are no `id:` or `retry:` fields, because a reconnect resyncs instead of resuming.

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
| `topics/`, `profiles/`, `config/` (the dirs and their direct children) | `topics` |
| `runs/*/jobs/*/output.log` appends, `.education-pipeline/`, `queue/` | none |

- **Job pairing.** Run status embeds the job-derived fields `continuation`, `draft_progress` and `cost` (`read_api.py:488-493`), and `{"kind":"jobs"}` carries no topic (decision 10). So each job change also sends `run{t}`, which carries the topic.
- **Attach pairing.** `/v1/profiles` counts run snapshots (`read_api.py:197`, `workspace.py:340-355`), so an attach also sends `topics`.
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
- **Write timeout.** The existing 30 s `handler.timeout` (`server.py:74,574`) bounds every `sendall`, so a peer that stops reading ends its stream after 30 s. Idle waits happen on a `Condition`, never on the socket.
- **Over capacity.** The answer is `_error(503, "events_capacity", "event stream limit reached; poll instead")`, the standard envelope (`server.py:617-622`), on an ordinary keep-alive connection.

## 3. The fingerprint

`workspace_fingerprint(root) -> dict[str, tuple]` is pure.

- **Calls.** It uses only `os.scandir` and `DirEntry.stat(follow_symlinks=False)`. It never opens, reads or parses a file. Directory listings are unavoidable, because they are how new topics and jobs are discovered.
- **Symlinks and races.** Symlinks are recorded, never followed. An entry that vanishes mid-scan is skipped, and its absence is then a change.
- **Values.** Each value is a sorted tuple of `(relpath, st_mtime_ns, st_size, st_ino)`.

| Key | Stat'ed | Why it catches the writes that matter |
| --- | --- | --- |
| `run:<t>` | `runs/<t>` and every dir and file below it, recursively, except the `jobs/` subtree | Every package write is `mkstemp` beside the target plus `os.replace` (`atomic_io.py:76,87`). That adds and renames directory entries, so the file gets a new inode and the parent directory's mtime moves. Stat'ing files, not only directories, also catches an in-place human edit of an existing response, which leaves the directory alone. |
| `jobs:<t>` | `runs/<t>/jobs/` and each job **directory** entry, one level only | `JobStore.save` is always atomic, so every save bumps its job dir's mtime. `output.log` appends change only the file, so the 1 s log tail never becomes a notice. |
| `attach:<t>` | `runs/<t>/inputs/profile.toml`, from the same walk | Profile attachment counts. |
| `topics` | `topics/`, `profiles/`, `config/` and their direct children | Hand edits of `model-plan.toml` are caught whether done in place or by replace. |

`diff_fingerprints(old, new, announced_jobs)` maps changed, added and removed keys to notices per §1. It skips `jobs:<t>` when `t` is in `announced_jobs`.

- **Cost.** One pass is O(files and directories in the run trees + job directories + topics/profiles/config children), with zero reads.
  - Measured in this container: 50 runs and 1,500 jobs (5,650 entries) took **23.6 ms** per pass.
  - For comparison, `GET /v1/topics` already walks every file of every run on each call (`runs.py:1018-1042`), and `GET /v1/jobs` parses every job record (`jobs.py:221-236`). The rail polls both of these today.
- **Interval.** `SCAN_INTERVAL_SECONDS = 1.0`. The next wait is `max(1.0, 10 × last pass)`, so scanning never uses more than 10 % of a core.
- **Start and stop.**
  - On 0→1 subscribers, `subscribe()` computes the baseline on the handler thread, under `_scan_lock`, *before* `hello`. It then bumps `_scan_gen` and starts the daemon thread `ep-events-scan` for that generation.
  - On 1→0 nothing is joined. The thread exits at its next wake, when it finds no subscribers or a newer generation. A quick 1→0→1 simply starts a fresh generation.
- **Nudge.** `JobStore` gains `on_saved: Callable[[Job], None] | None = None`, like `Worker.on_finished` (`jobs.py:868`).
  - `save()` calls it after the replace, inside a `try/except` that logs only the exception type, so a hook can never fail a save.
  - `serve()` wires it to `hub.job_saved(t)`. That call publishes `jobs` and `run{t}` immediately, under `_lock` only and without any stat, so worker threads never block. It also records `t` in `_announced`.
  - Each pass snapshots and clears `_announced` when it starts, and passes it on as `announced_jobs`.
  - This is exact because the CLI only *reads* job records (`cli.py:110,548`), so every job write happens inside the daemon. It also covers transitions faster than one mtime tick, which a directory mtime can miss.
  - Correctness for everything else rests on the scan (decision 11). Duplicate notices can happen and are harmless. Lost notices cannot.

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
  - `_closed`, `_scan_gen`, `_announced`, `_fingerprint`, and `_scan_lock`. Lock order is always `_scan_lock`, then `_lock`.
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
  4. `finally: unsubscribe(sub)`.
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
  - The state is mirrored to `document.documentElement.dataset.events` for e2e.

| Attempt outcome | Next attempt |
| --- | --- |
| Stream lived ≥ 10 s after `hello` (e.g. lifetime end) | 250–1000 ms, and backoff resets |
| Network error, EOF before `hello`, other 5xx, watchdog | 1, 2, 4, 8, 16, then 30 s (cap), ±20 % jitter |
| 503 `events_capacity` | 30 s |
| 401 | Memo cleared, then the backoff row |
| 404 (older daemon), no `ReadableStream`/`body`, `protocol != 1` | None: polling for the life of the page |

**`usePolling(fetcher, intervalMs, options?: { events?: NoticeFilter })`**, where `NoticeFilter = { run?: string | "*"; jobs?: true; topics?: true }`:

- Without `events`, or while `!up`, behaviour is exactly today's.
- On `up` the timer chain stops.
- Each `epoch` (resync) and each matching notice asks for one fetch. A request while this instance's fetch is in flight sets one `dirty` flag, worth exactly one follow-up fetch.
- Stream-driven fetches keep the payload-key bail-out. Only mount, `refresh()` and an interval change reset `lastKey`.
- On `up → down` the chain restarts with an immediate tick.
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
  2. 120 s of fake time with no frames costs **zero** calls.
  3. One `change run t` costs exactly one call for each `{run: t}` instance and one for the rail's `/v1/topics`, and zero for the rail's `/v1/jobs`.
  4. `change run other` costs the board zero calls.
  5. Three frames during an unresolved fetch cost exactly one follow-up per instance.
  6. Ending the stream resumes the intervals.

## 7. Test plan and size

**T62a, `tests/test_events.py`:** `test_fingerprint_opens_no_files`; `test_atomic_replace_in_run_tree_notices_that_topic_only`; `test_in_place_edit_of_response_file_is_noticed`; `test_job_record_save_notices_jobs_and_its_run`; `test_job_log_append_is_not_noticed`; `test_topics_profiles_and_plan_changes_notice_topics`; `test_profile_snapshot_attach_notices_run_and_topics`; `test_run_directory_created_or_removed_notices_run`; `test_non_artifact_names_under_runs_are_ignored`; `test_notice_order_topics_jobs_then_runs`; `test_pending_notices_coalesce_per_subscriber`; `test_subscribe_past_cap_returns_none`; `test_scanner_runs_only_while_subscribed`; `test_job_saved_publishes_now_and_scan_does_not_repeat_it`; `test_job_store_save_calls_on_saved_and_survives_a_failing_hook`; `test_close_wakes_waiters_and_refuses_new_subscribers`; `test_polled_reads_produce_no_notices` (every polled GET payload runs between two passes); `test_scan_error_does_not_kill_the_scanner`.

**T62a, `tests/test_events_endpoint.py`:** `test_events_rejects_bad_host`; `test_events_rejects_missing_and_wrong_token`; `test_events_query_string_token_is_not_accepted`; `test_events_headers_and_hello_frame`; `test_events_change_after_cli_advance_out_of_process` (a real `python -m education_pipeline -C ws advance g` subprocess); `test_events_burst_coalesces_to_one_frame_per_notice`; `test_events_cap_answers_503_envelope`; `test_events_heartbeat_comment_when_idle`; `test_events_stream_ends_at_max_lifetime`; `test_events_client_disconnect_frees_the_slot`; `test_events_hub_close_releases_open_streams`; `test_serve_shutdown_releases_streams` (a real `daemon.serve` thread, then `POST /v1/shutdown`).

**T62b:**

- `useEvents.test.tsx`: the parser cases, `noticeMatches`, every backoff row, the watchdog, and hide/show.
- `usePolling.test.ts`: additions only. Existing cases stay unedited.
- `RunBoardPage.events.test.tsx`: the §6 budget test.
- `client.test.ts`: the header is sent, a query token never is, and a 401 clears the memo.
- `web/e2e/events.spec.ts`:
  1. Create a run through the CLI, as `library.spec.ts:26-30` does, and open the board.
  2. Wait for `data-events="up"`.
  3. Assert **zero** `/v1/runs/{t}` requests over 6 s, which is longer than the 5 s poll.
  4. Run the CLI `advance`.
  5. The board's next action changes within 3 s.

| Half | Non-test lines | Non-test files | Tests |
| --- | --- | --- | --- |
| T62a | ~300: `events.py` ~220 (new), `server.py` ~60, `daemon/__init__.py` ~8, `jobs.py` ~8 | 4 | 2 files, ~650 lines |
| T62b | ~360: `useEvents.tsx` ~200 (new), `usePolling.ts` ~50, `client.ts` ~30, `App.tsx` ~5, 7 call-site files ~20 | 11 | 4 files + 1 e2e, ~500 lines |

Both halves stay under ~800 lines. T62b is one file under the 12-file threshold, which is why the parser, the notice type and the matcher share `useEvents.tsx` instead of getting their own modules.

## 8. Open risks

1. **Timestamps the scan cannot see.** Coarse or cached mtimes (FAT's 2 s, SMB or NFS attribute caching) can hide a change. On Windows, `DirEntry.stat` reports `st_ino = 0`, so a same-size replace within one timestamp tick is invisible. The 300 s lifetime resync bounds the staleness, where polling bounded it at 5–10 s. This is accepted for local-disk workspaces.
2. **Scan cost grows with job history.** Nothing prunes old job directories, and the 10 % stretch caps CPU, not latency.
3. **`/v1/topics` refetch rate.** The rail and the library refetch it on any `run` notice, so an active batch can drive this most expensive read to about 1/s, against 0.1/s today. If that measures badly, the lever is a per-instance minimum gap, which is not in T62.
4. **Lagging `last_activity`.** It includes `output.log` mtimes (`runs.py:1025`), which are deliberately unwatched, so it can lag during a running job until that job's next save.
5. **A GET that writes into a watched tree would loop:** notice, refetch, write, notice. A check in this session found no writes from the polled payloads, on a spec-stage guide run and a legacy run. That is not every state, so `test_polled_reads_produce_no_notices` guards it.
6. **More than 4 visible cockpit tabs.** The extra tabs fall back to polling, by design.
7. **jsdom.** `ReadableStream` and `TextDecoder` come from Node 22's globals. Confirm this in the red step.
8. **Existing e2e now runs on notices,** arriving in about 1 s or less, instead of polls. The phase's full Playwright gate on the merged head is the check.

## Where this note sharpens decisions 9–14

- **11:** Discovering new topics and jobs needs directory listings, so "stat-only" is read as "no file contents". Directory mtimes alone miss in-place edits, so files are stat'ed too.
- **12:** A heartbeat surfaces a dead peer on the *second* write after the close, not within one interval. The 1 s readability check closes that gap. The browser's connection pool, not the daemon's threads, sets the cap.
- **10:** The §1 pairings exist because `jobs` carries no topic and profiles depend on run snapshots.

None of decisions 9–14 is unworkable.
