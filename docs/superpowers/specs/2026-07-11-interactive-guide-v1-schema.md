# Interactive Guide v1 — Content Schema

**Status:** Proposed
**Parent:** `2026-07-11-interactive-guide-v1-milestone.md`

## 1. Design goals

Guide schema v1 must be:

- safe to render without model-authored executable code;
- expressive enough for a compelling short interactive course;
- deterministic to parse and validate with the Python standard library;
- readable in source control and recoverable from local files;
- stable across Python and TypeScript implementations;
- explicit about outcomes, personalization, sources, and time budget; and
- narrow enough that every supported component can be accessible and tested.

## 2. File and serialization rules

- Encoding is UTF-8.
- The root value is a JSON object.
- `schema_version` is the exact string `"1.0"`.
- Unknown fields are validation errors in v1. This catches model hallucinations
  and misspellings instead of silently dropping content.
- Object member order is not semantically meaningful.
- Canonical serialization uses two-space indentation, UTF-8 characters rather
  than ASCII escaping, keys sorted lexicographically at every object level, and
  one final newline.
- Arrays retain authorial order.
- Every field named `id`, including interaction choice and reveal-step IDs,
  matches `^[a-z][a-z0-9-]{0,63}$` and is unique within the whole guide.
- Human-facing strings must be non-empty after trimming.
- No single human-facing text field may exceed 20,000 Unicode code points.
- The entire parsed guide must fit under the daemon’s configured request/body
  limit. The current 1 MiB transport cap remains the initial limit.

## 3. Root object

```json
{
  "schema_version": "1.0",
  "course": {},
  "outcomes": [],
  "modules": [],
  "glossary": [],
  "sources": []
}
```

Required root fields are exactly those shown. `glossary` and `sources` may be
empty arrays; all other collections must be non-empty.

## 4. Course metadata

```json
{
  "id": "feedback-loops",
  "title": "Thinking in Feedback Loops",
  "subtitle": "A practical introduction through projects and gardens",
  "description": "A short course about recognizing and reasoning about feedback.",
  "language": "en",
  "blueprint": "conceptual-foundations",
  "estimated_minutes": 30,
  "difficulty": "introductory",
  "learner_summary": "Designed for a project manager who prefers concrete scenarios."
}
```

Required fields:

- `id`
- `title`
- `description`
- `language`: a BCP 47 language tag accepted by the application’s v1 validator
- `blueprint`: `conceptual-foundations` for the fixture; stored as a string so
  later registered blueprints do not require a schema-version change
- `estimated_minutes`: integer from 5 through 10,000
- `difficulty`: one of `introductory`, `intermediate`, `advanced`, `mixed`

Optional fields:

- `subtitle`
- `learner_summary`

`learner_summary` must be derived only from publishable profile information. It
must explain relevant adaptation without identifying or exposing the learner.

## 5. Outcomes

```json
{
  "id": "identify-loop",
  "text": "Identify reinforcing and balancing feedback in a familiar system."
}
```

Each outcome requires `id` and `text`. A guide has 1–20 outcomes. Outcome IDs are
referenced from modules and knowledge checks so coverage is deterministic.

## 6. Modules and sections

```json
{
  "id": "loop-basics",
  "title": "How loops behave",
  "summary": "Recognize the structure and behavior of common loops.",
  "outcome_ids": ["identify-loop"],
  "estimated_minutes": 14,
  "sections": []
}
```

Each module requires:

- `id`, `title`, and `summary`;
- one or more valid `outcome_ids`;
- `estimated_minutes`, an integer from 1 through 1,000; and
- one or more `sections`.

The sum of module estimates should be reasonably close to the course estimate;
the validator defines the warning threshold.

A section is:

```json
{
  "id": "reinforcing-loops",
  "title": "Reinforcing loops",
  "blocks": []
}
```

Each section requires `id`, `title`, and one or more blocks.

## 7. Shared block rules

Every block is an object with:

- `id`: globally unique guide ID; and
- `type`: one of the registered v1 types.

Blocks may optionally include:

- `outcome_ids`: valid outcomes directly practiced or taught by the block; and
- `source_ids`: valid sources supporting claims in the block.

Unknown block types are errors. Unknown block fields are errors.

Text-bearing fields use the safe Markdown subset unless the field is explicitly
described as plain text. Raw HTML is never part of the subset. Fenced code is
rendered as inert text and may be allowed inside rich text or worked steps, but
not as executable guide behavior.

## 8. Block type: `rich_text`

```json
{
  "id": "loop-introduction",
  "type": "rich_text",
  "outcome_ids": ["identify-loop"],
  "source_ids": ["meadows-2008"],
  "markdown": "A **feedback loop** occurs when..."
}
```

Required: `id`, `type`, `markdown`.
Optional: `outcome_ids`, `source_ids`.

This block provides headings below the section level, paragraphs, lists, tables,
emphasis, safe links, and inert code examples. It must not contain a top-level
course title.

## 9. Block type: `callout`

```json
{
  "id": "garden-analogy",
  "type": "callout",
  "kind": "connection",
  "title": "Connect it to gardening",
  "markdown": "More growth creates more leaves, which can create more growth..."
}
```

Required: `id`, `type`, `kind`, `markdown`.
Optional: `title`, `outcome_ids`, `source_ids`.

`kind` is one of:

- `key-idea`
- `connection`
- `example`
- `warning`
- `misconception`
- `source-note`

Kinds affect iconography and labels, not arbitrary styling.

## 10. Block type: `knowledge_check`

```json
{
  "id": "check-loop-type",
  "type": "knowledge_check",
  "outcome_ids": ["identify-loop"],
  "mode": "single",
  "prompt": "A savings balance earns interest. What kind of loop is this?",
  "choices": [
    {"id": "reinforcing", "label": "Reinforcing", "correct": true},
    {"id": "balancing", "label": "Balancing", "correct": false}
  ],
  "explanation": "Interest increases the balance, which increases later interest.",
  "retry": true
}
```

Required:

- `id`, `type`, `outcome_ids`, `mode`, `prompt`, `choices`, `explanation`,
  `retry`.

`mode` is `single` or `multiple`. There are 2–8 choices. Each choice requires a
globally unique `id`, plain-text `label`, and Boolean `correct`. A single-choice
check has exactly one correct choice; a multiple-choice check has at least one
correct and one incorrect choice.

The runtime does not show correctness until submission. It shows the explanation
after submission and, when `retry` is true, allows another attempt without
discarding the recorded completion state.

## 11. Block type: `worked_reveal`

```json
{
  "id": "map-garden-loop",
  "type": "worked_reveal",
  "outcome_ids": ["map-loop"],
  "prompt": "Map the reinforcing loop in a garden’s plant growth.",
  "steps": [
    {"id": "name-quantity", "title": "Choose the quantity", "markdown": "Start with plant biomass."},
    {"id": "trace-change", "title": "Trace the change", "markdown": "More biomass creates more leaf area..."}
  ],
  "conclusion": "The loop reinforces growth until a limiting factor becomes important."
}
```

Required: `id`, `type`, `outcome_ids`, `prompt`, `steps`, `conclusion`.

There are 2–12 ordered steps. Each step has a globally unique ID, optional plain-text title,
and Markdown body. The learner reveals steps one at a time. “Show all” is
available and does not imply mastery.

## 12. Block type: `scenario`

```json
{
  "id": "garden-intervention",
  "type": "scenario",
  "outcome_ids": ["choose-intervention"],
  "prompt": "Pests rise as plants become denser. What should you inspect first?",
  "choices": [
    {
      "id": "spray",
      "label": "Immediately increase pesticide use",
      "quality": "weak",
      "feedback": "This treats a symptom before checking the feedback structure."
    },
    {
      "id": "map",
      "label": "Map density, pest pressure, and predator response",
      "quality": "best",
      "feedback": "This reveals both reinforcing pressure and possible balancing response."
    }
  ],
  "debrief": "Good intervention begins by locating the important loop and delay."
}
```

Required: `id`, `type`, `outcome_ids`, `prompt`, `choices`, `debrief`.

There are 2–6 choices. Each choice requires `id`, plain-text `label`, `quality`,
and Markdown `feedback`. `quality` is one of `best`, `reasonable`, `weak`, or
`harmful`; exactly one choice is `best`. This is a one-decision scenario in v1,
not an arbitrary branching tree.

## 13. Block type: `reflection`

```json
{
  "id": "find-personal-loop",
  "type": "reflection",
  "outcome_ids": ["identify-loop"],
  "prompt": "Where do you see a reinforcing loop in a project you know?",
  "guidance": "Name the changing quantity and trace how it eventually affects itself.",
  "placeholder": "Write a private note..."
}
```

Required: `id`, `type`, `outcome_ids`, `prompt`.
Optional: `guidance`, `placeholder`.

The runtime provides a local note area. Notes never leave the guide, are not
included in exports or print output, and can be cleared from the course controls.
The schema never contains a learner’s response.

## 14. Glossary

```json
{
  "id": "feedback-loop",
  "term": "Feedback loop",
  "definition": "A chain of cause and effect that eventually influences its starting quantity."
}
```

Each entry requires globally unique `id`, plain-text `term`, and Markdown
`definition`. Terms are displayed in a glossary panel; automatic in-text term
replacement is deferred.

## 15. Sources

```json
{
  "id": "meadows-2008",
  "title": "Thinking in Systems",
  "authors": ["Donella H. Meadows"],
  "url": "https://example.org/source",
  "published": "2008",
  "note": "General background on feedback structures."
}
```

Required: `id`, `title`.
Optional: `authors` (non-empty strings), `url`, `published`, `note`.

Only `https` and `http` source URLs are supported in v1. The runtime marks
external links and opens them only after an explicit learner action. A source
record is provenance, not proof that every attached claim is correct.

## 16. Markdown subset and URL policy

Supported inline syntax:

- plain text;
- emphasis and strong emphasis;
- inline code;
- safe links; and
- escaped punctuation.

Supported block syntax inside Markdown-bearing fields:

- paragraphs;
- headings below the owning section’s level;
- ordered and unordered lists;
- fenced code rendered as text;
- block quotes; and
- simple tables.

Raw HTML is escaped. Images are not supported in v1; this avoids remote tracking,
asset packaging, inaccessible alt-text failures, and path ambiguity while the
guide contract is established.

Link targets may be:

- `https://...`
- `http://...`
- `#<known-guide-id>`

All other schemes, protocol-relative URLs, data URLs, absolute filesystem paths,
and relative filesystem traversal are rejected.

## 17. Cross-object invariants

Validation enforces:

- every ID is globally unique;
- every outcome/source reference exists;
- every outcome is assigned to at least one module;
- every outcome is taught by at least one explanatory block;
- every outcome is assessed or practiced by at least one knowledge check,
  scenario, worked reveal, or reflection;
- each module has at least one interactive block;
- the guide as a whole includes every required v1 interactive type for the
  selected milestone fixture contract;
- estimated module minutes total within 20% or 10 minutes, whichever is larger,
  of the course estimate;
- course and module ordering is preserved exactly as authored; and
- no private denylist string supplied by the run’s guide contract appears in a
  publishable field after normalization.

## 18. Versioning

- `1.0` readers accept only `1.0` documents.
- Additive optional fields require schema `1.1`, not silent acceptance by a 1.0
  reader.
- Removing or changing meaning requires schema `2.0`.
- The application may ship explicit migrations between known versions. A
  migration creates a new artifact and manifest event; it never overwrites an
  approved source silently.
- Export records both `guide_schema_version` and `guide_runtime_version`.

## 19. Canonical projection to Markdown

`final/guide.md` is generated from `guide.json` for reading, diffs, and graceful
portability. It contains:

- title and course description;
- outcomes;
- modules and sections in order;
- textual content for every block;
- answer choices and explanations clearly labeled;
- worked-reveal steps expanded;
- scenario feedback expanded;
- reflection prompts without learner notes;
- glossary; and
- sources.

The projection is deterministic and lossy only with respect to interactive
state—not educational content.
