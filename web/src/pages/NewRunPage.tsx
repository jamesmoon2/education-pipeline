import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  attachProfile,
  createTopic,
  getConfigPlan,
  getProfiles,
  importTopic,
  postAdvance,
} from "../api/client";
import ErrorNotice from "../components/ErrorNotice";
import { usePolling } from "../hooks/usePolling";
import type { PlanPayload } from "../api/types";

type TopicMode = "describe" | "toml";

// Step order is deliberately structural (spec §6): a blueprint-selection
// step can slot in between "topic" and "plan" without reworking navigation.
const STEP_ORDER = ["learner", "topic", "plan", "confirm"] as const;
type Step = (typeof STEP_ORDER)[number];

export default function NewRunPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("learner");
  const [profileId, setProfileId] = useState("");
  const [mode, setMode] = useState<TopicMode>("describe");

  // "Describe it" fields
  const [id, setId] = useState("");
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [audience, setAudience] = useState("");
  const [goals, setGoals] = useState("");

  // "Paste TOML" field
  const [toml, setToml] = useState("");

  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [planError, setPlanError] = useState<unknown>(null);

  // Create-time progress markers so a failed step can be retried without
  // repeating the steps that already succeeded (topic create is not
  // idempotent -- re-POSTing it would 409 already_exists).
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [attached, setAttached] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);

  const { data: profileData } = usePolling(getProfiles, 30_000);
  const profiles = profileData?.profiles ?? [];

  useEffect(() => {
    let cancelled = false;
    getConfigPlan().then(
      (payload) => {
        if (!cancelled) setPlan(payload);
      },
      (err) => {
        if (!cancelled) setPlanError(err);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const goBack = () => {
    const index = STEP_ORDER.indexOf(step);
    if (index > 0) setStep(STEP_ORDER[index - 1]);
  };
  const goNext = () => {
    const index = STEP_ORDER.indexOf(step);
    if (index < STEP_ORDER.length - 1) setStep(STEP_ORDER[index + 1]);
  };

  const topicReady =
    mode === "describe" ? id.trim().length > 0 && title.trim().length > 0 : toml.trim().length > 0;

  const describeFields = () => {
    const parsedGoals = goals
      .split("\n")
      .map((g) => g.trim())
      .filter((g) => g.length > 0);
    const fields: { id: string; title: string; brief?: string; audience?: string; goals?: string[] } = {
      id: id.trim(),
      title: title.trim(),
    };
    if (brief.trim()) fields.brief = brief.trim();
    if (audience.trim()) fields.audience = audience.trim();
    if (parsedGoals.length > 0) fields.goals = parsedGoals;
    return fields;
  };

  const createCourse = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      let topicId = createdId;
      if (!topicId) {
        const created =
          mode === "describe" ? await createTopic(describeFields()) : await importTopic(toml);
        topicId = created.id;
        setCreatedId(topicId);
      }
      if (profileId && !attached) {
        await attachProfile(topicId, profileId);
        setAttached(true);
      }
      await postAdvance(topicId);
      navigate(`/topics/${topicId}`);
    } catch (err) {
      setCreateError(err);
    } finally {
      setCreating(false);
    }
  };

  const summaryTopicId = mode === "describe" ? id.trim() : (createdId ?? "(from TOML)");

  return (
    <div className="new-run-page">
      <h2>New course</h2>
      <ol className="wizard-steps" aria-label="Wizard steps">
        {STEP_ORDER.map((name) => (
          <li key={name} aria-current={step === name ? "step" : undefined}>
            {name}
          </li>
        ))}
      </ol>

      {step === "learner" && (
        <section aria-labelledby="new-run-learner-heading">
          <h3 id="new-run-learner-heading">Learner</h3>
          {profiles.length === 0 ? (
            <p>
              No profiles yet — you can continue without one, or{" "}
              <Link to="/profiles">create or import a profile in Profiles</Link> first.
            </p>
          ) : (
            <label>
              Learner profile
              <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
                <option value="">No profile (generic course)</option>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.id} ({profile.attached_topic_count}{" "}
                    {profile.attached_topic_count === 1 ? "topic" : "topics"})
                  </option>
                ))}
              </select>
            </label>
          )}
          <p>
            <button onClick={goNext}>Continue</button>
          </p>
        </section>
      )}

      {step === "topic" && (
        <section aria-labelledby="new-run-topic-heading">
          <h3 id="new-run-topic-heading">Topic and brief</h3>
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
            </div>
          ) : (
            <div>
              <label>
                Topic TOML
                <textarea value={toml} onChange={(e) => setToml(e.target.value)} rows={8} />
              </label>
            </div>
          )}
          <p>
            <button onClick={goBack}>Back</button>{" "}
            <button disabled={!topicReady} onClick={goNext}>
              Continue
            </button>
          </p>
        </section>
      )}

      {step === "plan" && (
        <section aria-labelledby="new-run-plan-heading">
          <h3 id="new-run-plan-heading">Model plan</h3>
          <p>
            The effective plan below applies to every new course.{" "}
            <Link to="/settings">Adjust in Settings</Link> if needed — per-run overrides stay
            available from the run board.
          </p>
          {planError ? (
            <ErrorNotice prefix="Failed to load the model plan" error={planError} />
          ) : !plan ? (
            <p>Loading plan…</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Effort</th>
                </tr>
              </thead>
              <tbody>
                {plan.stages.map((stage) => (
                  <tr key={stage.stage}>
                    <td>{stage.stage}</td>
                    <td>{stage.provider ?? plan.provider}</td>
                    <td>{stage.model ?? "—"}</td>
                    <td>{stage.effort ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p>
            <button onClick={goBack}>Back</button>{" "}
            <button onClick={goNext}>Continue</button>
          </p>
        </section>
      )}

      {step === "confirm" && (
        <section aria-labelledby="new-run-confirm-heading">
          <h3 id="new-run-confirm-heading">Confirm</h3>
          <dl>
            <dt>Learner</dt>
            <dd>{profileId || "No profile (generic course)"}</dd>
            <dt>Topic</dt>
            <dd>{mode === "describe" ? `${summaryTopicId} — ${title.trim()}` : summaryTopicId}</dd>
            <dt>Estimated stages</dt>
            <dd>
              {(plan?.stages.map((stage) => stage.stage) ?? [
                "spec",
                "outline",
                "draft",
                "qa",
                "repair",
              ]).join(" → ")}
              , then deterministic finalize and export
            </dd>
            <dt>Model plan</dt>
            <dd>
              {plan
                ? `${plan.provider} (adjust in Settings before creating if needed)`
                : "default plan"}
            </dd>
          </dl>
          {createError ? (
            <ErrorNotice prefix="Course creation failed" error={createError} />
          ) : null}
          <p>
            <button onClick={goBack} disabled={creating}>
              Back
            </button>{" "}
            <button onClick={() => void createCourse()} disabled={creating}>
              Create course
            </button>
          </p>
        </section>
      )}
    </div>
  );
}
