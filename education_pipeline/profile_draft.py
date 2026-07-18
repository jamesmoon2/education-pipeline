"""Draft a learner-profile TOML from a free-text description.

An alternative intake to the structured cockpit form: the user describes the
learner in plain language, a configured provider CLI turns that description
into profile TOML, and the cockpit shows the TOML for review before it is
imported through the ordinary profile import path. Nothing here saves a
profile — the human approval gate stays in place.

Prompt construction and TOML extraction are deterministic; only the provider
call itself involves a model, mirroring the stage pipeline's split.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Callable

from education_pipeline.config import (
    ConfigError,
    ModelCatalog,
    ModelOption,
    ModelPlan,
    StageModelPlan,
)
from education_pipeline.profiles import parse_learner_profile
from education_pipeline.providers import get_runner

# Profile drafting is one bounded generation; stage jobs get 30 minutes but
# a profile is small — cap the wait so a hung provider cannot pin an HTTP
# request forever.
PROFILE_DRAFT_TIMEOUT_SECONDS = 600

_PROMPT_HEADER = """\
# Draft a learner profile

You are helping set up a learner profile for an education-content pipeline.
Turn the free-text description below into a TOML document.

Output rules (all of them matter):

- Output ONLY the TOML document — no commentary, no surrounding prose.
  A single fenced ```toml code block is also acceptable.
- Use only facts stated or clearly implied by the description. Leave out any
  key the description gives you nothing for; do not invent details.
- `id` is required: a short, filesystem-safe, lowercase-hyphenated slug
  derived from the description (e.g. "returning-biology-student").
- `target_learner` is required: one sentence naming who this profile is for.
- All other keys are optional. String-list keys hold one item per entry.

TOML schema (types are exact; omit unknown keys):

```toml
schema_version = 1
id = "example-learner"                # required
target_learner = "..."                # required
prior_education = "..."
prior_experience = "..."
professional_experience = "..."
current_skill_level = "..."
adjacent_domains = ["..."]
learning_goals = ["..."]
preferred_examples = ["..."]
examples_to_avoid = ["..."]
math_comfort = "..."
reading_level = "..."
pace = "..."
desired_depth = "..."
time_budget = "..."
assessment_styles = ["..."]
accessibility_constraints = ["..."]
tone_preference = "..."
sensitive_areas = ["..."]

[learning_preferences]
preferred_modalities = ["..."]
explanation_style = "..."
preferred_visual_aids = ["..."]
diagram_frequency = "..."
interaction_style = "..."
practice_style = ["..."]
feedback_style = "..."
worked_example_preference = "..."
common_sticking_points = ["..."]
attention_constraints = ["..."]
review_style = ["..."]

[localization]
jurisdiction = "..."
locale = "..."
units = "..."
language_register = "..."

[privacy]
private_by_default = true
include_in_published_output = false
# publishable_summary = "..."         # only if the description offers one
```

## Learner description

"""


def build_profile_draft_prompt(description: str) -> str:
    """Compose the deterministic drafting prompt around the free text."""

    text = description.strip()
    if not text:
        raise ConfigError("profile description must not be empty")
    return _PROMPT_HEADER + text + "\n"


_FENCE_RE = re.compile(r"```(?:toml)?[ \t]*\n(.*?)```", re.DOTALL)


def extract_toml(text: str) -> str:
    """Pull the TOML document out of a model response.

    Providers are told to answer with bare TOML, but a fenced code block —
    possibly with a sentence around it — is common enough to tolerate. When
    fences are present the longest block wins; otherwise the trimmed response
    is taken as-is and left for the TOML parser to judge.
    """

    fenced = _FENCE_RE.findall(text)
    body = max(fenced, key=len) if fenced else text
    body = body.strip()
    if not body:
        raise ConfigError("provider response contained no TOML")
    return body + "\n"


def draft_profile_toml(
    catalog: ModelCatalog,
    plan: ModelPlan,
    description: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    timeout: float = PROFILE_DRAFT_TIMEOUT_SECONDS,
    run_process: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """Run the drafting prompt through a provider and validate the result.

    Returns a JSON-serializable payload with the validated TOML text and the
    drafted profile id. Raises :class:`ConfigError` for anything the caller
    can fix (unknown/unavailable provider, provider failure, invalid TOML) so
    the daemon maps it to HTTP 400.
    """

    provider_id = provider or plan.provider
    runner = get_runner(provider_id)
    if not runner.executable:
        raise ConfigError(
            f"provider {provider_id!r} is not executable — pick a provider CLI, "
            "or copy the drafting prompt and run it yourself"
        )
    if not runner.is_available():
        raise ConfigError(f"provider {provider_id!r} is not available on PATH")

    if model is None:
        model_option = ModelOption(id="", label="")
    else:
        catalog_provider = catalog.require_provider(provider_id)
        try:
            model_option = catalog_provider.models[model]
        except KeyError as exc:
            raise ConfigError(
                f"unknown model {model!r} for provider {provider_id!r}"
            ) from exc

    prompt = build_profile_draft_prompt(description)
    stage_plan = StageModelPlan(
        stage="profile_draft",
        recommendation="draft a learner profile from a free-text description",
        model=model,
        effort=effort,
        provider=provider_id,
    )
    # The prompt travels via stdin (as stage jobs do); the path argument only
    # names the artifact for adapters that want it.
    invocation = runner.build_invocation(
        model_option, stage_plan, Path("profile-draft-prompt.md")
    )
    env = dict(os.environ)
    env.update(invocation.env)
    try:
        completed = run_process(
            invocation.argv,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigError(
            f"provider {provider_id!r} timed out after {int(timeout)}s"
        ) from exc
    except OSError as exc:
        raise ConfigError(f"failed to launch provider {provider_id!r}: {exc}") from exc
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or b"").decode("utf-8", errors="replace")[-500:]
        detail = f": {stderr_tail.strip()}" if stderr_tail.strip() else ""
        raise ConfigError(
            f"provider {provider_id!r} exited with code {completed.returncode}{detail}"
        )

    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stdout = stdout.replace("\r\n", "\n")
    response = runner.parse_response(stdout)
    toml_text = extract_toml(response.text)
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"provider returned invalid TOML: {exc}") from exc
    profile = parse_learner_profile(data)
    return {
        "toml": toml_text,
        "profile_id": profile.id,
        "provider": provider_id,
        "model": model,
        "effort": effort,
    }
