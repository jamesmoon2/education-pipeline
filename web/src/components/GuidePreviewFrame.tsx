import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { PersonalizationEvidence } from "../api/types";

export const GUIDE_PREVIEW_EVIDENCE_MESSAGE_TYPE =
  "education-pipeline:preview-evidence";

const GUIDE_ID_PATTERN = /^[a-z][a-z0-9-]{0,63}$/;

export interface GuidePreviewFrameHandle {
  revealEvidence(evidence: PersonalizationEvidence): boolean;
}

export function isGuidePreviewEvidence(value: PersonalizationEvidence): boolean {
  return (
    (value.kind === "module" || value.kind === "outcome") &&
    GUIDE_ID_PATTERN.test(value.id)
  );
}

const GuidePreviewFrame = forwardRef<GuidePreviewFrameHandle, { html: string }>(
  function GuidePreviewFrame({ html }, ref) {
    const frameRef = useRef<HTMLIFrameElement>(null);
    const readyRef = useRef(false);
    const generationRef = useRef(0);
    const pendingEvidenceRef = useRef<{
      generation: number;
      evidence: PersonalizationEvidence;
    } | null>(null);

    useLayoutEffect(() => {
      // A new srcDoc is a new opaque document with a new runtime listener.
      // Invalidate the prior generation's command even if an ID happens to be
      // valid in both documents, then wait for this runtime's load event.
      generationRef.current += 1;
      readyRef.current = false;
      pendingEvidenceRef.current = null;
    }, [html]);

    const postEvidence = (evidence: PersonalizationEvidence): boolean => {
      const contentWindow = frameRef.current?.contentWindow;
      if (!contentWindow) return false;
      contentWindow.postMessage(
        {
          type: GUIDE_PREVIEW_EVIDENCE_MESSAGE_TYPE,
          kind: evidence.kind,
          id: evidence.id,
        },
        // The sandboxed srcDoc has an opaque origin, so a narrower target
        // origin cannot address it. The runtime authenticates the sender by
        // requiring event.source === window.parent and validates the entire
        // three-field message before resolving any target.
        "*",
      );
      return true;
    };

    useImperativeHandle(ref, () => ({
      revealEvidence(evidence) {
        if (!isGuidePreviewEvidence(evidence)) return false;
        if (!readyRef.current || !frameRef.current?.contentWindow) {
          // A click means "show this target", so retaining the latest command
          // avoids both an unbounded queue and replaying superseded focus hops.
          pendingEvidenceRef.current = {
            generation: generationRef.current,
            evidence,
          };
          return true;
        }
        return postEvidence(evidence);
      },
    }), []);

    const handleLoad = () => {
      readyRef.current = true;
      const pending = pendingEvidenceRef.current;
      if (
        pending &&
        pending.generation === generationRef.current &&
        postEvidence(pending.evidence)
      ) pendingEvidenceRef.current = null;
    };

  return (
    <iframe
      key={html}
      ref={frameRef}
      onLoad={handleLoad}
      className="guide-preview-frame"
      title="Interactive guide preview"
      // Deliberately omit allow-same-origin. The opaque origin makes persisted
      // preview state unavailable; the runtime catches storage exceptions and
      // keeps only disposable in-memory state for this srcDoc instance.
      sandbox="allow-scripts"
      srcDoc={html}
    />
  );
  },
);

export default GuidePreviewFrame;
