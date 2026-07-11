import { useState } from "react";
import { importProfile, importTopic } from "../api/client";
import { useAction } from "../hooks/useAction";

export default function ImportForm({
  kind,
  onDone,
}: {
  kind: "topic" | "profile";
  onDone: () => void;
}) {
  const [toml, setToml] = useState("");
  const { busy, feedback, isError, run } = useAction(onDone);
  const doImport = kind === "topic" ? importTopic : importProfile;
  return (
    <div className="import-form">
      <label>
        {kind} TOML
        <textarea value={toml} onChange={(e) => setToml(e.target.value)} rows={8} />
      </label>
      <button
        disabled={busy || !toml.trim()}
        onClick={() =>
          run(() => doImport(toml), {
            retryWithOverwrite: () => doImport(toml, true),
            successMessage: `Imported ${kind}.`,
          })
        }
      >
        Import
      </button>
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
