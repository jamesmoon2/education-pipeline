import { Link } from "react-router-dom";
import { getTopics } from "../api/client";
import { usePolling } from "../hooks/usePolling";

export default function TopicListPage() {
  const { data, error } = usePolling(getTopics, 10_000);

  if (error) return <p className="error">Failed to load topics: {error.message}</p>;
  if (!data) return <p>Loading…</p>;
  if (data.topics.length === 0) {
    return (
      <p>
        No topics yet. Import one with <code>edu topic import &lt;file.toml&gt;</code>.
      </p>
    );
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Topic</th>
          <th>Title</th>
          <th>Next action</th>
          <th>Finalized</th>
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
          </tr>
        ))}
      </tbody>
    </table>
  );
}
