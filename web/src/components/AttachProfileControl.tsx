import { useState } from "react";
import { attachProfile } from "../api/client";
import { useAction } from "../hooks/useAction";

export default function AttachProfileControl({
  topicId,
  profiles,
  onDone,
}: {
  topicId: string;
  profiles: string[];
  onDone: () => void;
}) {
  const [profileId, setProfileId] = useState("");
  const { busy, feedback, isError, run } = useAction(onDone);
  if (profiles.length === 0) return null;
  return (
    <span className="attach-profile">
      <select
        aria-label={`Attach profile to ${topicId}`}
        value={profileId}
        onChange={(e) => setProfileId(e.target.value)}
      >
        <option value="">attach profile…</option>
        {profiles.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      <button
        disabled={busy || !profileId}
        onClick={() =>
          run(() => attachProfile(topicId, profileId), {
            successMessage: `Attached ${profileId}.`,
          })
        }
      >
        Attach
      </button>
      {feedback && <span className={isError ? "error" : "success"}> {feedback}</span>}
    </span>
  );
}
