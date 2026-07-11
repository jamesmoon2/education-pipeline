import { useState } from "react";
import { postResponse } from "../api/client";
import { useAction } from "../hooks/useAction";

export default function ResponseForm({
  topicId,
  stage,
  onDone,
}: {
  topicId: string;
  stage: string;
  onDone: () => void;
}) {
  const [text, setText] = useState("");
  const { busy, feedback, isError, run } = useAction(onDone);
  return (
    <div className="response-form">
      <label>
        Response for {stage}
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} />
      </label>
      <button
        disabled={busy || !text.trim()}
        onClick={() =>
          run(() => postResponse(topicId, stage, text), {
            retryWithOverwrite: () => postResponse(topicId, stage, text, true),
            successMessage: "Response saved.",
          })
        }
      >
        Save response
      </button>
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
