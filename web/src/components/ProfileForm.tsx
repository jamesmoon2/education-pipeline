import { cloneElement } from "react";
import type {
  LearnerProfile,
  ProfileMetadataValue,
  ProfileSensitivity,
} from "../api/types";
import { isMetadataNumber, metadataNumber, metadataNumberValidationMessage } from "../api/types";
import SensitivityBadge from "./SensitivityBadge";
import InfoTip from "./InfoTip";
import { PROFILE_HELP } from "../lib/profileHelp";

interface ProfileFormProps {
  value: LearnerProfile;
  onChange: (profile: LearnerProfile) => void;
  sensitivity: ProfileSensitivity;
  idLocked?: boolean;
  disabled?: boolean;
}

function Field({
  label,
  path,
  sensitivity,
  children,
}: {
  label: string;
  path: string;
  sensitivity: ProfileSensitivity;
  children: React.ReactElement<{ "aria-label"?: string }>;
}) {
  // A <div>, not a <label>: the InfoTip button would otherwise become the
  // label's implicitly associated control. The input is named via aria-label.
  return (
    <div className="profile-field">
      <span className="profile-field-label">
        {label} <SensitivityBadge tier={sensitivity[path]} />
        {PROFILE_HELP[path] && <InfoTip label={label} text={PROFILE_HELP[path]} />}
      </span>
      {cloneElement(children, { "aria-label": label })}
    </div>
  );
}

const lines = (value: string) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

const singleLine = (value: string) => value.replace(/\s*\n\s*/g, " ");

function metadataKind(value: ProfileMetadataValue): "string" | "boolean" | "integer" | "float" | "list" | "table" {
  if (isMetadataNumber(value)) return value.kind;
  if (Array.isArray(value)) return "list";
  if (typeof value === "object") return "table";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "float";
  return "string";
}

function defaultForKind(kind: ReturnType<typeof metadataKind>): ProfileMetadataValue {
  if (kind === "boolean") return false;
  if (kind === "integer") return metadataNumber("0", "integer");
  if (kind === "float") return metadataNumber("0.0", "float");
  if (kind === "list") return [];
  if (kind === "table") return {};
  return "";
}

function MetadataNode({
  value,
  path,
  onChange,
  onRemove,
  disabled,
}: {
  value: ProfileMetadataValue;
  path: string[];
  onChange: (value: ProfileMetadataValue) => void;
  onRemove?: () => void;
  disabled?: boolean;
}) {
  const kind = metadataKind(value);
  const labelPath = path.length > 0 ? path.join(".") : "root";
  const numericError = isMetadataNumber(value) ? metadataNumberValidationMessage(value) : null;
  const numericErrorId = `metadata-error-${path.length > 0 ? path.map((segment) => encodeURIComponent(segment)).join("/") : "root"}`;
  return (
    <div className="metadata-node">
      <div className="metadata-node-tools">
        <label>
          <span className="visually-hidden">Metadata type {labelPath}</span>
          <select
            aria-label={`Metadata type ${labelPath}`}
            value={kind}
            disabled={disabled}
            onChange={(event) => onChange(defaultForKind(event.target.value as ReturnType<typeof metadataKind>))}
          >
            <option value="string">text</option>
            <option value="boolean">Boolean</option>
            <option value="integer">integer</option>
            <option value="float">decimal</option>
            <option value="list">list</option>
            <option value="table">table</option>
          </select>
        </label>
        {onRemove && <button type="button" className="quiet-button" aria-label={`Remove metadata ${labelPath}`} disabled={disabled} onClick={onRemove}>Remove</button>}
      </div>
      {kind === "string" && (
        <input aria-label={`Metadata value ${labelPath}`} value={value as string} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
      )}
      {(kind === "integer" || kind === "float") && (
        <input
          aria-label={`Metadata value ${labelPath}`}
          type="text"
          inputMode={kind === "integer" ? "numeric" : "decimal"}
          value={isMetadataNumber(value) ? value.text : String(value)}
          aria-invalid={numericError ? true : undefined}
          aria-describedby={numericError ? numericErrorId : undefined}
          disabled={disabled}
          onChange={(event) => onChange(metadataNumber(event.target.value, kind))}
        />
      )}
      {(kind === "integer" || kind === "float") && numericError && (
        <span id={numericErrorId} className="error field-validation-error">{numericError}</span>
      )}
      {kind === "boolean" && (
        <input aria-label={`Metadata value ${labelPath}`} type="checkbox" checked={value as boolean} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      )}
      {kind === "list" && (
        <div className="metadata-children">
          {(value as ProfileMetadataValue[]).map((child, index, array) => (
            <MetadataNode
              key={index}
              value={child}
              path={[...path, String(index)]}
              disabled={disabled}
              onChange={(next) => onChange(array.map((item, itemIndex) => itemIndex === index ? next : item))}
              onRemove={() => onChange(array.filter((_, itemIndex) => itemIndex !== index))}
            />
          ))}
          <button type="button" className="quiet-button" aria-label={`Add list item to ${labelPath}`} disabled={disabled} onClick={() => onChange([...(value as ProfileMetadataValue[]), ""])}>Add list item</button>
        </div>
      )}
      {kind === "table" && (
        <MetadataTable
          value={value as { [key: string]: ProfileMetadataValue }}
          path={path}
          onChange={onChange}
          disabled={disabled}
        />
      )}
    </div>
  );
}

function MetadataTable({
  value,
  path,
  onChange,
  disabled,
}: {
  value: { [key: string]: ProfileMetadataValue };
  path: string[];
  onChange: (value: { [key: string]: ProfileMetadataValue }) => void;
  disabled?: boolean;
}) {
  const entries = Object.entries(value);
  const uniqueKey = () => {
    let index = entries.length + 1;
    while (`field_${index}` in value) index += 1;
    return `field_${index}`;
  };
  return (
    <div className="metadata-children">
      {entries.map(([key, child]) => {
        const childPath = [...path, key];
        const childLabelPath = childPath.join(".");
        return (
          <div className="metadata-entry" key={key}>
            <input
              className="metadata-key"
              aria-label={`Metadata key ${childLabelPath}`}
              value={key}
              disabled={disabled}
              onChange={(event) => {
                const nextKey = event.target.value;
                if (!nextKey || (nextKey !== key && nextKey in value)) return;
                const next: { [key: string]: ProfileMetadataValue } = {};
                for (const [entryKey, entryValue] of entries) next[entryKey === key ? nextKey : entryKey] = entryValue;
                onChange(next);
              }}
            />
            <MetadataNode
              value={child}
              path={childPath}
              disabled={disabled}
              onChange={(next) => onChange({ ...value, [key]: next })}
              onRemove={() => onChange(Object.fromEntries(entries.filter(([entryKey]) => entryKey !== key)))}
            />
          </div>
        );
      })}
      <button type="button" className="quiet-button" aria-label={`Add metadata field to ${path.length > 0 ? path.join(".") : "root"}`} disabled={disabled} onClick={() => onChange({ ...value, [uniqueKey()]: "" })}>Add metadata field</button>
    </div>
  );
}

export default function ProfileForm({ value, onChange, sensitivity, idLocked = false, disabled = false }: ProfileFormProps) {
  const set = <K extends keyof LearnerProfile>(key: K, next: LearnerProfile[K]) => onChange({ ...value, [key]: next });
  const optional = (key: keyof LearnerProfile, text: string) => set(key, (text.trim() ? text : undefined) as never);
  const arrayField = (key: keyof LearnerProfile, text: string) => set(key, lines(text) as never);
  const preference = <K extends keyof LearnerProfile["learning_preferences"]>(key: K, next: LearnerProfile["learning_preferences"][K]) =>
    set("learning_preferences", { ...value.learning_preferences, [key]: next });
  const localization = <K extends keyof LearnerProfile["localization"]>(key: K, next: LearnerProfile["localization"][K]) =>
    set("localization", { ...value.localization, [key]: next });
  const privacy = <K extends keyof LearnerProfile["privacy"]>(key: K, next: LearnerProfile["privacy"][K]) =>
    set("privacy", { ...value.privacy, [key]: next });

  const input = (label: string, key: keyof LearnerProfile, path = String(key), required = false) => (
    <Field label={label} path={path} sensitivity={sensitivity}>
      {key === "id" ? (
        <input
          required={required}
          disabled={disabled || idLocked}
          value={(value[key] as string | undefined) ?? ""}
          onChange={(event) => set(key, event.target.value as never)}
        />
      ) : (
        <textarea
          rows={2}
          required={required}
          disabled={disabled}
          value={(value[key] as string | undefined) ?? ""}
          onChange={(event) =>
            key === "target_learner"
              ? set(key, singleLine(event.target.value) as never)
              : optional(key, singleLine(event.target.value))
          }
        />
      )}
    </Field>
  );
  const textarea = (label: string, key: keyof LearnerProfile, path = String(key)) => (
    <Field label={label} path={path} sensitivity={sensitivity}>
      <textarea rows={3} disabled={disabled} value={(value[key] as string[]).join("\n")} onChange={(event) => arrayField(key, event.target.value)} />
    </Field>
  );
  const preferenceInput = (label: string, key: keyof LearnerProfile["learning_preferences"]) => (
    <Field label={label} path={`learning_preferences.${String(key)}`} sensitivity={sensitivity}>
      <textarea
        rows={2}
        disabled={disabled}
        value={(value.learning_preferences[key] as string | undefined) ?? ""}
        onChange={(event) => {
          const text = singleLine(event.target.value);
          preference(key, (text.trim() ? text : undefined) as never);
        }}
      />
    </Field>
  );
  const preferenceArray = (label: string, key: keyof LearnerProfile["learning_preferences"]) => (
    <Field label={label} path={`learning_preferences.${String(key)}`} sensitivity={sensitivity}>
      <textarea rows={3} disabled={disabled} value={(value.learning_preferences[key] as string[]).join("\n")} onChange={(event) => preference(key, lines(event.target.value) as never)} />
    </Field>
  );
  const localizationInput = (label: string, key: keyof LearnerProfile["localization"]) => (
    <Field label={label} path={`localization.${String(key)}`} sensitivity={sensitivity}>
      <textarea
        rows={2}
        disabled={disabled}
        value={value.localization[key] ?? ""}
        onChange={(event) => {
          const text = singleLine(event.target.value);
          localization(key, (text.trim() ? text : undefined) as never);
        }}
      />
    </Field>
  );

  return (
    <div className="profile-form">
      <section><h3>Identity</h3><div className="profile-field-grid">
        <Field label="Schema version" path="schema_version" sensitivity={sensitivity}><input type="number" readOnly value={value.schema_version} /></Field>
        {input("Profile id", "id", "id", true)}{input("Target learner", "target_learner", "target_learner", true)}
      </div></section>
      <section><h3>Background</h3><div className="profile-field-grid">
        {input("Prior education", "prior_education")}{input("Prior experience", "prior_experience")}{input("Professional experience", "professional_experience")}{input("Current skill level", "current_skill_level")}{textarea("Adjacent domains", "adjacent_domains")}
      </div></section>
      <section><h3>Learning plan</h3><div className="profile-field-grid">
        {textarea("Learning goals", "learning_goals")}{textarea("Preferred examples", "preferred_examples")}{textarea("Examples to avoid", "examples_to_avoid")}{input("Math comfort", "math_comfort")}{input("Reading level", "reading_level")}{input("Pace", "pace")}{input("Desired depth", "desired_depth")}{input("Time budget", "time_budget")}{textarea("Assessment styles", "assessment_styles")}{textarea("Accessibility constraints", "accessibility_constraints")}{input("Tone preference", "tone_preference")}{textarea("Sensitive areas", "sensitive_areas")}
      </div></section>
      <section><h3>Learning preferences</h3><div className="profile-field-grid">
        {preferenceArray("Preferred modalities", "preferred_modalities")}{preferenceInput("Explanation style", "explanation_style")}{preferenceArray("Preferred visual aids", "preferred_visual_aids")}{preferenceInput("Diagram frequency", "diagram_frequency")}{preferenceInput("Interaction style", "interaction_style")}{preferenceArray("Practice style", "practice_style")}{preferenceInput("Feedback style", "feedback_style")}{preferenceInput("Worked example preference", "worked_example_preference")}{preferenceArray("Common sticking points", "common_sticking_points")}{preferenceArray("Attention constraints", "attention_constraints")}{preferenceArray("Review style", "review_style")}
      </div></section>
      <section><h3>Localization</h3><div className="profile-field-grid">{localizationInput("Jurisdiction", "jurisdiction")}{localizationInput("Locale", "locale")}{localizationInput("Units", "units")}{localizationInput("Language register", "language_register")}</div></section>
      <section><h3>Privacy and metadata</h3><div className="profile-field-grid">
        <Field label="Private by default" path="privacy.private_by_default" sensitivity={sensitivity}><input type="checkbox" disabled={disabled} checked={value.privacy.private_by_default} onChange={(event) => privacy("private_by_default", event.target.checked)} /></Field>
        <Field label="Include summary in published output" path="privacy.include_in_published_output" sensitivity={sensitivity}><input type="checkbox" disabled={disabled} checked={value.privacy.include_in_published_output} onChange={(event) => privacy("include_in_published_output", event.target.checked)} /></Field>
        <Field label="Publishable summary" path="privacy.publishable_summary" sensitivity={sensitivity}><textarea rows={4} disabled={disabled} value={value.privacy.publishable_summary ?? ""} onChange={(event) => privacy("publishable_summary", event.target.value.trim() ? event.target.value : undefined)} /></Field>
      </div>
        <div className="metadata-editor"><h4>Metadata <SensitivityBadge tier={sensitivity["metadata.*"]} />
<InfoTip label="Metadata" text={PROFILE_HELP["metadata.*"]} /></h4><p className="field-help">Tables and lists may be nested. Values retain their selected TOML-compatible type.</p><MetadataTable value={value.metadata} path={[]} disabled={disabled} onChange={(metadata) => set("metadata", metadata)} /></div>
      </section>
    </div>
  );
}
