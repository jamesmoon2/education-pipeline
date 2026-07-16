# Interactive Guide v1 — Post-Milestone Independent Audit (Chunk 09)

- **Date:** 2026-07-11
- **Auditor:** Claude Code supervisor agent (Chunk 09), independent of the
  delivery chunks.
- **Base:** live worktree with `HEAD` at `f266234` (closeout commit);
  accepted feature head `434d11e` confirmed an ancestor of `HEAD`.
- **Mandate:** re-verify the milestone's definition of done against *live
  code*, not the delivery records, and record every finding with exact
  evidence. This audit fixes nothing; findings are recorded, not repaired.
- **Environment:** Python 3.12.3, Node v22.14.0, npm 11.4.1, Darwin 25.5.0,
  Playwright 1.61.1, build 1.5.1.

## 1. Verdict

The delivered milestone is **substantially sound**. Every required
verification command passes at the recorded counts, the normalized fixture
hash is unchanged, the wheel ships the runtime assets and installs and exports
with no Node, and the guide-v1 export/preview security posture is strong and
defense-in-depth. Two findings are recorded (one security defect on the
**legacy Markdown compatibility path**, one worktree-hygiene/record mismatch),
plus the previously-waived accessibility items and the owner-observed cockpit
discoverability gaps, which are carried forward as inputs to the next
milestone. No finding touches the frozen guide-v1 deliverable's runtime,
schema, validation, prompts, lifecycle, API shapes, or fixture.

## 2. Verification actually performed (exact results)

All commands were run on 2026-07-11 in this worktree.

| Step | Command | Result |
| --- | --- | --- |
| Ancestry | `git merge-base --is-ancestor 434d11e HEAD` | true (434d11e is an ancestor) |
| Whitespace | `git diff --check` | **FAILS** — `.gitignore:22: new blank line at EOF` (see F2) |
| Python suite | `python3 -m pytest` | **404 passed** (~35 s) |
| Web install + unit | `cd web && npm ci && npm test` | **79 passed** (13 files) |
| Type-check + build | `npm run build` | passed; `dist/assets/index-*.js` 189.30 kB (gzip 60.70 kB) |
| Browser acceptance | `npm run e2e` | **38 passed** (~4.7 s) |
| Wheel build | `python3 -m build` (isolated venv) | `education_pipeline-0.1.0-py3-none-any.whl`, **41 files** |
| Wheel assets | zip inspection | `guide_runtime/assets/runtime.js` **28,165 B**, `runtime.css` **7,560 B** (match on-disk sizes) |
| Clean install | `pip install --no-index --no-deps <wheel>` into fresh venv | OK; no runtime deps pulled |
| Out-of-checkout export | assemble fixture from a temp dir with the installed wheel | **60,118 B**, CSS/JS inline, **no `<script src>`**, only external URL is the content source anchor `https://www.chelseagreen.com/product/thinking-in-systems/` |
| `file:` acceptance | `npm run e2e` specs 26–33 (`guide runtime via file`) + 34–38 keyboard | render, keyboard interactions, persistence, print, and axe all pass from a `file:` URL |
| Fixture hash | `guide_sha256(normalize_guide(parse_guide(fixture)))` | `99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07` — **unchanged** |
| Private-artifact leak | `git ls-files -- runs/** topics/** profiles/** queue/** .remember/** .education-pipeline/**` | empty (clean) |
| Daemon discovery perms | `ls -l .education-pipeline/daemon.json` | `-rw-------` (0o600) |

**Packaging size note (not a finding):** the closeout *status* record cited
runtime.js 27,740 B and a 59,693 B export; live values are 28,165 B and
60,118 B. The delta is fully explained by the accepted `e2cb6f4` skip-link fix,
which post-dates that status record and grew runtime.js; the Chunk 08
*completion* record already accounts for the fix. This is expected, not drift.

## 3. Findings

### F1 — Legacy Markdown renderer emits live `javascript:` link hrefs (security defect; frozen legacy path)

**Severity:** Medium (High in the specific case of a same-origin cockpit
preview). **Surface:** legacy Markdown compatibility path only — **not** the
guide-v1 deliverable.

`education_pipeline/export.py:196-201` renders inline links by HTML-escaping
the whole string first (`_html.escape`, line 197) and then substituting
`_LINK_RE` matches into `<a href="\2">…</a>` (line 198). Escaping-first blocks
attribute breakout (a `"` in the URL becomes `&quot;` before the regex runs),
but there is **no URL-scheme allowlist**, so dangerous schemes survive intact.

Measured:

```text
render_html_body('[click me](javascript:alert(1))')
  → <p><a href="javascript:alert(1">click me</a>)</p>
render_html_body('[x](https://example.com" onmouseover="alert(2))')
  → <p><a href="https://example.com&quot; onmouseover=&quot;alert(2">x</a>)</p>
```

The first output is a live `javascript:` link; the second confirms attribute
injection is *not* possible (the quote is neutralized). So the defect is
precisely "no scheme allowlist," letting `javascript:` (and by the same logic
`data:`, `vbscript:`) URLs through.

This output reaches two sinks:

1. **Same-origin cockpit preview.** The daemon route `POST /v1/preview`
   returns `render_html_body(text)` verbatim (`daemon/server.py:313-317`); the
   cockpit injects it with `dangerouslySetInnerHTML`
   (`web/src/components/ResponseEditor.tsx:127-134`). The cockpit page
   (`web/index.html`) ships **no CSP**. A model-authored legacy-Markdown
   response containing a `javascript:` link, previewed and then clicked by the
   user, executes script in the authed loopback cockpit origin — which can read
   the session token via `GET /v1/session` and drive the workspace write API.
2. **Legacy HTML export.** `render_markdown_to_html` (`export.py:54-71`, used
   by `RunStore.export_run` at `runs.py:770` for non-guide-v1 runs) writes the
   same body into a standalone HTML document that also carries **no CSP meta**.

The function docstring (`export.py:74-80`) asserts the output is "safe to
inject into an authed same-origin page (the cockpit preview)." That claim is
**false** for `javascript:` hrefs and should be treated as the root
misconception behind the defect.

**Why the guide-v1 deliverable is not affected (stated explicitly):** the
guide renderer rejects the scheme at parse time — `_safe_href`
(`guides/document.py:41-47`) raises `GuideDocumentError` unless the target is a
known `#fragment` or an `http(s)://` URL with a netloc (verified:
`render_guide_markdown('[x](javascript:alert(1))', frozenset())` renders the
literal text, no anchor). The guide export additionally sets a strict CSP
(`guides/document.py:276`): `default-src 'none'; script-src '<hash>';
connect-src 'none'; base-uri 'none'; form-action 'none'` (etc.), which blocks
`javascript:` navigation even if a bad href somehow appeared. Guide-v1 preview
is further isolated in a sandboxed iframe (below).

**Disposition:** the milestone froze "export content"; this legacy path is in
scope of the freeze, so it is recorded here and **not fixed**. It should be
remediated (scheme allowlist in `_render_inline_text`, and/or a CSP on the
legacy export and cockpit) before any public `v0.1` that keeps the legacy
Markdown export, per the PRD release gate "no known … arbitrary-code execution
defect remains" (§11).

### F2 — Worktree fails `git diff --check`; contradicts the closeout "clean" record (low)

**Severity:** Low (hygiene + record/reality mismatch).

`git status --porcelain` shows one uncommitted change, `M .gitignore`, and
`git diff --check` reports `.gitignore:22: new blank line at EOF` (exit 2). The
change adds `.education-pipeline/` to the ignore list — correct hygiene, since
that directory holds the live daemon token and discovery file — but it is
**uncommitted** and introduces a trailing-blank-line whitespace error. Both the
Chunk 08 status and completion records state `git diff --check` is clean; the
live worktree does not satisfy that claim. Recorded, not corrected (the audit
does not modify frozen or unrelated surfaces without separate authorization).

## 4. Carried-forward items (recorded in prior records; re-confirmed live)

These are not new defects; they are open commitments the audit re-verifies and
hands to the next milestone.

- **Waived manual accessibility items (unverified).** Screen-reader smoke pass,
  human keyboard checklist, real print dialog, and real-device reflow were
  **waived without execution** by the owner (acceptance record §"Owner
  sign-off"). They remain recommended before public release.
- **O1 — initial Tab starts inside the current section.** On load the runtime
  normalizes the URL to `#<section-id>` via `history.replaceState`, so the
  first Tab lands inside the section rather than on the skip link (still
  reachable via Shift+Tab). Accepted nuance of frozen behavior; confirmed still
  present. The skip-link *activation* defect (former F1 of Chunk 08) is fixed
  and covered by e2e test 37.
- **Cockpit discoverability gaps (product, not defects).** Confirmed live:
  the empty board reads "No topics yet. Import one above."
  (`web/src/pages/TopicListPage.tsx:37`) with no guided New Course flow;
  topic/run creation requires pasting TOML; the guide preview is reachable only
  inside the response editor (`ResponseEditor.tsx`), with no standalone preview
  surface; and a finalized run's read-only state is not explained in the UI.
  These match the owner's session observations and the PRD's deferred "P1 —
  First-run and course-management experience."
- **Blueprint / course-brief depth.** Delivered only to the depth the
  acceptance fixture requires (PRD §10 P0 status note); deeper work sits under
  "P1 — Blueprint-driven pedagogy."

## 5. Surfaces audited and found clean

Stated explicitly so their absence from §3 is a conclusion, not an omission.

- **Daemon authentication.** Token is `secrets.token_urlsafe(32)`
  (`daemon/__init__.py:69`), compared constant-time with
  `secrets.compare_digest` (`server.py:106-108`); every `/v1` route except the
  read-only `/v1/session` bootstrap requires it (`server.py:174-177`,
  `_guard` at 133-140). Host header is restricted to `127.0.0.1`/`localhost`
  (DNS-rebinding guard, `server.py:102-104`); no CORS headers are ever emitted;
  the server binds `("127.0.0.1", 0)` (`server.py:91`). Discovery file is
  written atomically at 0o600 (`lifecycle.py:35,39`). Request bodies are capped
  at 1 MiB (`server.py:150-154`).
- **Guide-v1 preview isolation.** `POST /v1/guide-preview`
  (`server.py:318-349`) parses/normalizes/validates and returns runtime-rendered
  HTML that the cockpit shows only in `GuidePreviewFrame`
  (`web/src/components/GuidePreviewFrame.tsx`) with
  `sandbox="allow-scripts"` and **no** `allow-same-origin` — it cannot reach
  the cockpit origin, workspace, or network. Covered by
  `ResponseEditor.test.tsx:147-163`.
- **Guide-v1 export content.** Only finalized course content; the sole external
  URL in the fixture export is a content source anchor. No profile, prompt,
  manifest, log, or reflection-note data is embedded (verified by export
  inspection and by the privacy documentation in `docs/interactive-guides.md`).
- **Static-asset resolver.** `resolve_static` (`daemon/static.py:53-73`)
  resolves and rejects any path escaping `dist` (`..`, percent-encoded dots,
  out-pointing symlinks) via realpath containment (`static.py:57-60`).
- **Determinism / parity.** Normalized fixture hash reproduces exactly from
  both checkout and installed wheel; Python-rendered export and the browser
  runtime agree (e2e HTTP/`file:` parity specs pass).
- **Packaging.** Wheel carries both runtime assets and no generated-vs-source
  drift (assets are maintained source; on-disk sizes equal wheel sizes); clean
  venv install needs no runtime dependencies and no Node to export.
- **CI.** `.github/workflows/ci.yml` runs the Python 3.11/3.12 matrix + CLI
  smoke, a web unit/build job, an e2e job (Playwright chromium + `npm run
  e2e`), and an artifact-leak guard; the leak guard passes live.

## 6. Recommendations (for the proposal, not executed here)

1. Before any public `v0.1` retaining the legacy Markdown export: add a URL
   scheme allowlist to `_render_inline_text` and a CSP to both the legacy
   export document and the cockpit shell (F1).
2. Commit or revert the `.gitignore` change and restore a clean
   `git diff --check` (F2); keep `.education-pipeline/` ignored.
3. Schedule the waived manual accessibility passes on real assistive tech and
   devices ahead of release.
4. Treat the cockpit discoverability gaps as first-class next-milestone scope
   (see the companion proposal).
