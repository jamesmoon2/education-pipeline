import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { getStageContent, postGuidePreview } from "../api/client";
import type { PersonalizationEvidence } from "../api/types";
import GuidePreviewFrame, {
  isGuidePreviewEvidence,
  type GuidePreviewFrameHandle,
} from "./GuidePreviewFrame";
import InfoTip from "./InfoTip";

export interface CanonicalGuidePreviewHandle {
  revealEvidence(evidence: PersonalizationEvidence): boolean;
}

export interface CanonicalGuidePreviewProps {
  topicId: string;
  /** Bumped after a mutation: refetch in place, without remounting the frame. */
  refreshGeneration?: number;
  restoreSection?: string | null;
  onSectionChange?: (id: string) => void;
}

const CanonicalGuidePreview = forwardRef<
  CanonicalGuidePreviewHandle,
  CanonicalGuidePreviewProps
>(function CanonicalGuidePreview(
  { topicId, refreshGeneration = 0, restoreSection, onSectionChange },
  ref,
) {
  const frameRef = useRef<GuidePreviewFrameHandle>(null);
  const generationRef = useRef(0);
  const pendingEvidenceRef = useRef<{
    generation: number;
    topicId: string;
    evidence: PersonalizationEvidence;
  } | null>(null);
  const [preview, setPreview] = useState<{ topicId: string; html: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useImperativeHandle(ref, () => ({
    revealEvidence(evidence) {
      if (!isGuidePreviewEvidence(evidence)) return false;
      if (frameRef.current) return frameRef.current.revealEvidence(evidence);
      pendingEvidenceRef.current = {
        generation: generationRef.current,
        topicId,
        evidence,
      };
      return true;
    },
  }), [topicId]);

  const html = preview?.topicId === topicId ? preview.html : "";

  useLayoutEffect(() => {
    // Topic identity can cycle A -> B -> A. A monotonic generation prevents a
    // command from the first A document from becoming eligible in the second.
    generationRef.current += 1;
    pendingEvidenceRef.current = null;
  }, [topicId]);

  useEffect(() => {
    const pending = pendingEvidenceRef.current;
    if (
      !html ||
      !pending ||
      pending.generation !== generationRef.current ||
      pending.topicId !== topicId ||
      !frameRef.current?.revealEvidence(pending.evidence)
    ) return;
    pendingEvidenceRef.current = null;
  }, [html, topicId]);

  useEffect(() => {
    setPreview(null);
    setMissing(false);
    setError(null);
    setLoading(true);
  }, [topicId]);

  useEffect(() => {
    // A refresh keeps the current document on screen: the frame is keyed by
    // its HTML, so it reloads only when the rendered guide actually changes.
    let disposed = false;

    getStageContent(topicId, "repair")
      .then((stage) => {
        if (disposed) return null;
        // Finalization reads this exact approved repair artifact. Never use a
        // newer unapproved response: that would make the cockpit preview less
        // durable than the final/export source it is meant to represent.
        if (stage.approved === null) {
          setPreview(null);
          setMissing(true);
          setError(null);
          return null;
        }
        return postGuidePreview(stage.approved);
      })
      .then((result) => {
        if (disposed || !result) return;
        setMissing(false);
        setError(null);
        setPreview((current) =>
          current?.topicId === topicId && current.html === result.html
            ? current
            : { topicId, html: result.html },
        );
      })
      .catch((caught: unknown) => {
        if (!disposed) {
          setPreview(null);
          setMissing(false);
          setError(caught instanceof Error ? caught.message : "Guide preview is unavailable.");
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });

    return () => {
      disposed = true;
    };
  }, [topicId, refreshGeneration]);

  return (
    <section className="canonical-guide-preview" aria-labelledby="canonical-guide-preview-heading">
      <h3 id="canonical-guide-preview-heading">Guide preview</h3>
      <InfoTip
        label="Canonical guide"
        text="The cleaned-up, validated version of the draft that finalize will publish."
      />
      <p>Approved repair / final source</p>
      {loading && <p role="status">Loading guide preview…</p>}
      {missing && <p>No approved repair guide is available yet.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {html && (
        <GuidePreviewFrame
          ref={frameRef}
          html={html}
          restoreSection={restoreSection}
          onSectionChange={onSectionChange}
        />
      )}
    </section>
  );
});

export default CanonicalGuidePreview;
