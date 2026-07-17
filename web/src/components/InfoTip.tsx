import { useId, useState } from "react";

export interface InfoTipProps {
  /** The field/control name the tip explains; used in the accessible name. */
  label: string;
  /** Plain-language explanation shown in the tooltip. */
  text: string;
}

export default function InfoTip({ label, text }: InfoTipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className="info-tip">
      <button
        type="button"
        className="info-tip-trigger"
        aria-label={`About ${label}`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <span aria-hidden="true">ⓘ</span>
      </button>
      {open && (
        <span role="tooltip" id={id} className="info-tip-bubble">
          {text}
        </span>
      )}
    </span>
  );
}
