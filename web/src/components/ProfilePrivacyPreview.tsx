import { useEffect, useRef, useState } from "react";
import { hasInvalidMetadataNumber } from "../api/types";
import type { LearnerProfile, ProfilePreview } from "../api/types";
import { previewProfile } from "../api/client";

export default function ProfilePrivacyPreview({
  profile,
  debounceMs = 500,
  onPreview,
}: {
  profile: LearnerProfile;
  debounceMs?: number;
  onPreview?: (preview: ProfilePreview) => void;
}) {
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestNumber = useRef(0);

  useEffect(() => {
    const current = ++requestNumber.current;
    setPreview(null);
    setError(null);
    if (hasInvalidMetadataNumber(profile.metadata)) {
      setLoading(false);
      setError("Fix invalid metadata numbers to preview.");
      return;
    }
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      void Promise.resolve().then(() => previewProfile(profile)).then(
        (result) => {
          if (current !== requestNumber.current) return;
          setPreview(result);
          onPreview?.(result);
          setLoading(false);
        },
        (reason: unknown) => {
          if (current !== requestNumber.current) return;
          setPreview(null);
          setError(reason instanceof Error ? reason.message : "Preview failed.");
          setLoading(false);
        },
      );
    }, debounceMs);
    return () => window.clearTimeout(timer);
  }, [profile, debounceMs]);

  return (
    <aside className="privacy-preview" aria-labelledby="privacy-preview-heading" tabIndex={0}>
      <div className="privacy-preview-heading">
        <div>
          <p className="eyebrow">Server-rendered</p>
          <h2 id="privacy-preview-heading">Privacy preview</h2>
        </div>
        {loading && <span className="preview-status" role="status">Rendering privacy preview…</span>}
      </div>
      <p className="field-help">This is the exact private prompt context and publishable summary produced by the Python policy.</p>
      {error && <p className="error" role="alert">Preview unavailable: {error}</p>}
      {preview && (
        <>
          <section>
            <h3>Private prompt context</h3>
            <pre
              className="content profile-prompt-preview"
              role="region"
              aria-label="Private prompt context"
              tabIndex={0}
            >
              {preview.prompt_context}
            </pre>
          </section>
          <section>
            <h3>Published output</h3>
            {preview.publishable_summary ? <p className="publishable-summary">{preview.publishable_summary}</p> : <p className="muted">Not included in published output.</p>}
          </section>
          {preview.warnings.length > 0 && (
            <section className="profile-warning-list" aria-labelledby="profile-warnings-heading">
              <h3 id="profile-warnings-heading">Privacy warnings</h3>
              <ul>
                {preview.warnings.map((warning) => (
                  <li key={`${warning.code}:${warning.field_path}:${warning.fingerprint}`}>
                    <code>{warning.code}</code> at <code>{warning.field_path}</code> · fingerprint <code>{warning.fingerprint}</code>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </aside>
  );
}
