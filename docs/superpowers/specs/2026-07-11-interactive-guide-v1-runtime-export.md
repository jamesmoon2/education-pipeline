# Interactive Guide v1 — Runtime, Preview, and Export

**Status:** Proposed
**Parent:** `2026-07-11-interactive-guide-v1-milestone.md`

## 1. Purpose

The guide runtime turns validated guide JSON into a polished course that works
without Education Pipeline running. It is maintained application code, never
model output.

Preview and export must share the same renderer and runtime bundle. Preview is
therefore evidence of the exported experience, not a separate approximation.

## 2. Runtime architecture

The runtime has three inputs:

1. normalized guide JSON;
2. versioned runtime JavaScript; and
3. versioned runtime CSS/design tokens.

The export assembler produces one deterministic HTML document containing those
inputs. The runtime reads the embedded JSON, renders only registered component
types, and rejects unknown schema/runtime combinations before rendering course
content.

**Versions.** The runtime asset version is `1.2` (`RUNTIME_VERSION` in
`guide_runtime/__init__.py`). Runtime 1.2 reads guide schema `1.0`, `1.1` and
`1.2`, and adds diagram rendering (§6a) to runtime 1.1. The exported document
records both versions (`data-guide-schema`, `data-guide-runtime`); the runtime
refuses a document whose runtime version is not its own or whose schema is not
in its supported set. Exports keep the runtime they were built with, so an
older export is unaffected by a newer runtime.

The first implementation may use browser-native DOM APIs rather than shipping
the cockpit’s React bundle. This keeps exported guides small and independent of
the application build system. The runtime should be authored as ordinary source
files with unit and browser tests, not constructed as long Python string
literals.

## 3. Document assembly

The self-contained HTML document includes:

- HTML5 doctype and language from course metadata;
- responsive viewport and course title;
- application-owned CSS;
- a minimal static loading/error shell;
- guide JSON in a non-executable `application/json` script element;
- application-owned runtime JavaScript;
- schema/runtime/provenance metadata; and
- a restrictive content security policy.

A `diagram` block (schema 1.2) is assembled on the server as
`<figure class="block diagram" id="{block id}" data-diagram-kind="{kind}">`
holding a `<figcaption>` (title and optional caption) and a complete text
version in `<div class="diagram-text" data-role="diagram-text">`: an ordered
list of steps plus a list of connections (loop-back connections marked) for a
flow, nested lists for a concept map, an ordered list for a timeline, and a
`<table>` with `<th scope>` headers for a comparison. The figure contains no
heading elements, form controls or ids other than the block id.

Before embedding JSON, the exporter escapes characters that can terminate or
recontextualize a script element, including `<`, `>`, `&`, U+2028, and U+2029.
The runtime treats every text field as text or sends Markdown through the safe
application renderer. It never assigns model content directly to executable DOM
attributes.

## 4. Content security policy

The exported file includes a CSP equivalent to:

```text
default-src 'none';
img-src 'none';
style-src <hash-of-runtime-css>;
script-src <hash-of-runtime-js>;
connect-src 'none';
font-src 'none';
media-src 'none';
object-src 'none';
frame-src 'none';
base-uri 'none';
form-action 'none'
```

Exact syntax must be verified in supported browsers when opened from `file:`.
If a browser does not enforce meta CSP for the local-file context, safe DOM
construction and the no-generated-code boundary remain mandatory defenses.

Diagram rendering (§6a) leaves this policy unchanged: the SVG is built in the
page, not loaded, and uses no images.

Runtime CSS and JavaScript hashes are computed deterministically from the exact
embedded bytes. Export does not use `unsafe-eval`, remote scripts, inline event
attributes, remote fonts, or network requests.

## 5. Layout and navigation

The default layout has:

- course header with title, description, estimated time, and progress;
- collapsible module navigation;
- a main reading column;
- previous/next section controls;
- section position and module context;
- a final results page, after the last section, reporting per-outcome results;
- a review queue: entering a section two or more sections past a check the
  learner answered wrong opens a dismissible "Review what you missed" panel
  below that section's heading, naming each missed prompt with a link back to
  it; the results page lists the same missed prompts under their outcome;
- glossary and course-info panels; and
- a course controls menu for theme, print mode, keyboard shortcuts, progress
  reset, and local-data explanation.

Small screens use a single reading column and drawer navigation. Large screens
may show persistent module navigation, but the reading measure remains
comfortable.

Navigation state is reflected in the URL fragment using registered section IDs.
Loading an unknown fragment opens the first section and announces the issue
non-disruptively.

## 6. Interaction behavior

### Knowledge checks

- Choices use native radio buttons or checkboxes.
- Submit is disabled until the required selection exists.
- Feedback announces correct/incorrect state and displays the explanation.
- Retry clears the active selection but keeps attempt/completion history.
- Correctness is never conveyed by color alone.

### Worked reveals

- Initially shows the prompt and a “Reveal first step” control.
- Reveals one ordered step at a time.
- Provides “Show all” and “Reset steps.”
- Announces newly revealed content and moves focus only when the user requests
  it through the control.

### Scenarios

- Choices are presented as a single decision, not a quiz disguised as a branch.
- Selecting/submitting a choice reveals its feedback and the debrief.
- Quality labels such as “best” are explained after submission.
- Retry remains available while completion is retained.

### Reflections

- Provides a labeled textarea and optional guidance.
- Saves notes locally after a short debounce and on blur.
- Clearly states that notes stay in this browser profile for this local file.
- Print output omits notes.
- Resetting course data requires confirmation.

## 6a. Diagram rendering (runtime 1.2)

Diagrams are not interactions: they carry no `data-interactive`, record no
progress and add no focus stop other than the text-version `summary`.

At boot, after the course controls and before the interactive blocks are
enhanced, the runtime's `Diagrams` module walks every `figure.diagram` in
document order and looks up its data by block id in the embedded
`guide-data` (never in the text version). The data is re-checked defensively
(kind, counts, local ids, label lengths, edge endpoints, hub, comparison
values). Then:

- **Flow, concept map, timeline:** the runtime inserts an
  `<svg role="img">` before the text version, with `<title>` (the diagram
  title) and `<desc>` (a sentence derived from the data, such as the number
  of steps and connections and the steps in order). The text version moves
  into a closed `<details class="diagram-text-toggle">` "Text version"
  disclosure that stays in the DOM. The figure is marked
  `data-diagram-state="drawn"`.
- **Comparison:** no SVG. The server table is the rendering; the runtime marks
  it `data-diagram-state="table"` for styling only.
- **Failure:** if the data fails the check or drawing throws, any inserted SVG
  is removed, the text version stays in place outside any disclosure, the figure is marked
  `data-diagram-state="text"` and the block id is logged to the console. One
  bad diagram never stops the rest of the guide. Without JavaScript the text
  version is the diagram.

Layouts are computed from the data alone, with fixed constants and no DOM
measurement, so a given guide yields identical SVG markup in a given browser
engine:

- **Flow:** back edges are found by a depth-first search in document order;
  the remaining edges are layered by longest path from the sources, layers run
  top to bottom, nodes in a layer keep document order, and forward edges are
  straight arrows. Back edges (feedback loops) are dashed curves on the
  right-hand side.
- **Concept map:** the hub in the centre, the other nodes on a ring starting
  at 12 o'clock and running clockwise; edges are straight arrows clipped to
  the node boxes, with labels at their midpoints.
- **Timeline:** two SVGs, a horizontal axis with labels alternating above and
  below, and a vertical list; a CSS media query shows the vertical one on
  narrow screens.

Labels are wrapped by character count and truncated with an ellipsis past a
fixed number of lines; the text version is always complete.

Safety: SVG elements are created with `createElementNS` and filled with
`textContent`. The runtime never uses `innerHTML`, `style` attributes,
`<style>`, `<image>`, `<foreignObject>` or `<script>` in a diagram. All
colours come from classes in `runtime.css` over the existing theme tokens, so
light and dark themes apply unchanged, and a back edge is distinguished by
dashes and its arrowhead, never by colour alone. Diagrams have no animation.

## 7. Progress model

Progress is informational, not a credential or grade.

A section is complete when:

- the learner explicitly marks it complete; or
- all required interactive blocks in that section have been completed and the
  learner navigates beyond it.

An interaction is complete when:

- a knowledge check has been submitted at least once;
- all worked-reveal steps have been shown;
- a scenario choice has been submitted; or
- a reflection has non-whitespace text or is explicitly skipped.

The runtime shows section completion, interaction completion, and per-outcome
results. A knowledge check is correct when the selected set equals the correct
set; a scenario is correct when the chosen choice is the “best” one. Worked
reveals and reflections complete but never score.

Checks answered wrong on the latest attempt are offered back for review, both
in a later section and on the results page; following one of those links opens
the block and, where the block allows retries, returns it to its unanswered
view without changing what is stored until the learner answers again.

Results roll up per learning outcome, through the `outcome_ids` the blocks
already carry. An outcome is *on track* when every block answered for it was
correct on its latest attempt, and *to review* when any was wrong; a block
answered before results were recorded counts as complete for progress and as
unanswered here. A header indicator and the final results page report the
roll-up. These are the learner's own answers read back to them, stored only in
their browser: not a score, not a grade, and not a credential.

## 8. Local persistence

Exported guides store progress and reflection notes in `localStorage` when
available. The storage key includes:

- Education Pipeline namespace;
- course ID;
- guide content hash; and
- guide schema major version.

Stored state includes only:

- completed section IDs;
- interaction attempt/completion state;
- per-check results (the latest attempt and the first one);
- revealed-step counts;
- reflection text;
- last-open section;
- theme preference; and
- print mode.

It does not include learner profile data, source prompts, model provenance, or
run artifacts.

Storage reads are schema-checked and exception-safe. If browser policy disables
storage for local files, the guide remains fully usable for the current session
and displays a one-time non-blocking notice. A content-hash change starts a new
progress record rather than applying stale block IDs to a rebuilt course.

A downloaded progress file carries a format version. Version 2 adds the
per-check result fields to the same state shape, so a version-1 file still
restores in full — its answered blocks simply carry no recorded result. A
version this runtime does not know is refused rather than degraded, because a
newer shape could read as empty and quietly replace real progress.

Progress adopted from anywhere but this document's own record — a restored
progress file, or a previous export's storage key — has each answered check
and scenario rescored from its stored selection against the current answer
key, and where the rescore contradicts the stored result the first-attempt
field becomes null rather than carrying a verdict this course would no longer
produce.

## 9. Safe Markdown renderer

The current Markdown-subset renderer is the conceptual baseline, but v1 must add
the syntax promised by the schema spec and enforce the URL policy before
emitting anchors.

Requirements:

- escape raw HTML before inline transformations;
- never let escaped text become tag or attribute syntax after replacements;
- build links from parsed/validated targets, not regex substitution into an HTML
  attribute;
- add `rel="noopener noreferrer"` to external links;
- mark external links accessibly;
- create internal links only for known guide IDs;
- render fenced code as inert text; and
- return structured render errors rather than partial unsafe output.

The implementation may replace the existing regex-based inline-link renderer if
necessary to satisfy these constraints without adding a runtime dependency.

## 10. Preview integration

The existing body-only Markdown preview endpoint is retained for legacy runs.
Guide v1 adds a format-aware preview operation accepting guide JSON and returning
the full assembled preview document plus validation summary.

Recommended API:

```http
POST /v1/guide-preview
Content-Type: application/json
X-EP-Token: ...

{
  "text": "{...guide JSON...}",
  "include_validation": true
}
```

Success:

```json
{
  "html": "<!doctype html>...",
  "content_sha256": "...",
  "validation": {
    "blocking": 0,
    "errors": 0,
    "warnings": 2
  }
}
```

Malformed JSON returns `400 invalid_guide_json`. Structurally parseable guide
content returns preview HTML when it is safe to render, even if it has ordinary
quality warnings. A schema or security defect that makes rendering unsafe
returns `422 guide_not_renderable` with structured findings.

The cockpit displays preview in an iframe using `srcdoc` with a sandbox that
allows scripts but does not grant same-origin access. Preview persistence is
disabled or namespaced to disposable preview state. The parent page communicates
only through a small validated `postMessage` contract if findings navigation or
height reporting requires it.

## 11. Export behavior

HTML export reads `final/guide.json`; it never rebuilds from a stage response or
Markdown projection. It refuses when:

- the guide schema/runtime version is unsupported;
- the final validation report is absent or does not match the guide hash;
- a non-waived blocking finding remains;
- embedded runtime assets do not match their recorded version/hash; or
- the target exists and overwrite was not explicitly requested.

The export event records:

- source guide path and SHA-256;
- guide schema version;
- runtime version and asset hashes;
- validation report path and hash;
- export path and SHA-256; and
- effective non-sensitive model-stage provenance aliases.

Repeated export from identical canonical guide, runtime assets, metadata, and
validation inputs produces identical bytes. Time-varying event timestamps remain
in the manifest, not inside the export bytes. The guide displays a generation
date only if the canonical final metadata supplies one deterministically.

## 12. Print behavior

A course-controls print-mode control offers two modes, answer key (the
default) and learner copy:

- **Answer key** includes all educational content in a comprehensible
  expanded form: navigation and controls are hidden; all reveal steps and
  scenario feedback are visible; knowledge-check choices and explanations
  are visible; reflection prompts are visible but saved learner notes are
  not; link destinations are legible where practical; and modules and
  sections avoid pathological page breaks.
- **Learner copy** additionally hides knowledge-check correctness marks,
  explanations, and results; worked-reveal step bodies and the conclusion
  those steps build to; and scenario feedback and debriefs, while keeping
  every prompt, choice, and reflection prompt visible. The results page
  and review panels never print, in either mode.

In both modes every diagram's closed "Text version" disclosure opens for
printing (and closes again afterwards), and diagrams avoid page breaks inside
the figure.

The chosen mode is a display preference, not progress: it is stored
alongside theme preference and survives a progress reset.

## 13. Accessibility requirements

The fixture guide must pass automated checks plus manual keyboard review for:

- semantic landmark and heading order;
- visible focus;
- skip link;
- complete keyboard operation;
- keyboard shortcuts for paging sections (`ArrowLeft`/`ArrowRight`) and
  jumping to the course navigation (`/`), inert with a modifier held or
  while an editable control has focus, named in the course controls;
- labels and instructions for every control;
- live announcements that do not steal focus;
- 4.5:1 normal-text contrast and 3:1 large-text/UI contrast;
- no color-only state;
- responsive reflow at 320 CSS pixels;
- reduced-motion preference;
- page title and current-section context; and
- print readability.

Automated checks are necessary but not sufficient. The milestone acceptance log
records the manual keyboard scenario and supported screen-reader smoke test.

## 14. Theme and visual direction

Guide v1 ships one excellent default light theme and one dark theme. Both are
application-owned and use system fonts to remain offline and avoid font-license
or packaging complexity.

The visual direction should feel like a thoughtful modern field guide: strong
typographic hierarchy, generous reading rhythm, restrained color, and clearly
distinct learning interactions. It must not resemble the cockpit’s operational
UI or a generic documentation page.

Custom themes, user CSS, and model-selected styling are deferred.

## 15. Runtime failure behavior

If the embedded guide cannot load, the static shell displays a plain-language
error with schema version, runtime version, and a suggestion to re-export from a
compatible Education Pipeline version. It never leaves a blank page.

One malformed optional block must not crash navigation for the entire course in
development preview. Production export should prevent such content through
validation; defensive runtime handling still reports the block ID and continues
where safe.

## 16. Test contract

Required test layers:

- unit tests for every block renderer and state transition;
- parity fixtures proving Python normalization and runtime expectations agree;
- export tests for escaping, CSP, asset hashes, and byte determinism;
- browser tests from both HTTP preview and a local `file:` URL;
- accessibility automation on the fixture course;
- keyboard interaction tests for every component;
- persistence, reset, corrupt-storage, and unavailable-storage tests;
- print stylesheet snapshot or rendered-PDF inspection; and
- security regression fixtures for raw HTML, closing-script text, unsafe URLs,
  malformed JSON, and unknown block types.
