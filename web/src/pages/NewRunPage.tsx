import { useState } from "react";
import { Link } from "react-router-dom";
import {
  attachProfile,
  createTopic,
  getBlueprints,
  getProfiles,
  importTopic,
  postAdvance,
  getRunStatus,
} from "../api/client";
import type { BlueprintsPayload } from "../api/types";
import BlueprintPicker from "../components/BlueprintPicker";
import RunPlanPanel from "../components/RunPlanPanel";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

type TopicMode = "describe" | "toml";
type Step = "topic" | "blueprint" | "profile" | "plan";

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
  const [timeBudget, setTimeBudget] = useState("");

  // "Paste TOML" field
  const [toml, setToml] = useState("");

  // Blueprint step state
  const [blueprints, setBlueprints] = useState<BlueprintsPayload | null>(null);
  const [selectedBlueprint, setSelectedBlueprint] = useState("");

  const topicAction = useAction();
  const { data: profileData } = usePolling(getProfiles, 30_000);
  const profileAction = useAction();
  const advanceAction = useAction();

  const profiles = profileData?.profiles ?? [];

  // The blueprint the daemon would resolve on its own (topic field, else the
  // recommendation). The advance body carries the selection only when the
  // user overrides it, so an accepted recommendation keeps its
  // "recommended" provenance.
  const defaultBlueprintId =
    blueprints?.topic_blueprint ?? blueprints?.recommendation?.id ?? null;

  const enterPlanStep = async (topicId: string) => {
    // Wait for postAdvance (run init) to complete before rendering
    // RunPlanPanel, which fetches the run's plan — rendering it early would
    // race the run-init call against the daemon's "no run started" 404.
    const succeeded = await advanceAction.run(async () => {
      const override =
        selectedBlueprint && selectedBlueprint !== defaultBlueprintId
          ? { blueprint: selectedBlueprint }
          : undefined;
      await postAdvance(topicId, override);
      try {
        const status = await getRunStatus(topicId);
        setNextStage(status.next_action.stage);
      } catch {
        setNextStage(null);
      }
    });
    // Only advance the wizard when run init actually succeeded — otherwise
    // stay put so the error banner (rendered by the current step) is visible
    // instead of the wizard silently moving on to a run that never started.
    if (succeeded) {
      setStep("plan");
    }
  };

  const afterTopicCreated = async (createdTopicId: string) => {
    setCreatedId(createdTopicId);
    try {
      const payload = await getBlueprints(createdTopicId);
      setBlueprints(payload);
      setSelectedBlueprint(
        payload.topic_blueprint ??
          payload.recommendation?.id ??
          payload.blueprints[0]?.id ??
          "",
      );
      setStep("blueprint");
    } catch {
      // Blueprint selection is an enhancement; a failed registry fetch falls
      // back to the pre-blueprint flow (the daemon still records the
      // recommendation on its own).
      await continueAfterBlueprint(createdTopicId);
    }
  };

  const continueAfterBlueprint = async (topicId: string) => {
    if (profiles.length === 0) {
      await enterPlanStep(topicId);
    } else {
      setStep("profile");
    }
  };

  const submitDescribe = () => {
    const parsedGoals = goals
      .split("\n")
      .map((g) => g.trim())
      .filter((g) => g.length > 0);
    const fields: {
      id: string;
      title: string;
      brief?: string;
      audience?: string;
      goals?: string[];
      time_budget_minutes?: number;
    } = {
      id,
      title,
    };
    if (brief.trim()) fields.brief = brief.trim();
    if (audience.trim()) fields.audience = audience.trim();
    if (parsedGoals.length > 0) fields.goals = parsedGoals;
    if (timeBudget.trim()) fields.time_budget_minutes = Number(timeBudget.trim());
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

      {advanceAction.feedback && advanceAction.isError && (
        <p className="error">{advanceAction.feedback}</p>
      )}

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
              <label>
                Time budget (minutes, optional)
                <input
                  type="number"
                  min={5}
                  max={10000}
                  value={timeBudget}
                  onChange={(e) => setTimeBudget(e.target.value)}
                />
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

      {step === "blueprint" && createdId && blueprints && (
        <section aria-labelledby="new-run-blueprint-heading">
          <h3 id="new-run-blueprint-heading">Choose a blueprint</h3>
          <BlueprintPicker
            payload={blueprints}
            value={selectedBlueprint}
            onChange={setSelectedBlueprint}
          />
          <p>
            <button
              disabled={advanceAction.busy || !selectedBlueprint}
              onClick={() => void continueAfterBlueprint(createdId)}
            >
              Continue
            </button>
          </p>
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
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.id} ({profile.attached_topic_count} {profile.attached_topic_count === 1 ? "topic" : "topics"})
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
          <p className="blueprint-line">
            Blueprint: <strong>{selectedBlueprint || "(recommended default)"}</strong>
          </p>
          <RunPlanPanel topicId={createdId} nextStage={nextStage} />
          <p>
            <Link to={`/topics/${createdId}`}>Go to run board</Link>
          </p>
        </section>
      )}
    </div>
  );
}
