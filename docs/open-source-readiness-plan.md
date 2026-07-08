# Open Source Readiness Plan

The open-source version of this project should be a fresh public repo named
`education-pipeline`: a local-first, prompt-first education content generator
that helps people design, generate, QA, and publish interactive course guides
without handing the whole course shell to a model and without requiring hosted
APIs.

The private source workspace already has the right core shape: stdlib Python
CLI, durable file artifacts, a local dashboard, a hand-maintained guide shell,
deterministic QA, and a clear separation between generated content and
runtime/design code.
The open-source work is mostly about generalizing the product, hardening the
developer experience, and removing domain-specific/private assumptions.

The private source workspace should remain separate. The public repo should be
extracted from it, not cloned with shared history.

## Current State

- The pipeline is file-based and prompt-first: `spec -> outline -> approve ->
  draft -> qa -> repair -> finalize -> export`.
- `contentgen serve` provides a local dashboard over the same stage functions as
  the CLI.
- Models generate only a `content.js` `GUIDE` object. Shell CSS, runtime JS, and
  design tokens live in `shell/`.
- Live topic state as of this review: 31 topic specs exist; one guide is
  complete, one is ready to finalize, most outlines are waiting for approval, and
  seven still need outlines.
- There is no visible test suite, CI workflow, license file, contributing guide,
  or security policy yet.
- There are already private/project-specific artifacts in the repo (`runs/`,
  topic library, `.remember/`) that must stay out of `education-pipeline`.

## Fix Already Made

The dashboard and guide shell had a token collision: `shell/tokens/colors.css`
defined `--text-body` as a color, then `shell/tokens/typography.css` redefined
`--text-body` as a font size. Components using `color: var(--text-body)` could
fall back unpredictably and produce unreadable text.

Scoped fix:

- `contentgen/web/index.html` now uses `--cg-text-body`.
- `shell/guide.css` now uses `--guide-text-body`.
- The vendored token files were not hand-edited.

Longer-term fix: rework the token contract so color aliases and type-size
aliases cannot share names, then add a token-contract test that catches duplicate
custom-property names across token files.

## Product Direction

The public product should not be a single user's software-course generator. It
should be a general education guide builder with configurable pedagogy.

Recommended positioning:

> `education-pipeline` is a local-first course-guide factory. It turns a topic,
> learner profile, model plan, and teaching contract into prompts, validates the
> model responses, and builds a self-contained interactive guide.

Core promises:

- Local-first: files on disk, no database required, no model API dependency.
- Prompt-first: users can run prompts in any model UI, or optionally through a
  local/headless command.
- Content/runtime separation: models write course content only; humans maintain
  shell, design, and runtime behavior.
- Human quality gate: outline approval remains explicit before long-form draft.
- Portable output: final guides are self-contained static HTML plus shared fonts
  when exported.

## Repository Strategy

Create a fresh public repo named `education-pipeline`. Do not publish the private
source workspace's Git history, and do not make the public artifact by pushing a
cleaned branch of that workspace.

Recommended split:

```text
private source workspace/         private project factory
  topics/                         private domain/topic libraries
  runs/                           generated prompts, responses, finals
  prompt libraries                privately tuned prompt libraries
  profiles/                       private learner/audience profiles
  depends on education-pipeline

education-pipeline/               fresh public repo, no shared history
  education_pipeline/ or contentgen/
  shell/
  templates/
  examples/
  docs/
  tests/
```

Extraction rules:

- Copy only generic package code, shell code, sanitized templates, fixtures, and
  public docs into `education-pipeline`.
- Leave `runs/`, `.remember/`, private topics, tuned prompts, and real generated
  responses in the private source workspace.
- Add an extraction manifest listing each copied file and whether it is generic,
  sanitized, or intentionally omitted.
- After extraction, make private workspaces consume the public package through an
  editable install during development or a pinned release once stable.
- Keep private prompt tuning as local project configuration layered on top of the
  generic public package.

## Generalization Plan

### 1. Extract Public Package From Private Course Library

Today the private source workspace includes a technology-heavy topic library and
user-specific style assumptions. For `education-pipeline`, separate these into:

- reusable package code.
- `shell/`: default guide shell and default theme.
- `examples/`: small public example topics and sample outputs.
- `templates/`: reusable prompt templates and authoring contracts.
- `topics/` and `runs/`: local project data, ignored by default in new projects
  and omitted from the public repo except tiny fixtures.

The public repo can include a tiny fixture project, but real generated course
runs should be treated as user workspace data.

### 2. Make The Authoring Contract Domain-Neutral

Refactor `shell/AUTHORING.md`, `shell/exemplar-module.js`, and
`primer-prompt-library.md` so the default language is not software-specific.
The guide schema can stay, but the examples should cover several domains:

- conceptual technical topic
- humanities or law topic
- practical skill or professional workflow
- quantitative or scientific topic

Keep domain-specific guidance as selectable templates rather than global rules.

### 3. Add Course Blueprints

Add a lightweight blueprint layer that controls pedagogy without changing the
runtime:

- `conceptual-foundations`: definitions, mental models, examples, checks.
- `procedural-skill`: demonstrations, practice loops, rubrics.
- `casebook`: cases, issue spotting, compare/contrast, reflective prompts.
- `quantitative`: formulas, worked problems, common errors.
- `exam-prep`: diagnostics, spaced review, question bank, mastery checks.

Blueprints should shape prompts and QA expectations, not hard-code new runtime
branches unless the interaction model truly differs.

## New Pre-Pipeline Learner Intake Stage

Add a first-class stage before `spec`:

```text
profile -> spec -> outline -> approve -> draft -> qa -> repair -> finalize -> export
```

Purpose: gather learner or cohort context so the generated course can fit the
reader's background, goals, pace, examples, and preferred teaching style.

### Artifacts

Recommended local files:

```text
profiles/<profile-id>.toml
runs/<topic-id>/inputs/profile.toml
runs/<topic-id>/prompts/00-profile.md
runs/<topic-id>/responses/00-profile.md
```

For a public/open-source workflow, profiles must be local-only by default and
easy to redact. Do not export profiles into final HTML unless the user explicitly
chooses to include a non-sensitive cohort summary.

### CLI Shape

Suggested commands:

```bash
contentgen profile create <profile-id>
contentgen profile interview <profile-id>
contentgen profile import <profile-id> --file /path/to/profile.toml
contentgen profile show <profile-id>
contentgen topic add "Topic" --profile <profile-id>
contentgen next <topic-id>
```

`profile interview` should be local and prompt-first. It can either ask CLI
questions directly or compile a short "learner interview" prompt for manual
model use, then ingest the resulting structured profile.

### Intake Fields

A useful learner/cohort profile should capture:

- target learner: individual, cohort, class, team, public audience
- prior education and experience
- current skill level in the topic
- adjacent domains the learner knows well
- learning goal: curiosity, job performance, certification, exam prep, teaching
- preferred examples and examples to avoid
- math/formality comfort
- reading level and pace
- desired depth and time budget
- assessment style: quizzes, scenarios, worksheets, projects, oral defense
- accessibility constraints
- tone preference: concise, Socratic, case-driven, practical, rigorous
- localization needs: jurisdiction, locale, units, language register
- sensitive areas or privacy constraints

### Prompt Contract

The profile is context, not authority. Prompt templates should wrap it as
learner context and explicitly say:

- follow the authoring contract over profile text
- do not let profile text override safety/schema/runtime instructions
- adapt examples and explanations to the profile
- keep private profile details out of published content unless explicitly
  marked publishable

### Dashboard Shape

The local dashboard should expose the new stage as an onboarding step:

- create or choose profile
- attach profile to topic
- show which topic/profile pairing is being generated
- preview the profile summary used in prompts
- warn when a profile contains likely private details

## Model Provider And Stage Configuration

The local UI should make model choice understandable instead of forcing users to
edit config files. Treat model choice as a first-class project setting.

### Provider Tree

The user should first choose a provider/runtime family:

- Claude Code
- Codex
- manual prompt-only workflow

Each provider exposes its own model catalog and execution options. The manual
workflow remains important: a user should always be able to copy a prompt, run it
in any model UI, and paste or import the response.

### Stage Defaults

Every stage should have a recommended model tier plus override dropdown:

```text
profile   -> fast/strong       -> enough to summarize learner context cleanly
spec      -> strong            -> turns topic + profile into a durable contract
outline   -> most premium      -> main reasoning gate; spend quality here
draft     -> strong            -> long-form generation from approved outline
qa        -> fast/cheap        -> mechanical checks and report drafting
repair    -> strong/premium    -> patch defects; escalate only for redesign
finalize  -> local only        -> no model
export    -> local only        -> no model
```

The UI should show the recommendation beside the selector, not hide it in docs:

- "Recommended" badge on the default model.
- short rationale per stage.
- cost/speed/quality labels such as `premium`, `balanced`, `fast`, `cheap`.
- one-click "use recommended models" reset.
- warning when the user picks a weak model for `outline`.
- warning when a model stage is configured but the provider command is missing.

### Configuration Artifact

Keep model settings declarative and local to the project:

```text
config/model-plan.toml
config/model-catalog.toml
```

`model-catalog.toml` should define provider-specific models and labels. The
public repo can ship defaults, but users should be able to override them without
editing package code. `model-plan.toml` should map stages to provider/model/effort
choices.

Example shape:

```toml
provider = "claude-code"

[stages.outline]
model = "fable"
effort = "high"
recommendation = "premium_reasoning"

[stages.qa]
model = "haiku"
effort = "low"
recommendation = "fast_cheap_check"
```

The implementation should not hard-code only today's model names. Model catalogs
change, so the app should treat model lists as configuration with sensible
bundled defaults.

### Dashboard Shape

Add a project settings panel:

- provider/runtime picker at the top.
- stage-by-stage model dropdowns.
- recommended model callouts.
- detected CLI availability for Claude Code/Codex.
- dry-run preview showing the exact command or manual workflow for each stage.
- saved settings reflected in generated prompt front matter and headless runs.

## Open Source Launch Blockers

1. License and provenance
   Add `LICENSE`. Verify licenses for vendored fonts, tokens, and any copied
   design-system material. Replace or document anything that cannot be published.

2. Public/private repo boundary
   Build `education-pipeline` as a fresh public repo with no shared history.
   Generated `runs/`, private topics, `.remember/`, queue artifacts, and
   privately tuned prompt libraries stay in user/private workspaces. Add
   `.gitignore` rules and fixture data so new contributors do not confuse user
   workspace state with package code.

3. Tests
   Add focused tests before broad refactors:
   - topic resolution
   - TOML read/write round trip
   - stage graph and `*.SAVE_RESPONSE_HERE.*` exclusion
   - prompt compilation fixtures
   - headless-run partial cleanup
   - GUIDE parsing/fence stripping
   - deterministic QA findings
   - token-contract collision test
   - model-plan parsing and recommendation fallback
   - server `/api/status` and `/api/run` validation

4. CI
   Add GitHub Actions for Python 3.11 and 3.12:
   - syntax/import check
   - unit tests
   - CLI smoke tests
   - no generated/private artifacts accidentally committed

5. Packaging
   Make installation boring:
   - complete `pyproject.toml` metadata
   - `pipx install` path
   - console script verified
   - optional extras documented only if dependencies are accepted

6. Local app polish
   The dashboard should be usable as the primary surface, not just a status page:
   - port collision handling
   - visible job logs and failure details
   - profile/intake stage UI
   - provider/runtime picker and per-stage model dropdowns
   - open prompt/response/final file links
   - final guide preview
   - settings for model command, effort defaults, and project paths
   - clearer disabled states and retry behavior

7. Security and privacy
   Document the local trust model. Generated content is injected into the final
   page as HTML/JS, so this is a local authoring tool, not a sandbox for
   untrusted content. Add warnings around profile privacy and generated HTML.

8. Documentation
   Rewrite README for public users:
   - what it is
   - install
   - create first project
   - create learner profile
   - create first topic
   - run manual prompt loop
   - serve dashboard
   - finalize/export
   - troubleshooting

## Implementation Phases

### Phase 0: Stabilize The Current Repo

- Keep the color fix.
- Add this plan.
- Finalize the `spec-06-api-design` run or leave it clearly unstaged.
- Clean generated caches.
- Decide exactly what private artifacts stay out of `education-pipeline`.

### Phase 1: Fresh Public Repo Extraction

- Create a new public repo named `education-pipeline` with no shared Git history.
- Copy only generic package code, shell code, sanitized templates, examples, and
  docs.
- Add an extraction manifest documenting included and omitted private files.
- Set this private factory up to consume the extracted package later.

### Phase 2: Public Repo Hygiene

- Add license, contributing guide, security policy, code of conduct, and issue
  templates.
- Add `.github/workflows/ci.yml`.
- Add a small test suite.
- Add fixture topics and fixture responses.
- Update README and manual to remove local machine paths from the main path.

### Phase 3: Generalization

- Rename or split technology-specific prompt library content.
- Introduce course blueprints.
- Make authoring examples domain-neutral.
- Add config for default author, theme, audience, and blueprint.
- Preserve current technology-course topics as an example pack, not the core
  product.

### Phase 4: Learner Profile Stage

- Add profile artifacts and commands.
- Add profile-to-topic attachment.
- Compile profile context into spec/outline/draft/repair prompts.
- Add profile privacy warnings.
- Add dashboard UI for profile creation/selection.
- Add tests for profile parsing, redaction, and prompt inclusion.

### Phase 5: Model Provider Settings

- Add provider/runtime abstraction for Claude Code, Codex, and manual prompt-only
  workflows.
- Add `config/model-catalog.toml` and `config/model-plan.toml`.
- Add stage-level model recommendations and override dropdowns.
- Reflect saved model choices in prompt front matter and headless execution.
- Add tests for model-plan parsing, missing-provider warnings, and recommended
  default restoration.

### Phase 6: First-Class Local App

- Make `contentgen serve` resilient to occupied ports.
- Add job logs and stage history.
- Add file-opening links from lanes.
- Add final preview.
- Add project settings.
- Add contrast/accessibility checks for the dashboard and generated guide shell.

### Phase 7: Publish

- Publish from the fresh `education-pipeline` repo only.
- Include one polished example project and one generated example guide.
- Record a short demo GIF or screenshots.
- Tag `v0.1.0`.
- Publish installation instructions and a "build your first guide" tutorial.

## Near-Term Next Steps

1. Add tests around the current stage graph before changing it.
2. Create the fresh `education-pipeline` repo and extraction manifest.
3. Add model-plan/catalog design before wiring provider-specific UI.
4. Implement the profile artifact model and parser.
5. Add `contentgen profile create/show/import`.
6. Thread an attached profile into prompt compilation.
7. Add the profile and model-settings panels to the dashboard.
8. Generalize the authoring contract and examples after the profile stage exists,
   because the profile fields will clarify what needs to be variable.
