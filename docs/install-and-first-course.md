# Install and your first course

This is the canonical path from nothing to a personalized, offline,
interactive course. It needs Python 3.11+ and a modern browser. No model
provider is required — every stage can run manually.

## 1. Install

**From a packaged release (recommended).** Download the wheel from the
GitHub release and install it; the built cockpit is bundled, so no Node
toolchain is needed:

```bash
python3 -m pip install education_pipeline-<version>-py3-none-any.whl
education-pipeline --help
```

**From a source checkout (for development).** The engine works
immediately; the browser cockpit additionally needs its assets built once:

```bash
git clone https://github.com/jamesmoon2/education-pipeline
cd education-pipeline
python3 -m pip install -e ".[dev]"
(cd web && npm ci && npm run build)   # only needed for the cockpit
```

> **Keeping a source checkout current:** `git pull` updates the cockpit's
> *source*, not the built bundle the daemon serves. After any pull that
> touches `web/`, rebuild with `(cd web && npm run build)` — or launch
> with `education-pipeline ui --rebuild`. If you skip this, `ui` warns
> and the cockpit shows a banner. Release wheels bundle a prebuilt
> cockpit and never need this.

Installation is verified in CI on Linux, macOS, and Windows.

## 2. Launch

```bash
education-pipeline ui
```

One command does everything: it resolves your workspace (or offers to
create `~/EducationPipeline` on first run), validates it, starts the
local loopback-only daemon, prints the cockpit URL, and opens your
browser. Your workspace is a plain directory that holds every course you
make — see [`docs/backup-and-migration.md`](backup-and-migration.md).

## 3. See a finished course first (optional, 1 minute)

Open [`examples/feedback-loops/export/guide.html`](../examples/feedback-loops/export/guide.html)
from the repository in any browser. That single offline file — modules,
knowledge checks, worked reveals, scenarios, progress tracking — is what
you are about to build. The example directory also shows every
intermediate artifact a run produces.

## 4. Create your first course

In the cockpit, choose **New Course** (`/new`). The wizard walks through:

1. **Topic** — title, a short brief, audience, goals, optional time
   budget, and a pedagogical blueprint (a recommendation is preselected
   and explained).
2. **Learner profile (optional)** — who this course is for. Profiles are
   private by default: they tailor the course without being published.
3. **Model plan** — accept the recommended provider/model per stage,
   override any stage, or set stages to manual. If you have the Claude
   Code or Codex CLI installed and signed in, stages can run with one
   click; see [`docs/providers.md`](providers.md).

## 5. Run the stages

A course moves through `spec → outline → draft → qa → factcheck → repair`, and you
approve each stage before the next begins — the pipeline never
auto-approves your course.

- **With a provider:** press the run button on the course board; the next
  stage's prompt executes and the response appears for your review.
- **Manually:** open the stage's prompt, run it in any model interface,
  and paste or save the response back.

After the draft and repair stages, deterministic validation shows its
findings at the responsible stage; blocking findings must be resolved (or
explicitly waived with a reason) before the course can finalize.

## 6. Finalize and export

When the final validation gate is open, finalize and export from the
course board (or `education-pipeline export <topic> --format html`). You
get `guide.html` — one self-contained interactive file that works offline
from a `file:` URL — plus `guide.report.json`, a reproducible quality
report of exactly what was checked. Private profile data is structurally
absent from both; see
[`docs/privacy-and-local-trust.md`](privacy-and-local-trust.md).

## Prefer the terminal?

The CLI drives the same engine end to end (`topic import`, `advance`,
`approve`, `validate`, `finalize`, `export`). The example project's
[README](../examples/feedback-loops/README.md) walks the full CLI flow
using its committed stage responses, so you can complete a whole run
without calling any model.

## If something fails

Every error carries a stable code with a recovery action — the same text
in the cockpit, the CLI, and
[`docs/troubleshooting.md`](troubleshooting.md).
