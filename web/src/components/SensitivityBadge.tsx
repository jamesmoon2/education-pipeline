import type { ProfileSensitivityTier } from "../api/types";

export default function SensitivityBadge({ tier }: { tier?: ProfileSensitivityTier }) {
  if (!tier) return null;
  return (
    <span className={`sensitivity-badge sensitivity-${tier}`}>
      {tier[0].toUpperCase() + tier.slice(1)} sensitivity
    </span>
  );
}
