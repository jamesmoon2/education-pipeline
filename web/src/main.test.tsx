import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Phase 6 decisions 1 and 2 at the entry point. main.tsx has no exports; it
// renders into #root when imported, so each test re-imports it against a
// fresh module registry. App is stubbed: it records the root's data-theme at
// its first render, and throws on demand to exercise the app-level boundary.

const app = vi.hoisted(() => ({
  throws: false,
  themeAtRender: [] as Array<string | null>,
}));

vi.mock("./App", () => ({
  default: function AppStub() {
    app.themeAtRender.push(document.documentElement.getAttribute("data-theme"));
    if (app.throws) throw new Error("rail exploded");
    return "app stub";
  },
}));

let container: HTMLElement;

beforeEach(() => {
  vi.resetModules();
  app.throws = false;
  app.themeAtRender = [];
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  vi.spyOn(console, "error").mockImplementation(() => {});
  container = document.createElement("div");
  container.id = "root";
  document.body.appendChild(container);
});

afterEach(() => {
  container.remove();
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("main.tsx", () => {
  it("applies the stored theme synchronously, before the first render", async () => {
    localStorage.setItem("ep.theme", "dark");
    await import("./main");
    // Stamped by the time the module finishes evaluating...
    expect(document.documentElement.dataset.theme).toBe("dark");
    // ...and therefore already present when App first renders.
    expect(await screen.findByText("app stub")).toBeInTheDocument();
    expect(app.themeAtRender[0]).toBe("dark");
  });

  it("wraps App in a last-resort boundary that offers Reload the cockpit", async () => {
    app.throws = true;
    await import("./main");
    expect(
      await screen.findByRole("button", { name: "Reload the cockpit" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("rail exploded");
  });
});
