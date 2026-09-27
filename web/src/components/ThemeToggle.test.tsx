import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ThemeToggle from "./ThemeToggle";

// Phase 6 decision 2: a native <select aria-label="Theme"> offering
// "Match system" (default), "Light" and "Dark". A choice is stamped on
// <html data-theme> and persisted in localStorage `ep.theme`; "Match system"
// removes both. Blocked storage never throws: the choice holds for the session.

function themeSelect() {
  return screen.getByRole("combobox", { name: "Theme" });
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("ThemeToggle", () => {
  it("is a native select named Theme offering Match system, Light and Dark", () => {
    render(<ThemeToggle />);
    const select = themeSelect();
    expect(select.tagName).toBe("SELECT");
    const options = within(select).getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => option.textContent)).toEqual([
      "Match system",
      "Light",
      "Dark",
    ]);
    expect(options.map((option) => option.value)).toEqual(["system", "light", "dark"]);
  });

  it("defaults to Match system when nothing is stored", () => {
    render(<ThemeToggle />);
    expect(themeSelect()).toHaveValue("system");
    expect(themeSelect()).toHaveDisplayValue("Match system");
  });

  it.each([
    ["light", "Light"],
    ["dark", "Dark"],
  ])("starts from the stored %s choice", (stored, label) => {
    localStorage.setItem("ep.theme", stored);
    render(<ThemeToggle />);
    expect(themeSelect()).toHaveValue(stored);
    expect(themeSelect()).toHaveDisplayValue(label);
  });

  it("starts from Match system for an unknown stored value", () => {
    localStorage.setItem("ep.theme", "sepia");
    render(<ThemeToggle />);
    expect(themeSelect()).toHaveValue("system");
  });

  it("choosing Dark stamps the root and persists", async () => {
    render(<ThemeToggle />);
    await userEvent.selectOptions(themeSelect(), "Dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("ep.theme")).toBe("dark");
    expect(themeSelect()).toHaveValue("dark");
  });

  it("choosing Light stamps the root and persists", async () => {
    render(<ThemeToggle />);
    await userEvent.selectOptions(themeSelect(), "Light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("ep.theme")).toBe("light");
  });

  it("choosing Match system removes data-theme and the stored key", async () => {
    localStorage.setItem("ep.theme", "dark");
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    await userEvent.selectOptions(themeSelect(), "Match system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("ep.theme")).toBeNull();
    expect(themeSelect()).toHaveValue("system");
  });

  it("with storage blocked it renders, and a choice still holds for the session", async () => {
    const deny = () => {
      throw new DOMException("blocked", "SecurityError");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(deny);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(deny);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(deny);
    render(<ThemeToggle />);
    expect(themeSelect()).toHaveValue("system");
    await userEvent.selectOptions(themeSelect(), "Dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeSelect()).toHaveValue("dark");
    await userEvent.selectOptions(themeSelect(), "Match system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(themeSelect()).toHaveValue("system");
  });
});
