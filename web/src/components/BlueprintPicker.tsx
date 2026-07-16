import type { BlueprintsPayload } from "../api/types";

export default function BlueprintPicker({
  payload,
  value,
  onChange,
}: {
  payload: BlueprintsPayload;
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <fieldset className="blueprint-picker">
      <legend>Blueprint</legend>
      {payload.recommendation && (
        <p className="blueprint-rationale">{payload.recommendation.rationale}</p>
      )}
      {payload.blueprints.map((blueprint) => (
        <label key={blueprint.id} className="blueprint-option">
          <input
            type="radio"
            name="blueprint"
            checked={value === blueprint.id}
            onChange={() => onChange(blueprint.id)}
          />{" "}
          <strong>{blueprint.title}</strong>
          {payload.recommendation?.id === blueprint.id && (
            <span className="blueprint-recommended"> Recommended</span>
          )}
          <span className="blueprint-summary">{blueprint.summary}</span>
          <span className="blueprint-when-to-use">{blueprint.when_to_use}</span>
        </label>
      ))}
    </fieldset>
  );
}
