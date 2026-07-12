import { useState } from "react";
import { Link } from "react-router-dom";
import {
  attachProfile,
  createTopic,
  getProfiles,
  importTopic,
  postAdvance,
  getRunStatus,
} from "../api/client";
import RunPlanPanel from "../components/RunPlanPanel";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

type TopicMode = "describe" | "toml";
type Step = "topic" | "profile" | "plan";

export default function NewRunPage() {
  const [mode, setMode] = useState<TopicMode>("describe");
  const [step, setStep] = useState<Step>("topic");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [nextStage, setNextStage] = useState<string | null>(null);

  // "Describe it" fields
  const [id, setId] = useState("");
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [audience, setAudience] = useState("");
  const [goals, setGoals] = useState("");

  // "Paste TOML" field
  const [toml, setToml] = useState("");

  const topicAction = useAction();
  const { data: profileData } = usePolling(getProfiles, 30_000);
  const profileAction = useAction();
  const advanceAction = useAction();

  const profiles = profileData?.profiles ?? [];

  const enterPlanStep = async (topicId: string) => {
    // Wait for postAdvance (run init) to complete before rendering
    // RunPlanPanel, which fetches the run's plan — rendering it early would
    // race the run-init call against the daemon's "no run started" 404.
    await advanceAction.run(async () => {
      await postAdvance(topicId);
      try {
        const status = await getRunStatus(topicId);
        setNextStage(status.next_action.stage);
      } catch {
        setNextStage(null);
      }
    });
    setStep("plan");
  };

  const afterTopicCreated = async (createdTopicId: string) => {
    setCreatedId(createdTopicId);
    if (profiles.length === 0) {
      await enterPlanStep(createdTopicId);
    } else {
      setStep("profile");
    }
  };

  const submitDescribe = () => {
    const parsedGoals = goals
      .split("\n")
      .map((g) => g.trim())
      .filter((g) => g.length > 0);
    const fields: { id: string; title: string; brief?: string; audience?: string; goals?: string[] } = {
      id,
      title,
    };
    if (brief.trim()) fields.brief = brief.trim();
    if (audience.trim()) fields.audience = audience.trim();
    if (parsedGoals.length > 0) fields.goals = parsedGoals;
    void topicAction.run(
      async () => {
        const result = await createTopic(fields);
        await afterTopicCreated(result.id);
      },
      { successMessage: "Topic created." },
    );
  };

  const submitToml = () => {
    void topicAction.run(
      async () => {
        const result = await importTopic(toml);
        await afterTopicCreated(result.id);
      },
      { successMessage: "Topic imported." },
    );
  };

  const [profileId, setProfileId] = useState("");

  const attachAndContinue = () => {
    if (!createdId) return;
    void profileAction.run(
      async () => {
        await attachProfile(createdId, profileId);
        await enterPlanStep(createdId);
      },
      { successMessage: "Profile attached." },
    );
  };

  const skipProfile = () => {
    if (!createdId) return;
    void enterPlanStep(createdId);
  };

  return (
    <div className="new-run-page">
      <h2>Create your first course</h2>

      {step === "topic" && (
        <section aria-labelledby="new-run-topic-heading">
          <h3 id="new-run-topic-heading">Topic</h3>
          <p role="radiogroup" aria-label="Topic entry mode">
            <label>
              <input
                type="radio"
                name="topic-mode"
                checked={mode === "describe"}
                onChange={() => setMode("describe")}
              />
              Describe it
            </label>{" "}
            <label>
              <input
                type="radio"
                name="topic-mode"
                checked={mode === "toml"}
                onChange={() => setMode("toml")}
              />
              Paste TOML
            </label>
          </p>

          {mode === "describe" ? (
            <div>
              <label>
                Topic id
                <input value={id} onChange={(e) => setId(e.target.value)} />
              </label>
              <label>
                Title
                <input value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <label>
                Brief
                <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={3} />
              </label>
              <label>
                Audience
                <input value={audience} onChange={(e) => setAudience(e.target.value)} />
              </label>
              <label>
                Goals (one per line)
                <textarea value={goals} onChange={(e) => setGoals(e.target.value)} rows={4} />
              </label>
              <button
                disabled={topicAction.busy || !id.trim() || !title.trim()}
                onClick={submitDescribe}
              >
                Create topic
              </button>
            </div>
          ) : (
            <div>
              <label>
                Topic TOML
                <textarea value={toml} onChange={(e) => setToml(e.target.value)} rows={8} />
              </label>
              <button disabled={topicAction.busy || !toml.trim()} onClick={submitToml}>
                Import topic
              </button>
            </div>
          )}
          {topicAction.feedback && (
            <p className={topicAction.isError ? "error" : "success"}>{topicAction.feedback}</p>
          )}
        </section>
      )}

      {step === "profile" && createdId && (
        <section aria-labelledby="new-run-profile-heading">
          <h3 id="new-run-profile-heading">Attach a profile (optional)</h3>
          {profiles.length === 0 ? (
            <p>No profiles available.</p>
          ) : (
            <label>
              Profile
              <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
                <option value="">select a profile…</option>
                {profiles.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          )}
          <p>
            <button
              disabled={profileAction.busy || !profileId}
              onClick={attachAndContinue}
            >
              Attach
            </button>{" "}
            <button disabled={profileAction.busy} onClick={skipProfile}>
              Skip
            </button>
          </p>
          {profileAction.feedback && (
            <p className={profileAction.isError ? "error" : "success"}>{profileAction.feedback}</p>
          )}
        </section>
      )}

      {step === "plan" && createdId && (
        <section aria-labelledby="new-run-plan-heading">
          <h3 id="new-run-plan-heading">Review the model plan</h3>
          {advanceAction.feedback && advanceAction.isError && (
            <p className="error">{advanceAction.feedback}</p>
          )}
          <RunPlanPanel topicId={createdId} nextStage={nextStage} />
          <p>
            <Link to={`/topics/${createdId}`}>Go to run board</Link>
          </p>
        </section>
      )}
    </div>
  );
}
