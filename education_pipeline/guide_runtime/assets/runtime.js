(() => {
  "use strict";
  const shell = document.querySelector("[data-guide-shell]");
  const status = document.querySelector("[data-guide-status]");
  const data = document.getElementById("guide-data");
  const expectedSchema = document.documentElement.dataset.guideSchema;
  const expectedRuntime = document.documentElement.dataset.guideRuntime;
  try {
    const guide = JSON.parse(data.textContent);
    if (guide.schema_version !== "1.0" || expectedSchema !== "1.0" || expectedRuntime !== "1.0") {
      throw new Error("This guide requires a compatible Education Pipeline export.");
    }
    shell.hidden = false;
    status.hidden = true;
  } catch (error) {
    shell.hidden = true;
    status.hidden = false;
    status.textContent = `This guide could not be loaded (schema ${expectedSchema || "unknown"}, runtime ${expectedRuntime || "unknown"}). Re-export it with a compatible Education Pipeline version.`;
  }
})();
