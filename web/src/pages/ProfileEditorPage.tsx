import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiRequestError, duplicateProfile, getProfile, putProfile } from "../api/client";
import { hasInvalidMetadataNumber } from "../api/types";
import type { LearnerProfile, ProfileDetail, ProfileSensitivity } from "../api/types";
import ProfileForm from "../components/ProfileForm";
import ProfilePrivacyPreview from "../components/ProfilePrivacyPreview";

const emptyProfile = (): LearnerProfile => ({
  schema_version: 1,
  id: "",
  target_learner: "",
  adjacent_domains: [],
  learning_goals: [],
  preferred_examples: [],
  examples_to_avoid: [],
  assessment_styles: [],
  accessibility_constraints: [],
  sensitive_areas: [],
  learning_preferences: {
    preferred_modalities: [],
    preferred_visual_aids: [],
    practice_style: [],
    common_sticking_points: [],
    attention_constraints: [],
    review_style: [],
  },
  localization: {},
  privacy: { private_by_default: true, include_in_published_output: false },
  metadata: {},
});

const declinedNavigationDrafts = new Map<string, LearnerProfile>();

export default function ProfileEditorPage() {
  const { profileId } = useParams();
  const isNew = !profileId;
  const navigate = useNavigate();
  const [profile, setProfile] = useState<LearnerProfile>(emptyProfile);
  const [savedProfile, setSavedProfile] = useState<LearnerProfile>(emptyProfile);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [sensitivity, setSensitivity] = useState<ProfileSensitivity>({});
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; type: "success" | "error" | "conflict" } | null>(null);
  const [stale, setStale] = useState(false);
  const [duplicateId, setDuplicateId] = useState("");
  const [duplicating, setDuplicating] = useState(false);
  const feedbackRef = useRef<HTMLParagraphElement>(null);

  const dirty = useMemo(() => JSON.stringify(profile) !== JSON.stringify(savedProfile), [profile, savedProfile]);
  const invalidMetadata = useMemo(() => hasInvalidMetadataNumber(profile.metadata), [profile.metadata]);
  const draftKey = profileId ?? "__new_profile__";
  const purgeRetainedDraft = () => declinedNavigationDrafts.delete(draftKey);
  // The navigation guard below only reads the draft at the moment a navigation
  // is declined, so it reads it from here. Depending on `profile` directly
  // would tear down and re-register its global listeners -- a capture-phase
  // document click handler among them -- on every keystroke.
  const profileRef = useRef(profile);
  profileRef.current = profile;

  const load = async () => {
    const retainedDraft = declinedNavigationDrafts.get(draftKey);
    if (!profileId) {
      if (retainedDraft) {
        setProfile(retainedDraft);
        declinedNavigationDrafts.delete(draftKey);
      }
      return;
    }
    if (retainedDraft) setProfile(retainedDraft);
    setLoading(true);
    setFeedback(null);
    try {
      const next = await getProfile(profileId);
      setDetail(next);
      setProfile(retainedDraft ?? next.parsed);
      setSavedProfile(next.parsed);
      setSensitivity(next.sensitivity);
      setStale(false);
      if (retainedDraft) declinedNavigationDrafts.delete(draftKey);
    } catch (reason) {
      setFeedback({ message: reason instanceof Error ? reason.message : "Failed to load profile.", type: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [profileId]);

  useEffect(() => {
    if (!dirty) return;
    const expectedPath = profileId ? `/profiles/${encodeURIComponent(profileId)}` : "/profiles/new";
    const controlsBrowserHistory = window.location.pathname === expectedPath;
    const expectedHistoryState = window.history.state;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const protectLinks = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest("a");
      if (anchor) {
        if (!window.confirm("Discard unsaved profile changes?")) {
          event.preventDefault();
          event.stopPropagation();
        } else {
          purgeRetainedDraft();
        }
      }
    };
    const protectHistory = () => {
      if (!window.confirm("Discard unsaved profile changes?")) {
        if (controlsBrowserHistory) {
          declinedNavigationDrafts.set(draftKey, profileRef.current);
          window.history.pushState(expectedHistoryState, "", expectedPath);
          window.setTimeout(() => window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state })), 0);
        } else {
          window.history.go(1);
        }
      } else {
        purgeRetainedDraft();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", protectLinks, true);
    window.addEventListener("popstate", protectHistory);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", protectLinks, true);
      window.removeEventListener("popstate", protectHistory);
    };
  }, [dirty, draftKey, profileId]);

  useEffect(() => {
    if (feedback?.type === "error" || feedback?.type === "conflict") feedbackRef.current?.focus();
  }, [feedback]);

  const save = async () => {
    if (invalidMetadata) return;
    setSaving(true);
    setFeedback(null);
    setStale(false);
    try {
      const saved = await putProfile(profile.id, profile, isNew ? null : detail?.content_sha256 ?? null);
      setDetail(saved);
      setProfile(saved.parsed);
      setSavedProfile(saved.parsed);
      setSensitivity(saved.sensitivity);
      declinedNavigationDrafts.delete(draftKey);
      setFeedback({ message: isNew ? "Profile created." : "Changes saved.", type: "success" });
      if (isNew) navigate(`/profiles/${encodeURIComponent(saved.id)}`, { replace: true });
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.status === 409) {
        setStale(true);
        setFeedback({ message: "This profile changed on disk. Your unsaved input is still here; reload the current profile only when you are ready to replace it.", type: "conflict" });
      } else {
        setFeedback({ message: reason instanceof Error ? reason.message : "Profile save failed.", type: "error" });
      }
    } finally {
      setSaving(false);
    }
  };

  const duplicate = async () => {
    if (!profileId || !duplicateId.trim()) return;
    if (dirty) {
      if (!window.confirm("Discard unsaved profile changes?")) return;
      purgeRetainedDraft();
    }
    setDuplicating(true);
    setFeedback(null);
    try {
      const copied = await duplicateProfile(profileId, duplicateId.trim());
      navigate(`/profiles/${encodeURIComponent(copied.id)}`);
    } catch (reason) {
      setFeedback({ message: reason instanceof Error ? reason.message : "Profile duplication failed.", type: "error" });
    } finally {
      setDuplicating(false);
    }
  };

  if (loading) return <p>Loading profile…</p>;

  return (
    <div className="profile-editor-page">
      <div className="profile-editor-topline">
        <div>
          <Link to="/profiles" className="back-link">← Profiles</Link>
          <p className="eyebrow">{isNew ? "New learner context" : `${detail?.attached_topic_count ?? 0} attached topics`}</p>
          <h2>{isNew ? "Create learner profile" : profile.id}</h2>
        </div>
        <div className="editor-save-status">
          {dirty && <span className="dirty-indicator">Unsaved changes</span>}
          <button className="primary-button" disabled={saving || invalidMetadata || !profile.id.trim() || !profile.target_learner.trim()} onClick={() => void save()}>
            {saving ? "Saving…" : isNew ? "Create profile" : "Save changes"}
          </button>
        </div>
      </div>
      {feedback && <p id="profile-action-feedback" ref={feedbackRef} tabIndex={feedback.type === "success" ? undefined : -1} role={feedback.type === "success" ? "status" : "alert"} className={feedback.type === "success" ? "success action-feedback" : "error action-feedback"}>{feedback.message}</p>}
      {stale && <button type="button" aria-describedby="profile-action-feedback" onClick={() => void load()}>Reload current profile</button>}
      <div className="profile-workspace">
        <div className="profile-form-column">
          <ProfileForm value={profile} onChange={setProfile} sensitivity={sensitivity} idLocked={!isNew} disabled={saving} />
          {!isNew && (
            <section className="duplicate-panel" aria-labelledby="duplicate-profile-heading">
              <h3 id="duplicate-profile-heading">Duplicate profile</h3>
              <p className="field-help">Create a canonical copy with a new profile id.</p>
              <label>Duplicate as<input value={duplicateId} onChange={(event) => setDuplicateId(event.target.value)} /></label>
              <button disabled={duplicating || !duplicateId.trim()} onClick={() => void duplicate()}>{duplicating ? "Duplicating…" : "Duplicate profile"}</button>
            </section>
          )}
        </div>
        <ProfilePrivacyPreview profile={profile} onPreview={(preview) => setSensitivity(preview.sensitivity)} />
      </div>
    </div>
  );
}
