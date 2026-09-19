import { useEffect, useState } from "react";

export const THEME_KEY = "ep.theme";
export type ThemePreference = "system" | "light" | "dark";

const OPTIONS: { value: ThemePreference; label: string; glyph: JSX.Element }[] = [
  {
    value: "system",
    label: "System",
    glyph: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <rect x="2.5" y="4" width="15" height="10" rx="2" />
        <path d="M7 17h6" />
      </svg>
    ),
  },
  {
    value: "light",
    label: "Light",
    glyph: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="3.5" />
        <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4" />
      </svg>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    glyph: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M15.5 12.5A6.5 6.5 0 0 1 7.5 4.5a6.5 6.5 0 1 0 8 8z" />
      </svg>
    ),
  },
];

export function readThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

/** Reflect a preference on <html>; the stylesheet keys every token off it. */
export function applyTheme(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") {
    delete root.dataset.theme;
  } else {
    root.dataset.theme = preference;
  }
}

function storeTheme(preference: ThemePreference): void {
  try {
    if (preference === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, preference);
  } catch {
    // Storage blocked: the choice still applies for this page load.
  }
}

/**
 * Three-way theme control (design system §10: honor the system until the
 * learner chooses). index.html applies the stored value before first paint;
 * this control keeps the attribute and storage in step afterwards.
 */
export default function ThemeToggle() {
  const [preference, setPreference] = useState<ThemePreference>(readThemePreference);

  useEffect(() => {
    applyTheme(preference);
  }, [preference]);

  const choose = (next: ThemePreference) => {
    storeTheme(next);
    setPreference(next);
  };

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Theme" data-tour="theme">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={preference === option.value}
          aria-label={option.label}
          title={option.label}
          className="theme-toggle-option"
          onClick={() => choose(option.value)}
        >
          {option.glyph}
        </button>
      ))}
      <span className="theme-toggle-thumb" aria-hidden="true" data-value={preference} />
    </div>
  );
}
