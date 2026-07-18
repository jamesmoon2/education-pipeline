import { useEffect, useId, useState } from "react";
import { draftProfile, getConfigCatalog, getConfigProviders, importProfile } from "../api/client";
import type { CatalogProvider, ProviderAvailability } from "../api/types";
import InfoTip from "./InfoTip";

/**
 * Free-text alternative to the structured profile form: describe the learner
 * in plain language, let a configured provider CLI draft the profile TOML,
 * review/edit it, then import it as a normal profile. The model's output is
 * never saved without the explicit "Create profile" step.
 */
export default function ProfileDraftPanel({
  onCreated,
}: {
  onCreated?: (id: string) => void;
}) {
  const describeId = useId();
  const providerId = useId();
  const modelId = useId();
  const tomlId = useId();
  const [providers, setProviders] = useState<ProviderAvailability[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogProvider[] | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [description, setDescription] = useState("");
  const [toml, setToml] = useState<string | null>(null);
  const [draftedId, setDraftedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([getConfigProviders(), getConfigCatalog()])
      .then(([providersResp, catalogResp]) => {
        if (cancelled) return;
        setProviders(providersResp.providers);
        setCatalog(catalogResp.providers);
        const usable = providersResp.providers.find(
          (item) => item.executable && item.available,
        );
        if (usable) setProvider((current) => current || usable.id);
      })
      .catch((err) => {
        if (cancelled) return;
        setIsError(true);
        setFeedback(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const executable = (providers ?? []).filter((item) => item.executable);
  const usable = executable.filter((item) => item.available);
  const models = catalog?.find((item) => item.id === provider)?.models ?? [];

  const handleDraft = async () => {
    setBusy(true);
    setFeedback(null);
    setIsError(false);
    try {
      const result = await draftProfile(description, {
        provider: provider || undefined,
        model: model || undefined,
      });
      setToml(result.toml);
      setDraftedId(result.profile_id);
      setFeedback(`Drafted "${result.profile_id}" — review the TOML below, then create the profile.`);
    } catch (err) {
      setIsError(true);
      setFeedback(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async () => {
    if (!toml) return;
    setBusy(true);
    setFeedback(null);
    setIsError(false);
    try {
      const result = await importProfile(toml);
      setFeedback(`Profile "${result.id}" created.`);
      setToml(null);
      setDraftedId(null);
      setDescription("");
      onCreated?.(result.id);
    } catch (err) {
      setIsError(true);
      setFeedback(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="profile-draft-panel" aria-labelledby="profile-draft-heading">
      <h3 id="profile-draft-heading">Draft a profile from a description</h3>
      <InfoTip
        label="Draft a profile"
        text="Describe the learner in your own words; a configured provider CLI turns it into profile TOML. Nothing is saved until you review the TOML and create the profile — the structured form remains available for hand-built profiles."
      />
      <p className="field-help">
        Prefer free text over form fields? Describe the learner — background,
        goals, preferences, constraints — and let a provider draft the
        structured profile for your review.
      </p>
      {providers && usable.length === 0 ? (
        <p className="warning">
          No provider CLI is available on this machine, so drafting is
          disabled. Install Claude Code or Codex (see Settings), or use the
          structured form via “New profile”.
        </p>
      ) : null}
      <label htmlFor={describeId}>Learner description</label>
      <textarea
        id={describeId}
        rows={6}
        value={description}
        disabled={busy}
        onChange={(event) => setDescription(event.target.value)}
      />
      <div className="profile-draft-controls">
        <span className="profile-draft-field">
          <label htmlFor={providerId}>Provider</label>
          <select
            id={providerId}
            value={provider}
            disabled={busy}
            onChange={(event) => {
              setProvider(event.target.value);
              setModel("");
            }}
          >
            {executable.map((item) => (
              <option key={item.id} value={item.id} disabled={!item.available}>
                {item.id}
                {item.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
        </span>
        <span className="profile-draft-field">
          <label htmlFor={modelId}>Model</label>
          <select
            id={modelId}
            value={model}
            disabled={busy}
            onChange={(event) => setModel(event.target.value)}
          >
            <option value="">(provider default)</option>
            {models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </span>
        <button
          type="button"
          className="primary-button"
          disabled={busy || !description.trim() || usable.length === 0}
          onClick={() => void handleDraft()}
        >
          {busy && toml === null ? "Drafting…" : "Draft profile TOML"}
        </button>
      </div>
      {busy && toml === null && (
        <p role="status">
          Running the provider — this can take a minute or two.
        </p>
      )}
      {toml !== null && (
        <div className="profile-draft-review">
          <label htmlFor={tomlId}>
            Drafted TOML{draftedId ? ` (${draftedId})` : ""} — review and edit before creating
          </label>
          <textarea
            id={tomlId}
            rows={16}
            className="technical"
            value={toml}
            disabled={busy}
            onChange={(event) => setToml(event.target.value)}
          />
          <button type="button" className="primary-button" disabled={busy} onClick={() => void handleCreate()}>
            Create profile
          </button>
        </div>
      )}
      {feedback && (
        <p role={isError ? "alert" : "status"} className={isError ? "error" : "success"}>
          {feedback}
        </p>
      )}
    </section>
  );
}
