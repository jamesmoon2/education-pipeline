# Diagram Block (Guide Schema 1.2) — Design

- **Date:** 2026-09-23
- **Status:** Draft for owner review — implementation plan at
  [`docs/superpowers/plans/2026-09-23-phase-5-diagrams.md`](../plans/2026-09-23-phase-5-diagrams.md)
- **Branch:** `claude/p5-engineering-manager-twgrxe` (one local branch per thread, merged in)
- **Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`), tier-1 item B and
  "Build plan · Phase 5"
- **Related:** interactive-guide schema
  ([`2026-07-11-interactive-guide-v1-schema.md`](2026-07-11-interactive-guide-v1-schema.md)),
  runtime and export
  ([`2026-07-11-interactive-guide-v1-runtime-export.md`](2026-07-11-interactive-guide-v1-runtime-export.md)),
  validation pipeline
  ([`2026-07-11-interactive-guide-v1-validation-pipeline.md`](2026-07-11-interactive-guide-v1-validation-pipeline.md)),
  per-module drafting
  ([`2026-09-18-per-module-drafting-design.md`](2026-09-18-per-module-drafting-design.md)),
  Phase 4 mastery audit
  ([`2026-09-19-phase-4-mastery-post-milestone-audit.md`](2026-09-19-phase-4-mastery-post-milestone-audit.md))

## Summary

Learner profiles already carry `preferred_visual_aids` and `diagram_frequency`,
but a guide cannot show a picture: the schema has no visual block and the export
CSP is `img-src 'none'`. This design adds schema **1.2** = 1.1 plus one
non-interactive block type, `diagram`, whose content is plain data in four kinds:

```
flow         nodes + directed edges (cycles allowed)       -> layered SVG, loops as curves
concept_map  hub + nodes + edges (all connected to the hub) -> hub-and-ring SVG
timeline     ordered events                                -> axis SVG (horizontal / vertical)
comparison   items (columns) x criteria (rows)             -> server-rendered <table>, no SVG
```

The server (`document.py`) always renders a complete **text version** inside a
`<figure>`, so a guide works without JavaScript and in print. The maintained
runtime reads the same data from `guide-data`, lays it out deterministically,
inserts an `<svg role="img">` built with `createElementNS` and styled only by
`runtime.css` classes, and folds the text version into a `<details>` disclosure.
The model never supplies coordinates, sizes, colors, SVG or CSS. The CSP string
does not change.

## Goal

A new run can author diagrams; an exported guide draws them identically every
time, in both themes, accessibly, with a text equivalent that is always present.
Existing 1.0 and 1.1 runs, prompts, canonical bytes and validation results are
unchanged.

**Exit criterion.** `tests/fixtures/guides/feedback-loops.diagrams.guide.json`
(schema 1.2, one diagram of each kind) parses, validates with no diagram
findings, round-trips through canonical JSON, projects to Markdown, assembles to
a document whose static checks pass, and renders in Playwright with four
`figure.diagram` elements in the states `drawn`, `drawn`, `drawn`, `table`
(flow, concept map, timeline, comparison), axe-clean in light and dark themes.
A new run created with `create_run(topic)` records `interactive_guide 1.2`.
The 1.0 no-blueprint prompt SHA pins (`tests/test_prompts.py:576-582`) do not
move. The example course ships two diagrams and `build_example.py` shows no
diff.

## Current state (verified 2026-09-23 against `2a1aa50`, post Phase 4)

Every anchor below was read at `2a1aa50`. Where the plan's anchor is off by a
line, the verified one is given.

- **Versions.** `SUPPORTED_GUIDE_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})`
  (`guides/model.py:11`); `DEFAULT_GUIDE_SCHEMA_VERSION = "1.0"` (`model.py:15`)
  means "assumed when a source does not name one" and is used for unparseable
  reports (`validation.py:745,762`, `runs_reports.py:549`), so it must stay `1.0`.
  The runtime restates the set (`guide_runtime/__init__.py:9`) next to
  `RUNTIME_VERSION = "1.1"` (`:8`), and again in JS (`runtime.js:1950`,
  runtime check `:1954`). `parse.py:219-227` gates on the model set with a
  hard-coded message naming `'1.0' and '1.1'`; `parse.py:228` is the one
  per-feature gate in the parser (`annotations_allowed = schema_version == "1.1"`).
  `contract.py:143-149` gates the spec contract with a hard-coded message.
- **Runs.** `ContentContract.interactive_guide_v1()` / `_v1_1()` (`runs.py:193-199`).
  `create_run` picks `_v1_1()` when a profile snapshot file exists at manifest
  creation, else `_v1()` (`runs.py:497-503`, docstring `:467`).
  `_validate_content_contract` (`runs.py:2261-2272`) and `_guide_content_type`
  (`runs.py:2275-2280`, 1.0 constant at `:133-135`) enumerate versions. Spec
  approval refuses a contract block whose `guide_schema_version` differs from
  the run's (`runs.py:1998-2003`); the **guide JSON's** `schema_version` is not
  compared with the run contract anywhere (decision 13 adds the check). CLI `create`
  prints a hard-coded `(interactive_guide 1.0)` (`cli.py:489`, help `:219`) even
  for profiled 1.1 runs.
- **Blocks.** Six dataclasses and the `Block` union (`model.py:67-135`).
  `BLOCK_TYPES` (`parse.py:38-45`) is also imported by `contract.py:17` to
  validate outline `interaction_types` (`contract.py:249-256`). `_check_block`
  (`parse.py:485-572`) has no version parameter. `_normalize_block`
  (`parse.py:874-921`) falls through to `Reflection` for any unmatched type.
  Coverage: `taught` counts `rich_text`/`callout` (`parse.py:813-814`), the
  interactive set is fixed at `:788`.
- **Ids.** `_Checker.identifier` registers every id — including choice and
  reveal-step ids — in one guide-wide namespace (`parse.py:158-173`); the
  schema spec states the same (§2). `canonical._collect_ids`
  (`canonical.py:249-268`) walks every `id` key recursively to detect
  cross-module collisions before assembly.
- **Canonical form.** `guide_to_dict` (`canonical.py:35-48`) is a generic
  dataclass walk keyed by `field.name`, dropping `None` and, by name only,
  empty `serves_goals`/`goal_exclusions` (`:12`). Nothing else is special-cased.
  `canonical_guide_bytes` sorts keys (`:51-59`). Parse does **not** write the
  stripped text back: `_Checker.text` returns a stripped copy for checks only
  (`parse.py:113-145`), and `normalize_guide` reads the raw values.
- **Validation.** `RULES` (`validation.py:114-174`); a parse diagnostic whose
  code is not in `RULES` is remapped to `schema.invalid_value`
  (`validation.py:246-269`), so every new parse code needs a `RULES` entry.
  `_text_fields` (`validation.py:424-433`) walks dataclass fields by
  `field.name` and does not understand mappings. The block loop that re-checks
  in-memory `Guide` inputs is `validation.py:819-833`; its
  `source.missing_for_required_claim` check is limited to `RichText`/`Callout`
  (`:833`). Reading time uses
  `READING_TIME_BLOCK_SECONDS.get(type, 0)` (`validation.py:90-97,542`), and its
  word count is `_text_fields` over **every** string field, ids, `type` and
  `kind` included (`:537`); the constants dict is pinned by
  `tests/test_guide_validation.py:419`. The same `_text_fields` output feeds
  the privacy, placeholder and prompt-leak scans (`:787-812`). The optional
  audit fingerprints a block with `dataclasses.asdict` (`guides/audit.py:524`),
  i.e. by Python field names — deterministic, never user-visible.
  `CalibrationContext`'s docstring states the no-echo rule (`validation.py:77-78`).
- **Projection / document.** `_project_block` ends in `assert isinstance(block,
  Reflection)` (`projection.py:83-119`). `document._block` raises
  `GuideDocumentError("unsupported block type: …")` for unknown types
  (`document.py:235-249`); every block is `<article class="block {type}" id>`.
  `_inline` (`document.py:54-72`) is the inline Markdown subset (code, links,
  strong, em). `_all_ids` (`document.py:125-135`) collects `choices`/`steps`
  ids by attribute name. The CSP is built at `document.py:285`; `guide-data`
  is `guide_to_dict(public projection)` (`:286`). No test pins the CSP string.
- **Static checks.** `_Analyzer` (`static_checks.py:36-89`) checks control
  labels and heading order only.
- **Runtime.** `ENHANCERS` (`runtime.js:1376-1381`) is interactive-only and is
  dispatched over `[data-interactive="true"]` (`enhanceBlocks`, `:1410-1424`).
  Boot (`:1941-1990`) calls `enhanceCourseControls(guide)` (`:1967`) then
  `enhanceBlocks()` (`:1968`). Results and review walk only `SCORABLE_TYPES`
  (`:326`, `:363-365`, `:601-603`). Storage keys use the schema **major**
  (`:44-50`), so a 1.2 guide keeps the `v1` key space.
- **Prompts.** `_GUIDE_SCHEMA_REFERENCE_LINES` (`prompts.py:493-515`) name "the
  six registered block types"; so do `_GUIDE_JSON_QUALITY_HEAD_LINES` (`:538`),
  the repair lines (`:613`), `_MODULE_DRAFT_QUALITY_LINES` (`:1084`),
  `_MODULE_REPAIR_QUALITY_LINES` (`:1481`) and `_SECTION_REPAIR_QUALITY_LINES`
  (`:1521`); the outline contract lines (`:474`) do too, but they are about
  `interaction_types` and are never versioned. Every guide-JSON output list
  reaches the model through `_versioned_lines` (`:691-693`), directly (module
  draft `:1185`, module repair `:1763`, section repair `:1925`) or via
  `_guide_json_output_lines` (`:700-716`; callers `:938`, `:1443`, `:1765`,
  `:1927`). The module-draft prompt applies `_versioned_lines` **twice** to its
  schema reference (`:1185`, then again through `:1229-1231`). The skeleton
  embeds the **unversioned** reference (`:1007`) inside its output lines, which
  then pass through `_versioned_lines` once (`:1050-1054` → `:938`), so every
  §8.2 rewrite reaches the skeleton prompt too. QA and fact-check prompts take
  no schema version and embed no schema reference, so nothing in this design
  reaches them. The only prompt SHA pins that exist are the five **1.0**
  no-blueprint pins (`tests/test_prompts.py:576-582`) and the legacy pins
  (`:131-138`); **no 1.1 prompt is SHA-pinned today** (1.1 tests assert
  substrings only, e.g. `:1077-1078`), which is why §8.5 adds a matrix.
  `_guide_json_output_lines` appends the goal-annotation lines for every
  version other than `1.0` (`:704-716`) and does not know whether a profile is
  attached. `_private_personalization_lines` (`:733`) and
  `_profile_without_authoritative_goals` (`:785`) gate on `!= "1.1"`. The
  `profile` argument each compiler receives is the attached snapshot or `None`
  (`runs_personalization.py:129-131`, callers `runs.py:855,1442,…`,
  `runs_draft_units.py:248,403`), so `profile is not None` is exactly
  "a profile snapshot exists".
- **Profiles.** `LearnerPreferences.preferred_visual_aids` / `diagram_frequency`
  (`profiles.py:74-75`) are echoed verbatim into the profile context
  (`profiles.py:359-360`) and count toward the `pacing` facet
  (`guides/personalization.py:150-151`).
- **Blueprints.** `Blueprint` is a frozen dataclass without defaults
  (`blueprints.py:19-32`); keyword matching uses `\b…\b` over `.lower()`ed text
  (`blueprints.py:416`).
- **Cockpit.** `JsonTreeView` is a generic JSON walk (`JsonTreeView.tsx:35-76`);
  `StageContentView` picks it by `contentType.includes("json")`.
  `CanonicalGuidePreview` posts the approved repair text to
  `/v1/guide-preview` (`CanonicalGuidePreview.tsx:78-91`), which parses and
  calls `assemble_guide_document(mode="preview")` (`daemon/server.py:971-990`);
  `GuidePreviewFrame` renders it in a `sandbox="allow-scripts"` iframe
  (`GuidePreviewFrame.tsx:83-95`). `ResponseEditor` only treats the **1.0**
  guide content type as a guide (`ResponseEditor.tsx:13-14,42`) — a latent gap
  already true for 1.1 runs — and `StageContent.content_type` names only the
  1.0 guide type (`web/src/api/types.ts:358-361`).
- **Example.** `scripts/build_example.py:82` calls `create_run(TOPIC_ID)` with a
  profile attached, so the example is 1.1 today; `responses/spec.md:21` pins
  `"guide_schema_version": "1.1"`. The example profile asks for
  `preferred_visual_aids = ["concept maps"]`.

## Decisions (subject to owner review)

Plan decisions 1–12 are adopted. Refinements, each with its reason, are marked
**(refined)**; decisions I think may be wrong are raised in Open questions, not
changed.

1. **Data, never code** (plan 1). Adopted.
2. **Schema 1.2 = 1.1 + `diagram`** (plan 2). The model gains two named
   feature sets so no gate is written as a string comparison:
   `ANNOTATION_SCHEMA_VERSIONS = frozenset({"1.1", "1.2"})` and
   `DIAGRAM_SCHEMA_VERSIONS = frozenset({"1.2"})`, plus
   `LATEST_GUIDE_SCHEMA_VERSION = "1.2"`. **(refined)** `BLOCK_TYPES` stays the
   six 1.0 types, and `DIAGRAM_BLOCK_TYPE = "diagram"` is added beside it,
   because `contract.py` reuses `BLOCK_TYPES` for outline `interaction_types`
   and a diagram is not an interaction to plan.
3. **New runs get 1.2; existing runs keep their pin** (plan 3). `create_run`
   without a contract always records `interactive_guide 1.2`, profile or not.
   **(refined)** The goal-annotation prompt lines are gated as follows:
   version `1.0` never; version `1.1` always (unchanged, so a 1.1 run whose
   profile was detached after creation keeps byte-identical prompts); version
   `1.2` only when a profile is supplied. The plan's wording ("only when a
   profile snapshot exists") would move 1.1 bytes in that detached case and
   contradict its own byte-identity promise.
4. **Four kinds, two shapes** (plan 4). Kind values are **snake_case**:
   `flow`, `concept_map`, `comparison`, `timeline`. Reason: `kind` is a
   discriminator that, like block `type` (`rich_text`, `knowledge_check`),
   selects a schema shape and a code path in two languages, and it appears in a
   `data-` attribute and JS dispatch table, where hyphenated callout kinds
   (which only pick a label and icon) would read like ids.
5. **Hard limits** (plan 5). Adopted as numbers. **(refined)** Two limits are
   added because the plan did not bound these fields and they feed the SVG
   `<title>` and the figcaption: `title` ≤ 120, `caption` ≤ 240. **(refined)**
   Every diagram string must be a single line (no `\n`, `\r`, U+2028, U+2029),
   because labels are wrapped by character count and the inline renderer
   (`document._inline`) has no line-break semantics.
6. **Integrity rules** (plan 6). Adopted. Node, event, item and criterion ids
   are **diagram-local**: unique within the diagram (one local namespace across
   all four arrays), not registered in the guide-wide namespace, not link
   targets. The diagram's own `id` is a block id in the guide-wide namespace.
   Consequences made explicit: `canonical._collect_ids` must not descend into a
   diagram (else assembly would report two modules' `start` nodes as a
   collision), and schema spec §2 gains the exception. **(refined)** A
   `concept_map` duplicate edge is judged on the **unordered** pair, because
   A→B and B→A draw as one line with two labels at one midpoint; a `flow`
   judges the ordered pair (A→B plus B→A is a legitimate two-step loop).
7. **Coverage** (plan 7). Adopted: `diagram` joins `rich_text`/`callout` in
   `taught`; it is never interactive.
8. **Server text version, runtime picture** (plan 8). **(refined)** The
   `<figure>` *is* the block element (`class="block diagram"`, block `id`), not
   a figure inside an `<article>`, so the block keeps the shared `.block`
   styling and link-target behaviour; the figcaption carries both the title and
   the caption, because the figcaption is the figure's accessible name and the
   plan requires no heading elements. **(refined)** The text version marks
   loop-back connections using the same depth-first back-edge rule the runtime
   draws as curves (§5.3), implemented once in Python (`guides/diagrams.py`) and
   once in JS, so the words and the picture agree.
9. **CSP unchanged** (plan 9). Adopted; T55 adds the missing CSP pin test.
10. **Layouts** (plan 10). Adopted with concrete constants (§6). **(refined)**
    The timeline's width breakpoint is realised by rendering **two** SVGs
    (horizontal and vertical) and switching them with a CSS media query, not
    by measuring the viewport, so output stays byte-deterministic and needs no
    resize listener. **(refined)** Edge labels wrap at 16 characters into at
    most two lines (node labels: 18 characters, three lines).
11. **Profile preferences as fixed text** (plan 11). Adopted with the exact
    keyword table and lines in §8.4.
12. **Runtime 1.2** (plan 12). Adopted.
13. **Draft version must match the run (new; resolves the former open question
    1).** Today nothing compares an approved guide's `schema_version` with the
    run's pinned contract (only the spec contract is compared,
    `runs.py:1998-2003`; `GuideV1Mode.validate_approval` checks spec and outline
    only, `run_modes.py:386-388`), so a pinned 1.0/1.1 run could approve a
    draft declaring 1.2, and finalize/export would ship diagrams under a 1.0
    contract and content type. Rule, added in T52: `validate_approval` also
    runs for `draft` and `repair`; when the response text decodes as a JSON
    object whose `schema_version` is a string **in
    `SUPPORTED_GUIDE_SCHEMA_VERSIONS`** and differs from
    `content_contract(topic_id).schema_version`, approval raises
    `ConfigError("cannot approve {stage} for guide run {id!r}: guide schema_version {got!r} conflicts with the immutable run content contract: expected {expected!r}")`.
    Anything else (undecodable text, non-object, missing, non-string or
    *unsupported* version such as `"2.0"`) is left to validation, which already
    reports it as a blocker — existing tests deliberately approve a `"2.0"`
    repair to exercise the non-waivable path
    (`test_runs.py::test_guide_v1_non_waivable_blocker_cannot_be_bypassed`,
    `test_release_gate_acceptance.py::test_structural_refusal_export_raises_and_leaves_no_artifacts`).
    A scoped repair fragment carries no `schema_version`, so the rule is a
    no-op for it; the splice re-parses under the base draft's (already
    checked) version, so a diagram spliced into a 1.1 draft is refused as
    `schema.unknown_block_type`. Assembled per-module drafts carry the
    skeleton's version into `draft.response.json`, which is what approval
    reads. Verified against `2a1aa50`: this rule alone changes the result of
    **no** existing test (full suite green with it applied).

## Design

### 1. JSON shape

A diagram is a block in a section's `blocks` array. Common fields:

| Field | Required | Type / rule |
| --- | --- | --- |
| `id` | yes | guide-wide id (`^[a-z][a-z0-9-]{0,63}$`), unique across the guide |
| `type` | yes | `"diagram"` |
| `kind` | yes | `"flow"`, `"concept_map"`, `"comparison"` or `"timeline"` |
| `title` | yes | plain text, 1–120 chars, one line |
| `caption` | no | inline Markdown, 1–240 chars, one line |
| `outcome_ids` | no | 0+ outcome ids, no duplicates (like `callout`) |
| `source_ids` | no | 0+ source ids |

Kind fields (any field of another kind is `schema.unknown_field`):

| Kind | Required fields | Element shape |
| --- | --- | --- |
| `flow` | `nodes` (2–12), `edges` (1–16) | node `{id, label, detail?}`; edge `{from, to, label?}` |
| `concept_map` | `hub`, `nodes` (2–12, hub included), `edges` (1–12) | as `flow`; `hub` is a node id |
| `timeline` | `events` (2–10) | `{id, when, label, detail?}` |
| `comparison` | `items` (2–4), `criteria` (1–8) | item `{id, label}`; criterion `{id, label, values}`; `values` is an object mapping **every** item id to a cell string, no other keys |

Text limits (code points, measured after trimming, like `MAX_TEXT`): node,
event, item and criterion `label` ≤ 48; edge `label` and `when` ≤ 32; `detail`
and comparison cells ≤ 240; `title` ≤ 120; `caption` ≤ 240. Plain text:
`title`, every `label`, `when`, `hub`. Inline Markdown (`document._inline`
subset: code, `**strong**`, `*em*`, safe links; images and raw HTML rejected by
the existing text checks): `caption`, `detail`, cells.

Complete examples (all four are the diagrams in the T51 fixture; §11 says where):

```json
{
  "id": "growth-loop-flow",
  "type": "diagram",
  "kind": "flow",
  "title": "How plant growth reinforces itself",
  "caption": "The last connection closes a **reinforcing** loop.",
  "outcome_ids": ["map-loop"],
  "nodes": [
    {"id": "biomass", "label": "Plant biomass"},
    {"id": "leaf-area", "label": "Leaf area", "detail": "More biomass usually means more leaves."},
    {"id": "sunlight", "label": "Sunlight captured"},
    {"id": "growth", "label": "New growth"}
  ],
  "edges": [
    {"from": "biomass", "to": "leaf-area", "label": "increases"},
    {"from": "leaf-area", "to": "sunlight", "label": "increases"},
    {"from": "sunlight", "to": "growth", "label": "fuels"},
    {"from": "growth", "to": "biomass", "label": "adds to"}
  ]
}
```

```json
{
  "id": "loop-kinds-map",
  "type": "diagram",
  "kind": "concept_map",
  "title": "Kinds of feedback",
  "outcome_ids": ["identify-loop"],
  "hub": "feedback-loop",
  "nodes": [
    {"id": "feedback-loop", "label": "Feedback loop"},
    {"id": "reinforcing", "label": "Reinforcing loop", "detail": "Amplifies change in one direction."},
    {"id": "balancing", "label": "Balancing loop", "detail": "Pushes a quantity toward a goal or limit."},
    {"id": "delay", "label": "Delay"}
  ],
  "edges": [
    {"from": "feedback-loop", "to": "reinforcing", "label": "can be"},
    {"from": "feedback-loop", "to": "balancing", "label": "can be"},
    {"from": "balancing", "to": "delay", "label": "overshoots with a"}
  ]
}
```

```json
{
  "id": "watering-delay-timeline",
  "type": "diagram",
  "kind": "timeline",
  "title": "Why watering again too soon overcorrects",
  "outcome_ids": ["choose-intervention"],
  "events": [
    {"id": "water", "when": "Day 1, morning", "label": "Water the bed"},
    {"id": "surface", "when": "Day 1, evening", "label": "Surface still looks dry"},
    {"id": "roots", "when": "Day 3", "label": "Moisture reaches the roots", "detail": "The delay hides the effect of the first watering."},
    {"id": "recover", "when": "Day 4", "label": "Leaves recover"}
  ]
}
```

```json
{
  "id": "loop-types-comparison",
  "type": "diagram",
  "kind": "comparison",
  "title": "Reinforcing and balancing loops side by side",
  "outcome_ids": ["identify-loop"],
  "source_ids": ["meadows-2008"],
  "items": [
    {"id": "reinforcing", "label": "Reinforcing loop"},
    {"id": "balancing", "label": "Balancing loop"}
  ],
  "criteria": [
    {"id": "effect", "label": "What it does",
     "values": {"reinforcing": "Amplifies change in one direction", "balancing": "Pushes toward a goal or limit"}},
    {"id": "example", "label": "Garden example",
     "values": {"reinforcing": "More leaves capture more light", "balancing": "Watering stops once the soil is moist"}},
    {"id": "risk", "label": "Main risk",
     "values": {"reinforcing": "Runaway growth or collapse", "balancing": "*Overcorrection* when feedback is delayed"}}
  ]
}
```

Note the concept map and comparison reuse the local ids `reinforcing` and
`balancing`: legal, because they are diagram-local (decision 6).

### 2. Model (`guides/model.py`)

```python
SUPPORTED_GUIDE_SCHEMA_VERSIONS = frozenset({"1.0", "1.1", "1.2"})
ANNOTATION_SCHEMA_VERSIONS = frozenset({"1.1", "1.2"})
DIAGRAM_SCHEMA_VERSIONS = frozenset({"1.2"})
LATEST_GUIDE_SCHEMA_VERSION = "1.2"
DIAGRAM_KINDS = ("flow", "concept_map", "comparison", "timeline")   # this order is used everywhere a kind list is printed
DEFAULT_GUIDE_SCHEMA_VERSION = "1.0"                                # unchanged

@dataclass(frozen=True)
class DiagramNode:
    id: str
    label: str
    detail: str | None = None

@dataclass(frozen=True)
class DiagramEdge:
    from_id: str = field(metadata={"json": "from"})
    to_id: str = field(metadata={"json": "to"})
    label: str | None = None

@dataclass(frozen=True)
class TimelineEvent:
    id: str
    when: str
    label: str
    detail: str | None = None

@dataclass(frozen=True)
class ComparisonItem:
    id: str
    label: str

@dataclass(frozen=True)
class ComparisonValue:
    item_id: str
    text: str

@dataclass(frozen=True)
class ComparisonCriterion:
    id: str
    label: str
    values: tuple[ComparisonValue, ...] = field(
        default=(), metadata={"json_keyed": ("item_id", "text")}
    )

@dataclass(frozen=True)
class Diagram:
    id: str
    kind: str
    title: str
    type: str = "diagram"
    caption: str | None = None
    hub: str | None = None
    nodes: tuple[DiagramNode, ...] = field(default=(), metadata={"omit_empty": True})
    edges: tuple[DiagramEdge, ...] = field(default=(), metadata={"omit_empty": True})
    events: tuple[TimelineEvent, ...] = field(default=(), metadata={"omit_empty": True})
    items: tuple[ComparisonItem, ...] = field(default=(), metadata={"omit_empty": True})
    criteria: tuple[ComparisonCriterion, ...] = field(default=(), metadata={"omit_empty": True})
    outcome_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

Block: TypeAlias = RichText | Callout | KnowledgeCheck | WorkedReveal | Scenario | Reflection | Diagram
```

Only tuples, so every guide dataclass stays hashable. `ComparisonValue`s are
stored in the diagram's `items` order. `from` is a Python keyword, hence the
`json` field metadata (§4).

### 3. Parse and normalize (`guides/parse.py`)

- `_check_root` (`:215-236`): `annotations_allowed = schema_version in
  ANNOTATION_SCHEMA_VERSIONS`; `diagrams_allowed = schema_version in
  DIAGRAM_SCHEMA_VERSIONS`; pass `diagrams_allowed=` to `_check_modules`, which
  passes it to `_check_block(c, block, path, *, diagrams_allowed)`.
- Unsupported-version message becomes exactly
  `supported schema versions are exactly '1.0', '1.1' and '1.2'`.
- `_check_block`: `if block_type == "diagram" and not diagrams_allowed` → the
  existing `schema.unknown_block_type` diagnostic at `{path}/type` with message
  `unknown block type 'diagram'` (identical to any other unknown type; this is
  the §18 rule). Otherwise the generic path runs with spec
  `required = {"id", "type", "kind", "title"} ∪ KIND_FIELDS[kind]` and
  `optional = {"caption"} ∪ common_optional`, where `KIND_FIELDS = {"flow":
  {"nodes","edges"}, "concept_map": {"hub","nodes","edges"}, "timeline":
  {"events"}, "comparison": {"items","criteria"}}`. When `kind` is not one of
  the four, `required` is only the four common fields and **all** kind fields
  are optional, so a bad kind yields one `schema.invalid_value` at `{path}/kind`
  with message `invalid diagram kind` (any non-string `kind` included) and no
  cascade: `_check_diagram` is **not** called for a bad kind, so present kind
  arrays are not shape-checked. The generic block code
  already registers `id`, checks `outcome_ids` (minimum 0) and `source_ids`, and
  checks `title` as plain text. Then, for a valid kind only,
  `_check_diagram(c, block, path)`.
- `_check_diagram` (shape; runs on the raw dict):
  1. `caption` → `c.text(..., markdown=True)`; `hub` → `c.text`.
  2. Each present kind array → `c.array(value, p)` (no bounds here; bounds are
     `diagram_findings` rule 1, so a count error is reported once); each
     element → `c.obj` with required/optional sets `node {id,label}/{detail}`,
     `edge {from,to}/{label}`, `event {id,when,label}/{detail}`,
     `item {id,label}/{}`, `criterion {id,label,values}/{}`; every string
     field → `c.text` (`markdown=True` for `detail`); ids use `c.text`, **not**
     `c.identifier` (local namespace).
  3. `values`: not an object → `schema.invalid_type` at `…/criteria/{i}/values`,
     `must be an object`. For each key not among the string item ids →
     `diagram.unknown_value_key` at `…/criteria/{i}/values/{key}`, message
     `unknown item ID {key!r}`. For each item id with no key →
     `diagram.missing_value` at `…/criteria/{i}/values`, message
     `missing a value for item {item_id!r}`. Each value → `c.text(...,
     markdown=True)` at `…/values/{key}`.
  4. If the block raised no diagnostic since `_check_block` began
     (`len(c.errors)` unchanged), normalize it with `_normalize_block` and
     append every `diagram_findings(block, path)` result as a
     `ParseDiagnostic`. One implementation of the rules serves parse and
     validation (§3.1).
- Coverage (`:813`): `if kind in {"rich_text", "callout", "diagram"}:
  taught.update(refs)`. The interactive set (`:788`) and every message are
  unchanged.
- `_normalize_block`: a `diagram` branch **before** the `Reflection`
  fall-through builds `Diagram` from the raw dict: strings unchanged (no
  trimming — the same as every existing field, so existing canonical bytes are
  unaffected), arrays in authored order, `ComparisonValue(item_id, values[item_id])`
  in `items` order.

#### 3.1 Rules module (`guides/diagrams.py`, new, pure)

`diagram_findings(block: Diagram, base: str) -> tuple[tuple[str, str, str], ...]`
returns `(code, absolute_path, message)` in the order below (arrays in field
order `nodes, edges, events, items, criteria`; elements by index). Tests assert
on sets of `(code, path)` plus exact messages.

| # | Rule | Code | Path | Message |
| --- | --- | --- | --- | --- |
| 1 | Array count outside the kind's bounds | `schema.cardinality` | `{base}/nodes` etc. | `must contain {min}–{max} items` (en dash, as `_Checker.array`) |
| 2a | Local id not matching `ID_RE` | `schema.invalid_id` | `…/nodes/{i}/id` | `must match ^[a-z][a-z0-9-]{0,63}$` |
| 2b | Local id repeated in the diagram (nodes, events, items, criteria share one namespace) | `diagram.duplicate_id` | later occurrence `…/{array}/{i}/id` | `duplicates diagram ID first declared at {first_path}` |
| 3 | Trimmed length over limit | `diagram.text_too_long` | field path | `must not exceed {limit} characters` |
| 4 | The **raw, untrimmed** string contains `\n`, `\r`, U+2028 or U+2029 anywhere (a trailing `"\n"` fails too, because normalization keeps raw strings) | `diagram.multiline_text` | field path | `must be a single line` |
| 5 | Edge endpoint or `hub` not a node id | `diagram.unknown_node` | `…/edges/{i}/from`, `…/to`, `{base}/hub` | `unknown node ID {ref!r}` |
| 6 | `from == to` | `diagram.self_edge` | `…/edges/{i}` | `an edge must connect two different nodes` |
| 7 | Repeated pair (flow: ordered; concept map: unordered) | `diagram.duplicate_edge` | later `…/edges/{i}` | `duplicates the edge at {base}/edges/{j}` |
| 8 | Flow node in no edge | `diagram.isolated_node` | `…/nodes/{i}` | `node {id!r} has no edges` |
| 9 | Concept-map node not reachable from the hub, ignoring direction (only when `hub` resolves) | `diagram.disconnected` | `…/nodes/{i}` | `node {id!r} is not connected to the hub {hub!r}` |
| 10 | Criterion `values` item ids ≠ `items` ids (dataclass form) | `diagram.missing_value` / `diagram.unknown_value_key` | as in §3 step 3 | as in §3 step 3 |
| 11 | A field of another kind is non-empty/non-`None` (dataclass form) | `schema.unknown_field` | `{base}/{json name}` | `unknown field {name!r}` |

Rule 1 bounds: flow nodes 2–12, edges 1–16; concept_map nodes 2–12, edges
1–12; timeline events 2–10; comparison items 2–4, criteria 1–8. Rule 3 limits
per §1. Rules 10–11 can only fire for a `Guide` built in memory; for text input
§3 step 3 and `c.obj` catch them first.

The same module also holds `back_edge_indices(block) -> frozenset[int]` (§6.2,
DFS; used by the text version and projection) and
`KIND_LABELS = {"flow": "Flow diagram", "concept_map": "Concept map",
"comparison": "Comparison", "timeline": "Timeline"}`.

### 4. Canonical JSON (`guides/canonical.py`) — still generic

`guide_to_dict` keeps its dataclass walk with three metadata-driven rules, none
of which touch an existing field:

- key = `field.metadata.get("json", field.name)`;
- omitted when `None`, or when empty and (`field.name in _EMPTY_OMITTED_FIELDS`
  or `field.metadata.get("omit_empty")`);
- a field with `metadata["json_keyed"] = (key_attr, value_attr)` serializes as
  the object `{getattr(x, key_attr): guide_to_dict(getattr(x, value_attr))}` over
  its tuple.

So `outcome_ids` / `source_ids` serialize as `[]` when empty (as for every other
block), kind arrays of other kinds disappear, and a flow round-trips with no
`hub`. `canonical_guide_bytes(normalize_guide(parse_guide(canonical)))` is
byte-equal to `canonical` (tested for all four kinds). `_collect_ids`: when a
mapping has `type == "diagram"`, record its own `id` and do not descend.

`validation._text_fields` uses the same key rule for path segments and yields
a keyed field's texts at `{path}/{json name}/{key}` (e.g.
`…/criteria/0/values/reinforcing`), so validation paths equal parse paths. The
helper `json_field_items(value) -> Iterator[tuple[str, object, Field]]` lives in
`canonical.py` and is shared by both.

### 5. Validation (`guides/validation.py`)

- `RULES` gains (all `stage="draft"`, blocking, **not** waivable — a waiver
  cannot make an unparseable guide render):

| Code | Severity | Remediation |
| --- | --- | --- |
| `diagram.duplicate_id` | blocker | `Give every node, event, item and criterion a unique ID within its diagram.` |
| `diagram.unknown_node` | blocker | `Reference a node declared in the same diagram.` |
| `diagram.text_too_long` | error | `Shorten the diagram text to its limit.` |
| `diagram.multiline_text` | error | `Keep every diagram string on one line.` |
| `diagram.self_edge` | error | `Connect two different nodes.` |
| `diagram.duplicate_edge` | error | `Remove the repeated edge.` |
| `diagram.isolated_node` | error | `Connect the node or remove it.` |
| `diagram.disconnected` | error | `Connect every node to the hub through edges.` |
| `diagram.missing_value` | error | `Give the criterion a value for every item.` |
| `diagram.unknown_value_key` | error | `Key comparison values by the diagram's item IDs.` |

- Block loop (`:819-833`): `elif isinstance(block, Diagram):` if
  `checked_guide.schema_version not in DIAGRAM_SCHEMA_VERSIONS` append
  `schema.unknown_block_type` at `{path}/type`, message
  `unknown block type 'diagram'`; else append each `diagram_findings(block,
  path)` as `_finding(code, p, message, "", (block.id,))` (identity is the path,
  so two nodes failing one rule get distinct finding ids). For text input these
  never fire, because parse already failed.
- `READING_TIME_BLOCK_SECONDS["diagram"] = 30` **(refined; flagged)**: reading
  a picture costs time beyond its label words, which `_text_fields` already
  counts (as it does for every block, it also counts ids, `type`, `kind` and
  edge `from`/`to` ids as words; keyed `values` contribute their cells only,
  not the item-id keys). The pin `tests/test_guide_validation.py:419` gains the
  entry.
- `source.missing_for_required_claim` (`:833`) stays `RichText`/`Callout`
  only: a diagram restates structure the surrounding prose explains and
  sources, so it never raises that warning.
- The privacy / placeholder / prompt-leak scans need no change: they run over
  `_text_fields`, which (with §4's key rule) now yields every diagram string,
  including cells at `…/criteria/{i}/values/{item_id}`. The Markdown-only
  checks (`path.endswith("/markdown", …)`, `:805`) do not match `detail`,
  `caption` or cells, which is correct: they allow no fences or headings.
- No finding message contains a profile value; diagram messages contain only
  codes, limits, JSON paths and model-authored ids, and still pass through
  `_sanitize_finding`.

### 6. Markdown projection (`guides/projection.py`)

`_project_block` gains a `Diagram` branch before the `Reflection` assert.
Every branch starts `["", f"#### {title}", "", f"*{KIND_LABELS[kind]}*", ""]`
and ends, when `caption` is set, with `["", caption]`.

- **flow:** `f"{n}. {label}"` + `f": {detail}"` if detail, one per node; then
  `["", "Connections:", ""]`; then per edge
  `f"- {from label} → {to label}"` + `f" — {label}"` if labelled +
  `" (loops back)"` if its index is in `back_edge_indices`. **(refined)** No
  step number: a DFS back edge's target is a DFS ancestor, which is always on
  an earlier *layer* of the picture but not necessarily earlier in the
  document-order step list (nodes `[a, b, c]`, edges `a→c, c→b, b→c`: the back
  edge `b→c` would read "loops back to step 3" from step 2).
- **concept_map:** nodes in order hub first, then the others in document order:
  `f"- {label}"` + `" (central idea)"` for the hub + `f": {detail}"` if detail;
  under each, for its outgoing edges in edge order, `"  - "` + (`f"{label} "` if
  labelled) + `f"→ {target label}"`.
- **timeline:** `f"{n}. {when} — {label}"` + `f": {detail}"` if detail.
- **comparison:** a pipe table: `"| Criterion | {item labels joined ' | '} |"`,
  then `"| --- |" + " --- |" * len(items)`, then per criterion
  `f"| {label} | {cells in item order joined ' | '} |"`; every `|` inside a
  label or cell is written `\|`.

Exact output for the flow example (these lines follow the section's `###`
heading and any earlier blocks):

```

#### How plant growth reinforces itself

*Flow diagram*

1. Plant biomass
2. Leaf area: More biomass usually means more leaves.
3. Sunlight captured
4. New growth

Connections:

- Plant biomass → Leaf area — increases
- Leaf area → Sunlight captured — increases
- Sunlight captured → New growth — fuels
- New growth → Plant biomass — adds to (loops back)

The last connection closes a **reinforcing** loop.
```

### 7. Document markup (`guides/document.py`)

- `assemble_guide_document` already refuses versions outside
  `guide_runtime.SUPPORTED_SCHEMA_VERSIONS` (`:254`); T53 adds `"1.2"` there. A
  `Diagram` in a guide whose version is not in `DIAGRAM_SCHEMA_VERSIONS` raises
  `GuideDocumentError("unsupported block type: 'diagram'")` (the existing
  message shape).
- `_block`: `if b.type == "diagram": return _diagram_block(b, ids)` first.
  `_INTERACTIVE_TYPES` is unchanged; `_all_ids` needs no change (a `Diagram` has
  no `choices`/`steps`), so local ids never become link targets.
- `_diagram_block` emits, with no whitespace between tags (like every block),
  `esc = html.escape`, `inl = _inline(text, ids)`:

```html
<figure class="block diagram" id="{esc id}" data-diagram-kind="{kind}">
  <figcaption class="diagram-caption"><strong class="diagram-title">{esc title}</strong>[ <span class="diagram-caption-text">{inl caption}</span>]</figcaption>
  <div class="diagram-text" data-role="diagram-text">{BODY}</div>
</figure>
```

  `[…]` is present only with a caption (the single space before `<span>` is
  literal). `BODY` per kind:

  - **flow:**
    `<ol class="diagram-steps">` + per node
    `<li><span class="diagram-label">{esc label}</span>[: <span class="diagram-detail">{inl detail}</span>]</li>`
    + `</ol><p class="diagram-list-label">Connections</p><ul class="diagram-connections">`
    + per edge `<li>{esc from label} → {esc to label}[ — {esc label}][ (loops back)]</li>`
    + `</ul>`.
  - **concept_map:** `<ul class="diagram-map">` + per node (hub first)
    `<li><span class="diagram-label">{esc label}</span>[ (central idea)][: <span class="diagram-detail">{inl detail}</span>][<ul class="diagram-map-links">…</ul>]</li>`
    where each link is `<li>[{esc label} ]→ {esc target label}</li>`, and the
    nested list is omitted when the node has no outgoing edge; + `</ul>`.
  - **timeline:** `<ol class="diagram-events">` + per event
    `<li><span class="diagram-when">{esc when}</span> — <span class="diagram-label">{esc label}</span>[: <span class="diagram-detail">{inl detail}</span>]</li>`
    + `</ol>`.
  - **comparison:**
    `<table class="diagram-table"><thead><tr><th scope="col">Criterion</th>` +
    per item `<th scope="col">{esc label}</th>` + `</tr></thead><tbody>` + per
    criterion `<tr><th scope="row">{esc label}</th>` + per item
    `<td>{inl value}</td>` + `</tr>` + `</tbody></table>`.

- The figure contains no `h1`–`h6`, no form control and no `id` other than the
  block id. `data-diagram-state` is **not** emitted by the server.
- `guide-data` needs no change: `guide_to_dict` (§4) embeds each diagram as its
  canonical dict, e.g. the flow example as
  `{"caption":"The last connection closes a **reinforcing** loop.","edges":[{"from":"biomass","label":"increases","to":"leaf-area"},…],"id":"growth-loop-flow","kind":"flow","nodes":[{"id":"biomass","label":"Plant biomass"},{"detail":"More biomass usually means more leaves.","id":"leaf-area","label":"Leaf area"},…],"outcome_ids":["map-loop"],"source_ids":[],"title":"How plant growth reinforces itself","type":"diagram"}`.
- The CSP (`:285`) is unchanged.

### 8. Prompts (`prompts.py`, `guides/blueprints.py`)

#### 8.1 Gates

- `_private_personalization_lines` (`:733`) and
  `_profile_without_authoritative_goals` (`:785`): `guide_schema_version !=
  "1.1"` → `guide_schema_version not in ANNOTATION_SCHEMA_VERSIONS`. With
  `profile is None` both are unchanged no-ops.
- `_guide_json_output_lines(lines, guide_schema_version, *, profile_present:
  bool)` (keyword required; the four callers `:938`, `:1443`, `:1765`, `:1927`
  pass `profile is not None`): returns only the versioned lines when the version
  is `1.0`, or when it is in `DIAGRAM_SCHEMA_VERSIONS` and `not
  profile_present`; otherwise appends the five goal lines as today, with the
  first line's `Source schema 1.1 permits` written as
  `f"Source schema {guide_schema_version} permits"` **(refined)** — identical
  bytes for 1.1, and a 1.2 prompt does not name an older version.

#### 8.2 `_versioned_lines` for 1.2

For `guide_schema_version in DIAGRAM_SCHEMA_VERSIONS` only, after the existing
`"1.0"` → `"1.2"` replacement, apply to each line, in order:

1. `six registered block types` → `seven registered block types`;
2. ``(except `rich_text`/`callout`)`` → ``(except `rich_text`/`callout`/`diagram`)``;
3. ``Use Markdown only inside the designated `markdown` fields.`` →
   ``Use Markdown only inside the designated `markdown` fields, plus inline Markdown in a diagram's `caption`, `detail` and comparison cells.``;
4. after the line starting ``  - `reflection`:``, insert
   `_DIAGRAM_SCHEMA_REFERENCE_LINES` **unless the next line already equals its
   first line** (the module-draft prompt versions its reference twice, `:1185`
   and `:1225-1227`).

For 1.0 and 1.1 the function is byte-for-byte what it is today.

```python
_DIAGRAM_SCHEMA_REFERENCE_LINES = (
    "  - `diagram` (never interactive): `kind`, `title`, optional `caption`, `outcome_ids`, "
    "`source_ids`, plus the fields of its kind:",
    "    - `flow`: `nodes` (2-12 of `{id, label, detail?}`) and `edges` (1-16 of "
    "`{from, to, label?}`); cycles are allowed and are drawn as loops.",
    "    - `concept_map`: `hub` (one node id), `nodes` (2-12, including the hub) and `edges` "
    "(1-12); every node must connect to the hub through edges.",
    "    - `timeline`: `events` (2-10 of `{id, when, label, detail?}`), drawn in the given order.",
    "    - `comparison`: `items` (2-4 columns of `{id, label}`) and `criteria` (1-8 rows of "
    "`{id, label, values}`); `values` maps every item id to exactly one cell.",
    "    - Limits: `title` 120 characters, `label` 48, edge `label` and `when` 32, `detail`, "
    "`caption` and cells 240; every diagram string is a single line.",
    "    - `title`, labels and `when` are plain text; `caption`, `detail` and cells allow inline "
    "Markdown only. Ids inside a diagram only need to be unique within that diagram.",
    "    - A diagram is data, never drawing instructions: never supply coordinates, sizes, "
    "colors, SVG, or CSS.",
)
```

#### 8.3 Diagram guidance (1.2 whole-guide draft and module draft only)

`_guide_authoring_output_lines(lines, version, profile, *, blueprint=None,
diagram_guidance=False)`; `compile_guide_v1_draft_prompt` and
`compile_guide_v1_module_draft_prompt` pass `blueprint=blueprint,
diagram_guidance=True`; the skeleton passes nothing (it has no section
content); repair prompts are untouched ("change only what the findings
require"). When `diagram_guidance` and the version is in
`DIAGRAM_SCHEMA_VERSIONS`, the returned tuple is
`(*json_output_lines, "", *guidance, *personalization_suffix)`, where
`guidance` is:

```python
_DIAGRAM_GUIDANCE_LINES = (
    "## Diagram Guidance",
    "A `diagram` shows structure that the surrounding prose explains; it never replaces the "
    "explanation and never counts as an interaction.",
    "- Use `flow` for a process, a sequence of stages, or a chain of causes, including a loop "
    "that feeds back into an earlier step.",
    "- Use `concept_map` for one central idea and the ideas directly related to it, with a "
    "short verb phrase on each connection.",
    "- Use `comparison` to contrast two to four options against the same criteria.",
    "- Use `timeline` when the order of events or phases in time is the point.",
    "- No module needs a diagram. Add one only where the structure is easier to see than to "
    "read, and keep it small: short labels, with longer explanation in `detail` or in the prose.",
    "- Give every diagram a `title` that says what it shows; the learner-facing text "
    "alternative is derived from the title and the data.",
)
```

followed, when a blueprint is configured and its `diagram_kinds` is non-empty, by
`f"- The {blueprint.title} blueprint most often benefits from these kinds: {kinds}."`
(`kinds` = backticked kinds joined `", "`), followed by the profile lines of §8.4.

`Blueprint` gains a last field `diagram_kinds: tuple[str, ...] = ()` (a
default, so no constructor call changes; not used by 1.0/1.1 prompts):

| Blueprint id | `diagram_kinds` |
| --- | --- |
| `conceptual-foundations` | `("concept_map", "comparison")` |
| `procedural-skill` | `("flow",)` |
| `casebook` | `("flow", "comparison")` |
| `quantitative-scientific` | `("flow", "comparison")` |
| `exam-preparation` | `("comparison", "concept_map")` |
| `project-based` | `("timeline", "flow")` |

#### 8.4 Profile keyword map (fixed text out)

Kinds from `profile.learning_preferences.preferred_visual_aids`: for each entry,
`text = entry.casefold()`; a kind matches when any keyword matches
`re.search(rf"\b{re.escape(keyword)}(?:s|es)?\b", text)`.

| Kind | Keywords |
| --- | --- |
| `flow` | `flowchart`, `flow chart`, `flow diagram`, `process`, `sequence`, `cycle`, `loop`, `workflow`, `pipeline`, `step` |
| `concept_map` | `concept map`, `mind map`, `mindmap`, `concept diagram`, `network`, `relationship` |
| `comparison` | `comparison`, `compare`, `table`, `matrix`, `side-by-side`, `side by side`, `pros and cons`, `versus` |
| `timeline` | `timeline`, `time line`, `chronology`, `chronological`, `history` |

Frequency from `diagram_frequency`: `words = set(re.findall(r"[a-z]+",
value.casefold()))`; buckets `frequent = {frequent, frequently, often, many,
lots, every, most, heavy, plenty}`, `occasional = {occasional, occasionally,
some, sometimes, moderate, moderately}`, `rare = {rare, rarely, seldom, minimal,
minimally, few, sparing, sparingly, none, never, avoid}`; exactly one bucket
must match, otherwise nothing is emitted (the `_mapped_skill_level` rule,
`validation.py:546-557`). **(refined)** If `words` contains any of `{not, no,
without, don, doesn}` nothing is emitted either, because a bag-of-words
reading inverts negations ("not too many" would otherwise map to *frequent*);
emitting nothing is always safe, as no rule demands a diagram.

Emitted lines (profile present, version in `DIAGRAM_SCHEMA_VERSIONS`), in this
order, each only when it applies:

- `f"- The learner profile favors these diagram kinds; prefer them where the content has that structure: {kinds}."` (matched kinds in `DIAGRAM_KINDS` order, backticked, joined `", "`);
- frequent: `- The learner profile asks for frequent diagrams: consider one in most modules, wherever the content has structure a picture can show.`
- occasional: `- The learner profile asks for occasional diagrams: use one where it clearly helps, and not in every module.`
- rare: `- The learner profile asks for few diagrams: use one only where the structure is hard to follow in prose.`

No emitted line contains any profile string. The example profile
(`["concept maps"]`, no frequency) yields exactly
``- The learner profile favors these diagram kinds; prefer them where the content has that structure: `concept_map`.``

#### 8.5 Byte identity of 1.0 and 1.1

The five `_GUIDE_V1_NO_BLUEPRINT_PROMPT_TEXT_SHA256` pins compile with the
default version `1.0`, no profile, no blueprint: §8.2 is skipped for 1.0,
`_guide_json_output_lines` returns early for 1.0, §8.3 requires 1.2, and
`Blueprint.diagram_kinds` is read only under 1.2. For 1.1: §8.2 and §8.3 are
skipped, the goal lines are emitted exactly as before (§8.1), and the
annotation gates keep 1.1 in their set. T52 adds a parametrized test that
compiles every guide-v1 prompt (spec, outline, draft, skeleton, module draft,
qa, factcheck, repair, module repair, section repair) for 1.0 and 1.1, with and
without a profile and a blueprint, on `2a1aa50` and on the branch, and asserts
equal bytes (the expected SHAs are recorded in the test from `2a1aa50`).

### 9. Runs, CLI, contract

- `ContentContract.interactive_guide_v1_2()` →
  `cls(kind="interactive_guide", schema_version="1.2")` next to `_v1_1()`
  (`runs.py:197-199`).
- `create_run` (`runs.py:497-503`): default `requested` =
  `ContentContract.interactive_guide_v1_2()`, no profile lookup; docstring
  (`:467-468`) updated.
- `_validate_content_contract` accepts it; message ends
  `supported contracts are legacy_markdown and interactive_guide schemas '1.0', '1.1' and '1.2'`.
- `_guide_content_type("1.2")` →
  `"application/vnd.education-pipeline.guide+json;version=1.2"`.
- `contract.py:147` message: `spec contract guide_schema_version must be one of
  ['1.0', '1.1', '1.2'], got …` (built from `sorted(SUPPORTED_GUIDE_SCHEMA_VERSIONS)`).
- `GuideV1Mode.validate_approval` (`run_modes.py:386-388`): decision 13's
  draft/repair version gate, via a new `RunStore._validate_guide_version`
  beside `_validate_guide_approval`.
- CLI (`cli.py:489`): `print(f"created run {id} (interactive_guide
  {contract.schema_version})")` from `store.content_contract(id)`; help
  (`:219`): `create a legacy Markdown run instead of an interactive guide`.

### 10. Runtime (`runtime.js`, `runtime.css`, `guide_runtime/__init__.py`)

#### 10.1 Versions and hook

- `RUNTIME_VERSION = "1.2"`, `SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0",
  "1.1", "1.2"})` (`__init__.py:8-9`); `runtime.js:1950` →
  `new Set(["1.0", "1.1", "1.2"])`, `:1954` → `expectedRuntime !== "1.2"`.
- New module `const Diagrams = (() => { … return { install }; })();` placed
  before "Block dispatch". It is **not** an enhancer (diagrams carry no
  `data-interactive`). Boot calls `Diagrams.install(guide);` between
  `enhanceCourseControls(guide);` (`:1967`) and `enhanceBlocks();` (`:1968`).
  `install` never throws: all work is in per-figure `try/catch`.

#### 10.2 `install(guide)`

1. Index `guide-data` diagrams: walk `guide.modules[].sections[].blocks[]`,
   keep plain objects with `type === "diagram"` and a string `id`, into a
   `Map` by id. If `guide.schema_version !== "1.2"` the map is left empty.
2. For each `figure.diagram` in document order: `data = map.get(figure.id)`;
   `kind = figure.dataset.diagramKind`. If `!valid(data, kind)` →
   `failClosed(figure)`. Else if `kind === "comparison"` → set
   `data-diagram-state="table"`. Else draw (§10.4), insert the SVG(s)
   immediately before `[data-role="diagram-text"]`, wrap the text version
   (§10.6), set `data-diagram-state="drawn"`.
3. `failClosed(figure)`: remove any SVG this call inserted, leave the text
   version where it is and unwrapped, set `data-diagram-state="text"`, and
   `console.error("guide-runtime: diagram fell back to its text version:", id)`.
   No learner-visible note: the text version is complete.
4. Register `beforeprint` / `afterprint` listeners once (§10.7).

`valid(data, kind)` is a defensive re-check of guide-data (it may be edited by
hand): plain object, `type === "diagram"`, `data.kind === kind`, kind in the
four, non-empty string `title`; the kind's arrays exist with counts in §1's
bounds; every element is a plain object; local ids match `GUIDE_ID_PATTERN`
and are unique; every label/`when` is a non-empty string within its limit
(code points via `Array.from`); edge endpoints and `hub` name nodes; no
self-edges; each criterion's `values` is a plain object with a string for
every item id. Anything else returns `false`. Local-id lookups use `Map` /
`Set`, and `values` membership uses
`Object.prototype.hasOwnProperty.call(values, itemId)`, because an item id
may legally be `constructor`, which every plain object inherits.

#### 10.3 Shared drawing rules

- Elements via `document.createElementNS("http://www.w3.org/2000/svg", name)`
  and `setAttribute`; text via `textContent`. Never `innerHTML`, `style`
  attributes, `<style>`, `<image>`, `<foreignObject>` or `<script>`.
- Every coordinate is written with `fmt(v) = String(Math.round(v * 10) / 10)`
  (so `-0` prints `0`), attributes are set in a fixed order in code, and no DOM
  measurement is used, so a given guide yields identical SVG markup.
- `wrap(text, width, maxLines)`: split `text.trim()` on `/\s+/`; greedy fill
  lines of at most `width` code points joined by one space; a word longer than
  `width` is cut into `width`-point chunks, each on its own line; if the result
  has more than `maxLines` lines, keep the first `maxLines` and replace the last
  kept line with its first `width - 1` points (or the whole line, if shorter)
  plus `…`.
- SVG root: `<svg xmlns="http://www.w3.org/2000/svg" class="diagram-svg
  diagram-svg--{variant}" role="img" focusable="false" viewBox="0 0 {W} {H}"
  width="{W}" height="{H}" aria-labelledby="{id}__title{sfx}"
  aria-describedby="{id}__desc{sfx}">`, first children
  `<title id="{id}__title{sfx}">{title}</title>` and
  `<desc id="{id}__desc{sfx}">{desc}</desc>`. `variant` is `flow`,
  `concept-map`, `timeline-h` or `timeline-v`; `sfx` is `""` for flow and
  concept map and `-h` / `-v` for the two timeline SVGs. `__` cannot occur in a
  guide id, so these ids never collide with guide ids, and they are unique per
  figure and per variant.
- Arrowhead (flow and concept map only), one per SVG:
  `<defs><marker id="{id}__arrow{sfx}" class="diagram-marker" viewBox="0 0 10 10"
  refX="10" refY="5" markerWidth="6" markerHeight="6" markerUnits="strokeWidth"
  orient="auto-start-reverse"><path class="diagram-arrowhead" d="M0,0 L10,5 L0,10 z"/></marker></defs>`;
  edges carry `marker-end="url(#{id}__arrow{sfx})"`.
- Group order: `<g class="diagram-edges">`, `<g class="diagram-edge-labels">`,
  `<g class="diagram-nodes">` (timeline: `diagram-axis-group`,
  `diagram-event-group`). SVG class names are disjoint from the server text
  version's classes (§7), so no `runtime.css` rule meant for SVG (`fill`,
  `font-size` in px) ever styles the HTML text version. Node: `<g class="diagram-node[ diagram-node--hub]"><rect
  class="diagram-node-box" x y width height rx="6"/><text
  class="diagram-node-label" text-anchor="middle"><tspan x y>line</tspan>…</text></g>`.
  Edge: `<path class="diagram-edge[ diagram-edge--back]" d="…" marker-end="…"/>`.
  Edge label: `<g class="diagram-edge-label"><rect class="diagram-edge-label-bg"
  x y width height rx="3"/><text class="diagram-edge-label-text"
  text-anchor="middle"><tspan x y>line</tspan>…</text></g>`.

Constants (one `const DIAGRAM_LAYOUT = Object.freeze({...})`):
`MARGIN 24`, `NODE_W 160`, `NODE_PAD_Y 10`, `NODE_LINE_H 18`, `NODE_CHARS 18`,
`NODE_MAX_LINES 3`, `COL_GAP 40`, `LAYER_GAP 56`, `BACK_OFFSET 32`,
`EDGE_CHARS 16`, `EDGE_MAX_LINES 2`, `EDGE_LINE_H 15`, `EDGE_CHAR_W 7`,
`R_MIN 200`, `RING_GAP 24`, `SLOT_W 150`, `EVENT_CHARS 18`, `EVENT_CHARS_V 30`,
`EVENT_LINE_H 16`, `EVENT_BLOCK_LINES 5`, `TICK 16`, `MARKER_R 6`,
`ROW_H 96`, `VERT_W 360`.

- Node height, uniform per diagram: `NODE_H = 2 * NODE_PAD_Y + maxLines *
  NODE_LINE_H`, `maxLines` = the most wrapped lines of any node label. Label
  tspans: `x = box centre`, baseline `y_j = box.y + NODE_H/2 -
  lines*NODE_LINE_H/2 + 13 + j*NODE_LINE_H`.
- Edge label at point `(px, py)`: lines = `wrap(label, EDGE_CHARS,
  EDGE_MAX_LINES)`; bg `width = maxLineLen*EDGE_CHAR_W + 8`, `height =
  lines*EDGE_LINE_H + 4`, `x = px - width/2`, `y = py - height/2`; tspans at
  `x = px`, `y_j = py - lines*EDGE_LINE_H/2 + 11 + j*EDGE_LINE_H`.
- `W = Math.ceil(maxRight + MARGIN)`, `H = Math.ceil(maxBottom + MARGIN)`, where
  the maxima range over every node box, every back-edge control point and every
  edge-label background (timeline: fixed formulas below).

#### 10.4 Layouts

**Flow.**
1. Back edges (`back_edge_indices`, identical in Python): colour every node
   white; for each node in document order, if white, `visit(node)`;
   `visit(u)`: grey `u`; for each edge `u→v` in edge document order: if `v` is
   grey, the edge is a back edge; else if white, `visit(v)`; then black `u`.
2. Ranks: forward edges = all others (acyclic). `rank = 0` for all; repeatedly
   take the first node in document order whose forward in-degree among
   unprocessed nodes is 0, and for each forward edge `u→v` set `rank[v] =
   max(rank[v], rank[u] + 1)` (longest path from the sources).
3. Layer `r` = nodes of rank `r` in document order. `layerW_r = n_r*NODE_W +
   (n_r - 1)*COL_GAP`; `maxW = max layerW_r`; node `i` of layer `r`: `x =
   MARGIN + (maxW - layerW_r)/2 + i*(NODE_W + COL_GAP)`, `y = MARGIN +
   r*(NODE_H + LAYER_GAP)`.
4. Forward edge: `M cx_s,(y_s+NODE_H) L cx_t,y_t` (bottom centre to top
   centre); label at the segment midpoint.
5. Back edge number `k` (0-based, edge order): `sx = x_s + NODE_W`, `sy = y_s
   + NODE_H/2`, `tx = x_t + NODE_W`, `ty = y_t + NODE_H/2`, `cx = MARGIN + maxW +
   BACK_OFFSET*(k+1)`; `d = M sx,sy C cx,sy cx,ty tx,ty`; class
   `diagram-edge diagram-edge--back`; label at the curve midpoint `(0.125*(sx+tx)
   + 0.75*cx, (sy+ty)/2)`.

   For the flow example: ranks 0–3, `NODE_H = 38`, `viewBox="0 0 261 368"`
   (back label `adds to`: bg width 57 centred at x 208, right edge 236.5).

**Concept map.** `k = nodes.length - 1` ring nodes (document order, hub
excluded). `R = k <= 1 ? R_MIN : max(R_MIN, ceil((NODE_W + RING_GAP) / (2 *
sin(π/k))))`, which keeps adjacent ring boxes ≥ 184 apart centre to centre and
every ring box clear of the hub. Centre `cx = MARGIN + R + NODE_W/2`, `cy =
MARGIN + R + NODE_H/2`; hub box centred there (`diagram-node--hub`). Ring node
`i`: `θ = -π/2 + 2πi/k`, centre `(cx + R cos θ, cy + R sin θ)` (12 o'clock, then
clockwise). `W = 2*(MARGIN + R) + NODE_W`, `H = 2*(MARGIN + R) + NODE_H`. Each
edge is a straight segment between the two box centres clipped to each box
border (`t = min((NODE_W/2)/|dx|, (NODE_H/2)/|dy|)` from each centre), arrow at
the `to` end, label at the clipped segment's midpoint. Example:
`R = 200`, `viewBox="0 0 608 486"`.

**Timeline, horizontal (`timeline-h`).** `n` events; `BLOCK_H =
EVENT_BLOCK_LINES * EVENT_LINE_H` (80); `W = 2*MARGIN + n*SLOT_W`, `H =
2*MARGIN + 2*BLOCK_H + 2*TICK` (240); `AXIS_Y = MARGIN + BLOCK_H + TICK`. Axis
`<line class="diagram-axis">` from `(MARGIN, AXIS_Y)` to `(W - MARGIN, AXIS_Y)`.
Event `i` at `x_i = MARGIN + SLOT_W/2 + i*SLOT_W`: `<circle
class="diagram-event-marker" r="6">` on the axis; `<line class="diagram-tick">`
from the marker edge to `AXIS_Y ∓ TICK`; lines = `wrap(when, EVENT_CHARS, 2)`
(tspans class `diagram-event-when`) then `wrap(label, EVENT_CHARS, 3)` (class
`diagram-event-label`), `text-anchor="middle"`. Even `i` above the axis
(last baseline at `AXIS_Y - TICK - 4`, earlier lines `EVENT_LINE_H` higher),
odd `i` below (first baseline at `AXIS_Y + TICK + 14`). Example: `viewBox="0 0
648 240"`.

**Timeline, vertical (`timeline-v`).** `AXIS_X = MARGIN + 8`; event `i` marker
at `(AXIS_X, MARGIN + 8 + i*ROW_H)`; text `x = AXIS_X + 20`,
`text-anchor="start"`, `wrap(when, EVENT_CHARS_V, 2)` then `wrap(label,
EVENT_CHARS_V, 3)` (same tspan classes as horizontal), first baseline at
marker `y + 5`, then `+EVENT_LINE_H`; no ticks.
`W = VERT_W`, `H = 2*MARGIN + 8 + (n-1)*ROW_H + BLOCK_H`; axis from `(AXIS_X,
MARGIN)` to `(AXIS_X, H - MARGIN)`. Example: `viewBox="0 0 360 424"`. Both
timeline SVGs are inserted, horizontal first.

Known limitations (accepted; the text version is authoritative): long forward
edges and back edges from a non-rightmost node may cross other nodes; wide
layers, large rings and long horizontal timelines scale down to the column
width, so text in them can get small (a 10-event horizontal timeline is
1548 wide; an 11-node flow layer is 2160 wide) — the text version and browser
zoom remain the fallback. "Byte-deterministic" means identical markup for a
given guide **in a given browser engine**: ring coordinates use `Math.sin` /
`Math.cos`, whose last-bit results are not specified across engines, so the
Playwright determinism and `viewBox` assertions run in Chromium only and no
Python test predicts SVG bytes.

#### 10.5 Alt text (`<desc>`)

- flow: `` `Flow diagram with ${n} steps and ${e} connection${e===1?"":"s"}${b ? `, ${b} of which loop${b===1?"s":""} back to an earlier step` : ""}. Steps in order: ${labels.join("; ")}.` ``
  → example: `Flow diagram with 4 steps and 4 connections, 1 of which loops back to an earlier step. Steps in order: Plant biomass; Leaf area; Sunlight captured; New growth.`
- concept_map: `` `Concept map centered on ${hub}, connected to ${k} idea${k===1?"":"s"}: ${others.join("; ")}.` ``
  → `Concept map centered on Feedback loop, connected to 3 ideas: Reinforcing loop; Balancing loop; Delay.`
- timeline: `` `Timeline of ${n} events, from ${first.when} (${first.label}) to ${last.when} (${last.label}).` ``
  → `Timeline of 4 events, from Day 1, morning (Water the bed) to Day 4 (Leaves recover).`

Labels here are the full, unwrapped labels; `<title>` is the diagram title.

#### 10.6 Text-version disclosure

After inserting the SVG(s): create `<details class="diagram-text-toggle"
data-role="diagram-text-toggle">` with `<summary>Text version</summary>`,
insert it where the text `div` was, and move the `div` into it. Closed by
default; it stays in the DOM. Final figure order: `figcaption`, SVG(s),
`details`. Comparison figures get no `details`.

#### 10.7 Print, themes, motion

- `beforeprint`: every `details[data-role="diagram-text-toggle"]` that is
  closed gets `open` and a `data-print-opened` marker; `afterprint`: those lose
  `open` and the marker. CSS print: `.diagram-text-toggle>summary{display:none}`,
  `.diagram{break-inside:avoid}`. Print modes (answer key / learner copy) do
  not affect diagrams.
- Theme: all colour comes from the existing tokens, so `data-theme` and
  `prefers-color-scheme` apply unchanged. `runtime.css` adds exactly:

```css
figure.block.diagram{margin:1.25rem 0;border-left-color:var(--ep-color-accent)}
.diagram-caption{font-family:var(--ep-font-interface);font-size:.95rem}
.diagram-caption-text{display:block;color:var(--ep-color-text-muted)}
.diagram-svg{display:block;max-width:100%;height:auto;margin:.75rem 0;font-family:var(--ep-font-interface)}
.diagram-node-box{fill:var(--ep-color-surface);stroke:var(--ep-color-accent);stroke-width:1.5}
.diagram-node--hub .diagram-node-box{fill:var(--ep-color-accent-soft);stroke-width:2.5}
.diagram-node-label{fill:var(--ep-color-text);font-size:14px}
.diagram-edge{fill:none;stroke:var(--ep-color-text-muted);stroke-width:1.5}
.diagram-edge--back{stroke-dasharray:6 4}
.diagram-arrowhead{fill:var(--ep-color-text-muted)}
.diagram-edge-label-bg{fill:var(--ep-color-surface)}
.diagram-edge-label-text{fill:var(--ep-color-text-muted);font-size:12px}
.diagram-axis,.diagram-tick{stroke:var(--ep-color-border);stroke-width:2}
.diagram-event-marker{fill:var(--ep-color-accent)}
.diagram-event-when{fill:var(--ep-color-text);font-size:13px;font-weight:600}
.diagram-event-label{fill:var(--ep-color-text);font-size:13px}
.diagram-svg--timeline-v{display:none}
.diagram-text-toggle summary{cursor:pointer;font-family:var(--ep-font-interface);font-size:.9rem;color:var(--ep-color-accent)}
.diagram-table th[scope="row"]{background:var(--ep-color-surface-subtle)}
.diagram[data-diagram-state="table"] .diagram-text{overflow-x:auto}
@media(max-width:40rem){.diagram-svg--timeline-h{display:none}.diagram-svg--timeline-v{display:block}}
```

  plus the two print rules above inside the existing first `@media print`
  block. A back edge is distinguished by dashes and its arrowhead, never by
  colour alone.
- Reduced motion: diagrams have no animation or transition; the existing
  `prefers-reduced-motion` rule needs no change.
- Keyboard: SVGs are not focusable; the `summary` is the only new focus stop.
  Arrow-key paging is unaffected (a `summary` is not an editable target).

### 11. Static checks and cockpit (T55)

- `static_checks._Analyzer`: track open `<figure>` depth; a heading start tag
  while inside a figure sets `heading_ok = False` (defends plan decision 8's
  "no headings in a figure"). No new `ValidationContext` field.
- A new test pins the CSP string exactly: `default-src 'none'; img-src 'none';
  style-src '{hash(css)}'; script-src '{hash(js)}'; connect-src 'none';
  font-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none';
  base-uri 'none'; form-action 'none'`.
- Export sidecar: `runtime_version` becomes `1.2` via `assets.version`
  (`runs_reports.py:500`); assert it in the export test.
- `JsonTreeView.tsx`: no code change (generic); a vitest case renders a
  diagram block and finds the `from`, `to` and `values` keys and an item-id key
  under `values`.
- `CanonicalGuidePreview.tsx` / `GuidePreviewFrame.tsx`: no code change; the
  preview is the server document, and the sandbox already allows the runtime's
  scripts, so diagrams draw in the frame. A vitest case passes through HTML
  containing `figure.diagram` unchanged.
- `ResponseEditor.tsx:13-14,42`: `isGuide = contentType.startsWith(
  "application/vnd.education-pipeline.guide+json;")` (fixes 1.1 as well);
  `types.ts:358-361` adds the `version=1.1` and `version=1.2` literals. A vitest
  case shows a 1.2 response's preview calls `postGuidePreview`.

### 12. Example course (T56)

- `responses/spec.md`: contract `"guide_schema_version": "1.2"`;
  `draft.skeleton.json` and `repair.guide.json`: `"schema_version": "1.2"`.
- Module `loop-basics`, section `feedback-foundations`, directly after
  `loop-introduction`: the **flow** `growth-loop-flow` of §1 (outcome
  `map-loop`).
- Module `intervention-practice`, section `delays-and-leverage`, directly after
  `delay-explanation`: a **comparison** `intervention-comparison`, outcome
  `choose-intervention`, items `act-again` "Act again right away" and
  `wait-out` "Wait out the delay"; criteria `first-sign` "What you see first"
  ("A quick visible change" / "Little visible change"), `after-delay` "After
  the delay" ("*Overshoot* past the goal" / "Settles near the goal"), `cost`
  "Main cost" ("Wasted effort and swings" / "Patience while nothing seems to
  happen").
- Both blocks go into `draft.modules/<module>.json` and the canonical
  `repair.guide.json`; `build_example.py` returns to plain `create_run`
  (see Migration); `test_example_project.py` asserts diagram kinds
  `{"flow", "comparison"}` are present and the report gate stays open with no
  findings (re-check `time.estimate_implausible` after the added words).

## Migration and compatibility

- **Pinned runs.** Manifests are never rewritten; a 1.0 or 1.1 run keeps its
  prompts byte for byte (§8.5) and rejects diagrams at parse.
- **Default switch (T52).** Measured, not estimated: applying only the
  default switch (1.2 added to the version sets, `create_run` defaulting to
  `interactive_guide_v1_2()`, the annotation gates widened) to `2a1aa50` fails
  **84** existing tests (plus `test_guide_parse.py::…[1.2]`, which is T51's).
  Almost all fail for one reason: they create a run without a contract and
  then approve a spec contract pinned to `"1.0"` or `"1.1"`, which spec
  approval refuses (`runs.py:1998-2003`). Rule: a test whose **subject** is
  the default moves to 1.2; every other test pins the contract it always had,
  at its creation helper, so its meaning is unchanged. The fixes, by root:
  - `tests/test_runs.py:280` `_create_profiled_guide_run` → pass
    `content_contract=ContentContract.interactive_guide_v1_1()`. This one line
    covers the profiled/audit/trace tests in `test_runs.py` (the other 31), and the
    profiled callers in `test_cli.py` (4 audit/report tests),
    `test_write_api.py` (3 audit tests), `test_personalization_acceptance.py`
    (9), `test_release_gate_acceptance.py` (3
    `…byte_identical_in_every_audit_state[*]`) and `test_export.py`
    (`test_personalized_source_stays_local_while_export_and_sidecar_are_stripped`)
    wherever they build through it; any that create their own run pin
    `_v1_1()` the same way.
  - `tests/test_server.py:1229` (`_drive_guide_through_qa_http`, 9 scoped
    repair tests) → `interactive_guide_v1()`; `:1459` (profiled helper, 10
    personalization/audit HTTP tests) → `interactive_guide_v1_1()`.
  - `tests/test_release_gate_acceptance.py:266`
    (`test_contrasting_blueprint_drives_divergent_prompts_and_contract_gates`)
    and `tests/test_runs.py` `test_spec_approval_accepts_matching_blueprint_echo`,
    `test_validate_run_flags_blueprint_contract_mismatch_in_draft` → pin
    `interactive_guide_v1()`.
  - **Default is the subject — rewrite to 1.2:**
    `test_runs.py::test_create_run_default_is_interactive_guide_v1` (`:4256`),
    `::test_implicit_write_spec_prompt_creates_guide_v1_run` (`:4272`),
    `::test_mixed_workspace_legacy_and_guide_v1_progress_independently`
    (`:4315`), `::test_run_store_creates_run_directories` (`:1052`, asserts the
    manifest contract at `:1064-1067`),
    `::test_profiled_new_run_selects_1_1_but_existing_1_0_is_immutable`
    (`:4357`, becomes "new runs select 1.2 with or without a profile; an
    existing 1.0 or 1.1 manifest is untouched"),
    `::test_profiled_prompt_and_response_contract_propagate_schema_1_1`
    (`:4382`, pin `_v1_1()` and keep, plus a 1.2 twin),
    `test_cli.py::test_create_command_defaults_to_interactive_guide`
    (`:545-556`, prints `interactive_guide 1.2`),
    `test_write_api.py::test_guide_status_stage_content_and_validate_payloads`
    (`:865-870`, contract and `version=1.2` content type; its fixture draft is
    written straight to the approved path, so decision 13 does not apply).
  - `test_example_project.py` (2 regeneration tests): fixed by
    `scripts/build_example.py:82` passing
    `content_contract=ContentContract.interactive_guide_v1_1()` in T52 (export
    bytes unchanged); T56 removes it together with moving the example to 1.2.
  The complete failing list (84) is recorded in the T52 closeout; after these
  edits T52 must show exactly these tests changed and no other.
  Decision 13's approval gate, applied alone to `2a1aa50`, fails **zero**
  tests (verified).
- **Thread order.** A default 1.2 run cannot export a 1.2 document until T53
  adds 1.2 to the runtime set. Merge T53 before T52 when both are ready; no test
  exercises the gap, and the phase ships as one PR.
- **Canonical bytes** of every existing guide are unchanged (§4 only adds
  metadata on new fields); T51 pins the SHA of the existing fixture's canonical
  bytes before and after.
- **Runtime.** Old exports embed their own runtime and keep working. New
  exports carry `data-guide-runtime="1.2"`; progress storage keys use the schema
  major, and the progress file format stays version 2, so learner progress is
  unaffected. The example export is rebuilt in every runtime-touching thread.
- **Docs (T56).** Schema spec §2 (1.2 version string; diagram-local ids are the
  one exception to guide-wide uniqueness), a new block section for `diagram`,
  §16 (inline subset in `caption`/`detail`/cells), §17 (diagram teaches), §18
  (1.2 = 1.1 + `diagram`); the runtime spec (module, layouts, CSP); and
  `docs/interactive-guides.md`.

## Testing strategy (TDD; tests before behaviour)

- **T51** — `test_guide_parse.py`: the fixture parses and normalizes with all
  four kinds; `:278` parametrization swaps `"1.2"` for `"1.3"`; a diagram in 1.0
  and in 1.1 gives exactly `{("schema.unknown_block_type", "…/type")}`; one
  failing case per row of §3.1 (and each §3 shape case: bad kind, wrong-kind
  field, `values` not an object, extra and missing `values` keys) asserting
  code, path and message; limit boundaries at exactly the limit (pass) and one
  over (fail) for each text limit and array bound; local ids equal to a guide
  id or reused across two diagrams pass; a `#node-id` link in a `detail` is
  `link.unknown_internal_target`; a diagram-only outcome is not `untaught`.
  `test_guide_canonical.py`: round-trip bytes per kind; `from`/`to` and keyed
  `values` in output; no empty foreign arrays; existing-fixture canonical SHA
  unchanged; `assemble_guide` with two modules each holding a diagram with node
  `start` succeeds. `test_guide_validation.py`: every `diagram.*` rule entry;
  in-memory `Guide` inputs trigger each dataclass rule and the version rule;
  finding ids distinct per path; reading-time constant. `test_guide_projection.py`:
  exact text for each kind, including §6's flow output and `\|` escaping.
- **T52** — `test_prompts.py`: the §8.5 byte-identity matrix; the existing SHA
  pins untouched; new SHA pins for 1.2 draft, module draft, skeleton and repair
  with and without profile; the reference insertion appears exactly once in the
  module-draft prompt; each keyword row and frequency bucket, ambiguity → no
  line, and a profile string never appearing in the guidance section; 1.2
  without profile has no goal lines and no private section; blueprint line per
  `diagram_kinds`; frequency negation → no line. `test_runs.py` /
  `test_cli.py` / `test_write_api.py` / `test_server.py` / acceptance tests per
  Migration; `test_guide_contract.py` accepts 1.2. Decision 13: a 1.0 and a
  1.1 run each refuse to approve a whole-guide draft and an unscoped repair
  declaring another supported version (exact message), still approve a
  `"2.0"` or unparseable response (validation blocks it later), and a scoped
  repair fragment carrying a diagram into a 1.1 draft is refused by the
  splice.
- **T53** — `test_guide_document.py`: exact figure markup for flow and
  timeline, `data-diagram-kind`, no heading inside the figure, a diagram in a
  1.1 `Guide` raises, `guide-data` embeds `from`/`to`; runtime version 1.2
  (`:214-218` renamed). `guide-runtime.spec.ts`: the diagrams fixture renders
  flow and timeline as `drawn` with `svg[role=img]`, the §10.4 `viewBox` values,
  `desc` strings of §10.5, one `.diagram-edge--back`, marker ids unique in the
  document, `details` closed with summary "Text version", two renders give
  identical SVG `outerHTML`, the vertical timeline shows at 375 px width,
  `beforeprint` opens and `afterprint` restores the details (dispatched with
  `window.dispatchEvent(new Event("beforeprint"))`, since
  `page.emulateMedia({media: "print"})` fires neither event); tampered
  guide-data (unknown `to`) leaves state `text` with no SVG while the rest of
  the guide boots; the unknown-schema test expects `runtime 1.2`; axe clean in
  light and dark. `guide-progress.spec.ts` unchanged and green.
- **T54** — same shape for concept map (`viewBox="0 0 608 486"`, hub class,
  edge labels, clipped endpoints) and comparison (state `table`, no SVG, `th
  scope` headers, no `details`).
- **T55** — `test_guide_static_checks.py`: diagrams fixture passes; a heading
  injected into a figure fails heading order. CSP pin test. Export sidecar
  `runtime_version == "1.2"` and CSP unchanged in `test_export.py`. Vitest for
  `JsonTreeView`, `CanonicalGuidePreview`, `ResponseEditor`.
- **T56** — `test_example_project.py` (kinds present, gate open, no private
  values, regeneration byte-equal); docs lint by review.

## Open questions

**Manager resolutions at T50 close (2026-09-23):** 1 — decision 13 ships in T52. 2 — node ids stay diagram-local. 3 — confirmed: 1.1 goal lines stay version-gated (byte identity), 1.2 gates them on profile presence. 4 — keep. 5 — accept 30 s; revisit if the example trips `time.estimate_implausible`. 6 — crossings accepted for this version and recorded in the audit ledger.

1. **Guide version vs run version** — resolved by decision 13 (an approval
   gate, not a validation rule: `validate_guide` has no run context, and a
   finding would still let the mismatched draft be approved). Confirm it
   belongs in T52 rather than a follow-up.
2. **Diagram-local ids** follow plan decision 6 but cost a special case in
   `_collect_ids` and an exception to schema §2. The alternative (guide-wide
   node ids, like choice ids) needs no special case but makes the model prefix
   every node id. Default: local, as the plan says.
3. **1.1 goal-line gate.** Plan decision 3 says the goal lines appear only with
   a profile; this spec keeps 1.1 version-gated to honour byte identity
   (decision 3 refinement). Confirm.
4. **`none`/`never` in `diagram_frequency`** map to the "few diagrams" line
   rather than forbidding diagrams. Default: keep; no rule demands a diagram.
5. **Reading time** `diagram: 30` s is a guess; it can move
   `time.estimate_implausible` for diagram-heavy courses.
6. **Layout crossings** (§10.4 limitations): accept for v1, or add
   dummy-node routing for long edges later?

## Non-goals (this phase)

- Interactive or animated diagrams, zoom, tooltips, drill-down.
- Images, uploaded assets, Mermaid or any model-supplied markup, coordinates
  or styling; any CSP change.
- Other kinds (stock-and-flow, quantitative charts, trees, Venn).
- Cockpit diagram editing, a diagram QA rubric, or a rule that requires
  diagrams anywhere.
- Migrating existing 1.0/1.1 runs or exports to 1.2.

## Success metrics

- The four-kind fixture renders identically across two page loads and in both
  themes, axe-clean, with every SVG's text alternative derived from data.
- Zero change to the 1.0/1.1 prompt bytes, to existing canonical bytes, and to
  the CSP string (all pinned by tests).
- `runtime.js` grows by ≤ 450 lines and `runtime.css` by ≤ 30 lines.
- The example course ships a flow with a feedback loop and a comparison, and
  its export is byte-reproducible.
- Pre-existing pytest cases pass unmodified except: the default-switch tests
  and pinned creation helpers listed under Migration; the `"1.2"`-is-unsupported
  parametrization (`test_guide_parse.py:278`); the reading-time constants pin
  (`test_guide_validation.py:419`); and the runtime/schema-version tests
  (`test_guide_document.py:214-218`, the `guide-runtime.spec.ts`
  unknown-schema case).
