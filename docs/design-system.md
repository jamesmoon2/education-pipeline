# Education Pipeline Design System

**Status:** Cockpit shipped on the "Threshold" revision (§4, §5, §6.7, §12); guide
runtime still on the earlier mineral palette pending §13 Phase D
**Applies to:** Local cockpit, interactive guide runtime, preview, export, and print
**Product source:** [`product-requirements.md`](product-requirements.md)
**Working name:** Learning Workbench · visual revision: **Threshold (388 nm)**

## 1. Design thesis

Education Pipeline should feel like a well-made instrument for serious independent
learning: calm enough for an hour of reading, precise enough to trust during a
multi-stage generation run, and legible enough that the machinery never obscures
the learner's next decision.

The product has two modes with different needs:

- The **workbench** is where a learner defines, generates, inspects, repairs, and
  approves a course. It should feel operational, compact, and trustworthy.
- The **guide** is where the learner studies. It should feel spacious, readable,
  and intellectually engaging.

They should not look identical. They should share type, color semantics, spacing,
control behavior, and one structural signature: the **learning thread**.

The learning thread is a visible line connecting consequential states. In the
workbench it traces the course from brief through export. In a guide it traces
outcomes, modules, checkpoints, and completion. It is not a decorative timeline;
it answers either “where did this artifact come from?” or “where am I in the
learning sequence?”

## 2. Audience and posture

### Primary posture: capable adult, unfamiliar domain

The center of gravity is a mid-career professional who is learning outside their
current specialty. The interface may contain sophisticated concepts, but it must
not assume that the learner knows pipeline terminology, model configuration, or
the subject being studied.

### Secondary posture: motivated student

High-school and college learners need the same clarity, feedback, keyboard access,
and visible progress. The visual identity should not become juvenile, gamified, or
classroom-administrative to accommodate them.

### Brand attributes

- Rigorous, not academic-theatrical.
- Encouraging, not congratulatory.
- Technical, not developer-only.
- Crafted, not ornamental.
- Local and inspectable, not cloud-magical.

## 3. Experience principles

### 3.1 Show the next sound move

Every workbench screen has one visually dominant next action. Secondary actions
stay available without competing with it. A page should answer “what is safe to do
next?” before it explains internal state.

### 3.2 Make quality visible

Validation, approval, provenance, and privacy are part of the product's value.
Represent them as structured evidence near the artifact they govern, not as a
dashboard of decorative scores.

### 3.3 Let density follow the task

The course library and setup flow use generous spacing. Stage workspaces and model
configuration may be denser. Guides prioritize line length, rhythm, and whitespace.
One global density setting would make at least one of these surfaces worse.

### 3.4 Explain in learner language

Use “Create course,” “Review outline,” and “Check guide” in primary paths. Terms
such as `response_ingested`, hashes, provider commands, and schema versions belong
in details, provenance, and diagnostics.

### 3.5 Preserve orientation

The learner should always be able to see the course name, current stage or module,
completion state, and way back. Avoid modal journeys for primary work.

### 3.6 Earn every visual element

Rules, icons, labels, and color must encode hierarchy, state, provenance, or an
action. Decoration that could be moved to an unrelated AI product does not belong.

## 4. Visual direction

### 4.1 Palette — Threshold (388 nm)

388 nm is the violet edge of visible light: the last wavelength the eye can see
before ultraviolet. The cockpit borrows that threshold as its organizing idea. A
brief nobody can read yet sits in the near-ultraviolet; an exported guide is warm,
visible light. Everything in between is the spectrum the learning thread traces.

The palette is therefore violet-ink rather than blue-mineral, with one cyan
"signal" for live work and one amber for the warm end of the spectrum. The dark
theme is a room under blacklight — what matters fluoresces, the rest recedes. The
light theme is the same room with the shutters open.

| Foundation | Light | Dark | Role |
| --- | --- | --- | --- |
| Ink | `#16132B` | `#EDEBF8` | Primary text (canvas in dark) |
| Paper | `#F4F3FB` | `#0D0B1A` | Canvas |
| Graphite | `#5B5876` | `#A9A5C6` | Secondary text and quiet controls |
| Violet | `#5B3DF5` | `#A78BFA` | Primary action, links, focus, the tour |
| Signal (cyan) | `#0E7490` | `#22D3EE` | A provider job is working right now |
| Lichen | `#136247` | `#6EE7B7` | Completion and sound state |
| Amber | `#7F430A` | `#FBBF24` | Attention, warnings, review-needed |

Error uses oxide red (`#B83232` / `#FB7185`) as a semantic exception, reserved for
failed or unsafe states and never used as a brand accent.

The **spectrum** is the one gradient in the product: violet → cyan → amber. It is
allowed on exactly four things — the learning thread's completed connectors, the
brand mark, the dock's edge tube, and a completion meter — because in each place
it encodes progress from unseen to visible. No other surface may use a gradient
of more than one hue.

The **dock** is always the dark strip, in both themes: a blacklight tube beside
the page. Tokens for it are prefixed `--ep-color-rail-*`.

Every light-theme text/surface pair clears WCAG AA with margin (≥ 5:1 for
semantic text on its soft surface) so a half-second transform animation or a
translucent surface can never pull it under 4.5:1.

### 4.2 Semantic color tokens

Use product-prefixed names. Never reuse one custom-property name for a color and a
type size.

```css
:root {
  color-scheme: light;
  --ep-color-canvas: #f7f8fa;
  --ep-color-surface: #ffffff;
  --ep-color-surface-subtle: #eef1f5;
  --ep-color-text: #182033;
  --ep-color-text-muted: #5d6678;
  --ep-color-border: #cfd5df;
  --ep-color-border-strong: #9fa9ba;
  --ep-color-accent: #3157a4;
  --ep-color-accent-hover: #264784;
  --ep-color-accent-soft: #e7edfa;
  --ep-color-success: #47705d;
  --ep-color-success-soft: #e7f0eb;
  --ep-color-warning: #a05410;
  --ep-color-warning-soft: #f8ecdd;
  --ep-color-danger: #b23a3a;
  --ep-color-danger-soft: #fae9e8;
  --ep-color-focus: #5277c5;
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --ep-color-canvas: #121722;
  --ep-color-surface: #1a2130;
  --ep-color-surface-subtle: #222b3b;
  --ep-color-text: #eef1f6;
  --ep-color-text-muted: #b4bdcc;
  --ep-color-border: #394457;
  --ep-color-border-strong: #59667a;
  --ep-color-accent: #91ace8;
  --ep-color-accent-hover: #b2c5ef;
  --ep-color-accent-soft: #273655;
  --ep-color-success: #8eb8a1;
  --ep-color-success-soft: #22382e;
  --ep-color-warning: #e2a363;
  --ep-color-warning-soft: #462f1d;
  --ep-color-danger: #ef9390;
  --ep-color-danger-soft: #472526;
  --ep-color-focus: #a8bff0;
}
```

Status is never conveyed by color alone. Pair color with a plain-language label
and, where useful, a stable shape: check for complete, square for current, ring for
waiting, triangle for attention, and octagon for blocked.

### 4.3 Typography

Bundle fonts with the application so the cockpit and exported guide work offline.
Before distribution, include the exact font files, licenses, and provenance in the
release asset audit.

| Role | Family | Use |
| --- | --- | --- |
| Interface | IBM Plex Sans | Navigation, controls, workbench headings, tables |
| Reading | Literata | Guide prose, course introductions, extended explanations |
| Technical | IBM Plex Mono | Commands, hashes, JSON paths, logs, provenance |

All three are open-source families suitable for local bundling. System fallbacks
must remain functional while fonts load or if an asset is unavailable.

```css
--ep-font-interface: "IBM Plex Sans", "Segoe UI", sans-serif;
--ep-font-reading: "Literata", Georgia, serif;
--ep-font-technical: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
```

The contrast between interface sans and reading serif distinguishes making from
learning without splitting the brand. Course titles remain in Plex Sans; Literata
begins with the course description and lesson prose. This avoids an ornamental
“luxury editorial” treatment.

#### Type scale

| Token | Size / line height | Use |
| --- | --- | --- |
| `display` | `2.75rem / 1.05` | Guide title on wide screens only |
| `title` | `2rem / 1.15` | Page title, module title |
| `heading` | `1.375rem / 1.25` | Section and panel heading |
| `subheading` | `1.0625rem / 1.35` | Card title, interaction prompt |
| `body` | `1rem / 1.55` | Workbench body and controls |
| `reading` | `1.125rem / 1.72` | Guide prose |
| `small` | `0.875rem / 1.45` | Supporting text and metadata |
| `micro` | `0.75rem / 1.35` | Provenance labels and compact table metadata |

Use sentence case. Avoid all-caps eyebrow text. Utility labels may use `0.02em`
letter spacing; headings and body copy should not.

### 4.4 Spacing, shape, and depth

```css
--ep-space-1: 0.25rem;
--ep-space-2: 0.5rem;
--ep-space-3: 0.75rem;
--ep-space-4: 1rem;
--ep-space-6: 1.5rem;
--ep-space-8: 2rem;
--ep-space-12: 3rem;
--ep-space-16: 4rem;

--ep-radius-control: 0.55rem;
--ep-radius-surface: 1rem;
--ep-radius-dialog: 1.25rem;
```

- Use a four-pixel base grid.
- Pill shapes are reserved for segmented controls (tabs, content mode, wizard
  step track, theme toggle) and status chips.
- Depth has three steps: `--ep-shadow-1` for resting controls and panels,
  `--ep-shadow-2` for hover and the pipeline thread, `--ep-shadow-3` for floating
  dialogs, toasts and the tour card.
- **Glass** (`--ep-color-surface-glass` + `backdrop-filter: blur(14px)`) is for
  panels that sit over the aurora backdrop: the library table, the pipeline
  thread, wizard and settings sections, stat tiles. Solid `--ep-color-surface`
  is for reading surfaces — rendered Markdown, code, diffs, the guide frame —
  where nothing should show through the text.
- The **aurora** backdrop is three slow light fields behind the shell (46–64 s
  drift, `alternate`, stopped under `prefers-reduced-motion`) with a film-grain
  veil. It is the one purely atmospheric element in the product and is kept at low
  alpha so every foreground pair is measured against the canvas token.
- A card still means a separable object or action; the shell's page sections are
  glass panels, not cards, and carry no chrome beyond a border and a title.
- Minimum interactive target is 44 by 44 CSS pixels in primary learning flows.

## 5. Signature: the learning thread

The learning thread is a 3-pixel rule with nodes at meaningful states. Completed
connectors carry the spectrum (violet → cyan → amber); future connectors are the
border color; a running node pulses cyan; a node awaiting review glows amber; the
node the run is waiting on is enlarged with a violet halo. Labels, not color,
communicate state — every node still says "Complete", "Needs review", "Ready to
run" in words.

### In the workbench

- A node is a pipeline stage with its state and next allowed action.
- Selecting a stage reveals its artifact without losing the thread.
- Validation and approval attach to the relevant node as evidence, not detached
  dashboard widgets.
- The primary action sits immediately after the active node.

### In a guide

- A node is a module or section, not every heading.
- The thread shows location and completion, and provides previous/next movement.
- Outcomes connect to the sections that practice or assess them in an optional
  “Learning map” view.
- On small screens it becomes a thin horizontal progress track below the guide
  header.

### Motion

Three durations (`140 / 260 / 520 ms`) and two curves (`--ep-ease-out`, a soft
`--ep-ease-spring` for markers and the tour spotlight). Page entrances translate
10px upward and **never fade**: an opacity fade blends text toward the canvas for
half a second, which is exactly when an automated contrast check samples it. Live
lamps (running job, jobs beacon) pulse; nothing else loops. Respect
`prefers-reduced-motion` (all animation collapses to 1 ms) and never animate
reading content on scroll.

## 6. Layout system

### 6.1 Workbench shell

Wide screens use a compact application rail, a primary workspace, and an optional
context panel. The workspace, not a centered card, owns the viewport.

```text
┌──────────────┬────────────────────────────────┬─────────────────────┐
│ Education    │ Course title / current stage   │ Context             │
│ Pipeline     │                                │ validation          │
│              │ Primary artifact or task       │ provenance          │
│ Courses      │                                │ help                │
│ Profiles     │                                │                     │
│ Settings     │                                │                     │
└──────────────┴────────────────────────────────┴─────────────────────┘
  13rem         minmax(34rem, 1fr)                18–22rem, optional
```

- Maximum shell width: `90rem`.
- Primary reading/editing column: `42–52rem` depending on artifact type.
- Tables and diffs may use the full workspace width.
- Below `64rem`, the context panel moves below the artifact.
- Below `48rem`, the application rail becomes a top bar and drawer.

The global header says **Education Pipeline**, not “Education Pipeline Cockpit.”
“Cockpit” is a useful product metaphor but developer-oriented interface copy.

### 6.2 Course library

Courses are rows or quiet list items, not a grid of oversized cards. Each item
shows title, learner, current stage, last activity, and one next-action link.
Filtering and archive controls remain secondary.

### 6.3 New course

Use a guided sequence with a persistent course-contract summary.

```text
┌───────────────────────────────┬──────────────────────────┐
│ What do you want to learn?    │ Course so far            │
│                               │ Topic                    │
│ focused question / fields     │ Intended outcome         │
│                               │ Time and depth           │
│ Back            Continue      │ Learner profile          │
└───────────────────────────────┴──────────────────────────┘
```

The sequence is Topic → Outcome → Learner → Approach → Model plan → Review. Do not
expose topic IDs, TOML, or per-stage providers in the default path. Offer those in
“Import existing definition” and “Adjust model plan.”

### 6.4 Course run

The run board is the fullest expression of the learning thread. The active stage
expands in place to show its plain-language state, blocking evidence, and primary
action. Completed and future stages remain compact. Summary counts support the
thread but do not replace it.

### 6.5 Stage workspace

Use three stable views: Artifact, Compare, and Details. Prompt, command, logs,
provenance, and raw response live in Details. Findings appear in the context panel
and deep-link to the affected location. Editing uses the full workspace width with
a sticky save bar that clearly distinguishes Save, Approve, and Rerun.

### 6.6 Guide shell

```text
┌───────────────────────────────────────────────────────────┐
│ Course title                                42% complete  │
├──────────────┬──────────────────────────────┬─────────────┤
│ Learning     │ Module / section             │ Study tools │
│ thread       │                              │ Outcomes    │
│ Modules      │ 64–72 character prose        │ Glossary    │
│ Sections     │ Examples and interactions    │ Notes       │
└──────────────┴──────────────────────────────┴─────────────┘
```

The right study-tools rail is optional and collapses before the module rail. On
mobile, course progress stays visible, module navigation opens as a drawer, and
study tools appear after the current section.

### 6.7 Guided tour

The tour is a blacklight passed over the workbench: a dimmed backdrop, a glowing
cutout on the surface being explained, and a card beside it. It exists because the
cockpit has real machinery (stages, jobs, model plans) and the first-run welcome
panel can only say so much.

- Two tours: **workbench** (eight steps, hops `/` → `/new` → `/settings`) and
  **run board** (five steps over one run's thread, evidence, plan and jobs).
- Never auto-launches. Entry points: the dock button, the welcome panel, Settings
  → Appearance → "Replay the tour", the run board's "Explain this board", and a
  `?tour=1` deep link (consumed once, then removed from the address bar).
- Steps anchor to `data-tour="…"` hooks. The provider waits up to 1.5 s for an
  anchor after a route hop; a missing anchor degrades to a centered card, never
  an error.
- Modal and keyboard-complete: `role="dialog" aria-modal`, focus moves to the card
  on every step and returns to the launcher on exit, ←/→ step, Esc leaves, Tab
  cycles inside the card.
- Completion or skipping is remembered in `localStorage` (`ep.tour.completed`).
- Copy stays in learner language (§3.4): what a surface is for and what is safe
  to do there.

## 7. Component language

### 7.1 Actions

- **Primary:** filled Blueprint; one per action region.
- **Secondary:** surface with strong border.
- **Quiet:** text button for low-consequence actions.
- **Danger:** outline by default; filled only in the final destructive confirmation.

Button labels state the result: “Review outline,” “Run validation,” “Save changes,”
“Approve outline.” Avoid “Submit,” “Proceed,” and “Generate” without an object.

### 7.2 Fields

Labels sit above controls and remain visible. Help text explains consequences or
gives a concrete example; placeholders do not replace labels. Advanced technical
fields use the technical font only for their values. Validation appears adjacent
to the field and gives a recovery action.

### 7.3 Status markers

Use compact markers for real state only: Draft, Needs review, Ready to run,
Running, Blocked, Complete, Stale, and Waived. Prefer these words over internal
state constants. Do not use tags as decoration or as a substitute for grouping.

### 7.4 Evidence panel

Validation findings, approvals, privacy checks, and provenance share one evidence
pattern:

1. plain-language status;
2. affected artifact/location;
3. why it matters;
4. recommended action; and
5. technical details on disclosure.

Blocking findings use a left danger rule and octagon marker, but avoid turning the
entire panel red.

### 7.5 Empty, loading, and error states

- Empty: explain what will live here and offer the next valid action.
- Loading: preserve the page frame and use a text status for waits under two
  seconds; use a skeleton only when it prevents layout shift.
- Error: name what failed, what was preserved, and what the learner can do next.
- Offline/local: do not present normal local-only behavior as a warning.

### 7.6 Dialogs

Reserve dialogs for confirmation, compact creation, and blocking decisions.
Waivers are a justified dialog because they require a deliberate recorded reason.
Editing, comparison, setup, and normal navigation stay on pages or panels.

## 8. Guide learning objects

Every object has a pedagogical job and a stable visual grammar. These are not
arbitrary content cards.

| Object | Visual treatment | Job |
| --- | --- | --- |
| Concept | Normal reading flow with a strong heading | Explain one coherent idea |
| Worked example | Numbered steps on the thread, conclusion below | Expose reasoning or procedure |
| Knowledge check | Bordered response area, feedback in place | Retrieve and correct |
| Scenario | Decision prompt with consequence-led choices | Practice judgment |
| Reflection | Quiet ruled field with local-storage note | Connect learning to experience |
| Cross-training | Split “What transfers / Where it breaks” block | Reuse prior professional judgment safely |
| Failure mode | Ochre rule, tripwire statement, concrete example | Prevent simplistic application |
| Evidence | Source, confidence, and claim relationship | Support verification |

Knowledge checks and scenarios should not turn green as a whole on success. Mark
the selected response, state the outcome in text, and make the explanation the
strongest follow-up element.

Diagrams, comparison tables, and relationship maps are core learning content, not
optional decoration. They should follow the same color semantics, provide text
alternatives, and remain meaningful in print.

## 9. Iconography and illustration

- Icons are a small inline SVG set in `web/src/components/icons.tsx`: one stroke
  weight (1.6) on a 20-unit grid, `currentColor`, always `aria-hidden` beside a
  text label. No icon font, no network.
- The brand mark is a spectrum bar cut at 388 nm with three nodes — the three
  artifacts every stage keeps (prompt, response, approved copy).
- Icons accompany labels in primary navigation; they do not replace labels.
- Status icons use the stable shapes described in the color section.
- Do not use sparkles, robots, magic wands, brains, graduation caps, or floating
  abstract geometry as product identity.
- Course imagery, when present, should be subject-specific and instructional: a
  real diagram, annotated object, map, or process—not generic inspiration art.

## 10. Accessibility and resilience

- Meet WCAG 2.2 AA contrast and interaction requirements as a baseline.
- Keep a visible 3px focus ring with a 2px offset on all interactive elements.
- Never remove focus outlines in favor of color-only hover changes.
- Use landmarks, heading order, descriptive page titles, live regions, and skip
  links consistently across cockpit and guide.
- Support 200% text zoom without horizontal scrolling in normal prose flows.
- Keep guide prose at 64–72 characters per line.
- Honor system light/dark preference until the learner chooses a stored theme.
- Preserve full guide content and structure when JavaScript or local storage is
  unavailable.
- Print removes navigation and controls, expands disclosures and interactions,
  repeats table headings, and avoids splitting learning objects when possible.
- No design-system dependency may introduce a network requirement into ordinary
  guide use.

## 11. Voice and vocabulary

### Use

- Course, learner, outcome, module, section, practice, review, check, source.
- Build course, review outline, run checks, repair guide, preview course, export.
- “Stored on this device” and “Included in the exported guide.”
- “Needs review” and “Blocked by 2 findings.”

### Avoid in the default path

- Pipeline internals such as ingest, artifact state constants, payload, or hash.
- “AI-powered,” “magic,” “effortless,” “instant expert,” or quality superlatives.
- “Oops,” apology-led errors, or celebratory confetti.
- “Cockpit” as a global product label.

Provider and model names are factual configuration. They should not become visual
brand elements.

## 12. Anti-slop guardrails

The following patterns are out of character unless a specific learning object
requires them. The Threshold revision deliberately admits four effects — the
spectrum gradient, glow, glass and the aurora — under the rules in §4.1 and §4.4:
each must encode progress, live state, attention or layering, and each has a
named token and a reduced-motion fallback. Outside those rules they remain slop:

- multi-hue gradients on anything but the four spectrum surfaces; glow on a
  resting element; glass over reading text; more than one aurora;
- a giant marketing headline inside the working application;
- a grid of identical rounded cards for unrelated content;
- rainbow status chips or decorative tags;
- oversized metric tiles that detach counts from the artifacts they describe;
- serif display type on a cream canvas used to simulate intellectual seriousness;
- terminal styling applied to ordinary learner-facing controls;
- constant hover motion, scroll reveals, parallax, or ambient animation;
- model-provider logos in the main workflow; and
- vague generated copy standing in for real product states.

## 13. Migration from the current UI

The current code is a sound semantic starting point, but its visual layer is
mostly browser defaults and the cockpit and guide use unrelated token systems.
Migrate without rewriting working behavior.

### Phase A — Foundations

1. Add bundled, licensed font assets and a shared token source.
2. Map tokens into `web/src/styles.css` and
   `education_pipeline/guide_runtime/assets/runtime.css`.
3. Establish reset, focus, typography, controls, status, surface, and dark-theme
   primitives.
4. Add visual regression fixtures for light, dark, mobile, and print.

### Phase B — Workbench shell (done: Threshold revision)

1. ~~Replace the centered `64rem` application wrapper with the rail/workspace shell.~~
   Shipped as the dock + workspace shell with the aurora backdrop.
2. ~~Rename the visible header to “Education Pipeline.”~~
3. ~~Restyle the course library, New Course sequence, and run board around next
   action and the learning thread.~~ Library gained stat tiles and completion
   meters; the run board leads with the next action and the spectrum thread.
4. Map existing `PrimaryAction`, `RunPlanPanel`, `PlanStageRow`, and
   `ValidationFindingsPanel` behaviors to shared components before changing their
   interaction contracts. (Interaction contracts were left untouched in this
   revision; every accessible name and role is unchanged.)
5. Added: three-way theme control (system / light / dark, applied before first
   paint), the guided tour (§6.7), a skip link, and page-enter motion.

### Phase C — Stage workspace

1. Introduce Artifact, Compare, and Details views.
2. Move validation and provenance into the evidence panel.
3. Improve editor, diff, log, conflict, stale-state, and save-action hierarchy.
4. Verify the entire keyboard flow before adding motion.

### Phase D — Guide runtime

1. Apply reading typography, the guide shell, and learning-thread navigation.
2. Give each supported interaction type its defined pedagogical treatment.
3. Add Cross-training, Failure mode, and Evidence objects only through versioned,
   reusable schema/runtime work—not one-off generated markup.
4. Verify preview/export parity, no-network behavior, persistence fallback, dark
   theme, responsive behavior, and print.

## 14. Definition of done for the visual-system milestone

- Cockpit and guide derive from one documented, product-prefixed token system.
- The course library, New Course, Course Run, Stage Workspace, and Guide Preview
  have approved responsive compositions.
- Every existing state has a plain-language label and non-color-only treatment.
- The learning thread works in both run and guide contexts without implying false
  linearity.
- Bundled font and icon licenses are present and pass the public asset audit.
- Light, dark, 200% zoom, keyboard-only, reduced-motion, mobile, and print checks
  pass on representative fixtures.
- Preview and exported guide remain visually and behaviorally equivalent.
- No ordinary guide use requires network access.
- User testing confirms that a learner can identify the current state, next action,
  blocking issue, and route back without instruction.
