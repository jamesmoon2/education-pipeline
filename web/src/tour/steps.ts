/**
 * Guided-tour content. Each tour is an ordered list of steps; a step either
 * anchors to a live element (a `[data-tour=…]` hook rendered by the shell or
 * a page) or, with no `target`, floats centered over the workspace. Steps
 * may hop routes: the provider navigates before revealing the step and waits
 * briefly for the anchor to mount. An anchor that never appears (a library
 * with no courses yet, a board with no validation section) degrades to a
 * centered card — the words still land, only the spotlight is skipped.
 *
 * Copy stays in learner language (design system §3.4): what a surface is
 * for and what is safe to do there, never internal state names.
 */
export interface TourStep {
  /** Stable id; used for keys and test hooks. */
  id: string;
  title: string;
  body: string;
  /** CSS selector of the element to spotlight. Omit for a centered card. */
  target?: string;
  /** Pathname to navigate to before showing the step. */
  route?: string;
}

export type TourId = "workbench" | "run-board";

export const WORKBENCH_TOUR: TourStep[] = [
  {
    id: "welcome",
    title: "Your course workbench",
    body:
      "Education Pipeline turns a short brief into an interactive guide, one reviewable stage at a time. Everything you see here lives in a folder on this computer. This tour takes about two minutes.",
  },
  {
    id: "nav",
    target: '[data-tour="nav"]',
    title: "Four places to be",
    body:
      "Courses is your library. New course starts a guided setup. Profiles hold learner context that shapes examples and depth. Settings chooses which models run each stage.",
  },
  {
    id: "library",
    route: "/",
    target: '[data-tour="library"]',
    title: "The course library",
    body:
      "Each row is a course. The Next action column always names the one safe move — click it to land exactly where that work happens. Filters and sorting are up top; archive, duplicate and reveal-in-folder sit on the right.",
  },
  {
    id: "wizard",
    route: "/new",
    target: '[data-tour="wizard"]',
    title: "Five steps to a course",
    body:
      "Pick a learner, describe the topic, choose a blueprint, confirm the model plan, then review. Your draft is saved as you type, so you can wander to Profiles or Settings and come back.",
  },
  {
    id: "activity",
    target: '[data-tour="activity"]',
    title: "Live activity, on every page",
    body:
      "Provider jobs can run for minutes. Running jobs and courses that are ready for your review surface here wherever you are, so nothing finishes silently.",
  },
  {
    id: "model-plan",
    route: "/settings",
    target: '[data-tour="model-plan"]',
    title: "Choose models per stage",
    body:
      "A preset fills the whole plan; any stage row can override provider, model and effort. Manual copy/paste is always available, so no CLI is ever required to finish a course.",
  },
  {
    id: "theme",
    target: '[data-tour="theme"]',
    title: "Light, dark, or follow the system",
    body:
      "The dark theme is tuned like a room under blacklight: what matters fluoresces, the rest recedes. Your choice is remembered on this device.",
  },
  {
    id: "done",
    title: "Everything stays on this device",
    body:
      "Prompts, responses, approvals and exports are plain files in your workspace. Replay this tour any time from the dock, or from Settings → Appearance.",
  },
];

export const RUN_BOARD_TOUR: TourStep[] = [
  {
    id: "next-action",
    target: '[data-tour="next-action"]',
    title: "What to do next",
    body:
      "Every board leads with the single next move for this run, and the button beneath it performs exactly that move. Nothing advances without your approval.",
  },
  {
    id: "pipeline",
    target: '[data-tour="pipeline"]',
    title: "The learning thread",
    body:
      "One node per stage, in order. Each links to that stage's prompt, response and approved copy. A number on a node counts findings that still need attention there.",
  },
  {
    id: "validation",
    target: '[data-tour="validation"]',
    title: "Evidence, not scores",
    body:
      "Validation checks the guide's structure with no model involved. Blocking findings must be fixed or deliberately waived before the guide can be finalized.",
  },
  {
    id: "run-plan",
    target: '[data-tour="run-plan"]',
    title: "This run's model plan",
    body:
      "Override the workspace defaults for this course only. Changes apply from the next stage that runs.",
  },
  {
    id: "jobs",
    target: '[data-tour="jobs"]',
    title: "Job history",
    body:
      "Every provider run is recorded with its status, duration and log. A failed job keeps its log so you can see why before retrying.",
  },
];

export const TOURS: Record<TourId, TourStep[]> = {
  workbench: WORKBENCH_TOUR,
  "run-board": RUN_BOARD_TOUR,
};
