// Plain-language explanations for the model-plan surface (design system §3.4).
export const STAGE_HELP: Record<string, string> = {
  profile: "Reserved for a future profile-summarization step. Learner-profile context is attached to stage prompts directly today, so this row doesn't affect runs yet.",
  spec: "Turns your topic brief into the course contract — scope, modules, and success criteria — that every later stage builds against.",
  outline: "Expands the spec into a module-by-module lesson outline.",
  draft: "Writes the full course content from the outline.",
  qa: "Checks the draft against the spec for pedagogy, coverage, and scope — not deep factual verification.",
  factcheck: "Adversarially checks factual claims in the draft. Findings go to repair along with model-QA findings.",
  repair: "Fixes the problems QA and fact-check found.",
  audit: "Optional review of how well the course matches the attached learner profile.",
};

export const PROVIDER_HELP =
  "Which tool runs this stage. Claude Code and Codex run automatically through their CLIs; Manual copy/paste means you run the prompt yourself in any model UI.";

export const EFFORT_HELP =
  "Recorded guidance for how much reasoning this stage deserves. It's saved with the plan and shown in run provenance, but provider CLIs currently run with their own defaults — changing it doesn't change model behavior or cost yet.";
