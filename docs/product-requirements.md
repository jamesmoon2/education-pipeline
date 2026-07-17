# Education Pipeline Product Requirements

**Status:** Authoritative product direction
**Last updated:** 2026-07-12
**Target:** Local-first public application, initial release `v0.1`
**Supersedes:** `docs/archive/roadmap.md`,
`docs/archive/open-source-readiness-plan.md`, and
`docs/archive/frontendplan.md`

## 1. Product summary

Education Pipeline is a local application for creating personalized,
high-quality, interactive courses about nearly any subject.

A learner describes what they want to learn, why they want to learn it, what
they already know, and the kinds of examples and teaching approaches that work
for them. Education Pipeline turns that context into a staged course-production
run. Large language models create and revise the educational content, while the
application supplies the workflow, recommended model plan, human approval
points, deterministic checks, maintained interactive-guide runtime, and durable
local project state.

The intended promise is:

> Tell Education Pipeline what you want to learn and how you learn best. Using
> the Claude, ChatGPT/Codex, or manual model workflow available to you, it helps
> produce a rigorous interactive course tailored to your goals and interests—on
> your own machine, under your control.

This is both:

1. a **course factory** that plans, generates, checks, repairs, and packages a
   personalized course; and
2. a **pipeline cockpit** for configuring, observing, editing, approving,
   resuming, and managing that production process.

## 2. Product thesis

Generic model prompts can produce plausible educational prose, but they rarely
produce a coherent course with an explicit learning contract, consistent
pedagogy, meaningful practice, deterministic quality checks, and a reliable
interactive shell. Asking one model to produce an entire course in one pass also
makes failures hard to inspect or repair.

Education Pipeline improves the outcome by separating responsibilities:

- The learner supplies goals, context, interests, constraints, and approvals.
- Models perform bounded creative and reasoning tasks at explicit stages.
- The pipeline preserves artifacts and enforces the stage contract.
- Deterministic validators catch structural and mechanical failures.
- Model-based QA evaluates qualities that cannot be checked mechanically.
- A maintained application-owned runtime turns structured course content into a
  polished interactive guide.

The combination—not any single prompt or model—is the product.

## 3. Target users and jobs

### Primary users

- Curious adults who want a serious self-guided course on a personal or
  professional interest.
- Professionals learning a new domain, skill, tool, regulation, or body of
  knowledge.
- Students supplementing formal instruction with a course adapted to their
  background and goals.
- Educators, tutors, and subject-matter experts creating a first draft of a
  tailored learning experience.
- Technically comfortable model subscribers who prefer local files and visible
  control over opaque hosted generation.

### Core jobs to be done

- “Help me turn a broad interest into a course with a realistic learning goal.”
- “Teach this in terms that connect to what I already know and care about.”
- “Let me choose where to spend premium-model reasoning and where a faster model
  is enough.”
- “Show me what the models produced at every step and let me intervene.”
- “Catch broken structure, missing outcomes, weak practice, and unsupported
  claims before I call the course complete.”
- “Give me a polished course I can open locally and use without running the
  generation system.”
- “Let me stop today and resume later without losing work or hidden state.”

## 4. Product principles

1. **Local first.** Project data, learner profiles, prompts, responses, logs,
   and outputs live on the user’s machine.
2. **No hosted service required.** The application does not require Education
   Pipeline accounts, cloud storage, or project-owned inference infrastructure.
3. **Bring the model access you already have.** Supported local provider tools
   may use the user’s existing authenticated subscription; a manual copy/paste
   workflow must always remain available.
4. **Personalization is a contract, not decoration.** Learner context must
   influence objectives, explanations, examples, practice, pace, and assessment
   without leaking private profile details into published material.
5. **Quality through stages.** Important decisions are decomposed into
   inspectable artifacts with approval and validation gates.
6. **Deterministic where possible.** Models should not perform tasks that the
   application can check or render reliably in code.
7. **Content/runtime separation.** Models create structured educational content;
   the application owns the guide schema, components, styling, navigation,
   persistence, and accessibility behavior.
8. **Provider flexibility.** Each model stage can use a recommended default or a
   user-selected provider/model/effort combination.
9. **Durable and recoverable.** Files on disk are the source of truth, and every
   run can be inspected, resumed, copied, or archived.
10. **Power with a calm default path.** A new user should succeed with sensible
    defaults; advanced controls remain available without dominating onboarding.

## 5. Goals and non-goals

### Goals

- Produce genuinely interactive, self-contained course guides rather than only
  prose documents.
- Tailor every course to an explicit learner profile and course brief.
- Support the complete course-production loop in the local web application.
- Make provider and per-stage model choices understandable and configurable.
- Combine human review, model QA, and deterministic validation.
- Preserve complete local provenance without exposing private learner context in
  an exported guide by default.
- Make the default workflow approachable to someone who has model access but is
  not a software developer.
- Ship as an installable, documented open-source project with a representative
  example course.

### Non-goals for `v0.1`

- Hosted generation, storage, synchronization, accounts, or collaboration.
- A marketplace or public directory of courses.
- Multi-user editing, classroom administration, grading, or learning-management
  system integration.
- Mobile-native applications.
- Training or fine-tuning models.
- Supplying inference credits or proxying paid model APIs.
- Executing arbitrary untrusted generated code.
- Automatically publishing learner profiles, private prompt context, or run
  history with a guide.
- Perfect factual verification of arbitrary subjects. The product can require
  citations, check source shape, and surface uncertainty, but it cannot guarantee
  that every model claim is true.

## 6. End-to-end user experience

### 6.1 Install and open

The user installs Education Pipeline, launches it with one obvious command or
desktop shortcut, and the local cockpit opens in their browser. Port selection,
daemon discovery, and authentication are handled by the application.

The first-run experience explains three facts plainly:

- everything is stored locally;
- model work uses a supported local provider or a manual copy/paste loop; and
- course quality improves when the learner gives useful context and reviews the
  major gates.

### 6.2 Create a project and learner profile

The user creates or opens a workspace, then creates a learner profile through a
guided form. The profile captures goals, prior knowledge, interests, preferred
examples, desired rigor, available time, assessment preferences, accessibility
needs, locale, and privacy constraints.

The application shows:

- the private profile used during generation;
- the redacted/publishable summary, if any; and
- a warning before private details could enter an exported artifact.

Profiles are reusable and snapshotted into a run so later profile changes do not
silently change an existing course.

### 6.3 Define the course

The user supplies a topic and a short course brief: desired outcome, scope,
depth, time budget, constraints, and optional starting materials. The
application recommends a pedagogical blueprint such as conceptual foundations,
procedural skill, casebook, quantitative practice, or exam preparation. The user
can accept or change it.

Before generation begins, the application previews the learner/topic pairing,
estimated stages, and selected model plan.

### 6.4 Configure the model plan

The default path is “Use recommended models.” Advanced settings allow the user
to select provider, model alias, and effort for each model-powered stage.

The application must:

- detect supported local provider tools and explain unavailable choices;
- include manual prompt-only operation for every stage;
- show quality/speed/cost guidance without claiming exact prices;
- warn when a weak configuration is chosen for a reasoning-heavy stage;
- show the exact local command before execution when useful;
- keep model catalogs configurable because model names and capabilities change;
  and
- record the effective provider/model/effort with the run artifact.

The default plan should spend the strongest reasoning on the course contract,
outline, and difficult repairs; use a strong long-context model for drafting;
and allow a faster model for mechanical QA where appropriate.

### 6.5 Build the course through visible stages

The core production graph is:

```text
learner profile + course brief
            ↓
          spec
            ↓
         outline ── human approval
            ↓
          draft
            ↓
  deterministic validation + model QA
            ↓
          repair
            ↓
     final validation + preview
            ↓
          export
```

Each stage exposes its inputs, generated prompt, response, status, validation
results, model provenance, and next action. A user can run through a configured
provider, copy the prompt to another model, paste a response, edit a response,
compare revisions, approve a gate, or retry a failed stage.

The system never silently approves major creative artifacts.

### 6.6 Preview, learn from, and export the course

The final preview runs the same maintained guide runtime as the exported course.
The user can navigate the course, exercise interactions, inspect validation
results, and return to the relevant stage when something is wrong.

Exports are portable and usable without Education Pipeline running. The primary
format is a self-contained interactive HTML guide, with Markdown available as a
content/provenance artifact. Export excludes private profile details, prompts,
and run logs unless the user explicitly selects a separate diagnostic bundle.

## 7. Functional requirements

### 7.1 Workspace and course library

- Create, open, and validate a local workspace.
- List courses by status, learner, topic, last activity, and completion state.
- Resume the exact next action from durable files.
- Duplicate a course or start a new run from an existing brief.
- Archive a course without deleting exported guides.
- Reveal relevant files in the operating system.
- Detect externally changed artifacts and avoid overwriting them silently.

### 7.2 Learner profiles and personalization

- Create, edit, duplicate, select, and attach local profiles.
- Distinguish private fields from publishable fields.
- Snapshot the effective profile into each run.
- Make the prompt contract treat profile text as data, never instructions.
- Require each major artifact to demonstrate how it serves the learner’s goals,
  prior knowledge, interests, pacing, and assessment preferences.
- Include a personalization audit that identifies generic sections and private
  details that should not be published.

### 7.3 Course brief and blueprints

- Capture topic, outcomes, boundaries, prerequisites, time budget, difficulty,
  tone, jurisdiction/locale where relevant, and source expectations.
- Offer pedagogical blueprints with distinct prompt and QA contracts.
- Allow a user to inspect and override the recommended blueprint.
- Treat blueprint selection as configuration, not a forked application runtime.

Initial blueprints:

- conceptual foundations;
- procedural skill;
- casebook or issue-spotting;
- quantitative/scientific;
- exam preparation; and
- project-based learning.

### 7.4 Provider and model settings

- Support Claude Code, Codex, and manual prompt-only workflows at launch.
- Keep provider adapters isolated behind a stable execution contract.
- Maintain project-local model catalog and model plan files.
- Provide global defaults plus per-course and per-stage overrides.
- Test provider availability without sending course content.
- Make the effective command, model, and effort visible in the UI.
- Never require an Education Pipeline API key or hosted account.

### 7.5 Pipeline orchestration

- Preserve the staged spec → outline → draft → QA → repair flow.
- Support cancellation, retry, logs, and failure recovery for provider jobs.
- Prevent incompatible concurrent writes to the same run/stage.
- Preserve prompts and responses as inspectable artifacts.
- Record append-only lifecycle and provenance events.
- Allow manual response ingestion at every model-powered stage.
- Support targeted regeneration of a failed stage without discarding approved
  upstream work.

### 7.6 Human review and editing

- Make the course contract and outline explicit approval gates.
- Provide response editing with stale-content protection.
- Show prompt/response and before/after comparisons.
- Invalidate downstream approval when an upstream artifact changes.
- Explain the consequence of rerunning or editing an approved artifact.
- Keep unsaved browser edits during recoverable conflicts.

### 7.7 Deterministic quality system

Quality checks should produce structured findings with severity, location,
explanation, and remediation guidance. Release-blocking findings prevent final
export unless explicitly waived with a recorded reason.

Required deterministic checks include:

- guide-schema validity and required fields;
- unique and stable identifiers;
- declared learning-outcome coverage;
- required section and interaction presence for the selected blueprint;
- internal links, navigation targets, and asset references;
- broken or unsafe URI schemes;
- citation/source record shape when citations are required;
- empty, placeholder, truncated, or fence-wrapped model output;
- leaked prompt instructions or likely private profile fields;
- content-size and reading-time budget warnings;
- interaction configuration validity;
- HTML sanitization and script-policy enforcement;
- keyboard navigation and baseline accessibility checks;
- runtime smoke validation in a real browser; and
- deterministic export reproducibility for the same approved inputs.

Model QA complements these checks by assessing conceptual accuracy, coherence,
pedagogy, personalization, examples, practice quality, and alignment with the
approved course contract. Model QA never substitutes for schema or runtime
validation.

### 7.8 Interactive guide content model

The final course is represented as structured content conforming to a versioned
guide schema. Models may populate supported structures but may not emit
arbitrary executable JavaScript.

The schema must support:

- course metadata, outcomes, prerequisites, and estimated duration;
- modules, sections, summaries, and glossary entries;
- examples, analogies, callouts, and misconception warnings;
- knowledge checks with explanations and retry behavior;
- flashcards or retrieval prompts;
- scenarios, decision points, and case comparisons;
- worked examples and step-by-step reveals;
- exercises, reflection prompts, and rubrics;
- progress markers and local completion state; and
- source/citation records and confidence notes where appropriate.

The schema is intentionally smaller than arbitrary web content. New interaction
types are added to the maintained runtime only when they are reusable, testable,
accessible, and meaningfully improve learning.

### 7.9 Maintained guide runtime

The application owns the runtime and visual system used by all exported guides.
It must provide:

- responsive navigation and progress;
- accessible components and full keyboard operation;
- readable typography, themes, and print behavior;
- local persistence of progress without a server;
- graceful behavior when local storage is unavailable;
- no network requirement for ordinary guide use;
- no analytics or tracking by default;
- versioned schema/runtime compatibility; and
- safe rendering of generated content without arbitrary code execution.

The editor preview and exported artifact must use the same renderer so that
preview is trustworthy.

### 7.10 Export and provenance

- Export a portable interactive HTML guide as the primary deliverable.
- Export Markdown and machine-readable structured content for inspection and
  future migration.
- Include non-sensitive provenance: application version, schema version,
  blueprint, generation date, and model-stage aliases.
- Exclude private learner data and working artifacts by default.
- Offer a separate opt-in diagnostic bundle for prompts, responses, logs, and
  validation reports.
- Make export warnings and waived findings visible before packaging.

### 7.11 Local application operations

- Bind only to loopback by default.
- Handle occupied ports and stale discovery state automatically.
- Keep browser/API authentication invisible in normal use.
- Provide clear job progress, logs, cancellation, and actionable errors.
- Pause unnecessary polling when the app is not visible.
- Support clean shutdown and recovery after an interrupted provider process.
- Document the local trust boundary and risks of opening untrusted projects.

## 8. Application information architecture

The cockpit should converge on these primary areas:

1. **Home / Course Library** — recent courses, status, next action, create/open.
2. **New Course** — learner, topic, course brief, blueprint, and model-plan
   review.
3. **Course Run** — stage board, primary next action, validation state, and
   completion progress.
4. **Stage Workspace** — inputs, prompt, response/editor, comparisons, logs,
   findings, and approval.
5. **Course Preview** — the real interactive runtime plus validation overlay.
6. **Profiles** — private learner profiles and publishable summaries.
7. **Settings** — workspace paths, providers, model catalog, model plan,
   defaults, theme, and privacy controls.

Progressive disclosure is required. The default screen emphasizes the next safe
action; prompt internals, commands, and advanced model controls remain one level
deeper.

## 9. As-built baseline

The following capabilities exist in the repository and form the starting
baseline for this PRD:

- stdlib Python package and CLI;
- local topic and learner-profile storage with run snapshots;
- durable staged runs through spec, outline, draft, QA, repair, finalize, and
  Markdown/HTML export;
- explicit approval gates and resumable run status;
- configurable model catalog/plan parsing foundations;
- Claude Code and Codex provider adapters;
- local provider-job daemon with logs, cancellation, discovery, and loopback
  security controls;
- React/Vite cockpit for topics, run status, stage content, provider jobs,
  approvals, editing, diffs, preview, finalize, export, and downloads;
- Python, frontend unit, and browser end-to-end test foundations; and
- public-repository hygiene including license, contribution/security documents,
  issue templates, and CI.

This list is a product-level baseline, not a claim that each capability has
reached the usability or release quality required below.

## 10. Prioritized roadmap

### P0 — Define and prove the interactive-course contract

**Status: Delivered 2026-07-11** (closeout evidence in
[`docs/superpowers/plans/2026-07-11-interactive-guide-v1.md`](superpowers/plans/2026-07-11-interactive-guide-v1.md)
§12 and `docs/testing/2026-07-11-interactive-guide-v1-acceptance.md`). Course
brief and blueprint schemas were delivered only to the depth the acceptance
fixture requires; deeper blueprint work remains under "P1 — Blueprint-driven
pedagogy". Remaining manual accessibility items were waived by the owner and
are tracked for the post-milestone audit.

Milestone specifications:

- [`docs/superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md`](superpowers/specs/2026-07-11-interactive-guide-v1-milestone.md)
- [`docs/superpowers/specs/2026-07-11-interactive-guide-v1-schema.md`](superpowers/specs/2026-07-11-interactive-guide-v1-schema.md)
- [`docs/superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md`](superpowers/specs/2026-07-11-interactive-guide-v1-runtime-export.md)
- [`docs/superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md`](superpowers/specs/2026-07-11-interactive-guide-v1-validation-pipeline.md)

- Define guide schema v1 and the allowed interaction vocabulary.
- Define course brief and blueprint schemas.
- Build the maintained runtime and renderer for a small, excellent initial set:
  modules, callouts, knowledge checks, worked reveals, scenarios, and progress.
- Change the draft/repair/finalize contract to produce and validate structured
  guide content.
- Preview and export the same runtime.
- Build one synthetic example course as the acceptance fixture.

**Exit criterion:** a new run produces a personalized, navigable, offline
interactive guide with at least three meaningful interaction types, and no
model-generated executable code.

### P0 — Finish model-plan configuration

**Status: Delivered 2026-07-12** (closeout evidence in
[`docs/superpowers/plans/2026-07-11-model-plan-configuration.md`](superpowers/plans/2026-07-11-model-plan-configuration.md)
Wave Log). Accepted limitations and follow-on debt are recorded in the
post-milestone audit; the two scheduled debt items (API-hygiene 400s and
atomic manifest writes) move to "P0 — Establish deterministic release gates".

Milestone specifications:

- [`docs/superpowers/specs/2026-07-11-model-plan-configuration-design.md`](superpowers/specs/2026-07-11-model-plan-configuration-design.md)
- [`docs/superpowers/specs/2026-07-12-model-plan-configuration-post-milestone-audit.md`](superpowers/specs/2026-07-12-model-plan-configuration-post-milestone-audit.md)

- Expose provider availability and project defaults in Settings.
- Add per-stage provider/model/effort controls with “Use recommended” reset.
- Add warnings and explanations for model choices.
- Persist and display effective configuration and provenance.
- Make manual operation a first-class choice, not a fallback error path.

**Exit criterion:** a user can configure and execute a mixed-provider run from
the cockpit without editing TOML, while an advanced user can still edit the
underlying local configuration.

### P0 — Establish deterministic release gates

**Status: Delivered 2026-07-13** (closeout evidence in
[`docs/superpowers/plans/2026-07-12-deterministic-release-gates.md`](superpowers/plans/2026-07-12-deterministic-release-gates.md)
Wave Log, acceptance tests `tests/test_release_gate_acceptance.py`, and e2e
`web/e2e/release-gates.spec.ts`). Accepted limitations, carried-forward triage,
and three open owner decisions are recorded in the post-milestone audit.

Milestone specifications:

- [`docs/superpowers/specs/2026-07-12-deterministic-release-gates-design.md`](superpowers/specs/2026-07-12-deterministic-release-gates-design.md)
- [`docs/superpowers/specs/2026-07-13-deterministic-release-gates-post-milestone-audit.md`](superpowers/specs/2026-07-13-deterministic-release-gates-post-milestone-audit.md)

- Implement structured validator results and severities.
- Add schema, privacy, outcome coverage, link, interaction, accessibility, and
  browser-runtime checks.
- Show findings at the responsible stage and support rerun after repair.
- Require recorded waivers for remaining release blockers.

**Exit criterion:** export provides a clear, reproducible quality report and
cannot silently package structurally invalid or privacy-leaking content.

### P1 — Make personalization visible and safe

**Status: Delivered 2026-07-16** (closeout evidence in
[`docs/superpowers/plans/2026-07-13-personalization.md`](superpowers/plans/2026-07-13-personalization.md)
Wave Log; engine acceptance in `tests/test_personalization_acceptance.py`;
browser acceptance in `web/e2e/personalization.spec.ts` and
`web/e2e/guide-runtime.spec.ts`). The delivered implementation starts with
Wave 0 commit `dc75c54`; the complete per-wave commit list is recorded in that
Wave Log. Accepted limitations are recorded in the post-milestone audit named
by the closeout plan.

Milestone specification:

- [`docs/superpowers/specs/2026-07-12-personalization-design.md`](superpowers/specs/2026-07-12-personalization-design.md)

- Build profile creation/editing and publishable-summary UI.
- Add privacy classification and warnings.
- Add a personalization audit and outcome-to-learner trace.
- Show “why this course fits you” in preview without exposing private details.

**Exit evidence:** structured profiles are snapshot-attached to runs; guide
source 1.1 produces a private, hash-bound trace and a stripped public
projection; the optional audit remains nonblocking and projects only safe
findings; the cockpit supports stale-state recovery and sandboxed evidence
navigation; repeat exports produce deterministic public sidecars without
private profile values, goals, exclusion reasons, or source annotations.

### P1 — First-run and course-management experience

**Status: Delivered 2026-07-16** (closeout evidence in
[`docs/superpowers/plans/2026-07-16-first-run-course-management.md`](superpowers/plans/2026-07-16-first-run-course-management.md)
Wave Log; launcher/orchestration tests in `tests/test_ui.py` and
`tests/test_registry.py`; reveal security tests in `tests/test_reveal.py`;
browser acceptance in `web/e2e/new-run.spec.ts` and `web/e2e/library.spec.ts`;
the CI `packaging-smoke` job installs the built wheel into a clean venv and
asserts `education-pipeline ui --no-browser` serves the cockpit index).
Accepted limitations are recorded in the post-milestone audit ledger named by
the closeout plan. Profile editing and blueprint recommendation remain in
their own P1 milestones per the spec's out-of-scope list.

Milestone specification:

- [`docs/superpowers/specs/2026-07-12-first-run-course-management-design.md`](superpowers/specs/2026-07-12-first-run-course-management-design.md)

- Add workspace selection and setup validation.
- Add a guided New Course flow.
- Add course library filtering, duplication, archiving, and reveal-in-files.
- Add an `education-pipeline ui` launcher or equivalent one-step entry point.
- Replace developer-oriented errors with user-directed recovery actions.

**Exit evidence:** `education-pipeline ui` resolves a workspace (flag →
user-level registry → first-run creation prompt), validates/scaffolds it, and
serves the wheel-bundled cockpit; the library filters/sorts an enriched
payload and supports archive/unarchive (manifest flag with an
`archived_course` write guard), duplicate-from-brief, and workspace-confined
reveal-in-files with a copyable-path fallback; first-run onboarding is a
dismissable welcome panel plus purposeful empty states; every daemon error
carries a stable catalog code that the cockpit's `ErrorNotice` and the CLI
map to user-directed recovery actions.

### P1 — Blueprint-driven pedagogy

- Ship the initial blueprint set and selection guidance.
- Add blueprint-specific prompt and QA requirements.
- Add section-level regeneration so one weak lesson does not require rebuilding
  the full draft.
- Add time-budget and difficulty calibration checks.

### P2 — Public `v0.1` release

- Rewrite the README around installation and the first successful course.
- Ship one polished synthetic example project and exported guide.
- Verify package installation on supported operating systems.
- Document provider authentication, privacy, local trust, troubleshooting, and
  backup/migration.
- Complete dependency, asset, font, and copied-material provenance review.
- Record a short local demo and tag the release.

## 11. `v0.1` release criteria

The product is ready for `v0.1` when a new user can:

1. install and launch the local app from documented instructions;
2. create a learner profile and course brief without editing source files;
3. accept recommended model settings or select a model plan in the UI;
4. complete a full run with either a supported provider or manual prompt flow;
5. inspect, edit, approve, retry, and resume work without losing artifacts;
6. see deterministic and model-based quality findings with actionable repair
   paths;
7. preview and export a personalized interactive guide that works offline;
8. confirm that private profile and run data are absent from the normal export;
   and
9. complete the documented example workflow on each supported platform.

Engineering release gates:

- all Python, frontend, and end-to-end tests pass;
- no known critical data-loss, privacy, path-traversal, or arbitrary-code
  execution defect remains;
- interruption and stale-write recovery are covered by tests;
- exported guides pass the supported accessibility and browser smoke checks;
- schema and runtime versions are recorded and compatible; and
- public fixtures contain no private source-workspace artifacts.

## 12. Success measures

For a local pre-telemetry product, success is evaluated with explicit usability
tests and fixture runs rather than hidden analytics.

- **First-course success:** a new user can reach a valid interactive export from
  a clean install using the tutorial.
- **Time to first meaningful preview:** the user can create a profile, brief,
  spec, and outline preview without understanding repository internals.
- **Recovery:** every intentionally interrupted acceptance run resumes from the
  correct next action without artifact loss.
- **Personalization:** the final-course audit can trace each declared learner
  goal to course content or explain why it was excluded.
- **Quality:** the reference fixture set reliably triggers and then clears known
  schema, privacy, outcome-coverage, interaction, and accessibility failures.
- **Portability:** an exported guide opens and retains its core interactions on
  a machine without Education Pipeline or a network connection.
- **Model flexibility:** the same fixture course completes through recommended,
  mixed-provider, and fully manual model plans.

## 13. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Model output is persuasive but educationally weak | Approved contract and outline, blueprint-specific rubric, model QA, deterministic outcome coverage, human gates |
| Personalization leaks sensitive details | Private/publishable field separation, prompt boundary, leak checks, export deny-by-default |
| Model-generated HTML/JS creates a security and reliability problem | Versioned structured guide schema and application-owned renderer; no arbitrary generated code |
| Provider CLIs or model names change | Adapter boundary, configurable catalogs, availability checks, manual workflow |
| “Recommended” model plan becomes stale | Versioned, editable recommendations with rationale; never hard-code the product around one model name |
| Pipeline feels too technical | Guided New Course flow, strong defaults, progressive disclosure, next-action UI |
| Factual verification is overstated | Source expectations, citation-shape checks, uncertainty display, clear product limitation |
| Long runs waste premium model use | Stage-level model selection, previewed commands, targeted regeneration, resume and retry |
| Interactive scope grows without bound | Small supported interaction vocabulary with explicit admission criteria |
| Local files are lost or corrupted | Atomic writes, content hashes, append-only events, backups/export guidance, migration tests |

## 14. Next-level product opportunities

These ideas fit the local-first vision but are not required for `v0.1`:

- **Interest graph:** locally capture recurring interests and familiar domains so
  new courses can deliberately use analogies that work across subjects.
- **Diagnostic preflight:** generate a short local diagnostic before outlining,
  allowing the course to skip known material and focus on real gaps.
- **Learning-path composer:** combine several completed courses into a local
  curriculum with prerequisites and shared outcomes.
- **Section-level repair:** validate and regenerate one lesson or interaction
  while preserving the approved rest of the course.
- **Teach-back mode:** add prompts and rubrics that ask the learner to explain a
  concept, then compare the explanation against the course contract locally.
- **Practice variants:** generate additional exercises from an approved concept
  and rubric without rewriting the lesson.
- **Source packs:** let users attach local notes, PDFs, or reference material to
  a course brief with explicit provenance and prompt-injection boundaries.
- **Course health report:** show outcome coverage, interaction balance, estimated
  time, difficulty curve, citation state, and unresolved waivers in one view.
- **Reproducible rebuilds:** compare a course rebuilt with a newer model plan or
  schema while preserving the original and highlighting meaningful changes.
- **Optional guide packs:** later distribute curated blueprints, interaction
  components, or example courses as local installable packages—without creating
  hosting infrastructure or a required marketplace.

## 15. Product decisions and open questions

### Decisions

- The product is a fully local application, not a hosted service.
- The primary output is a genuinely interactive course guide.
- The application owns the guide runtime; models own bounded content creation.
- Learner tailoring, configurable model mixtures, deterministic quality gates,
  and visible human control are core product features.
- Claude Code, Codex, and manual workflows are the initial provider paths.
- Recommended defaults are essential, but every model-powered stage remains
  configurable.
- Hosting, accounts, remote collaboration, and course discovery are out of scope
  for the initial product.

### Open questions to resolve during P0 design

1. What exact structured content format should guide schema v1 use, and how is
   it migrated across runtime versions?
2. Which three to five interaction types create the strongest initial learning
   experience without overextending the runtime?
3. Which deterministic findings block export, and which are warnings or
   explicitly waivable?
4. What provider-install/authentication experience can be documented reliably
   on each supported operating system?
5. Which operating systems and browsers are release-blocking for `v0.1`?
6. How should factual-source requirements vary by blueprint and subject risk?
7. How much learner-progress state belongs inside an exported guide, and how
   should users reset or transfer it?

## 16. Immediate next artifact

The P0 interactive-guide contract spec set and detailed implementation plan are
complete and linked above. Execution begins by landing the documentation
baseline, then implementing the canonical schema/fixture before opening the
parallel validation and runtime workstreams. See
[`docs/superpowers/plans/2026-07-11-interactive-guide-v1.md`](superpowers/plans/2026-07-11-interactive-guide-v1.md).
