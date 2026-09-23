# Phase 5 — Diagram block (schema 1.2)

**Goal:** Let a guide show a picture without letting a model write code. Learner profiles already carry `preferred_visual_aids` and `diagram_frequency`, and the shipped example asks for flowcharts, concept maps and comparison tables, but the guide can render none of them: the export CSP is `img-src 'none'` and the schema has no visual block. After this phase, guide schema 1.2 adds one non-interactive block, `diagram`, whose content is plain data (nodes, edges, rows) in four kinds: flow, concept map, comparison and timeline. The maintained runtime draws it as SVG (or, for comparison, a table) with theme tokens, deterministic layouts and alt text derived from the data. A text version is always rendered on the server, so the guide works without JavaScript and in print. The CSP does not change.

**Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`), tier-1 item B and "Build plan · Phase 5". Threads are numbered as there. Line anchors are as of `2a1aa50` (post Phase 4, PR #41 merged).

**Method:** strict TDD. One subagent writes the failing tests and a different one makes them pass. The manager reviews diffs, never transcripts. Every thread ends on the full pytest suite green. `npm run build` and `npm run test` run when `web/` changes, and the Playwright guide specs (`guide-runtime.spec.ts` and `guide-progress.spec.ts`) run when the runtime or the document assembler changes. The shipped example export is byte-pinned (`tests/test_example_project.py`), so any thread that touches `runtime.js`, `runtime.css` or `document.py` rebuilds it with `python3 scripts/build_example.py`. A thread that grows past ~800 changed lines or 12 files is split.

**Baseline at open:** pytest 2201 passed, 1 skipped (Python 3.11). vitest 627. `npm run build` clean. Playwright guide specs 103/103 (local runs use `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`). `runtime.js` is 1991 lines and `runtime.css` 164.

**Design spec:** [`../specs/2026-09-23-diagram-block-design.md`](../specs/2026-09-23-diagram-block-design.md)
**Audit ledger:** [`../specs/2026-09-23-phase-5-diagrams-post-milestone-audit.md`](../specs/2026-09-23-phase-5-diagrams-post-milestone-audit.md)

## Threads

| ID | Thread | Exit criteria | Status |
| --- | --- | --- | --- |
| T50 | Design spec | The spec settles block shape per kind, limits, validation rules and codes, version gating, run version selection, server-rendered text version, runtime layouts, CSP-safe styling, prompt lines and profile mapping. An adversarial review has been folded in and every line reference checked. | - [ ] |
| T51 | Model, parse, normalize, validate, project | `Diagram` dataclass in the `Block` union. Parser gated on schema 1.2. Normalizer. Validation rules and codes from the spec. Canonical JSON round-trip. Markdown projection as a text rendering. `SUPPORTED_GUIDE_SCHEMA_VERSIONS` gains 1.2 wherever it is restated. A 1.1 document carrying a diagram is rejected. Fixture `tests/fixtures/guides/feedback-loops.diagrams.guide.json` covers all four kinds. Unit tests cover every rule. | - [ ] |
| T52 | Prompts and personalization | Schema 1.2 reference lines for the diagram block. New runs get schema 1.2. Blueprint guidance says when to use each kind. Profile visual-aid preferences map to fixed instructions and add no new echo of profile values. Prompts for 1.0 and 1.1 contracts stay byte-identical (existing SHA pins untouched). There are new snapshot pins for 1.2. | - [ ] |
| T53 | Runtime renderer: flow and timeline | `document.py` renders the `<figure>` with a server-side text version. The runtime draws flow as a layered layout (longest-path rank, back edges routed as curves so feedback loops work, arrowheads) and timeline as a linear layout. Styling comes only from classes in `runtime.css` and theme tokens, with no inline style. `RUNTIME_VERSION` becomes 1.2, and schema 1.2 is accepted by the runtime and the document assembler. e2e renders the fixture in both themes, and axe is clean. | - [ ] |
| T54 | Runtime renderer: concept map and comparison | Concept map uses a hub-plus-ring radial layout with edge labels. Comparison is a styled server-rendered table (no SVG). Exit criteria are the same as T53. | - [ ] |
| T55 | Cockpit and export | The cockpit preview and JSON tree show diagrams (preview goes through the server renderer). Static checks cover the new figure markup. The export sidecar records runtime 1.2. The CSP string is unchanged. There are tests in `test_guide_static_checks.py`, `test_guide_document.py` and the cockpit unit tests where anything is touched. | - [ ] |
| T56 | Fixture, docs, audit | The example course gains two diagrams (a flow with a feedback loop and a comparison) and moves to schema 1.2. `build_example.py` shows no diff. Docs (`interactive-guides.md`, the schema spec §2/§16/§18 and the runtime spec) are updated. The audit ledger and phase closeout are written. | - [ ] |

## Order and parallelism between threads

The order is T50 → T51. After T51, T52 (prompts, engine only) and T53 (document assembler and runtime) touch disjoint files and run in parallel. T54 follows T53 because both grow the same renderer module in `runtime.js`. T55 and T56 follow.

## Decisions settled at open

1. **Data, never code.** A diagram is JSON data. The model never supplies SVG, CSS, coordinates, colours or sizes. Layout is computed deterministically by the maintained runtime from the data alone, so the same guide draws the same picture every time.
2. **Schema 1.2 is 1.1 plus `diagram`.** 1.2 accepts everything 1.1 accepts, including the optional personalization annotations, plus one block type. The parser and the runtime reject a diagram in a 1.0 or 1.1 document as an unknown block type, which is the §18 rule that additive fields need a version bump rather than silent acceptance. Every restated copy of the supported-version set gains 1.2 (`model.py:11`, `guide_runtime/__init__.py:9`, `parse.py:226`, `contract.py:147`, `runs.py:2262-2283`, `runtime.js:1950`). Per-feature gates written as `== "1.1"` become "1.1 or later" (`parse.py:228`, `prompts.py:733,785`).
3. **New runs get 1.2; existing runs keep their pinned version.** A run's contract already pins its schema version, so existing workspaces keep producing 1.0 or 1.1 prompts byte for byte, and their SHA pins do not move. New runs get 1.2 whether or not a profile exists, so every new course can use diagrams. The 1.1 goal-annotation prompt lines appear only when a profile snapshot exists (today they appear for any non-default version). A 1.2 run without a profile is not asked about goal ids.
4. **Four kinds, two shapes.**
   - `flow` and `concept_map` are graphs: `nodes` (`id`, `label`, optional `detail`) and `edges` (`from`, `to`, optional `label`).
   - A `concept_map` names one `hub` node.
   - `timeline` is an ordered `events` list (`id`, `when`, `label`, optional `detail`) drawn in the given order.
   - `comparison` is `items` (the columns: `id`, `label`) and `criteria` (the rows: `id`, `label`, `values` keyed by every item id).
   - Kind values follow the snake_case style of existing enums or the hyphen style of callout kinds. The spec picks one and says why.
   - Every diagram has `id`, `title`, optional `caption`, optional `outcome_ids` (minimum 0, like callouts) and optional `source_ids`.
5. **Hard limits** (validation errors, not warnings), which keep layouts legible without a layout engine:
   - Graph kinds have 2–12 nodes. A flow has at most 16 edges and a concept map at most 12.
   - A timeline has 2–10 events.
   - A comparison has 2–4 items and 1–8 criteria.
   - A label is at most 48 characters, an edge label or `when` at most 32, and a `detail` or cell at most 240.
   - Labels are plain text, not Markdown. `detail`, `caption` and cells use the existing inline Markdown subset.
   - The spec may adjust a number with a reason. It may not remove the limits.
6. **Integrity rules.**
   - Ids are unique within the diagram.
   - Every edge endpoint and the hub resolve to a node.
   - No self-edges, and no duplicate `from`/`to` pairs.
   - A comparison row has a value for every item and no extra keys.
   - Every concept-map node is connected to the hub through edges, ignoring direction.
   - A flow may contain cycles. Feedback loops are the example course's subject, so cycles are allowed, and the layout draws back edges as curves.
   - A flow node with no edges is an error.
   - Diagram ids share the guide-wide block id namespace.
7. **Coverage.** A diagram teaches: it counts toward an outcome's `taught` coverage like `rich_text` and `callout`, and it is never interactive. The rule that every module has at least one interactive block is unchanged. No diagram is required anywhere, and no rule demands one.
8. **Server-rendered text version, runtime-drawn picture.**
   - `document.py` renders `<figure class="diagram" data-diagram-kind="…" id="…">` holding the title, a text version and the caption in `<figcaption>`. The text version is an ordered list of steps and edges for flow, nested lists for a concept map, an ordered list for a timeline, and a real `<table>` with `<th scope>` headers for comparison. The figure contains no heading elements, so the heading-order static check is unaffected.
   - The runtime inserts an `<svg role="img">` before the text version, with `<title>` and `<desc>` derived from the data. The text version then collapses into a `<details>` "Text version" disclosure that stays in the DOM.
   - Comparison gets no SVG: the table is the rendering, and the runtime only adds styling hooks.
   - Without JavaScript the text version is the diagram.
   - The runtime lays out the data embedded in `guide-data`, not the text version.
9. **CSP unchanged.** The SVG is built with `createElementNS` and styled only by classes defined in `runtime.css`, using the existing theme tokens. There are no `style` attributes, no `<style>` element inside the SVG, no `<image>`, no `innerHTML` and no `foreignObject`. `default-src 'none'; img-src 'none'` stays, and the hashed style and script sources stay. A test pins the CSP string.
10. **Layouts.**
    - **Flow:** layered by longest path from the sources. Cycles are broken at back edges, found by a depth-first search in document order. Nodes within a layer are ordered by document order. Layers run top to bottom, and straight edges use arrowheads. Back edges are drawn as curves on the right-hand side.
    - **Timeline:** one horizontal axis, with events evenly spaced in the given order and labels alternating above and below. It becomes a vertical list below a width breakpoint.
    - **Concept map:** the hub is at the centre and the other nodes are placed evenly on one ring, in document order starting at 12 o'clock, with edge labels at the midpoints.
    - **All kinds:** labels wrap by character count into at most three lines, and the `viewBox` scales to fit. Output is byte-deterministic for a given guide.
11. **Profile preferences reach prompts as fixed text.** The profile context already carries `preferred_visual_aids` and `diagram_frequency` verbatim (`profiles.py:359-360`), and that is unchanged. For 1.2 prompts, a deterministic keyword map (for example "flowchart" or "process" to `flow`, "concept map" to `concept_map`, "comparison" or "table" to `comparison`, "timeline" to `timeline`) selects which fixed kind-guidance lines to emphasise. The added lines contain only fixed text and kind names, never a profile string. With no profile, the generic guidance applies. Validation findings about diagrams never echo profile values (`validation.py:78`).
12. **Runtime version 1.2.** `RUNTIME_VERSION` goes 1.1 → 1.2 in T53 (`guide_runtime/__init__.py:8`, `runtime.js:1954`). The progress store and progress file are untouched, because diagrams are not interactive and store nothing.

## Anchors at open

- Model and parse:
  - `guides/model.py:11,15` (versions), `:68-133` (blocks and the `Block` union).
  - `guides/parse.py:37-38` (`MAX_TEXT`, `BLOCK_TYPES`), `:221-228` (version gate), `:485-564` (`_check_block`), `:692` (`_refs`), `:754-820` (references and coverage), `:874` (`_normalize_block`).
- Validation: `guides/validation.py:78` (no echo), `:114-179` (rules), `:424` (`_text_fields`), `:806-820` (block loop).
- Projection and document:
  - `guides/canonical.py:35-60`.
  - `guides/projection.py:83-120`.
  - `guides/document.py:75-123` (Markdown subset), `:232-249` (`_INTERACTIVE_TYPES`, `_block`), `:254-258` (version checks), `:285` (CSP), `:338`.
- Static checks: `guides/static_checks.py:19-73,113-117`.
- Runtime:
  - `runtime.js:326` (`SCORABLE_TYPES`), `:1376` (`ENHANCERS`), `:1410` (`enhanceBlocks`), `:1950-1956` (version checks), `:1985`.
  - `guide_runtime/__init__.py:8-9`.
- Prompts:
  - `prompts.py:439-464` (spec contract), `:493-515` (`_GUIDE_SCHEMA_REFERENCE_LINES`).
  - `:556,605,1007,1185,1763,1925` (uses), `:682-733` (version helpers), `:785`.
  - `blueprints.py:20-32`.
- Runs: `runs.py:194-199,497-502,2262-2283`.
- Profiles: `profiles.py:76-77,359-360`, `guides/personalization.py:150-151`.
- Tests:
  - `tests/test_guide_parse.py:253,278`, `tests/test_prompts.py:575-582`.
  - `tests/test_example_project.py:84-87,158`.
  - `web/e2e/guide-runtime.spec.ts:13-36,66-87`.

## Closeout log

(One line per thread as it lands: what changed, test counts, accepted limitations.)
