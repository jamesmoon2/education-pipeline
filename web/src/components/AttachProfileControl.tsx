import { useState } from "react";
import { attachProfile } from "../api/client";
import { useAction } from "../hooks/useAction";
import type { ProfileSummary } from "../api/types";

export default function AttachProfileControl({
  topicId,
  profiles,
  onDone,
}: {
  topicId: string;
  profiles: ProfileSummary[];
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
        {profiles.map((profile) => (
          <option key={profile.id} value={profile.id}>
            {profile.id} ({profile.attached_topic_count} {profile.attached_topic_count === 1 ? "topic" : "topics"})
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
