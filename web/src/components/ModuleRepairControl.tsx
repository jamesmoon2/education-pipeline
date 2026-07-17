import { useCallback, useState } from "react";
import { getRepairModules, postAdvance } from "../api/client";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

/**
 * "Regenerate one module": lists the approved draft's modules with their open
 * finding counts and prepares a module-scoped repair prompt through the
 * normal prep/run/paste flow. Hidden while the module list is unavailable
 * (e.g. no approved draft yet).
 */
export default function ModuleRepairControl({
  topicId,
  onPrepared,
}: {
  topicId: string;
  onPrepared: () => void;
}) {
  const fetchModules = useCallback(() => getRepairModules(topicId), [topicId]);
  const { data, error, refresh } = usePolling(fetchModules, 10_000);
  const [moduleId, setModuleId] = useState("");
  const prepare = useAction(() => {
    refresh();
    onPrepared();
  });

  if (error || !data) return null;

  return (
    <section className="module-repair" aria-labelledby="module-repair-heading">
      <h3 id="module-repair-heading">Regenerate one module</h3>
      <p>
        Prepare a repair prompt scoped to a single weak module. The rest of the
        approved draft is preserved byte-for-byte when the response is
        approved.
      </p>
      <label>
        Module
        <select value={moduleId} onChange={(e) => setModuleId(e.target.value)}>
          <option value="">select a module…</option>
          {data.modules.map((module) => (
            <option key={module.id} value={module.id}>
              {module.title} ({module.open_findings} open{" "}
              {module.open_findings === 1 ? "finding" : "findings"})
            </option>
          ))}
        </select>
      </label>{" "}
      <button
        disabled={prepare.busy || !moduleId}
        onClick={() =>
          prepare.run(
            () => postAdvance(topicId, { repairModule: moduleId }),
            { successMessage: `Scoped repair prompt prepared for ${moduleId}.` },
          )
        }
      >
        Regenerate this module
      </button>
      {prepare.feedback && (
        <p
          className={prepare.isError ? "error" : "success"}
          role={prepare.isError ? "alert" : "status"}
        >
          {prepare.feedback}
        </p>
      )}
    </section>
  );
}
