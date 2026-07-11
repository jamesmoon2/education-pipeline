# Interactive Guide v1 — Milestone Specification

**Status:** Proposed
**Date:** 2026-07-11
**Product requirement:** `docs/product-requirements.md`, P0 “Define and prove
the interactive-course contract”

**Implementation plan:**
`docs/superpowers/plans/2026-07-11-interactive-guide-v1.md`

## 1. Purpose

This milestone changes Education Pipeline’s primary output from rendered course
prose into a safe, portable, genuinely interactive course guide.

The existing pipeline, approvals, provider execution, durable files, editor,
preview, and export paths remain the foundation. The milestone introduces a
versioned structured-content contract, an application-owned guide runtime, and
deterministic validation before finalization.

The milestone is complete when a full run produces an offline interactive HTML
guide with meaningful learning interactions, without accepting or executing
model-generated HTML or JavaScript.

## 2. Spec set

This milestone is defined by four documents:

1. This milestone contract.
2. [`2026-07-11-interactive-guide-v1-schema.md`](2026-07-11-interactive-guide-v1-schema.md)
   — canonical course-content format and initial interaction vocabulary.
3. [`2026-07-11-interactive-guide-v1-runtime-export.md`](2026-07-11-interactive-guide-v1-runtime-export.md)
   — maintained runtime, preview, offline export, accessibility, and security.
4. [`2026-07-11-interactive-guide-v1-validation-pipeline.md`](2026-07-11-interactive-guide-v1-validation-pipeline.md)
   — deterministic findings, prompt changes, run-state integration, finalization,
   and migration.

If these documents conflict, this milestone contract controls scope; the more
specific document controls technical details within that scope.

## 3. Outcomes

The milestone must deliver:

- guide schema v1 as the canonical final-course content model;
- six supported block types, including four interactive learning components;
- deterministic parsing, normalization, and validation;
- a maintained, dependency-conscious guide renderer and runtime;
- the same renderer in cockpit preview and exported HTML;
- offline, self-contained HTML export;
- safe local progress persistence in exported guides;
- structured validation reports visible to the pipeline and cockpit;
- prompt contracts that make draft and repair responses valid guide JSON;
- one synthetic fixture course used across unit, integration, and browser tests;
  and
- a compatibility path for existing Markdown runs and exports.

## 4. Scope decisions

### 4.1 Canonical format

The canonical course content is UTF-8 JSON in a versioned Education Pipeline
schema. Human-readable instructional text inside the JSON uses the existing safe
Markdown subset.

JSON is selected for v1 because it is supported by the Python standard library,
can be validated deterministically, is portable across Python and TypeScript,
and keeps models from defining executable behavior. The implementation does not
adopt JSON Schema as a runtime dependency; a checked-in JSON Schema document may
be generated or maintained for editor/tooling use, but application validation is
authoritative.

### 4.2 Model boundary

Models may produce:

- course metadata and educational text;
- modules, sections, outcomes, sources, glossary entries;
- instances of supported block types; and
- answer keys, explanations, feedback, and rubrics within those types.

Models may not produce:

- raw HTML;
- CSS;
- JavaScript or other executable code for guide behavior;
- component names outside the schema vocabulary;
- arbitrary event handlers, URLs used as code, or embedded remote assets; or
- modifications to the guide runtime.

### 4.3 Initial interaction set

Guide v1 supports:

- rich explanatory text;
- callouts;
- knowledge checks;
- progressive worked reveals;
- decision scenarios; and
- reflection prompts with local notes.

Knowledge checks, worked reveals, scenarios, and reflection prompts are the four
interactive learning components. Navigation and progress are runtime features,
not model-authored blocks.

The milestone does not include arbitrary branching courses, executable coding
labs, free-form model grading inside an exported guide, network-backed widgets,
or third-party component plugins.

### 4.4 Pipeline shape

The creative stages remain:

```text
spec → outline → draft → qa → repair
```

The draft and repair stages change from free-form Markdown to guide JSON. Two
deterministic machine steps become visible in the run lifecycle:

```text
approved draft → draft validation → model QA
approved repair → final validation → finalize → export
```

Draft validation informs QA and repair. Final validation gates finalization.

### 4.5 Compatibility

Existing Markdown runs are preserved and remain readable/exportable through the
legacy renderer. They are not silently rewritten into guide JSON. New runs
created after lifecycle integration flips the new-run default use guide schema
v1. An explicit legacy override remains available for compatibility testing and
recovery; a run's content contract is immutable after its first prompt.

## 5. User experience

### 5.1 During drafting

The Stage Workspace shows JSON source editing as an advanced surface. The
default surface is a structured preview with:

- course/module navigation;
- validation status;
- the selected block and its JSON path;
- a source view toggle; and
- stale-content-safe save behavior.

For this milestone, a full form-based visual course editor is not required. The
existing response editor may remain the editing mechanism as long as it provides
JSON syntax feedback, preserves the user buffer, and previews the real runtime.

### 5.2 Validation and repair

Findings appear with severity, rule, location, message, and suggested action.
Selecting a finding navigates to the closest module, section, or block in
preview/source view.

Draft findings do not prevent QA from running. They are added to the QA and
repair context. Final blocking findings prevent finalization. The user may edit
and reapprove the repair response, then rerun final validation.

### 5.3 Preview and export

Preview is an isolated instance of the exact guide renderer used for export. It
shows learner interactions and responsive behavior, but preview progress is
disposable and separate from an exported guide’s saved progress.

Export produces a single HTML file that can be opened directly without an
Education Pipeline process or network connection.

## 6. Artifact contract

A guide-v1 run uses these additional or changed artifacts:

```text
runs/<topic-id>/
  inputs/
    guide-contract.json
  responses/
    draft.response.json
    repair.response.json
  approved/
    draft.json
    repair.json
  reports/
    draft-validation.json
    final-validation.json
  final/
    guide.json
    guide.md
    guide.html
```

`guide-contract.json` records the schema version, blueprint, required outcomes,
time budget, and personalization constraints used by the run. It is generated
deterministically from the approved specification, topic, and snapshotted
profile at the point the draft prompt is written.

`guide.json` is the canonical finalized course. `guide.md` is a deterministic
readable projection, not the source for interactive export. `guide.html` is the
self-contained runtime export.

Legacy Markdown runs retain their existing `.md` stage artifacts and
`final/guide.md` behavior.

## 7. System boundaries

### Python package

The Python package owns:

- guide data types and parsing;
- normalization and canonical serialization;
- validation rules and reports;
- Markdown projection;
- HTML export assembly;
- schema/runtime version compatibility;
- run artifact paths and transitions; and
- API serialization of guide content and findings.

### Guide runtime

The runtime owns:

- guide layout and navigation;
- rendering of the supported block vocabulary;
- interaction state and feedback;
- progress calculation and local persistence;
- accessibility behavior; and
- print and responsive presentation.

### Cockpit

The cockpit owns:

- preview isolation;
- source editing and error feedback;
- findings navigation;
- validation/revalidation actions;
- finalization/export controls; and
- status presentation.

## 8. Milestone acceptance scenario

The required synthetic fixture is a short personalized course titled “Thinking
in Feedback Loops.” Its learner knows project management, enjoys gardening
examples, wants a 30-minute conceptual course, and prefers scenario-based
practice.

The fixture contains:

- three explicit learning outcomes;
- two modules with at least two sections each;
- rich text and callouts;
- two knowledge checks with explanations;
- one multi-step worked reveal;
- one decision scenario using a gardening analogy;
- one reflection prompt;
- a glossary and at least one source record; and
- no private profile details.

Acceptance requires all of the following:

1. A guide JSON fixture parses, normalizes, and validates with no blockers.
2. Known-bad variants trigger stable rule IDs for schema, privacy, outcome,
   unsafe-link, and interaction defects.
3. The pipeline can ingest/approve JSON draft and repair responses.
4. Draft validation is included in the QA and repair context.
5. Final validation blocks finalization until blockers are fixed or permissibly
   waived.
6. Finalize creates canonical `guide.json` and derived `guide.md`.
7. Preview and export render the same modules and blocks.
8. The exported HTML works from a local file with networking disabled.
9. Knowledge-check feedback, reveal steps, scenario feedback, reflection notes,
   navigation, and progress work by keyboard.
10. Refreshing the exported guide restores progress and notes locally.
11. No generated HTML, generated script, private profile text, or unsafe URL is
    accepted into the exported artifact.
12. Existing Markdown fixture runs still export through the legacy path.

## 9. Non-functional requirements

- Parsing, validation, finalization, and export are deterministic for identical
  approved inputs and application/runtime versions.
- Atomic-write and no-clobber semantics continue to apply.
- The Python package remains stdlib-only at runtime unless a later explicit
  dependency decision supersedes this requirement.
- The exported runtime has no required network calls or external assets.
- The initial fixture export should remain comfortably below 1 MiB; 2 MiB is a
  hard milestone warning threshold, not a universal future product limit.
- Interactive controls meet WCAG 2.2 AA design intent and pass the automated and
  manual checks enumerated in the runtime spec.
- Unsupported schema versions fail closed with a useful compatibility error.

## 10. Explicitly deferred

- Full visual block authoring.
- Importing PDFs or source packs.
- Diagnostic learner preflight.
- Section-level model jobs and revision history beyond existing manifest events.
- Additional blueprints beyond what is necessary to encode the fixture’s
  conceptual-foundations contract.
- Course libraries, profile-management polish, and model-settings UI.
- Guide pack/plugin distribution.
- Hosted publishing, sync, collaboration, accounts, or analytics.

## 11. Delivery sequence

Implementation planning should slice the milestone in this order:

1. Guide types, parser, canonical serializer, and fixture.
2. Deterministic validators and report format.
3. Static renderer/runtime with fixture browser tests.
4. Self-contained export and isolated cockpit preview.
5. Draft/repair prompt and artifact migration.
6. Run-state, API, and cockpit findings integration.
7. Legacy compatibility, end-to-end acceptance, and documentation.

Each slice must preserve a green existing test surface or explicitly update a
test whose contract this spec intentionally replaces.
