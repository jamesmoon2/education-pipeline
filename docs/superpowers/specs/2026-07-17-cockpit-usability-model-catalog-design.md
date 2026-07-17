# Cockpit Usability + Real Model Catalog — Design

Date: 2026-07-17
Status: Draft for review

## Problem

The cockpit works but is not friendly to a first-time user:

1. The shipped model catalog is a placeholder. Claude Code exposes fake aliases
   ("Balanced", "Premium reasoning"), Codex lists stale `gpt-5.4` models, and the
   default plan provider is `manual` — so "Use recommended" lands users on
   "Manual prompt workflow", a concept never explained in the UI.
2. Forms use bare labels ("Target learner", "Brief", "Topic id") with no
   explanation of what the user is expected to supply.
3. Only `<textarea>` fields can be enlarged; single-line text inputs
   (math comfort, reading level, pace, …) cannot.
4. Body and secondary text sizes (16px root, 12–13px small text) read small.

## Goals

- Ship a real model catalog and real per-stage recommendations.
- Let users pick between three recommended presets: Max quality, Balanced,
  Cost efficient — each defined for both Claude Code and Codex.
- Explain every form field with an accessible tooltip; make every free-text
  field enlargeable; raise the type scale by ~2px.
- Sweep the remaining pages for jargon and unexplained controls.

## Non-goals

- No provider-adapter changes (`providers/claude_code.py`, `codex.py` argv
  construction is untouched; `effort` remains recorded metadata).
- No new write API. Presets fill the existing overrides map client-side and are
  persisted through the existing `PUT /v1/config/plan`.
- No visual redesign beyond the type-scale bump — the design system stands.

## 1. Model catalog (`config/model-catalog.example.toml`)

Replace the placeholder catalog. Model ids are catalog-local; `argv_model`
carries the real CLI id.

**Claude Code** (`claude-code`):

| id | label | argv_model | quality | default_effort |
|---|---|---|---|---|
| `fable-5` | Fable 5 | `claude-fable-5` | premium | high |
| `opus-4-8` | Opus 4.8 | `claude-opus-4-8` | premium | high |
| `sonnet-5` | Sonnet 5 | `claude-sonnet-5` | strong | medium |
| `haiku-4-5` | Haiku 4.5 | `claude-haiku-4-5` | fast | low |

**Codex** (`codex`):

| id | label | argv_model | quality | default_effort |
|---|---|---|---|---|
| `sol` | GPT-5.6 Sol | `gpt-5.6-sol` | premium | high |
| `terra` | GPT-5.6 Terra | `gpt-5.6-terra` | strong | medium |
| `luna` | GPT-5.6 Luna | `gpt-5.6-luna` | fast | low |

Quality values stay within the catalog's ranked vocabulary
(`fast` < `strong` < `premium`) so `weak_stage_warning` keeps working;
novel tier names would silently rank as "strong" and defeat the warning.

**Manual** stays, relabeled: label "Manual copy/paste", description
"No CLI required — copy each stage prompt into any model UI, then paste the
response back." Its single model keeps id `prompt-only` with a matching
plain-language description. Manual is never a default and has no presets.

Every model's `description` says when to use it in plain language (e.g.
Fable 5: "Deepest reasoning for course design; slower and most expensive.").

## 2. Recommended presets

### Data model

Presets are data in the catalog TOML, parsed by `config.py`, served read-only.

```toml
[[presets]]
id = "balanced"
label = "Balanced"
description = "Deep design where it counts, fast models for mechanical steps."

[presets.stages.claude-code]
profile = { model = "sonnet-5" }
spec    = { model = "fable-5",  effort = "high" }
# … one entry per model-driven stage

[presets.stages.codex]
profile = { model = "terra" }
spec    = { model = "sol", effort = "high" }
# …
```

Validation (ConfigError on violation): preset ids unique; every referenced
provider and model exists in the catalog; every model-driven stage
(`profile`, `spec`, `outline`, `draft`, `qa`, `repair`, `audit`) present in
each provider mapping; `effort` optional, one of low/medium/high.

### The three presets

Claude Code mappings (Codex corollary in parentheses: Fable/Opus → Sol,
Sonnet → Terra, Haiku → Luna):

| Stage | Max quality | Balanced | Cost efficient |
|---|---|---|---|
| profile | Opus 4.8 (Sol) | Sonnet 5 (Terra) | Haiku 4.5 (Luna) |
| spec | Fable 5 (Sol) | Fable 5 (Sol) | Sonnet 5 (Terra) |
| outline | Fable 5 (Sol) | Opus 4.8 (Sol) | Sonnet 5 (Terra) |
| draft | Opus 4.8 (Sol) | Opus 4.8 (Sol) | Sonnet 5 (Terra) |
| qa | Opus 4.8 (Sol) | Haiku 4.5 (Luna) | Haiku 4.5 (Luna) |
| repair | Opus 4.8 (Sol) | Opus 4.8 (Sol) | Sonnet 5 (Terra) |
| audit | Opus 4.8 (Sol) | Opus 4.8 (Sol) | Sonnet 5 (Terra) |

Efforts: `high` for spec/outline/draft/repair/audit in Max quality and for
spec/outline in Balanced; `medium` elsewhere; `low` for qa/profile in
Cost efficient.

Two honesty notes, reflected in all UI copy:

- **`profile` is plan-topology-only today.** The daemon only enqueues
  `SUPPORTED_STAGES` (spec…audit); nothing executes the plan's `profile`
  entry. Presets still fill it so applying a preset leaves no stale row in
  the settings UI (the row already renders today), and its tooltip says the
  row is reserved and does not affect runs yet.
- **`effort` is recorded metadata.** Provider adapters do not pass effort to
  the CLIs (a stated non-goal); its tooltip must not promise behavior,
  speed, or cost changes.

### API

`GET /v1/config/catalog` payload gains a `presets` array:

```json
{"providers": [...], "presets": [{"id": "balanced", "label": "Balanced",
  "description": "...", "stages": {"claude-code": {"profile": {"model":
  "sonnet-5", "effort": null}, ...}, "codex": {...}}}]}
```

### Default plan (`config/model-plan.example.toml`)

`provider = "claude-code"` with per-stage `[stages.X]` entries equal to the
Balanced preset (model + effort). The existing `recommendation` strings are
kept. A fresh workspace therefore starts on Claude Code / Balanced, never
manual.

## 3. Settings page UX

- Replace "Use recommended (all stages)" with a **preset picker**: three
  buttons (Max quality / Balanced / Cost efficient), each showing its
  description, plus a compact provider toggle (Claude Code / Codex,
  defaulting to the plan's current top-level provider when it has presets,
  else Claude Code). Clicking a preset fills every stage row from that
  preset's mapping for the chosen provider; rows remain hand-editable;
  nothing persists until Save (existing stale-plan/409 flow unchanged).
- Per-row "Use recommended" becomes "Reset to default" and applies the
  **Balanced** preset value for that stage under the row's current provider
  (falling back to provider-default/no-model when the provider has no
  presets, e.g. manual).
- Add stage tooltips: each row's stage name gets an InfoTip explaining the
  stage ("spec — turns your topic brief into the course contract the later
  stages build against", etc.). Add tooltips for Provider and Effort.
- Provider availability section: unchanged behavior, but wording explains
  what availability means ("the CLI was found on this machine").

## 4. InfoTip component

`web/src/components/InfoTip.tsx`: a ⓘ button rendering an accessible tooltip.

- `<button type="button" aria-label="About {field}">` with
  `aria-describedby` pointing at the tooltip text node.
- Shows on hover and on focus; dismisses on Escape/blur; text wraps at
  ~36ch; positioned via CSS (no portal library — stdlib-style, zero deps).
- Copy lives beside the component that uses it (a `fieldHelp.ts` map per
  form), so text stays reviewable in one place per page.
- axe (existing Playwright + @axe-core suite) must pass on pages using it.

## 5. Learner profile form

- Every field gets an InfoTip with concrete guidance and an example, e.g.
  - Target learner: "Who this course is for, in a sentence. Example: 'My
    12-year-old who loves Minecraft' or 'Junior analysts new to SQL'."
  - Math comfort: "How much math the learner is happy to see, in your own
    words — e.g. 'avoid equations', 'algebra is fine', 'loves proofs'."
  - (Full copy table written during implementation; every field in
    `ProfileForm` is covered — identity, background, learning plan,
    preferences, localization, privacy, metadata.)
- Free-text single-line inputs become auto-growing textareas (`rows={1}`,
  `resize: vertical`, min-height matching current inputs) so every text
  field can be enlarged. Numbers, checkboxes, selects, and the metadata
  type/key controls are unchanged. Values remain single strings — newlines
  entered in previously-single-line fields are normalized to spaces on
  change, so the stored TOML shape is untouched.

## 6. New-course wizard

- Topic id: InfoTip ("Short folder-safe identifier for this course, e.g.
  `intro-to-sql`. Lowercase letters, digits, and hyphens.") plus a
  `placeholder="intro-to-sql"`; validate the format client-side with the
  daemon's rules and show the error inline before Continue.
- Brief: InfoTip ("2–4 sentences on what the course should cover and why
  the learner wants it. The models design the whole course from this, so
  the more specific the better.") plus placeholder example.
- Audience, Goals, Time budget, learner-profile step, blueprint step, and
  the plan step each get one-line explanations/tooltips in the same voice.

## 7. Type scale

- Root `font-size` 16px → 18px (`--ep-*` rem-based sizes scale with it).
- Floor small text: tokens currently at 0.75rem (12px) move to 0.8125rem
  and 0.8125rem moves to 0.875rem, so nothing renders below ~14.6px at the
  new root. Line-heights and spacing tokens unchanged (rem-based, scale
  automatically). Playwright visual smoke: no horizontal overflow on the
  five main pages at 1280×800.

## 8. UI audit sweep

One pass over TopicListPage, RunBoardPage, StageViewerPage, ProfilesPage,
JobsPanel, ExportControls, PersonalizationPanel, ValidationFindingsPanel:

- Any label a first-time user can't parse gets an InfoTip or inline help
  in the same voice (reuse `lib/labels.ts` learner-language conventions).
- Buttons that act on jargon ("advance", "waive", "canonicalize") get
  sentence-style explanations near them.
- Findings recorded in the implementation plan as a checklist; no layout
  changes beyond adding help affordances.

## Error handling

- Catalog/preset validation errors surface exactly like today's catalog
  errors (daemon fails the config load with a ConfigError message naming
  the offending preset/stage).
- Settings: applying a preset for a provider whose CLI is unavailable is
  allowed (plan is data); existing per-stage availability warnings and the
  weak-model warning still render after Save.
- Existing workspaces with a customized catalog/plan are untouched — the new
  files are package defaults used only when the workspace lacks its own.

## Testing

- **pytest**: preset TOML parsing (valid + each validation failure), catalog
  payload includes presets, new example files parse and cross-validate
  (every preset model exists; default plan equals Balanced/claude-code),
  existing plan PUT flows unchanged.
- **vitest**: InfoTip (hover/focus/escape, aria wiring); SettingsPage preset
  application (fills overrides, Save posts them, provider toggle switches
  mapping); PlanStageRow reset-to-default; ProfileForm textarea conversion +
  newline normalization; NewRunPage topic-id validation + tooltips render.
- **Playwright + axe**: presets end-to-end against a live daemon; axe passes
  on settings, profile editor, and new-course pages with tooltips open;
  overflow smoke at the new type scale.

## Out of scope

- Per-run plan overrides UI (already exists, unchanged).
- Passing `effort` through to provider CLIs.
- Codex/Claude pricing display.
