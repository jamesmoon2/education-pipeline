import { describe, expect, it } from "vitest";
// Vite's ?raw import reads the module source as a string (no @types/node in
// this project, so node:fs would not type-check under `npm run build`).
import pageSource from "./NewRunPage.tsx?raw";

// Phase 6 decision 3 guard: the wizard's 17 form + lifecycle useStates move
// into the pure reducer in lib/newRunWizard.ts. Only the five remote-data
// states stay useState: blueprints, blueprintsError, restoringBlueprints,
// plan and planError. (At open, NewRunPage.tsx had 22.)

function code(source: string): string {
  // Comments may mention useState freely; count only code.
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

describe("NewRunPage wizard state shape", () => {
  it("keeps at most 5 useState calls (the remote-data states)", () => {
    const calls = code(pageSource).match(/\buseState\s*[<(]/g) ?? [];
    expect(calls.length).toBeLessThanOrEqual(5);
  });

  it("drives the form and lifecycle state through wizardReducer from ../lib/newRunWizard", () => {
    const source = code(pageSource);
    expect(source).toMatch(/from\s+["']\.\.\/lib\/newRunWizard["']/);
    expect(source).toMatch(/\buseReducer\s*[<(]/);
    expect(source).toMatch(/\bwizardReducer\b/);
  });
});
