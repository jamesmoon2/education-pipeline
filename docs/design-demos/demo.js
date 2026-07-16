const root = document.documentElement;

function setTheme(theme) {
  if (theme === "dark") root.dataset.theme = "dark";
  else delete root.dataset.theme;
  document.querySelectorAll("[data-theme-label]").forEach((label) => {
    label.textContent = theme === "dark" ? "Use light theme" : "Use dark theme";
  });
}

const storedTheme = localStorage.getItem("ep-demo-theme");
if (storedTheme) setTheme(storedTheme);

document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("ep-demo-theme", nextTheme);
    setTheme(nextTheme);
  });
});

document.querySelectorAll("[data-guide-menu]").forEach((button) => {
  button.addEventListener("click", () => {
    const nav = button.closest(".guide-nav");
    const open = nav?.classList.toggle("open") ?? false;
    button.setAttribute("aria-expanded", String(open));
    button.textContent = open ? "Hide course map" : "Show course map";
  });
});

document.querySelectorAll("[data-check-answer]").forEach((button) => {
  button.addEventListener("click", () => {
    const check = button.closest(".knowledge-check");
    const selected = check?.querySelector("input[name='loop-check']:checked");
    const feedback = check?.querySelector(".check-feedback");
    if (!feedback) return;
    if (!selected) {
      feedback.innerHTML = "<strong>Choose one response first.</strong> Then check your reasoning.";
    } else if (selected.value === "delay") {
      feedback.innerHTML = "<strong>Sound diagnosis.</strong> The team is reacting to delayed evidence as if it described the current system. Shortening or explicitly modeling the delay is more useful than increasing the target again.";
    } else {
      feedback.innerHTML = "<strong>Look one level deeper.</strong> The visible miss is real, but it does not explain why each corrective push briefly helps and then creates a larger miss. The delay is the structural clue.";
    }
    feedback.classList.add("visible");
    feedback.setAttribute("tabindex", "-1");
    feedback.focus();
  });
});

document.querySelectorAll("[data-complete-section]").forEach((button) => {
  button.addEventListener("click", () => {
    const progress = document.querySelector(".guide-progress-value");
    const label = document.querySelector("[data-progress-copy]");
    if (progress) progress.style.width = "58%";
    if (label) label.textContent = "58% complete";
    button.textContent = "Section complete";
    button.classList.remove("button-primary");
    button.classList.add("button-secondary");
    button.setAttribute("aria-pressed", "true");
  });
});

document.querySelectorAll("[data-approve-outline]").forEach((button) => {
  button.addEventListener("click", () => {
    const current = document.querySelector(".thread-stage.current");
    const next = current?.nextElementSibling;
    if (!current || !next) return;
    current.classList.remove("current");
    current.classList.add("complete");
    const currentStatus = current.querySelector(".status");
    if (currentStatus) {
      currentStatus.className = "status status-complete";
      currentStatus.textContent = "Approved";
    }
    next.classList.add("current");
    const nextStatus = next.querySelector(".status");
    if (nextStatus) {
      nextStatus.className = "status status-current";
      nextStatus.textContent = "Ready to run";
    }
    button.textContent = "Outline approved";
    button.disabled = true;
    next.querySelector("h2")?.setAttribute("tabindex", "-1");
    next.querySelector("h2")?.focus();
  });
});
