// Plain-language help for the new-course wizard.
export const TOPIC_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export const NEW_RUN_HELP: Record<string, string> = {
  learner: "Attaching a learner profile personalizes the whole course to that person. You can also continue without one for a generic course.",
  topic_id: "Short folder-safe identifier for this course, e.g. intro-to-sql. Start with a letter or digit; then letters, digits, dots, dashes, or underscores.",
  brief: "2–4 sentences on what the course should cover and why the learner wants it. The models design the whole course from this — the more specific, the better.",
  audience: "Who the course is written for if no learner profile is attached, e.g. 'busy professionals new to investing'.",
  goals: "What the learner should be able to do afterward. One goal per line.",
  time_budget: "Rough total learning time in minutes; the outline sizes modules to fit.",
  toml: "Advanced: paste a complete topic definition in TOML instead of describing it field by field.",
  blueprint: "A blueprint is the pedagogical pattern for the course — how lessons, practice, and assessment are arranged. The recommendation is based on your topic.",
};
