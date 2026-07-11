import { useState } from "react";
import { Link } from "react-router-dom";
import { getProfiles, getTopics } from "../api/client";
import AttachProfileControl from "../components/AttachProfileControl";
import ImportForm from "../components/ImportForm";
import { usePolling } from "../hooks/usePolling";

export default function TopicListPage() {
  const { data, error, refresh } = usePolling(getTopics, 10_000);
  const { data: profileData } = usePolling(getProfiles, 30_000);
  const [importKind, setImportKind] = useState<"topic" | "profile" | null>(null);

  if (error) return <p className="error">Failed to load topics: {error.message}</p>;
  if (!data) return <p>Loading…</p>;

  const profiles = profileData?.profiles ?? [];

  return (
    <div>
      <p className="toolbar">
        <button onClick={() => setImportKind(importKind === "topic" ? null : "topic")}>
          Import topic…
        </button>{" "}
        <button onClick={() => setImportKind(importKind === "profile" ? null : "profile")}>
          Import profile…
        </button>
      </p>
      {importKind && (
        <ImportForm
          kind={importKind}
          onDone={() => {
            setImportKind(null);
            refresh();
          }}
        />
      )}
      {data.topics.length === 0 ? (
        <p>No topics yet. Import one above.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Topic</th>
              <th>Title</th>
              <th>Next action</th>
              <th>Finalized</th>
              <th>Profile</th>
            </tr>
          </thead>
          <tbody>
            {data.topics.map((t) => (
              <tr key={t.id}>
                <td>
                  <Link to={`/topics/${t.id}`}>{t.id}</Link>
                </td>
                <td>{t.error ? <span className="error">{t.error}</span> : (t.title ?? "—")}</td>
                <td>{t.run ? t.run.next_action.action : "no run"}</td>
                <td>{t.run?.finalized ? "yes" : "no"}</td>
                <td>
                  <AttachProfileControl topicId={t.id} profiles={profiles} onDone={refresh} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
