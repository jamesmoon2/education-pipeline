/**
 * The cockpit's own theme choice (Phase 6 decision 2). Three states:
 *
 * - "system" (the default) leaves <html> without `data-theme`, so the
 *   `prefers-color-scheme` block in styles.css governs. That is why there is
 *   no matchMedia listener here and no token is ever duplicated.
 * - "light" / "dark" are stamped on <html data-theme> and persisted per
 *   browser in localStorage `ep.theme`.
 *
 * Storage access never throws: with storage blocked the choice simply holds
 * for the session (the stamp) and reads fall back to "system".
 */

export const THEME_STORAGE_KEY = "ep.theme";

export type ThemePreference = "system" | "light" | "dark";

export type ThemeStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

/** The stored explicit choice, else "system" (nothing stored, unknown value, storage blocked). */
export function readThemePreference(storage?: ThemeStorage): ThemePreference {
  try {
    const raw = (storage ?? window.localStorage).getItem(THEME_STORAGE_KEY);
    return raw === "light" || raw === "dark" ? raw : "system";
  } catch {
    return "system";
  }
}

/** Persist an explicit choice; "system" removes the key. */
export function storeThemePreference(preference: ThemePreference, storage?: ThemeStorage): void {
  try {
    const target = storage ?? window.localStorage;
    if (preference === "system") target.removeItem(THEME_STORAGE_KEY);
    else target.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage blocked: the stamp from applyTheme still holds for this session.
  }
}

/** Stamp an explicit choice on the root; "system" removes the attribute entirely. */
export function applyTheme(
  preference: ThemePreference,
  root: HTMLElement = document.documentElement,
): void {
  if (preference === "system") root.removeAttribute("data-theme");
  else root.dataset.theme = preference;
}
