import { afterEach, describe, expect, it, vi } from "vitest";
import {
  THEME_STORAGE_KEY,
  applyTheme,
  readThemePreference,
  storeThemePreference,
} from "./theme";
import type { ThemePreference, ThemeStorage } from "./theme";

// Phase 6 decision 2: three states, no matchMedia. An explicit choice is
// stored in localStorage `ep.theme` and stamped on <html data-theme>;
// "system" removes both and leaves the CSS media query in charge.

function memoryStorage(initial: Record<string, string> = {}): ThemeStorage & {
  entries: Map<string, string>;
} {
  const entries = new Map(Object.entries(initial));
  return {
    entries,
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => {
      entries.set(key, value);
    },
    removeItem: (key: string) => {
      entries.delete(key);
    },
  };
}

function throwingStorage(): ThemeStorage {
  const deny = () => {
    throw new DOMException("blocked", "SecurityError");
  };
  return { getItem: deny, setItem: deny, removeItem: deny };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("THEME_STORAGE_KEY", () => {
  it("is ep.theme", () => {
    expect(THEME_STORAGE_KEY).toBe("ep.theme");
  });
});

describe("readThemePreference", () => {
  it.each(["light", "dark"] as const)("reads a stored %s", (pref) => {
    expect(readThemePreference(memoryStorage({ "ep.theme": pref }))).toBe(pref);
  });

  it("reads system when nothing is stored", () => {
    expect(readThemePreference(memoryStorage())).toBe("system");
  });

  it.each(["system", "", "blue", "DARK", " dark", "null"])(
    "reads an unknown stored value %j as system",
    (raw) => {
      expect(readThemePreference(memoryStorage({ "ep.theme": raw }))).toBe("system");
    },
  );

  it("reads system when storage throws, and never throws out", () => {
    expect(() => readThemePreference(throwingStorage())).not.toThrow();
    expect(readThemePreference(throwingStorage())).toBe("system");
  });

  it("defaults to localStorage", () => {
    localStorage.setItem("ep.theme", "dark");
    expect(readThemePreference()).toBe("dark");
  });

  it("reads system when the default localStorage throws", () => {
    localStorage.setItem("ep.theme", "dark");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(readThemePreference()).toBe("system");
  });
});

describe("storeThemePreference", () => {
  it.each(["light", "dark"] as const)("stores %s under ep.theme", (pref) => {
    const storage = memoryStorage();
    storeThemePreference(pref, storage);
    expect(storage.entries.get("ep.theme")).toBe(pref);
  });

  it("system removes the key", () => {
    const storage = memoryStorage({ "ep.theme": "dark", other: "kept" });
    storeThemePreference("system", storage);
    expect(storage.entries.has("ep.theme")).toBe(false);
    expect(storage.entries.get("other")).toBe("kept");
  });

  it.each(["light", "dark", "system"] as const)(
    "never throws out when storage throws (%s)",
    (pref) => {
      expect(() => storeThemePreference(pref, throwingStorage())).not.toThrow();
    },
  );

  it("defaults to localStorage", () => {
    storeThemePreference("light", undefined);
    expect(localStorage.getItem("ep.theme")).toBe("light");
    storeThemePreference("system");
    expect(localStorage.getItem("ep.theme")).toBeNull();
  });

  it("never throws out when the default localStorage throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => storeThemePreference("dark")).not.toThrow();
    expect(() => storeThemePreference("system")).not.toThrow();
  });
});

describe("applyTheme", () => {
  it.each(["light", "dark"] as const)("stamps data-theme=%s on the given root", (pref) => {
    const root = document.createElement("div");
    applyTheme(pref, root);
    expect(root.dataset.theme).toBe(pref);
    expect(root.getAttribute("data-theme")).toBe(pref);
  });

  it("system removes data-theme entirely (not an empty value)", () => {
    const root = document.createElement("div");
    root.dataset.theme = "dark";
    applyTheme("system", root);
    expect(root.hasAttribute("data-theme")).toBe(false);
  });

  it("switches between explicit choices", () => {
    const root = document.createElement("div");
    const sequence: ThemePreference[] = ["dark", "light", "system", "dark"];
    const seen = sequence.map((pref) => {
      applyTheme(pref, root);
      return root.getAttribute("data-theme");
    });
    expect(seen).toEqual(["dark", "light", null, "dark"]);
  });

  it("defaults to document.documentElement", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    applyTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("does not touch storage", () => {
    applyTheme("dark", document.createElement("div"));
    expect(localStorage.getItem("ep.theme")).toBeNull();
  });
});
