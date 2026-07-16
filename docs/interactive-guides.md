# Interactive Guides (guide v1)

This page documents the interactive-guide workflow delivered by the
`interactive_guide` 1.0 content contract: what the pipeline produces, where
artifacts live, how validation findings and waivers gate finalization, and
what the exported guide does (and does not) share.

## Workflow and compatibility

New runs default to the guide v1 contract: the draft and repair stages produce
canonical guide JSON instead of Markdown, and the finalized run exports a
self-contained interactive HTML course rendered by the maintained runtime.
Models author course *content* only — the guide shell, runtime behavior,
design system, and validation rules live in this package's source.

```text
create → spec → outline → draft → (draft validation) → qa → repair
       → (final validation) → finalize → export
```

- `education-pipeline create <topic>` starts a guide run; pass
  `--legacy-markdown` to start a legacy Markdown run instead.
- **Legacy runs are untouched.** A manifest without a `content_contract` field
  is read as legacy Markdown; opening the upgraded tools never mutates or
  strands an existing run. The contract is pinned in `manifest.json` when the
  run is created and cannot silently change afterward. Mixed workspaces (legacy
  and guide runs side by side) list and resume correctly in the CLI, API, and
  cockpit.

## Content contract and artifact layout

Each run directory records its contract in `manifest.json` under
`content_contract` (kind `interactive_guide`, content type
`application/vnd.education-pipeline.guide+json;version=1.0`). Stage artifacts
keep the standard layout, with format-aware suffixes:

```text
runs/<topic>/
  manifest.json                      # includes the pinned content_contract
  prompts/<stage>.prompt.md          # written by advance; run in your model
  responses/<stage>.response.json    # draft/repair guide JSON (…​.md for other stages)
  approved/<stage>.json|.md          # copied on approval
  reports/draft-validation.json      # deterministic validation report
  reports/final-validation.json
  reports/validation-waivers.json    # accepted findings (exact-hash waivers)
  final/guide.json                   # finalized canonical guide JSON
  final/guide.md                     # projected Markdown view of the guide
  final/guide.html                   # exported self-contained interactive HTML
```

Draft and repair prompts embed a machine-readable guide contract, so the model
returns guide JSON that the deterministic pipeline can parse, normalize, and
validate. Everything is a plain file; a run can be resumed from the workspace
alone.

## Validation findings and waivers

Validation is deterministic (no model call). `advance` runs it as a machine
step after the draft is approved (draft phase) and after repair (final phase);
reports are stored under `reports/` and are hash-bound to the exact content
they validated — editing an upstream artifact makes the report *stale*, and
stale reports never gate anything in your favor.

- **Findings** carry a severity and a stable identity. Blocking findings
  prevent finalization; the cockpit shows current, stale, and waived findings
  separately, with navigation back to the exact source stage (JSON Pointer and
  related guide IDs).
- **Waivers** accept a specific finding on the exact content hash it was
  reported against, and require a written reason. A waiver goes stale with its
  content: re-editing invalidates it. Non-waivable findings cannot be waived.
- **Finalization** requires a *current* final validation report whose blocking
  findings are all resolved or waived. **Export** re-checks the same gate.

If validation fails after an edit, the recovery loop is: edit the stage
response → re-approve → revalidate → finalize. The cockpit coordinates these
steps and explains which downstream artifacts each edit invalidated.

## Preview isolation

The cockpit previews guides in a sandboxed iframe served by the loopback-only
daemon, using the same maintained runtime as the final export. Model-authored
content is data, never code: guides carry no HTML or scripts of their own, and
the preview cannot reach the cockpit origin, your workspace, or the network.

## The exported guide

`education-pipeline export <topic> --format html` writes one self-contained
HTML file containing the guide content plus the packaged runtime (CSS and
JavaScript inlined). It works offline from a `file:` URL — no daemon, no Node,
no network requests. The canonical guide JSON can be exported alongside it.

### Local progress storage and reset

Learner progress (completed sections, interaction state, reflection notes,
theme choice) is stored only in the reader's own browser `localStorage`, keyed
by course ID, content hash, and schema version — so a revised export starts
fresh rather than replaying stale progress. The built-in reset control clears
progress for that guide after confirmation. Nothing is transmitted anywhere.

### Privacy boundary

The export contains only finalized course content. Learner profiles, run
manifests, prompts, validation reports, and reflection notes are never
embedded in the exported file, and notes typed by a reader never appear in
print output or leave their browser. Keep real learner profiles and generated
runs in local workspaces; they do not belong in this repository (see
`extraction-manifest.md`).
