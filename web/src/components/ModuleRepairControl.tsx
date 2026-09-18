import { useCallback, useState } from "react";
import { getRepairModules, postAdvance } from "../api/client";
import type { RepairModulesPayload } from "../api/types";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

type RepairModule = RepairModulesPayload["modules"][number];

/**
 * The section to preselect once a module is chosen: the module's sole
 * section with open findings, but only when the module itself carries no
 * module-level findings (those can only be fixed by a whole-module repair,
 * so a section-scoped default would be misleading). Any other shape —
 * zero or several qualifying sections, or module-level findings present —
 * falls back to whole-module scope ("").
 */
function preselectSection(module: RepairModule): string {
  if (module.module_level_findings > 0) return "";
  const withFindings = module.sections.filter((s) => s.open_findings > 0);
  return withFindings.length === 1 ? withFindings[0].id : "";
}

/**
 * "Regenerate one module": lists the approved draft's modules with their open
 * finding counts and prepares a module- or section-scoped repair prompt
 * through the normal prep/run/paste flow. Hidden while the module list is
 * unavailable (e.g. no approved draft yet).
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
  const [sectionId, setSectionId] = useState("");
  const prepare = useAction(() => {
    refresh();
    onPrepared();
  });

  if (error || !data) return null;

  const selectedModule = data.modules.find((module) => module.id === moduleId);

  const handleModuleChange = (id: string) => {
    setModuleId(id);
    const module = data.modules.find((m) => m.id === id);
    setSectionId(module ? preselectSection(module) : "");
  };

  const scopedToSection = selectedModule && sectionId !== "";

  return (
    <section className="module-repair" aria-labelledby="module-repair-heading">
      <h3 id="module-repair-heading">Regenerate one module</h3>
      <p>
        Prepare a repair prompt scoped to a single weak module, or narrower —
        a single section of it. The rest of the approved draft is preserved
        byte-for-byte when the response is approved.
      </p>
      <label>
        Module
        <select
          value={moduleId}
          onChange={(e) => handleModuleChange(e.target.value)}
        >
          <option value="">select a module…</option>
          {data.modules.map((module) => (
            <option key={module.id} value={module.id}>
              {module.title} ({module.open_findings} open{" "}
              {module.open_findings === 1 ? "finding" : "findings"})
            </option>
          ))}
        </select>
      </label>{" "}
      {selectedModule && (
        <label>
          Section
          <select
            value={sectionId}
            onChange={(e) => setSectionId(e.target.value)}
          >
            <option value="">Whole module</option>
            {selectedModule.sections.map((section) => (
              <option key={section.id} value={section.id}>
                {section.title} ({section.open_findings} open{" "}
                {section.open_findings === 1 ? "finding" : "findings"})
              </option>
            ))}
          </select>
        </label>
      )}{" "}
      {selectedModule && selectedModule.module_level_findings > 0 && (
        <p>
          Whole module is required: this module has module-level findings
          that a section-scoped repair cannot fix.
        </p>
      )}
      <button
        disabled={prepare.busy || !moduleId}
        onClick={() =>
          prepare.run(
            () =>
              postAdvance(topicId, {
                repairModule: moduleId,
                ...(scopedToSection ? { repairSection: sectionId } : {}),
              }),
            {
              successMessage: scopedToSection
                ? `Scoped repair prompt prepared for ${moduleId} / ${sectionId}.`
                : `Scoped repair prompt prepared for ${moduleId}.`,
            },
          )
        }
      >
        {scopedToSection ? "Regenerate this section" : "Regenerate this module"}
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
