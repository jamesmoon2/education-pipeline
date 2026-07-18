import { Link } from "react-router-dom";
import { getProfiles } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import ErrorNotice from "../components/ErrorNotice";
import ProfileDraftPanel from "../components/ProfileDraftPanel";

export default function ProfilesPage() {
  const { data, error, refresh } = usePolling(getProfiles, 30_000);
  if (error) return <ErrorNotice prefix="Failed to load profiles" error={error} onRetry={refresh} />;
  if (!data) return <p>Loading profiles…</p>;
  return (
    <div className="profiles-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Personalization workspace</p>
          <h2>Learner profiles</h2>
          <p className="page-intro">Shape instruction locally while keeping publication boundaries visible.</p>
        </div>
        <Link className="primary-cta button-link" to="/profiles/new">New profile</Link>
      </div>
      {data.profiles.length === 0 ? (
        <div className="empty-state profile-empty-state">
          <h3>No learner profiles yet</h3>
          <p>Create a structured profile to tailor a course’s examples, depth, and practice.</p>
          <Link to="/profiles/new">Create a profile →</Link>
        </div>
      ) : (
        <ul className="profile-list">
          {data.profiles.map((profile) => (
            <li key={profile.id}>
              <Link to={`/profiles/${encodeURIComponent(profile.id)}`}>{profile.id}</Link>
              <span>{profile.attached_topic_count} attached {profile.attached_topic_count === 1 ? "topic" : "topics"}</span>
            </li>
          ))}
        </ul>
      )}
      <ProfileDraftPanel onCreated={refresh} />
    </div>
  );
}
