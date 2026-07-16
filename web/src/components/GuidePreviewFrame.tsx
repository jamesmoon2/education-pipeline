export default function GuidePreviewFrame({ html }: { html: string }) {
  return (
    <iframe
      className="guide-preview-frame"
      title="Interactive guide preview"
      // Deliberately omit allow-same-origin. The opaque origin makes persisted
      // preview state unavailable; the runtime catches storage exceptions and
      // keeps only disposable in-memory state for this srcDoc instance.
      sandbox="allow-scripts"
      srcDoc={html}
    />
  );
}
