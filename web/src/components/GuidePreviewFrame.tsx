import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { PersonalizationEvidence } from "../api/types";

export const GUIDE_PREVIEW_EVIDENCE_MESSAGE_TYPE =
  "education-pipeline:preview-evidence";
const GUIDE_PREVIEW_POSITION_MESSAGE_TYPE = "education-pipeline:preview-position";
const GUIDE_PREVIEW_SHOW_MESSAGE_TYPE = "education-pipeline:preview-show";

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

/** The section a preview-position message reports, or null when it is not one. */
function readPreviewPosition(data: unknown): { id: string; initial: boolean } | null {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const message = data as Record<string, unknown>;
  if (Object.keys(message).sort().join(",") !== "id,initial,type") return null;
  if (message.type !== GUIDE_PREVIEW_POSITION_MESSAGE_TYPE) return null;
  if (typeof message.id !== "string" || !GUIDE_ID_PATTERN.test(message.id)) return null;
  if (typeof message.initial !== "boolean") return null;
  return { id: message.id, initial: message.initial };
}

export interface GuidePreviewFrameProps {
  html: string;
  /** Section to send a freshly booted document to, when it boots elsewhere. */
  restoreSection?: string | null;
  /** Each section the reviewer moves to inside the frame (never the boot one). */
  onSectionChange?: (id: string) => void;
}

const GuidePreviewFrame = forwardRef<GuidePreviewFrameHandle, GuidePreviewFrameProps>(
  function GuidePreviewFrame({ html, restoreSection, onSectionChange }, ref) {
    const frameRef = useRef<HTMLIFrameElement>(null);
    const bridgeRef = useRef({ restoreSection, onSectionChange });
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

    useLayoutEffect(() => {
      bridgeRef.current = { restoreSection, onSectionChange };
    }, [restoreSection, onSectionChange]);

    // A layout effect, so the listener is in place before the srcDoc runtime
    // can boot and report. The frame's opaque origin is always "null", so the
    // sender is identified by window identity alone; a replaced iframe (new
    // HTML) is a new contentWindow, which retires the old document's messages.
    useLayoutEffect(() => {
      const onMessage = (event: MessageEvent) => {
        const contentWindow = frameRef.current?.contentWindow;
        if (!contentWindow || event.source !== contentWindow) return;
        const position = readPreviewPosition(event.data);
        if (!position) return;
        const { restoreSection: restore, onSectionChange: report } = bridgeRef.current;
        if (!position.initial) {
          report?.(position.id);
          return;
        }
        // The runtime reports while it boots, which can precede this iframe's
        // load event, so the answer goes straight back to the same window.
        if (restore && restore !== position.id && GUIDE_ID_PATTERN.test(restore)) {
          contentWindow.postMessage({ type: GUIDE_PREVIEW_SHOW_MESSAGE_TYPE, id: restore }, "*");
        }
      };
      window.addEventListener("message", onMessage);
      return () => window.removeEventListener("message", onMessage);
    }, []);

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
