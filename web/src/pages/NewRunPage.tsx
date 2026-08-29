import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  attachProfile,
  createTopic,
  getConfigPlan,
  getProfiles,
  importTopic,
  postAdvance,
  recommendBlueprints,
} from "../api/client";
import BlueprintPicker from "../components/BlueprintPicker";
import ErrorNotice from "../components/ErrorNotice";
import InfoTip from "../components/InfoTip";
import { NEW_RUN_HELP, TOPIC_ID_PATTERN } from "../lib/newRunHelp";
import {
  clearNewRunDraft,
  loadNewRunDraft,
  saveNewRunDraft,
} from "../lib/newRunDraft";
import { usePolling } from "../hooks/usePolling";
import type { BlueprintsPayload, PlanPayload } from "../api/types";

type TopicMode = "describe" | "toml";

// Step order is deliberately structural (spec §6); the blueprint-selection
// step slots in between "topic" and "plan" exactly as anticipated.
const STEP_ORDER = ["learner", "topic", "blueprint", "plan", "confirm"] as const;
type Step = (typeof STEP_ORDER)[number];

// Learner-language step labels (design system §3.4); the keys stay the
// structural step ids.
const STEP_LABELS: Record<Step, string> = {
  learner: "Learner",
  topic: "Topic",
  blueprint: "Blueprint",
  plan: "Model plan",
  confirm: "Review",
};

export default function NewRunPage() {
  const navigate = useNavigate();
  // Draft saved by a previous visit, loaded once per mount: the wizard links
  // out mid-flow (Profiles, Settings), and navigating there unmounts this
  // page — without the draft everything typed would be lost.
  const [initialDraft] = useState(loadNewRunDraft);
  const [restoredNoteVisible, setRestoredNoteVisible] = useState(initialDraft !== null);
  const [step, setStep] = useState<Step>(initialDraft?.step ?? "learner");
  const [profileId, setProfileId] = useState(initialDraft?.profileId ?? "");
  const [mode, setMode] = useState<TopicMode>(initialDraft?.mode ?? "describe");

  // "Describe it" fields
  const [id, setId] = useState(initialDraft?.id ?? "");
  const [title, setTitle] = useState(initialDraft?.title ?? "");
  const [brief, setBrief] = useState(initialDraft?.brief ?? "");
  const [audience, setAudience] = useState(initialDraft?.audience ?? "");
  const [goals, setGoals] = useState(initialDraft?.goals ?? "");

  // "Paste TOML" field
  const [toml, setToml] = useState(initialDraft?.toml ?? "");

  // Explicit label/input association for fields whose labels also carry an
  // InfoTip. The tip's trigger is a labelable <button>; without htmlFor the
  // wrapping label would associate with the button instead of the input.
  const topicIdInputId = useId();
  const briefInputId = useId();
  const audienceInputId = useId();
  const goalsInputId = useId();
  const timeBudgetInputId = useId();
  const tomlInputId = useId();

  // Blueprint step state: the registry + recommendation for the in-progress
  // topic, and the user's (possibly overridden) selection.
  const [blueprints, setBlueprints] = useState<BlueprintsPayload | null>(null);
  const [blueprintsError, setBlueprintsError] = useState<unknown>(null);
  const [selectedBlueprint, setSelectedBlueprint] = useState(
    initialDraft?.selectedBlueprint ?? "",
  );
  const [timeBudget, setTimeBudget] = useState(initialDraft?.timeBudget ?? "");

  // A draft restored at or past the blueprint step re-fetches blueprints on
  // mount (effect below). Until that settles the restored selection cannot be
  // told apart from a user override, so course creation waits on this flag.
  const [restoringBlueprints, setRestoringBlueprints] = useState(
    () =>
      initialDraft !== null &&
      STEP_ORDER.indexOf(initialDraft.step) >= STEP_ORDER.indexOf("blueprint"),
  );

  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [planError, setPlanError] = useState<unknown>(null);

  // Create-time progress markers so a failed step can be retried without
  // repeating the steps that already succeeded (topic create is not
  // idempotent -- re-POSTing it would 409 already_exists).
  const [createdId, setCreatedId] = useState<string | null>(initialDraft?.createdId ?? null);
  const [attached, setAttached] = useState(initialDraft?.attached ?? false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);

  // Mirror the wizard into sessionStorage so mid-flow navigation can restore
  // it. A pristine wizard stores nothing — a fresh visit leaves storage
  // untouched, and a hand-reverted wizard cleans up after itself.
  const pristine =
    step === "learner" &&
    mode === "describe" &&
    !profileId && !id && !title && !brief && !audience && !goals && !toml &&
    !selectedBlueprint && !timeBudget && createdId === null && !attached;
  useEffect(() => {
    if (pristine) {
      clearNewRunDraft();
      return;
    }
    saveNewRunDraft({
      step, profileId, mode, id, title, brief, audience, goals, toml,
      selectedBlueprint, timeBudget, createdId, attached,
    });
  }, [step, profileId, mode, id, title, brief, audience, goals, toml,
    selectedBlueprint, timeBudget, createdId, attached, pristine]);

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

  // The blueprint the daemon would resolve on its own (the topic's own
  // field, else the recommendation). The advance body carries the selection
  // only when the user overrides it, so an accepted recommendation keeps
  // its "recommended" provenance in the run manifest.
  const defaultBlueprintId =
    blueprints?.topic_blueprint ?? blueprints?.recommendation?.id ?? null;
  const blueprintOverride =
    selectedBlueprint && selectedBlueprint !== defaultBlueprintId
      ? selectedBlueprint
      : undefined;

  // Request generation for blueprint fetches: only the request that is still
  // the newest may apply its results, so a stale response (from before Start
  // over or a re-entered blueprint step) cannot clobber newer state.
  const blueprintsGeneration = useRef(0);

  const loadBlueprints = async (preferredSelection?: string) => {
    const generation = ++blueprintsGeneration.current;
    setBlueprintsError(null);
    try {
      const payload = await recommendBlueprints(
        mode === "describe" ? describeFields() : { toml },
      );
      if (generation !== blueprintsGeneration.current) return;
      setBlueprints(payload);
      setSelectedBlueprint(
        preferredSelection &&
          payload.blueprints.some((blueprint) => blueprint.id === preferredSelection)
          ? preferredSelection
          : payload.topic_blueprint ??
              payload.recommendation?.id ??
              payload.blueprints[0]?.id ??
              "",
      );
    } catch (err) {
      if (generation !== blueprintsGeneration.current) return;
      // Selection is an enhancement: with the registry unavailable the
      // wizard still proceeds and the daemon records its own recommendation.
      setBlueprints(null);
      setSelectedBlueprint("");
      setBlueprintsError(err);
    }
  };

  const enterBlueprintStep = async () => {
    await loadBlueprints();
    goNext();
  };

  // The blueprints payload is fetched on step entry and deliberately not
  // persisted, so a draft restored at or past the blueprint step re-fetches
  // it here (failure falls back exactly like normal step entry). Mount-only:
  // the deliberately empty deps pin the restored draft's field values.
  useEffect(() => {
    if (!initialDraft) return;
    if (STEP_ORDER.indexOf(initialDraft.step) < STEP_ORDER.indexOf("blueprint")) return;
    // loadBlueprints never rejects, so finally is simply "settled either way".
    void loadBlueprints(initialDraft.selectedBlueprint || undefined).finally(() => {
      setRestoringBlueprints(false);
    });
  }, []);

  const startOver = () => {
    clearNewRunDraft();
    // Invalidate any in-flight blueprint fetch so a late response cannot
    // repopulate the freshly reset wizard.
    blueprintsGeneration.current++;
    setRestoringBlueprints(false);
    setRestoredNoteVisible(false);
    setStep("learner");
    setProfileId("");
    setMode("describe");
    setId("");
    setTitle("");
    setBrief("");
    setAudience("");
    setGoals("");
    setToml("");
    setBlueprints(null);
    setBlueprintsError(null);
    setSelectedBlueprint("");
    setTimeBudget("");
    setCreatedId(null);
    setAttached(false);
    setCreateError(null);
  };

  const idInvalid = id.trim().length > 0 && !TOPIC_ID_PATTERN.test(id.trim());

  const topicReady =
    mode === "describe"
      ? id.trim().length > 0 && !idInvalid && title.trim().length > 0
      : toml.trim().length > 0;

  const describeFields = () => {
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
      id: id.trim(),
      title: title.trim(),
    };
    if (brief.trim()) fields.brief = brief.trim();
    if (audience.trim()) fields.audience = audience.trim();
    if (parsedGoals.length > 0) fields.goals = parsedGoals;
    if (timeBudget.trim()) fields.time_budget_minutes = Number(timeBudget.trim());
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
      await postAdvance(
        topicId,
        blueprintOverride ? { blueprint: blueprintOverride } : undefined,
      );
      clearNewRunDraft();
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
            {STEP_LABELS[name]}
          </li>
        ))}
      </ol>

      {restoredNoteVisible && (
        <p className="next-action" role="status">
          <span>Restored your in-progress course draft.</span>
          <button onClick={startOver} disabled={creating}>
            Start over
          </button>
          <button onClick={() => setRestoredNoteVisible(false)}>Dismiss</button>
        </p>
      )}

      {step === "learner" && (
        <section aria-labelledby="new-run-learner-heading">
          <h3 id="new-run-learner-heading">Learner</h3>
          <p className="field-help">{NEW_RUN_HELP.learner}</p>
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
              <div className="wizard-field">
                <label htmlFor={topicIdInputId}>Topic id</label>
                <InfoTip label="Topic id" text={NEW_RUN_HELP.topic_id} />
                <input
                  id={topicIdInputId}
                  value={id}
                  placeholder="intro-to-sql"
                  onChange={(e) => setId(e.target.value)}
                />
              </div>
              {idInvalid && (
                <p className="error field-validation-error">
                  Topic id must start with a letter or digit and use only letters, digits,
                  dots, dashes, and underscores.
                </p>
              )}
              <label>
                Title
                <input value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <div className="wizard-field">
                <label htmlFor={briefInputId}>Brief</label>
                <InfoTip label="Brief" text={NEW_RUN_HELP.brief} />
                <textarea
                  id={briefInputId}
                  value={brief}
                  placeholder="e.g. A hands-on introduction to SQL for analysts who live in spreadsheets today — enough to query, join, and summarize real tables confidently."
                  onChange={(e) => setBrief(e.target.value)}
                  rows={3}
                />
              </div>
              <div className="wizard-field">
                <label htmlFor={audienceInputId}>Audience</label>
                <InfoTip label="Audience" text={NEW_RUN_HELP.audience} />
                <input
                  id={audienceInputId}
                  value={audience}
                  placeholder="e.g. busy professionals new to investing"
                  onChange={(e) => setAudience(e.target.value)}
                />
              </div>
              <div className="wizard-field">
                <label htmlFor={goalsInputId}>Goals (one per line)</label>
                <InfoTip label="Goals" text={NEW_RUN_HELP.goals} />
                <textarea
                  id={goalsInputId}
                  value={goals}
                  placeholder="e.g. Join two tables confidently"
                  onChange={(e) => setGoals(e.target.value)}
                  rows={4}
                />
              </div>
              <div className="wizard-field">
                <label htmlFor={timeBudgetInputId}>Time budget (minutes, optional)</label>
                <InfoTip label="Time budget" text={NEW_RUN_HELP.time_budget} />
                <input
                  id={timeBudgetInputId}
                  type="number"
                  min={5}
                  max={10000}
                  value={timeBudget}
                  placeholder="e.g. 120"
                  onChange={(e) => setTimeBudget(e.target.value)}
                />
              </div>
            </div>
          ) : (
            <div>
              <div className="wizard-field">
                <label htmlFor={tomlInputId}>Topic TOML</label>
                <InfoTip label="Topic TOML" text={NEW_RUN_HELP.toml} />
                <textarea
                  id={tomlInputId}
                  value={toml}
                  placeholder={'id = "intro-to-sql"\ntitle = "Intro to SQL"'}
                  onChange={(e) => setToml(e.target.value)}
                  rows={8}
                />
              </div>
            </div>
          )}
          <p>
            <button onClick={goBack}>Back</button>{" "}
            <button disabled={!topicReady} onClick={() => void enterBlueprintStep()}>
              Continue
            </button>
          </p>
        </section>
      )}

      {step === "blueprint" && (
        <section aria-labelledby="new-run-blueprint-heading">
          <h3 id="new-run-blueprint-heading">Choose a blueprint</h3>
          <p className="field-help">{NEW_RUN_HELP.blueprint}</p>
          {blueprintsError ? (
            <ErrorNotice
              prefix="Blueprint recommendations are unavailable; the daemon will still record its own recommendation"
              error={blueprintsError}
            />
          ) : blueprints ? (
            <BlueprintPicker
              payload={blueprints}
              value={selectedBlueprint}
              onChange={setSelectedBlueprint}
            />
          ) : (
            <p>Loading blueprints…</p>
          )}
          <p>
            <button onClick={goBack}>Back</button>{" "}
            <button onClick={goNext}>Continue</button>
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
            <dt>Blueprint</dt>
            <dd>
              {selectedBlueprint
                ? `${selectedBlueprint}${blueprintOverride ? "" : " (recommended)"}`
                : "recommended default"}
            </dd>
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
            <button
              onClick={() => void createCourse()}
              disabled={creating || restoringBlueprints}
            >
              Create course
            </button>
            {restoringBlueprints && (
              <span className="field-help"> Restoring blueprint choices…</span>
            )}
          </p>
        </section>
      )}
    </div>
  );
}
