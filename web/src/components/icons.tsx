/**
 * The cockpit's line icons: one stroke weight, 20-unit grid, currentColor.
 * Inline so the bundle needs no icon font and the dock renders offline.
 * Every icon is decorative (aria-hidden) — the adjacent label carries meaning.
 */
const base = {
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: "false" as const,
};

export function LibraryIcon() {
  return (
    <svg {...base}>
      <path d="M3.5 4.5h4v11h-4zM8.5 4.5h4v11h-4zM13.2 5.2l3.3-.7 2 10.8-3.3.7z" />
    </svg>
  );
}

export function SparkIcon() {
  return (
    <svg {...base}>
      <path d="M10 3v14M3 10h14" />
      <path d="M5.3 5.3l1.6 1.6M13.1 13.1l1.6 1.6M14.7 5.3l-1.6 1.6M6.9 13.1l-1.6 1.6" opacity="0.55" />
    </svg>
  );
}

export function ProfileIcon() {
  return (
    <svg {...base}>
      <circle cx="10" cy="7" r="3.2" />
      <path d="M4 17c.6-3.2 3-5 6-5s5.4 1.8 6 5" />
    </svg>
  );
}

export function SettingsIcon() {
  return (
    <svg {...base}>
      <path d="M4 6h12M4 10h12M4 14h12" />
      <circle cx="7.5" cy="6" r="1.6" fill="var(--ep-color-surface)" />
      <circle cx="12.5" cy="10" r="1.6" fill="var(--ep-color-surface)" />
      <circle cx="8.5" cy="14" r="1.6" fill="var(--ep-color-surface)" />
    </svg>
  );
}

export function TourIcon() {
  return (
    <svg {...base}>
      <path d="M10 2.5a5 5 0 0 1 5 5c0 3.3-5 9-5 9s-5-5.7-5-9a5 5 0 0 1 5-5z" />
      <circle cx="10" cy="7.5" r="1.6" />
    </svg>
  );
}

export function ArrowIcon() {
  return (
    <svg {...base}>
      <path d="M4 10h12M11 5l5 5-5 5" />
    </svg>
  );
}

/**
 * Brand mark: a spectrum bar cut at 388 nm — the violet edge of what the eye
 * can see — with three nodes for the three artifacts every stage keeps
 * (prompt, response, approved). Drawn once, colored by tokens.
 */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="ep-spectrum" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="var(--ep-spectrum-start)" />
          <stop offset="0.55" stopColor="var(--ep-spectrum-mid)" />
          <stop offset="1" stopColor="var(--ep-spectrum-end)" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="24" height="24" rx="7" fill="var(--ep-brand-tile)" />
      <path d="M14 6.5v15" stroke="url(#ep-spectrum)" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="14" cy="8" r="2.1" fill="var(--ep-spectrum-end)" />
      <circle cx="14" cy="14" r="2.1" fill="var(--ep-spectrum-mid)" />
      <circle cx="14" cy="20" r="2.1" fill="var(--ep-spectrum-start)" />
    </svg>
  );
}
