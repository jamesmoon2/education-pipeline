# Deterministic Release Gates — Post-Milestone Audit & Next-Milestone Proposal

- **Date:** 2026-07-13
- **Auditor:** post-milestone audit (Opus), recorded per the milestone's
  closeout task; independent of the wave managers and task implementers.
- **Base:** the milestone's final gate commit `762c684` (last code commit) and
  the plan record `c993fba`; Wave Log rows 0–4 in
  [`docs/superpowers/plans/2026-07-12-deterministic-release-gates.md`](../plans/2026-07-12-deterministic-release-gates.md).
  Commits after `c993fba` on `main` are docs-only (wave-runner design,
  personalization plan) and are not part of this milestone. The working tree
  additionally carries **uncommitted** personalization Wave-0 work
  (`education_pipeline/privacy.py`, `profiles.py`); it is out of scope here and
  the recorded gate below is the gate at `762c684`, not at a dirty tree.
- **Mandate:** confirm the milestone's exit criterion against live code and the
  recorded gates, state every accepted limitation explicitly, and propose one
  coherent next milestone grounded in the PRD. **This audit fixes nothing;
  findings are recorded, not repaired.** Recorded gates are treated as
  canonical — no prior wave's suite was re-run.

## 1. Verdict

The milestone is **closed and sound**. The PRD §10 exit criterion — *export
provides a clear, reproducible quality report and cannot silently package
structurally invalid or privacy-leaking content* — is met, and it is met by
executable record rather than by assertion.

Both halves of the criterion are independently pinned:

- **"Cannot silently package"** — three distinct refusal paths are proven, each
  with sabotage-RED evidence: a structural blocker
  (`test_structural_refusal_export_raises_and_leaves_no_artifacts`), a privacy
  leak from the attached profile
  (`test_privacy_refusal_blocks_export_until_waived`), and — the path the final
  review found unguarded by tests — export's own internal `apply_waivers` gate
  at `runs.py:985`, which is the *sole* defense after waive → finalize →
  `unwaive` (`test_export_refuses_after_unwaive_following_finalize`). Waivers
  are hash-bound, so a waiver recorded against different content is dropped and
  the gate **closes**; it can never silently open one
  (`test_stale_waiver_never_reopens_the_gate`).
- **"Clear, reproducible quality report"** — the sidecar is canonical and
  timestamp-free:
  `test_export_and_sidecar_are_byte_identical_across_independent_runs` drives
  two *independent workspaces* to export and compares bytes, which is stronger
  than the plan's wording (same-workspace re-export). Clarity is carried by
  stage-attributed findings (report schema v2, 45 rules) surfaced in the CLI,
  the daemon payload, and the cockpit.
- **The loop closes in the product, not just the engine** —
  `web/e2e/release-gates.spec.ts` drives seed → draft badge → stage link →
  repair in editor → re-run → waive with reason → export → on-disk
  `gate.open === true`, plus a page-wide axe scan.

**Live-code confirmation (this audit, by reading, not re-running):** the five
acceptance tests exist as named in `tests/test_release_gate_acceptance.py`; the
privacy denylist is genuinely wired (`RunStore._private_profile_values` at
`runs.py:1282`, consumed by `_validated_final` at `:1266` **and**
`_compute_phase_report` at `:1340`); `privacy.exact_private_value` is a
waivable blocker attributed to the `draft` stage
(`guides/validation.py:61`). Every one of the twelve carried-forward triage
items reproduces in current source at the line cited in §7 — the deferred list
is accurate, not stale.

Zero Critical or Important findings remain open. The milestone's recurring
defect class was **tests that would pass against unfixed code**; from Wave 3 on,
every fix and every acceptance test carried independently re-verified RED
evidence, and that discipline is what surfaced the two real gaps closed in Wave
4 (dead `private_values` wiring; the untested export-internal gate).

## 2. Final gate (recorded results)

| Suite | Milestone start (`57f715e`) | Final gate (`762c684`) |
| --- | --- | --- |
| pytest | 478 | **600** |
| vitest | 114 | **127** |
| Playwright e2e | 41 | **42** |
| `npm run build` (tsc) | clean | clean |

Every wave gated on the full four-suite run before recording; no baseline
regression occurred at any gate. PRD §10 "P0 — Establish deterministic release
gates" is marked **Delivered 2026-07-13** with the Wave Log, the acceptance
suite, and the e2e as closeout evidence.

## 3. What shipped

- **Wave 0 — hardening debt** (`5f03d56..d492ccc`): atomic, per-topic-serialized
  manifest writes; wrong-shape PUT/POST bodies → 400 across the write builders;
  unknown stage-override keys rejected at write (strict at write, lenient on
  disk). Absorbed the two scheduled debt items from the model-plan audit §7.
- **Wave 1 — real static checks** (`3103042..b0e5fd3`):
  `guides/static_checks.py` computes `ValidationContext` from the **assembled
  export document**, so the checked artifact is the shipped artifact;
  finalize/export gate on it and export writes exactly the checked string.
- **Wave 2 — attribution + sidecar report** (`ee3ceac..d0a291f`): `Finding.stage`
  (report schema v2), `findings_by_stage` in the daemon payload, the canonical
  timestamp-free sidecar `guide.report.json`, and the cockpit re-run affordance.
- **Wave 3 — CLI parity** (`c03bb24..f4e4f39`): `validate | findings | report |
  waive | unwaive`, `RunStore.gate_result` / `validate_and_gate` /
  `record_waiver` / `remove_waiver`, plus the owner-approved Task 3.1b making
  the cockpit's badges and re-run button waiver-aware (`effective_blocking`).
- **Wave 4 — acceptance + closeout** (`918caf3..762c684`): the five-test
  acceptance suite, the UI-loop e2e, unified CLI exit codes, and the milestone
  close.

### 3.1 Defects found and fixed mid-milestone

Recorded because they characterize where this design bites:

1. **Wave 0 — `create_waiver` could brick a run.** Its guard diverged from the
   loader, so the endpoint could return 200 while persisting a file its own
   loader rejects; it also crashed on element-level corruption and **dropped the
   HTTP connection** with no status line, and its unserialized read-modify-write
   lost 30/30 concurrent waivers. Resolved by making `load_waiver_set` the single
   schema authority and `record_waiver` its sole locked, atomic writer.
2. **Wave 1 — the size gate was silently dropped.** Parsing before applying
   `MAX_GUIDE_SOURCE_BYTES` removed the `schema.size_limit` blocker and
   **livelocked `report_state` at "stale"** (the report digest no longer matched
   the raw-source sha). Fixed by falling back to the raw-`str` validate path
   before parsing.
3. **Wave 2 — pre-v2 reports produced `/stages/undefined` links.** A required TS
   `stage` field interpolated directly; fixed to optional + phase-derived
   fallback. Separately, RunBoard badges counted **stale** reports, inflating the
   actionable-work signal.
4. **Wave 3 — one corrupt waivers file 400'd the entire topic list.** A
   `load_waiver_set` call placed outside a `ConfigError` handler turned a
   graceful degrade into an HTTP 400 on `GET /v1/runs/{topic}` — the endpoint the
   cockpit polls every 5 s — and because the topic-list payload calls
   `run_status_payload` for *every* topic, one bad file on one run took out
   `/v1/topics`. Every read-path call site is now guarded.
5. **Wave 4 — `private_values` was dead end-to-end.** `privacy.exact_private_value`
   could never fire from a real run because nothing passed a denylist;
   the privacy half of the exit criterion was unproven until `918caf3`. This is
   the single most important find of the milestone: the criterion's headline
   guarantee was not actually wired.

### 3.2 Behavior changes beyond the plan (owner should know)

- **Draft-phase validation now screens profile leaks.** Wiring
  `_private_profile_values` into `_compute_phase_report` means draft reports are
  now profile-sensitive: a draft that quotes its attached learner profile
  verbatim can newly **block**. This is correct (catch the leak at the stage that
  introduced it — the rule is stage-attributed to `draft`) and fail-closed under
  waiver hash-binding, but it is a new way for a previously-passing draft to stop.
  See §8.
- **CLI exit codes unified** (`762c684`): `0` = gate open/success, `1` = gate
  blocked, `2` = usage/config error. Previously engine `ConfigError` leaked to
  `main()` → exit 1 in `validate`/`findings`/`report`, colliding with "gate
  blocked", so `validate typo-topic || echo blocked` mislabeled a nonexistent run
  as a blocked gate. `waive`/`unwaive` by design never exit 1.
- **`web/e2e/helpers/daemon.ts` (`bootDaemon`) extracted** — this spec would have
  been the sixth inline copy of the daemon-boot dance. Existing specs were
  deliberately not migrated (see §7, item 11).

## 4. Design decisions recorded (for future executors)

- **The manifest-lock composition contract.** `_manifest_write_lock` is a plain
  **non-reentrant** `threading.Lock`, one per topic, guarding the manifest *and*
  the waivers file. The rule is **one read-modify-write cycle per critical
  section**: compose by taking the lock once and calling the unlocked `_locked`
  primitives; **never** nest a public wrapper inside the lock. The deadlock is
  deliberate — an earlier `RLock` made nesting "work" and silently **lost
  updates** instead. Fail-loud was chosen over silent corruption. The inverse
  error (calling a `_locked` primitive *without* the lock) silently loses updates
  and **nothing enforces it** — the contract is documented, not checked.
- **The waivers-file existence contract.** `read_api._validation_summary` skips an
  expensive per-poll gate recompute **only when the waivers file does not exist**.
  Therefore *no writer may leave an empty waivers file behind* — a no-op removal
  writes nothing, and removing the last waiver `unlink`s the file.
  `_write_waiver_set_locked` is the sole writer; keep it that way. Relatedly,
  `load_waiver_set` **raises** on a malformed file and returns `None` only for
  "no file" — conflating the two caused §3.1(4).
- **Two notions of "the report" coexist — do not pair them.** The on-disk report
  JSON, and the report freshly recomputed by `_compute_phase_report`. Pairing a
  *stale* on-disk body with a *fresh* recomputed gate makes a surface disagree
  with itself; this bug was found independently in **both** `_cmd_report` and
  `_validation_summary`. Rule: only trust a recomputed gate when `report_state`
  is `"current"`; otherwise fall back to raw counts and let the stale banner work.
- **`assets_match` stays computed when assembly fails.** Settled in Wave 1 against
  the plan's own prose: forcing it True on render failure would mask real
  tampering. Only the document-derived checks default True.
- **`gate_result` recomputes rather than rehydrating.** There is no
  `ValidationReport.from_dict()`, and adding one would be new untested schema
  surface for zero gain. The recompute is fail-safe: a waiver set bound to
  different content is dropped and the gate closes.
- **Waivers are hash-bound in one direction only, and that is the safe one.** A
  stale waiver can never open a gate; it can only fail to open one.

## 5. Accepted limitations beyond the carried triage

Residuals from Waves 0–2 that the Wave-4 roll-up did not carry forward. Each is
explicitly accepted; re-triage only if its precondition changes.

- **`_locked` primitives' "caller holds the lock" contract is documented, not
  enforced** (a `lock.locked()` assert would catch the dev-time error). Pairs with
  §7 item 12 — today a nesting regression hangs CI rather than failing it.
- **The lock's name still says "manifest"** though it also guards waivers.
- **Loader-accepted extra keys in the waivers file are dropped from the GET
  payload** rather than echoed.
- **Status polling assembles the full export document per status call**
  (~1.4 ms on the canonical fixture; deterministic; plan-mandated). Perf note only.
- **Static-analyzer latent shell-coupling:** `<input type="hidden">` would be
  treated as needing a label; script/style CDATA inside a `<label>` counts as
  label text; an unclosed `<label>` at EOF escapes the label check. All three are
  **unreachable through today's assembler output** — the analyzer only ever sees
  assembled documents. Add the hidden-input exemption whenever `static_checks.py`
  is next touched.
- **Sidecar write `OSError` after the HTML write lands on the last-resort 500**
  (same exposure class as the pre-existing HTML write; pairs with §7 item 8).
- **The exported event carries redundant-but-equal `quality_report_file_sha256`
  and `quality_report_sha256`**; `ValidationFindingsPanel.test.tsx`'s fixture
  claims `report_schema_version: 1` while its findings carry `stage` — a hybrid
  that cannot exist on disk.
- **`report` reflects export-time gate state (the frozen sidecar) while `validate`
  reflects current state.** Now warned on stderr and documented; intentional —
  the sidecar is a *record of what shipped*, not a live view.
- **Note-level, accepted (from the Wave-4 triage):** the README's blanket "all
  five commands share one exit-code contract" sentence is slightly loose for
  `waive`/`unwaive` (the per-command bullets are precise); `_cmd_report`'s
  `ConfigError → 2` catch is a shade wider than "nonexistent run / no report";
  the e2e's page-wide axe scan is stricter than the plan asked for.

## 6. Surfaces confirmed clean

- **Runtime dependency boundary held.** `education_pipeline/` remains
  standard-library-only; `pyproject.toml` still declares `dev = ["pytest>=8"]` as
  the sole dev dependency. Every new component (`static_checks.py`, the quality
  report emitter, the waiver store) is hand-written stdlib. This is precisely why
  §7 item 12 (pytest-timeout) is an owner decision and not an implementer's call.
- **Write discipline.** All new writes are atomic (temp file + `os.replace`); the
  manifest and waivers file are serialized per topic; the sidecar is deterministic.
- **Determinism.** The export and its sidecar are byte-identical across two
  *independent workspaces* — the strongest form of the reproducibility claim, and
  the one actually tested.
- **Fail-closed under every ambiguity found.** Stale report → refuse. Stale waiver
  → gate closes. Corrupt waivers file on a **write** path → raise. Unparseable
  source → blockers, no document. The only paths that degrade gracefully are
  **read** paths, and that is deliberate.

## 7. Carried-forward triage from the Wave 4 outcome

The Wave-4 close deferred these to this audit. The list is reproduced **verbatim**
from the plan, then given a disposition. All twelve were re-verified against live
code during this audit and every one still reproduces.

> **Deferred to the post-milestone audit** (carry verbatim into the audit doc):
> no daemon DELETE/unwaive route (cockpit parity); `write_api` → private
> `runs._record_waiver` (promote a public method); `_validation_summary`'s flat
> `"draft"` default for stage-less findings; `report_state` ignores
> `report_schema_version` (recommendation: treat `< 2` as stale); `role="status"`
> live region on the findings badge; `_finalize_guide_v1`'s duplicate parse;
> heading-order rule tracks deepest-seen not previous (plan-level, owner policy
> call); `load_runtime_assets()` OSError → last-resort 500 on status polling;
> truncated-body handler hang (pre-existing, loopback+auth only);
> `_private_profile_values` field-selection spec paragraph; migrating older e2e
> specs onto `bootDaemon`; **pytest-timeout** (a lock-nesting regression still
> hangs CI silently — needs a new dev dependency, so issue-first per repo rules).

| # | Item | Verified at | Disposition |
| --- | --- | --- | --- |
| 1 | No daemon DELETE/unwaive route (cockpit parity) | no `do_DELETE` in `daemon/server.py` | **RESOLVED** — release-gate-hardening plan (2026-07-13), Task 5 |
| 2 | `write_api` → private `runs._record_waiver` | `write_api.py:145` | **RESOLVED** — release-gate-hardening plan, Task 4 |
| 3 | `_validation_summary`'s flat `"draft"` default | `read_api.py:164`, `:212` | **backlog** (NOT dead after #4 — see corrected §7.1: stale reports are still displayed, so the shims still fire) |
| 4 | `report_state` ignores `report_schema_version` | `runs.py:1218–1252` | **RESOLVED** — owner adopted §7.1; release-gate-hardening plan, Task 2 |
| 5 | `role="status"` live region on the findings badge | `RunBoardPage.tsx:152` | **RESOLVED** — release-gate-hardening plan, Task 6 |
| 6 | `_finalize_guide_v1`'s duplicate parse | `runs.py` `_finalize_guide_v1` +25/+30 | **backlog** |
| 7 | Heading-order tracks deepest-seen, not previous | `static_checks.py:52–54` | **RESOLVED** — owner adopted §7.2 with the markdown-offset fix; release-gate-hardening plan, Task 3 |
| 8 | `load_runtime_assets()` OSError → 500 on status polling | `guide_runtime/__init__.py:19–25` | **backlog** |
| 9 | Truncated-body handler hang (pre-existing) | `daemon/server.py` `_read_body` | **backlog** |
| 10 | `_private_profile_values` field-selection spec paragraph | `runs.py:1282–1309` | **RESOLVED by personalization Wave 0**, not this audit — see §8 (superseded) |
| 11 | Migrating older e2e specs onto `bootDaemon` | 5 specs still inline | **backlog** (opportunistic) |
| 12 | **pytest-timeout** | `pyproject.toml:33` | **RESOLVED** — owner adopted §7.3 option 1; release-gate-hardening plan, Task 1 |

**Notes on the non-decision items.**

- **#1 + #2 are one piece of work and #1 is the sharpest user-facing gap on the
  list.** The cockpit can *open* a gate (create a waiver) but cannot *re-close*
  one: a waiver recorded by mistake — with a wrong reason, or against the wrong
  finding — is unremovable from the UI, and the only recovery is the CLI or
  hand-editing the workspace. For a milestone whose entire premise is "you cannot
  silently ship bad content", a UI that can only ever loosen the gate is the wrong
  asymmetry. The fix is small and the two items share a diff: add
  `DELETE /v1/runs/{topic}/waivers/{finding_id}` over the existing
  `RunStore.remove_waiver`, and while there, promote a public method returning
  both the `WaiverResult` and the locked-write `WaiverSet` so `write_api` stops
  reaching into `runs._record_waiver`.
- **#3 is contingent on #4.** If the owner adopts the `< 2 is stale`
  recommendation, legacy stage-less findings self-heal on the first revalidation
  and this default becomes unreachable. Decide #4 first; #3 is then a deletion.
- **#5** is a real a11y defect on a shipped surface: `role="status"` is a live
  region, and with 5 s polling every count change re-announces to screen readers.
  A plain `span` with `aria-label` (or visually-hidden text) is the correct
  affordance. Cheap; the next milestone touches this page anyway.
- **#8 and #9 are both "the daemon degrades badly on an input it should reject
  cleanly"**, and both are loopback + token-gated. #8 needs a `try/except OSError
  → ConfigError` (or asset caching, which also erases the §5 per-poll perf note).
  #9 needs a socket timeout; it is pre-existing (reproduces at `d46406a`), and a
  buggy client — not only an attacker — can leak a handler thread forever.
- **#11** is test hygiene. Migrate a spec onto `bootDaemon` the next time that
  spec is edited for another reason; a dedicated migration commit is not worth it.

### 7.1 Owner decision — should a v1 report be treated as stale?

> **RULED 2026-07-13: adopted.** Implemented by the release-gate-hardening
> plan, Task 2 (`REPORT_SCHEMA_VERSION` constant; `report_state` reads any
> report whose `report_schema_version` is missing, non-integer, or `< 2` as
> `"stale"`). The "shims become dead code" claim below was **corrected** — see
> the amended paragraphs.

**The situation.** `report_state` (`runs.py:1218`) derives freshness purely from
content: it compares the report's recorded `guide_sha256` against the hash of the
approved source. It never looks at `report_schema_version`. So a **v1 report**
(pre-Wave-2: no stage attribution on findings) sitting against unchanged content
reports `"current"` **forever**. Nothing will ever prompt a revalidation, and the
run keeps its stage-less findings indefinitely — which is exactly the condition
that keeps compatibility shims #3 alive across three surfaces (CLI, daemon, web),
each with its own fallback for the missing `stage`.

**Recommendation on record: treat `report_schema_version < 2` as stale.** One
extra comparison in `report_state`. Legacy workspaces then self-heal: the run
shows the ordinary stale banner, the user clicks the re-run affordance that
already exists, and the report comes back at v2 with stage attribution.

*Correction (2026-07-13, at adoption):* the original text here claimed the three
stage-less-finding fallbacks "become dead code and can be deleted." **They do
not.** A stale report is still *displayed* — the CLI prints the on-disk body with
a stderr warning, and the cockpit renders it under the stale banner — so a v1
report on disk is still read and rendered, and the shims still fire until the
user actually revalidates. What the rule buys is a **sunset**: the report is
re-derived at v2 on the next validation instead of sitting "current" forever.
Deleting the shims remains a separate future cleanup, gated on being willing to
assert that no v1 reports exist anywhere.

**What the owner is actually deciding.** The cost is that any workspace holding a
v1 report is told it is stale on first sight after upgrade, even though its
*content* is unchanged and its findings are still substantively correct. That is a
one-time, self-clearing prompt with a one-click fix — but it is a visible "your
report is stale" on a run the user did not touch, and it is a deliberate widening
of what "stale" means: today the word means *the content moved*, and this would
also make it mean *the schema moved*. The alternative is to keep the shims
forever and accept that stage attribution is best-effort for legacy runs.

**Blast radius if adopted:** `report_state` only; no schema change, no migration
code. **Blast radius if declined:** without the sunset, a v1 report sits
"current" forever, so the three `"draft"`-defaulting shims must be preserved
indefinitely by anyone touching stage attribution — including the next
milestone, which extends the report schema again. (Adopting does not delete the
shims either — see the correction above — but it bounds their lifetime to
"until the next revalidation" instead of "forever".)

### 7.2 Owner decision — heading-order: deepest-seen or previous?

> **RULED 2026-07-13: adopted, coupled with the markdown-offset fix.** The
> owner chose previous-heading tracking AND changed the learner-markdown
> heading render offset from `+2` to `+1` in the same change (release-gate-
> hardening plan, Task 3). The offset fix is what makes the tightening
> shippable: without it, a section whose first block is a `rich_text` opening
> with `##` rendered `h2 → h4` — a real skip whose only remediation (`#`) is
> banned by `markdown.invalid_heading_level`, i.e. a blocking finding with no
> legal fix. With `+1`, `##` renders `<h3>` directly under the section's
> `<h2>`. The canonical fixture contains zero markdown headings and zero
> skips under the tightened rule, so its bytes and export SHA were unchanged
> (verified at landing).

**The situation.** `static_checks.py:52–54` implements exactly what the plan
specified: *no heading is more than one level deeper than the deepest heading seen
so far*, tracked via `self._deepest_heading = max(...)`. This is a **plan-level
weakness, not an implementation bug** — the implementer built what was asked.

Two documents pass this rule that a WCAG-style skip check would fail:

- `h1, h2, h3, …` then a later `h2 → h4` — the `h4` is only compared against the
  deepest heading *ever seen* (`h3`), not against the `h2` immediately before it,
  so a genuine one-level skip in that section goes unreported.
- A document whose **very first heading is `h4`** — there is no deepest-seen yet
  (`self._deepest_heading` is 0, and the guard short-circuits), so an outline that
  begins four levels deep passes clean.

**What the owner is actually deciding.** Whether `heading_order_valid` means
*"the document's heading depth never jumps ahead of the structure it has already
established"* (today's rule — a coarse well-formedness check) or *"no heading skips
a level relative to its predecessor"* (the accessibility rule users will assume it
is, given the name). These are different checks with the same name, and the second
is what an auditor reading the sidecar report will believe they are getting.

**Recommendation: switch to previous-heading tracking**, and treat a first heading
deeper than `h1` (or deeper than `h2`, if the shell owns the `h1`) as a skip.
Tracking the previous heading is a strictly smaller amount of state than tracking
the deepest.

**Cost of the switch, stated plainly:** it is a **gate-tightening change**.
Documents that pass today can begin to fail, and `structure.heading_order` is a
blocking rule — so this can newly refuse an export that previously shipped. It
therefore belongs at the *front* of a milestone (where the fallout is absorbed
deliberately), never as a drive-by fix. If the owner would rather not tighten the
gate at all, the honest alternative is to **rename the rule** so it stops implying
an accessibility guarantee it does not make.

### 7.3 Owner decision — pytest-timeout (issue-first per repo rules)

> **RULED 2026-07-13: option 1 adopted — add the dependency.** The owner ruled
> that the dev-dependency line yields here: the codebase deliberately adopted
> hang-on-error as a safety mechanism and needs a hang detector to make it
> debuggable. Implemented by the release-gate-hardening plan, Task 1
> (`pytest-timeout` in the dev extra; global 60 s per-test ceiling via
> `addopts = "-q --timeout=60"` — the CLI form rather than the bare `timeout`
> ini key, because pytest-timeout 2.4.0 does not surface the ini key through
> `config.getoption`, which the guard test asserts). Runtime stays
> stdlib-only.

**The situation.** `CLAUDE.md` states plainly: `pytest` is the sole dev
dependency, and runtime dependencies require prior discussion in an issue.
`pyproject.toml:33` still reads `dev = ["pytest>=8"]`. Adding `pytest-timeout` is
therefore **not** an implementer's call, which is why it has ridden three
consecutive wave triages without being fixed.

**Why it keeps coming back.** The manifest-lock contract (§4) is enforced by
deadlock *on purpose* — nesting a public wrapper inside the lock is designed to
hang rather than to silently lose updates. That was the right trade. But the
consequence is that **a lock-nesting regression does not fail CI; it hangs CI**,
burning the job's full wall-clock budget and reporting a timeout with no failing
test to point at. The very safety property the design depends on is the thing that
makes its failure mode maximally expensive to diagnose. Wave 0 called this out and
it has been true at every gate since.

**What the owner is actually deciding:** whether the "one dev dependency" rule is
absolute, or whether it yields to a case where the codebase has *deliberately*
adopted hang-on-error as a safety mechanism and now needs a hang detector to make
that mechanism debuggable.

**Options.**

1. **File the issue and add `pytest-timeout`** (recommended): `dev = ["pytest>=8",
   "pytest-timeout"]` plus a global `timeout` in `[tool.pytest.ini_options]`. A
   nesting regression becomes a crisp per-test failure naming the exact test. This
   is a **dev**-dependency change only; the runtime stdlib-only guarantee — the one
   that actually matters for users installing the package — is untouched.
2. **Stdlib-only alternative:** a `faulthandler.dump_traceback_later()` call in a
   session-scoped `conftest.py` fixture. No new dependency, and it dumps every
   thread's stack on hang, which is genuinely useful for a *lock* bug. It is
   cruder (it aborts the process rather than failing one test) and it is bespoke
   code the repo must maintain.
3. **Accept the hang.** Defensible only if CI hangs are cheap and rare. Note that
   the failure mode is silent and the diagnosis is manual every single time.

Option 2 deserves real consideration: it is the option the repo's own constraints
point at, it costs nothing, and for a deadlock it arguably gives *better*
diagnostics than pytest-timeout does. If the owner wants to hold the dependency
line, it is not a consolation prize.

## 8. ~~Draft spec paragraph~~ — SUPERSEDED (2026-07-13, by personalization Wave 0)

> **This section is SUPERSEDED. Do not insert the draft paragraph below into
> any spec.** Personalization Wave 0 (`e5b0f17`) replaced the field-selection
> policy this section documented. The **policy of record** is now
> `education_pipeline/privacy.py`: `_PROFILE_FIELD_SENSITIVITY` (the per-field
> tier map), `SensitivityTier`, and `profile_private_values`. Carried-triage
> item #10 is therefore **resolved by personalization Wave 0**, not by the
> release-gate-hardening batch or by ratifying this section.
>
> **Recorded divergence — owner policy question, deliberately NOT "fixed" by
> the hardening batch.** The new policy screens **HIGH *and* MEDIUM** tier
> fields, and MEDIUM includes `learning_goals`, `preferred_examples`,
> `examples_to_avoid`, and `adjacent_domains`. The draft below had
> deliberately **excluded** exactly those four, on the stated grounds that
> they are pedagogical inputs the guide is *supposed to act on*: a course
> built for a learner whose goal is "ship a Rust CLI" should contain that
> phrase, and denylisting it makes the gate refuse personalization that is
> working correctly. Verified against the shipped code at the time of this
> note: a profile with `learning_goals=("ship a Rust CLI tool",)` yields a
> denylist containing `'ship a rust cli tool'`, and `privacy.
> exact_private_value` is a **blocking** finding. No test pairs a goal-bearing
> profile with a guide that quotes it, so the refusal is latent — it fires on
> real runs, not in the suite. Whether MEDIUM should include the goal-shaped
> pedagogical fields is an owner call to make within the personalization
> milestone; it is recorded here so it is decided rather than discovered.

The historical draft paragraph is retained below **for the record only** (it is
the text the divergence note above diffs against):

> **Private-value selection for `privacy.exact_private_value`.** When a run has an
> attached learner profile, `RunStore._private_profile_values` derives the denylist
> the guide validator screens content against. The selection policy is
> **identity-bearing free text in; categorical preference values out.** Included:
> `target_learner` (always), `prior_education`, `prior_experience`,
> `professional_experience`, `current_skill_level`, and every entry of
> `sensitive_areas` and `accessibility_constraints`. These are free-text fields
> that can carry a name, employer, cohort, institution, diagnosis, or other
> identifying detail, and a guide that reproduces one verbatim has leaked the
> learner into the artifact. Excluded: the categorical and enumerated preference
> fields (reading level, pace, tone, `explanation_style`, `preferred_modalities`,
> `practice_style`, and the rest of the pedagogy groups), which describe *how* to
> teach rather than *who* is being taught; a guide that reads "worked examples
> first" has not disclosed anything about the learner. Also excluded, deliberately:
> `publishable_summary`, which is by definition the one profile-authored string the
> owner has opted into publishing — screening it would refuse the very content the
> privacy block exists to permit.
>
> **Two judgment calls are worth naming, because they are the ones a reader will
> question.** First, the goal-shaped free-text tuples — `learning_goals`,
> `preferred_examples`, `examples_to_avoid`, `adjacent_domains` — are free text but
> are **not** screened. They are pedagogical *inputs the guide is supposed to act
> on*: a course built for a learner whose stated goal is "ship a Rust CLI" should
> absolutely contain that phrase, and denylisting it would make the gate refuse the
> personalization working correctly. The policy screens fields that identify the
> *person*, not fields that direct the *course*. Second, the denylist is exact-match
> on the field value (fingerprinted in the finding, never echoed into the report), so
> it detects verbatim reproduction, not paraphrase or inference. A model that
> *describes* the learner's employer without quoting the field will not trip this
> rule. This is a deliberate floor, not a ceiling: `exact_private_value` is a
> deterministic backstop against copy-through, and semantic leak detection is the
> job of the model-based audit stage, not of this check.
>
> **Consequence — draft-phase reports are now profile-sensitive.** The denylist is
> passed at both the `draft` and `final` phases (via `_compute_phase_report`), and
> `privacy.exact_private_value` is a **waivable blocker attributed to the `draft`
> stage**. A draft that quotes its attached profile verbatim therefore blocks at
> draft, where the leak was introduced and where the repair is cheapest, rather than
> surfacing only at export. This means a previously-passing draft can newly block
> once a profile is attached. That is intended. It is fail-closed and waivable, and
> waivers are hash-bound, so accepting a disclosed value never carries silently into
> changed content.

**Note for the ratifier.** This paragraph documents a policy the *next* milestone
is already scoped to replace: the personalization design (§"Current state") calls
this selection out by name as "not backed by a complete field-classification
policy" and commits to replacing it with a per-field sensitivity classification —
**without regressing the shipped refusal path**. Ratifying this paragraph is
therefore not a long-term commitment to these seven fields; it is recording the
contract the acceptance suite currently pins, so that the replacement can be
diffed against something explicit rather than against an implementer's inference.

## 9. Next-milestone proposal

**Proposed milestone: "P1 — Make personalization visible and safe"** (PRD §10),
with a small Wave-0 hardening batch drawn from this audit's triage — mirroring how
this milestone's Wave 0 absorbed the model-plan audit's findings, and how that
milestone's Wave 0 absorbed the one before it.

**Why this one.** It is the PRD's own next item: with release gates delivered, the
P0 tier is closed, and the PRD explicitly sequences personalization waves 3+ behind
*this* milestone's Wave 2 (stage attribution + sidecar report) — a dependency now
satisfied. It is also the milestone that finishes what Wave 4 started by accident.
Wiring `private_values` proved the privacy refusal path works, but it did so on an
**implementer-derived field list with no backing policy** (§8): the product now
enforces a privacy guarantee whose definition of "private" was inferred rather than
specified. The personalization spec already names this gap and commits to replacing
it with a real per-field classification. Leaving that inversion — enforcement ahead
of policy — standing for another milestone is the least comfortable thing in this
audit. Every alternative (first-run experience, blueprint pedagogy) sits behind it
in the PRD's ordering and none of them close it. The design is specified
(`2026-07-12-personalization-design.md`, revised 2026-07-13 against the delivered
baseline) and a five-wave plan is committed (`2026-07-13-personalization.md`), so
the milestone is ready to execute rather than needing to be invented.

**Wave 0 hardening batch (from this audit):** the DELETE/unwaive route plus the
public `record_waiver` promotion (#1, #2 — one diff, and the cockpit's
open-but-never-close asymmetry is the sharpest gap on the list); the
`role="status"` live-region fix (#5); and the `report_schema_version` decision
(#4), which should land **before** the report schema is extended again — this
milestone extends it, and doing so on top of an unresolved v1-compatibility
question means shipping a second generation of the same shims. §7.2 (heading-order)
and §7.3 (pytest-timeout) need owner rulings before they can be scheduled at all;
if §7.2 is adopted, it belongs in Wave 0 too, because it tightens a blocking gate
and the fallout must be absorbed deliberately rather than discovered mid-milestone.

**Exit criterion (from PRD §10):** profiles are created and edited in the cockpit
without touching files; every profile field has an application-owned sensitivity
classification; publication permission is enforced independently of that
classification; the final-course record carries a machine-checkable
goal-to-content trace plus a model audit of tailoring quality; and the cockpit
shows "why this course fits you" without private detail entering the exported
guide or its public quality report.

**Deferred with rationale:** the §5 accepted limitations stay accepted (unreachable,
loopback-benign, or documented intent) and should be re-triaged only if their
preconditions change. The §7 backlog items (#3, #6, #8, #9, #11) are cleanup with no
user-visible consequence; fold each into the next diff that touches its file rather
than scheduling it. #3 in particular should simply be **deleted** if #4 is adopted.
