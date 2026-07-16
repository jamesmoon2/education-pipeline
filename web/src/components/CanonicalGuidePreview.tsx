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

export interface CanonicalGuidePreviewHandle {
  revealEvidence(evidence: PersonalizationEvidence): boolean;
}

const CanonicalGuidePreview = forwardRef<
  CanonicalGuidePreviewHandle,
  { topicId: string }
>(function CanonicalGuidePreview({ topicId }, ref) {
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
    let disposed = false;
    setPreview(null);
    setMissing(false);
    setError(null);
    setLoading(true);

    getStageContent(topicId, "repair")
      .then((stage) => {
        if (disposed) return null;
        // Finalization reads this exact approved repair artifact. Never use a
        // newer unapproved response: that would make the cockpit preview less
        // durable than the final/export source it is meant to represent.
        if (stage.approved === null) {
          setMissing(true);
          return null;
        }
        return postGuidePreview(stage.approved);
      })
      .then((result) => {
        if (!disposed && result) setPreview({ topicId, html: result.html });
      })
      .catch((caught: unknown) => {
        if (!disposed) {
          setError(caught instanceof Error ? caught.message : "Guide preview is unavailable.");
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });

    return () => {
      disposed = true;
    };
  }, [topicId]);

  return (
    <section className="canonical-guide-preview" aria-labelledby="canonical-guide-preview-heading">
      <h3 id="canonical-guide-preview-heading">Guide preview</h3>
      <p>Approved repair / final source</p>
      {loading && <p role="status">Loading guide preview…</p>}
      {missing && <p>No approved repair guide is available yet.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {html && <GuidePreviewFrame ref={frameRef} html={html} />}
    </section>
  );
});

export default CanonicalGuidePreview;
