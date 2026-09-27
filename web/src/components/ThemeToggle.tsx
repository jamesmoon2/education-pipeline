import { useId, useState } from "react";
import {
  applyTheme,
  isThemePreference,
  readThemePreference,
  storeThemePreference,
} from "../lib/theme";
import type { ThemePreference } from "../lib/theme";

const OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: "system", label: "Match system" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/**
 * Rail-footer theme select (Phase 6 decision 2). The stored choice was
 * already stamped on <html> by main.tsx before the first render; this only
 * reflects it and applies and persists a new one.
 */
export default function ThemeToggle() {
  const selectId = useId();
  const [preference, setPreference] = useState<ThemePreference>(() => readThemePreference());

  const choose = (value: string) => {
    const next = isThemePreference(value) ? value : "system";
    setPreference(next);
    applyTheme(next);
    storeThemePreference(next);
  };

  return (
    <div className="theme-toggle">
      <label htmlFor={selectId}>Theme</label>
      <select id={selectId} value={preference} onChange={(e) => choose(e.target.value)}>
        {OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
