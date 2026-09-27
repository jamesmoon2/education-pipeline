# Motion Diagrams (Guide Schema 1.3) — Design

- **Date:** 2026-09-27
- **Status:** Implemented on `claude/funny-ptolemy-2b3tdu`
- **Builds on:** [diagram block design (schema 1.2)](2026-09-23-diagram-block-design.md)

## Summary

Schema **1.3** = 1.2 plus one optional diagram field, `motion`, and two
diagram kinds, `sequence` and `stack`. Motion is **data**: the model says
*what* the movement means (`flow`, `step` or `rotate`); the maintained runtime
decides how anything moves, including a WebGL rendering of `stack`. The model
still never supplies coordinates, sizes, colours, timings, SVG, CSS or code.

```
motion   flow    things travel along every connection (flow, stack)
         step    parts play one at a time, learner-controlled (flow, timeline, sequence, stack)
         rotate  the picture turns (concept_map ring, stack in 3D)

sequence actors (2-6, left to right) + messages (1-16, in order)  -> lifelines SVG
stack    layers (2-6, top first)                                  -> 3D slabs (WebGL) or SVG
```

## Why a schema change, not a prompt change

Motion cannot come from prompt wording alone: the model emits guide JSON, and
the runtime draws every diagram from data (spec 1.2, decision 1). The owner's
request — "if it's a flow, things should flow; if it rotates, rotate; use
WebGL where it helps" — therefore needs a data field the model can set and
runtime code that honours it. Letting the model write WebGL or SVG directly
was rejected: it would break the export CSP (hashed scripts only), the
validator's guarantees, byte-determinism, and the accessibility contract.
Every motion is instead a maintained, reviewed rendering of plain data.

## Decisions

1. **Motion names meaning, per kind.** `MOTIONS_BY_KIND` allows only the
   motions whose movement shows something that kind's picture has:
   `flow: (flow, step)`, `concept_map: (rotate,)`, `timeline: (step,)`,
   `sequence: (step,)`, `stack: (flow, step, rotate)`, `comparison: ()`.
   Anything else is `diagram.invalid_motion` (error, blocking, not waivable).
2. **Gated like every feature.** `MOTION_SCHEMA_VERSIONS = {"1.3"}`; 1.3 joins
   the supported, annotation and diagram sets; `LATEST = "1.3"`. A 1.2 guide
   with `motion` gets `schema.unknown_field`; with a new kind,
   `schema.invalid_value` (invalid diagram kind), in parse and in in-memory
   validation alike.
3. **New runs get 1.3.** `create_run` records `interactive_guide 1.3`;
   existing manifests keep their pin. Content type `…;version=1.3`.
4. **1.0–1.2 bytes do not move.** Prompts for 1.2 are now SHA-pinned too
   (`test_guide_v1_prompts_for_1_2_are_byte_identical_to_pre_motion_base`).
   Diagrams without `motion` render the same figure markup as in 1.2. Audit
   location fingerprints leave the new fields out while unset, so finding
   identifiers (and waivers keyed by them) survive the upgrade.
5. **The picture is complete without motion.** Nothing is hidden at rest:
   motion only adds travel, highlight and turning. The text version is
   unchanged in role, and `step` narration is built from the labels and
   `detail` the model already writes.

## JSON shape

```json
{"id": "save-order", "type": "diagram", "kind": "sequence", "motion": "step",
 "title": "What happens when you click Save",
 "actors": [{"id": "browser", "label": "Browser"}, {"id": "api", "label": "API"},
            {"id": "db", "label": "Database", "detail": "Stores the row."}],
 "messages": [{"from": "browser", "to": "api", "label": "POST /orders"},
              {"from": "api", "to": "db", "label": "INSERT order", "detail": "One row per order."},
              {"from": "db", "to": "api", "label": "OK"},
              {"from": "api", "to": "browser", "label": "201 Created"}]}
```

`stack`: `layers` of `{id, label, detail?}`, top first. Limits: actor, layer
and message `label` 48, `detail` 240, single line. Actor and layer ids are
diagram-local. Every actor must send or receive a message
(`diagram.isolated_node`); message ends must name actors
(`diagram.unknown_node`) and differ (`diagram.self_edge`). Repeated messages
are legal (a client may ask twice).

## Document, projection, text version

- The figure gains `data-diagram-motion="<motion>"` only when set.
- `sequence` text version: *Participants* list, then *Messages, in order*
  (`A → B — label: detail`). `stack`: *Layers, top to bottom*.
- Projection (QA/repair Markdown) labels the kind `*Sequence diagram* ·
  motion: step`, so reviewers see the intended motion.

## Prompts

- 1.3 schema reference: the 1.2 reference with `motion` in the common fields,
  the two kinds, a one-line motion map, and "never supply … timings … or code;
  the maintained runtime draws and animates it".
- 1.3 draft and module-draft guidance replaces 1.2's "no module needs a
  diagram" restraint with a stronger bar ("wherever a module teaches a
  structure that is easier to see than to read … draw it") and a `### Motion`
  section: when each motion teaches, ordering elements so motion tells the
  story, `detail` on every step, and never relying on motion alone.
- 1.3 outline gains a `## Visual Plan` request so the draft builds diagrams
  the outline planned.

## Runtime 1.3

- **flow + `flow`:** glowing particles travel every edge (loops included) at a
  constant speed; spacing is derived from path length, computed from the
  layout geometry, never measured from the DOM.
- **`step` (flow, timeline, sequence, stack):** a token travels each
  connection / message in order, lighting its target; a toolbar gives
  **Play/Pause, Step, Restart**, and a polite live region narrates
  "Step 2 of 4: API → Database — INSERT order. One row per order."
- **concept_map + `rotate`:** the ring orbits the hub; labels stay upright.
- **stack:** a deterministic SVG of isometric slabs is always drawn (it is
  the accessible image). When WebGL is available it is replaced visually by a
  WebGL rendering of the same slabs (orthographic camera, so slab centres land
  exactly where the SVG labels point): `rotate` turns it on a turntable,
  `flow` streams particles down through the layers and back up, `step` lifts
  each layer in turn. No WebGL → the SVG stays, with the same motion done in
  2D where it applies.
- **Accessibility:** every moving figure has a visible pause control (WCAG
  2.2.2); nothing autoplays under `prefers-reduced-motion: reduce`; motion
  starts only when the figure is on screen and stops when it leaves; the
  canvas is `aria-hidden`, the SVG keeps `role="img"` with its title and
  description.
- CSP unchanged: animation is attribute/CSSOM updates from the hashed runtime.

## Non-goals

Model-authored animation timing, arbitrary 3D scenes, and shader code. A
"GraphQL" mention in the request was read as **WebGL** (a query language has
no role in drawing).
