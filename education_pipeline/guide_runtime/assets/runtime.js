(() => {
  "use strict";

  // ---------------------------------------------------------------------
  // Small utilities
  // ---------------------------------------------------------------------

  const qs = (sel, root) => (root || document).querySelector(sel);
  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const PREVIEW_EVIDENCE_MESSAGE_TYPE = "education-pipeline:preview-evidence";
  const GUIDE_ID_PATTERN = /^[a-z][a-z0-9-]{0,63}$/;

  function isPlainObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  // Deterministic, dependency-free digest of the exact embedded JSON text.
  // Not cryptographic; chosen because it runs synchronously (SubtleCrypto is
  // async and its availability under file: origins is inconsistent across
  // browsers), needs no imports, and only has to be stable for a given
  // input, not collision-resistant against an adversary.
  function contentHash(text) {
    let h = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(16).padStart(8, "0");
  }

  // ---------------------------------------------------------------------
  // Persistence: schema-checked, exception-safe localStorage wrapper
  // ---------------------------------------------------------------------

  const STORAGE_NS = "education-pipeline";
  const PROGRESS_FILE_FORMAT = "education-pipeline.guide-progress";
  const PROGRESS_FILE_VERSION = 1;

  function schemaMajor(schemaVersion) {
    return String(schemaVersion).split(".")[0];
  }

  function storageKey(courseId, hash, schemaVersion) {
    return `${STORAGE_NS}:guide:${courseId}:${hash}:v${schemaMajor(schemaVersion)}`;
  }

  function emptyState() {
    return { completedSections: [], interactions: {}, lastSection: null, theme: "system" };
  }

  function validateState(raw) {
    if (!isPlainObject(raw)) return null;
    const out = emptyState();
    if (Array.isArray(raw.completedSections)) {
      out.completedSections = raw.completedSections.filter((x) => typeof x === "string");
    }
    if (isPlainObject(raw.interactions)) {
      for (const [id, value] of Object.entries(raw.interactions)) {
        if (typeof id !== "string" || !isPlainObject(value) || typeof value.type !== "string") continue;
        const entry = { type: value.type, completed: Boolean(value.completed) };
        if (value.type === "knowledge_check") {
          entry.submittedCount = Number.isFinite(value.submittedCount) ? value.submittedCount : 0;
          entry.selectedIds = Array.isArray(value.selectedIds)
            ? value.selectedIds.filter((x) => typeof x === "string")
            : [];
        } else if (value.type === "worked_reveal") {
          entry.revealedCount = Number.isFinite(value.revealedCount) ? value.revealedCount : 0;
        } else if (value.type === "scenario") {
          entry.selectedId = typeof value.selectedId === "string" ? value.selectedId : null;
        } else if (value.type === "reflection") {
          entry.text = typeof value.text === "string" ? value.text : "";
          entry.skipped = Boolean(value.skipped);
        } else {
          continue;
        }
        out.interactions[id] = entry;
      }
    }
    if (typeof raw.lastSection === "string") out.lastSection = raw.lastSection;
    if (raw.theme === "light" || raw.theme === "dark" || raw.theme === "system") out.theme = raw.theme;
    // Optional: exports before this field existed stored no timestamp, and a
    // state without one stays valid -- it only sorts last when choosing which
    // earlier version's progress to offer. Anything non-finite is dropped
    // rather than carried forward.
    if (Number.isFinite(raw.updatedAt)) out.updatedAt = raw.updatedAt;
    // Optional, and only ever recorded as true: the learner has answered the
    // carry-over offer for this export (resumed or started fresh), so it must
    // not be raised again. Absent means "not asked yet", which is what every
    // older stored state correctly means.
    if (raw.migrationDecided === true) out.migrationDecided = true;
    return out;
  }

  const Persistence = (() => {
    let available = null;
    let noticeShown = false;

    function probe() {
      if (available !== null) return available;
      try {
        const key = "__ep_guide_probe__";
        window.localStorage.setItem(key, "1");
        window.localStorage.removeItem(key);
        available = true;
      } catch (_error) {
        available = false;
      }
      return available;
    }

    function notifyUnavailable() {
      if (noticeShown) return;
      noticeShown = true;
      try {
        const el = qs('[data-role="storage-notice"]');
        if (el) {
          el.hidden = false;
          el.textContent =
            "This browser is not allowing local storage for this file, so progress and notes will only last for this viewing.";
        }
      } catch (_error) {
        /* never let the notice itself throw */
      }
    }

    function read(key) {
      if (!probe()) {
        notifyUnavailable();
        return null;
      }
      try {
        const raw = window.localStorage.getItem(key);
        if (!raw) return null;
        return validateState(JSON.parse(raw));
      } catch (_error) {
        return null;
      }
    }

    function write(key, value) {
      if (!probe()) {
        notifyUnavailable();
        return false;
      }
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
        return true;
      } catch (_error) {
        notifyUnavailable();
        return false;
      }
    }

    // Every key currently in storage, for callers that must look beyond their
    // own. Reading the index is silent about availability: whoever needed the
    // notice has already tried a real read or write.
    function keys() {
      if (!probe()) return [];
      try {
        const out = [];
        for (let i = 0; i < window.localStorage.length; i++) {
          const key = window.localStorage.key(i);
          if (typeof key === "string") out.push(key);
        }
        return out;
      } catch (_error) {
        return [];
      }
    }

    return { read, write, keys };
  })();

  // ---------------------------------------------------------------------
  // State: in-memory progress/persistence record
  // ---------------------------------------------------------------------

  const State = (() => {
    let key = null;
    let data = emptyState();

    function init(storageKeyValue, loaded) {
      key = storageKeyValue;
      data = loaded || emptyState();
    }
    // Stamped on every write so a later export can tell which of this
    // course's stored records is the most recent one to offer.
    function save() {
      if (!key) return false;
      data.updatedAt = Date.now();
      return Persistence.write(key, data);
    }
    function get() {
      return data;
    }
    // Replace the whole record (migration or a restored progress file).
    // Returns whether it reached storage, which decides whether the caller
    // can safely reload to rebuild the interactive blocks.
    function adopt(next) {
      data = next || emptyState();
      return save();
    }
    // The learner has answered the carry-over offer for this export.
    function markMigrationDecided() {
      data.migrationDecided = true;
      return save();
    }
    function setTheme(theme) {
      data.theme = theme;
      save();
    }
    function markSectionComplete(id) {
      if (!data.completedSections.includes(id)) {
        data.completedSections.push(id);
        save();
      }
    }
    function setLastSection(id) {
      data.lastSection = id;
      save();
    }
    function interaction(id) {
      return data.interactions[id];
    }
    function setInteraction(id, entry) {
      data.interactions[id] = entry;
      save();
    }
    function resetProgress() {
      data = { completedSections: [], interactions: {}, lastSection: null, theme: data.theme };
      save();
    }
    return {
      init,
      get,
      save,
      adopt,
      markMigrationDecided,
      setTheme,
      markSectionComplete,
      setLastSection,
      interaction,
      setInteraction,
      resetProgress,
    };
  })();

  // ---------------------------------------------------------------------
  // Progress display
  // ---------------------------------------------------------------------

  const Progress = (() => {
    function update() {
      try {
        const sectionEls = qsa('main section[data-role="guide-section"]');
        const totalSections = sectionEls.length;
        const completedSections = State.get().completedSections.length;
        const interactiveEls = qsa('[data-interactive="true"]');
        const totalInteractions = interactiveEls.length;
        let doneInteractions = 0;
        interactiveEls.forEach((el) => {
          const entry = State.interaction(el.id);
          if (entry && entry.completed) doneInteractions += 1;
        });
        const el = qs('[data-role="progress-summary"]');
        if (el) {
          el.textContent =
            `${completedSections} of ${totalSections} section${totalSections === 1 ? "" : "s"} complete · ` +
            `${doneInteractions} of ${totalInteractions} interaction${totalInteractions === 1 ? "" : "s"} complete. ` +
            "This tracks progress only, not mastery.";
        }
      } catch (_error) {
        /* progress display is informational; never let it break the guide */
      }
    }
    return { update };
  })();

  // ---------------------------------------------------------------------
  // Navigation: single-section-at-a-time display, fragment routing
  // ---------------------------------------------------------------------

  const Nav = (() => {
    let sections = [];
    let current = null;

    function collect() {
      sections = qsa('main section[data-role="guide-section"]').map((el) => ({ id: el.id, el }));
    }
    function indexOf(id) {
      return sections.findIndex((s) => s.id === id);
    }
    function first() {
      return sections.length ? sections[0].id : null;
    }
    function announce(message) {
      const el = qs('[data-role="nav-announcement"]');
      if (el) el.textContent = message;
    }
    function updatePositionText() {
      sections.forEach((s, i) => {
        const posEl = qs('[data-role="section-position"]', s.el);
        if (posEl) posEl.textContent = `Section ${i + 1} of ${sections.length}`;
        const prevBtn = qs('[data-role="prev-section"]', s.el);
        const nextBtn = qs('[data-role="next-section"]', s.el);
        if (prevBtn) prevBtn.disabled = i === 0;
        if (nextBtn) nextBtn.disabled = i === sections.length - 1;
      });
    }
    function updateNavLinks() {
      qsa('[data-role="nav-link"]').forEach((a) => {
        if (a.dataset.sectionId === current) a.setAttribute("aria-current", "location");
        else a.removeAttribute("aria-current");
      });
    }
    function maybeAutoCompleteLeaving(id) {
      const entry = sections[indexOf(id)];
      if (!entry) return;
      const interactive = qsa('[data-interactive="true"]', entry.el);
      if (interactive.length === 0) return;
      const allDone = interactive.every((el) => {
        const s = State.interaction(el.id);
        return Boolean(s && s.completed);
      });
      if (allDone) State.markSectionComplete(id);
    }
    function show(id, options) {
      const opts = options || {};
      const idx = indexOf(id);
      if (idx === -1) return false;
      if (current && current !== id) maybeAutoCompleteLeaving(current);
      sections.forEach((s) => s.el.classList.toggle("is-current", s.id === id));
      current = id;
      State.setLastSection(id);
      updateNavLinks();
      if (location.hash.slice(1) !== id) {
        try {
          history.replaceState(null, "", `#${id}`);
        } catch (_error) {
          // Sandboxed srcDoc previews have an opaque origin, so Chromium may
          // reject history mutation. Navigation state remains in-memory and
          // the rest of runtime boot (including the evidence bridge) must
          // still complete.
        }
      }
      if (opts.focus) {
        const heading = qs("h2", sections[idx].el);
        if (heading) {
          if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
          heading.focus({ preventScroll: false });
        }
      }
      Progress.update();
      return true;
    }
    function next() {
      const i = indexOf(current);
      if (i > -1 && i < sections.length - 1) show(sections[i + 1].id, { focus: true });
    }
    function prev() {
      const i = indexOf(current);
      if (i > 0) show(sections[i - 1].id, { focus: true });
    }
    // Resolves any known guide ID (a section, or a block/choice/step nested
    // inside one) to the section that owns it. Returns null for IDs that do
    // not exist anywhere in the document.
    function resolveOwningSectionId(targetId) {
      const el = document.getElementById(targetId);
      if (!el) return null;
      if (el.matches('section[data-role="guide-section"]')) return el.id;
      const owning = el.closest('section[data-role="guide-section"]');
      return owning ? owning.id : null;
    }
    function goToTarget(targetId) {
      const sectionId = resolveOwningSectionId(targetId);
      if (!sectionId) {
        // In-document targets outside any section (e.g. the skip link's
        // #guide-main) still deserve their native jump: move focus without
        // changing the visible section or announcing an unknown fragment.
        const el = document.getElementById(targetId);
        if (el) {
          if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
          el.focus();
        }
        return;
      }
      show(sectionId, { focus: false });
      if (sectionId !== targetId) {
        const el = document.getElementById(targetId);
        requestAnimationFrame(() => {
          el.scrollIntoView({ block: "start" });
          if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
          el.focus({ preventScroll: true });
        });
      }
    }
    function revealEvidenceTarget(target) {
      const owning = target.matches('section[data-role="guide-section"]')
        ? target
        : target.closest('section[data-role="guide-section"]');
      if (owning) show(owning.id, { focus: false });
      requestAnimationFrame(() => {
        target.scrollIntoView({ block: "start" });
        if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      });
    }
    function handleUnknownFragment(id) {
      show(first());
      announce(
        `The link "#${id}" does not match a section in this course. Showing the first section instead.`
      );
    }
    function toggleDrawer() {
      const nav = qs(".guide-nav");
      const btn = qs('[data-role="nav-toggle"]');
      if (!nav) return;
      const open = !nav.classList.contains("is-open");
      nav.classList.toggle("is-open", open);
      if (btn) btn.setAttribute("aria-expanded", String(open));
    }
    function boot() {
      collect();
      if (sections.length === 0) return;
      updatePositionText();
      sections.forEach((s) => {
        const prevBtn = qs('[data-role="prev-section"]', s.el);
        const nextBtn = qs('[data-role="next-section"]', s.el);
        const markBtn = qs('[data-role="mark-complete"]', s.el);
        if (prevBtn) prevBtn.addEventListener("click", prev);
        if (nextBtn) nextBtn.addEventListener("click", next);
        if (markBtn) {
          markBtn.addEventListener("click", () => {
            State.markSectionComplete(s.id);
            const status = qs('[data-role="section-status"]', s.el);
            if (status) status.textContent = "Marked complete.";
            Progress.update();
          });
        }
      });
      document.addEventListener("click", (event) => {
        const anchor = event.target.closest('a[href^="#"]');
        if (!anchor) return;
        const targetId = anchor.getAttribute("href").slice(1);
        if (!targetId) return;
        event.preventDefault();
        goToTarget(targetId);
      });
      window.addEventListener("hashchange", () => {
        const id = location.hash.slice(1);
        if (!id) return;
        const sectionId = resolveOwningSectionId(id);
        if (sectionId) goToTarget(id);
        else handleUnknownFragment(id);
      });
      const initialHash = location.hash.slice(1);
      const restored = State.get().lastSection;
      if (initialHash) {
        if (resolveOwningSectionId(initialHash)) goToTarget(initialHash);
        else handleUnknownFragment(initialHash);
        return;
      }
      let startId = first();
      if (restored && indexOf(restored) > -1) startId = restored;
      show(startId);
    }
    return { boot, toggleDrawer, revealEvidenceTarget };
  })();

  // ---------------------------------------------------------------------
  // Sandboxed cockpit preview evidence bridge
  // ---------------------------------------------------------------------

  function installPreviewEvidenceBridge(guide) {
    if (document.documentElement.dataset.guideMode !== "preview") return;
    const outcomeIds = new Set(
      Array.isArray(guide.outcomes)
        ? guide.outcomes
            .filter((outcome) => isPlainObject(outcome) && typeof outcome.id === "string")
            .map((outcome) => outcome.id)
        : [],
    );

    window.addEventListener("message", (event) => {
      if (event.source !== window.parent || !isPlainObject(event.data)) return;
      const keys = Object.keys(event.data).sort();
      if (keys.length !== 3 || keys.join(",") !== "id,kind,type") return;
      if (event.data.type !== PREVIEW_EVIDENCE_MESSAGE_TYPE) return;
      if (event.data.kind !== "module" && event.data.kind !== "outcome") return;
      if (typeof event.data.id !== "string" || !GUIDE_ID_PATTERN.test(event.data.id)) return;

      let target = null;
      if (event.data.kind === "module") {
        target = qsa('section[data-role="guide-section"]').find(
          (section) => section.dataset.moduleId === event.data.id,
        ) || null;
      } else {
        target = outcomeIds.has(event.data.id)
          ? document.getElementById(event.data.id)
          : null;
      }
      if (!target) return;
      Nav.revealEvidenceTarget(target);
    });
  }

  // ---------------------------------------------------------------------
  // Defensive per-block enhancement
  // ---------------------------------------------------------------------

  function reportBlockError(article, error) {
    try {
      const id = (article && article.id) || "unknown-block";
      if (typeof console !== "undefined" && console.error) {
        console.error("guide-runtime: block failed to enhance:", id, error);
      }
      const note = document.createElement("p");
      note.className = "block-error";
      note.setAttribute("role", "note");
      note.textContent = `This block (${id}) could not be made interactive here; its content is still shown above.`;
      if (article) article.appendChild(note);
    } catch (_error) {
      /* the error reporter itself must never throw */
    }
  }

  // ---------------------------------------------------------------------
  // Knowledge check
  // ---------------------------------------------------------------------

  function enhanceKnowledgeCheck(article) {
    const id = article.id;
    const mode = article.dataset.mode;
    const retryAllowed = article.dataset.retry === "true";
    const inputs = qsa('[data-role="kc-choice"]', article);
    const items = qsa(".choice-item", article);
    const submitBtn = qs('[data-role="kc-submit"]', article);
    const retryBtn = qs('[data-role="kc-retry"]', article);
    const resultEl = qs('[data-role="kc-result"]', article);

    function selectedIds() {
      return inputs.filter((i) => i.checked).map((i) => i.dataset.choiceId);
    }
    function updateSubmitEnabled() {
      submitBtn.disabled = selectedIds().length === 0;
    }
    function applySubmittedView(selected) {
      const correctIds = inputs.filter((i) => i.dataset.correct === "true").map((i) => i.dataset.choiceId);
      const isCorrect =
        mode === "single"
          ? selected.length === 1 && correctIds.includes(selected[0])
          : selected.length === correctIds.length && correctIds.every((c) => selected.includes(c));
      items.forEach((li) => {
        const input = qs("input", li);
        const isSelected = selected.includes(input.dataset.choiceId);
        li.dataset.state = isSelected ? (input.dataset.correct === "true" ? "correct" : "incorrect") : "";
      });
      article.classList.add("is-submitted");
      resultEl.textContent = isCorrect ? "Correct." : "Not quite — review the explanation below.";
    }
    function lock() {
      inputs.forEach((i) => (i.disabled = true));
      submitBtn.hidden = true;
      if (retryBtn) retryBtn.hidden = !retryAllowed;
    }

    inputs.forEach((i) => i.addEventListener("change", updateSubmitEnabled));
    submitBtn.addEventListener("click", () => {
      const selected = selectedIds();
      if (selected.length === 0) return;
      applySubmittedView(selected);
      lock();
      const prior = State.interaction(id);
      State.setInteraction(id, {
        type: "knowledge_check",
        completed: true,
        submittedCount: (prior && prior.submittedCount ? prior.submittedCount : 0) + 1,
        selectedIds: selected,
      });
      Progress.update();
    });
    if (retryBtn) {
      retryBtn.addEventListener("click", () => {
        inputs.forEach((i) => {
          i.checked = false;
          i.disabled = false;
        });
        items.forEach((li) => (li.dataset.state = ""));
        article.classList.remove("is-submitted");
        resultEl.textContent = "";
        submitBtn.hidden = false;
        retryBtn.hidden = true;
        updateSubmitEnabled();
      });
    }

    const entry = State.interaction(id);
    if (entry && entry.completed) {
      (entry.selectedIds || []).forEach((cid) => {
        const input = inputs.find((i) => i.dataset.choiceId === cid);
        if (input) input.checked = true;
      });
      applySubmittedView(entry.selectedIds || []);
      lock();
    }
    updateSubmitEnabled();
  }

  // ---------------------------------------------------------------------
  // Worked reveal
  // ---------------------------------------------------------------------

  function enhanceWorkedReveal(article) {
    const id = article.id;
    const steps = qsa('[data-role="reveal-step"]', article);
    const revealBtn = qs('[data-role="wr-reveal-next"]', article);
    const showAllBtn = qs('[data-role="wr-show-all"]', article);
    const resetBtn = qs('[data-role="wr-reset"]', article);
    const live = qs('[data-role="wr-live"]', article);
    let revealed = 0;

    function apply() {
      steps.forEach((li, i) => li.classList.toggle("is-revealed", i < revealed));
      const done = revealed >= steps.length;
      article.classList.toggle("is-complete", done);
      revealBtn.hidden = done;
      showAllBtn.hidden = done;
      if (resetBtn) resetBtn.hidden = revealed === 0;
      revealBtn.textContent = revealed === 0 ? "Reveal first step" : "Reveal next step";
    }
    function persist() {
      State.setInteraction(id, {
        type: "worked_reveal",
        completed: revealed >= steps.length,
        revealedCount: revealed,
      });
      Progress.update();
    }

    revealBtn.addEventListener("click", () => {
      if (revealed >= steps.length) return;
      revealed += 1;
      apply();
      if (live) live.textContent = steps[revealed - 1].textContent.trim();
      persist();
    });
    showAllBtn.addEventListener("click", () => {
      revealed = steps.length;
      apply();
      if (live) live.textContent = "All steps revealed.";
      persist();
    });
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        revealed = 0;
        apply();
        if (live) live.textContent = "Steps reset.";
        persist();
      });
    }

    const entry = State.interaction(id);
    if (entry && Number.isFinite(entry.revealedCount)) {
      revealed = Math.min(entry.revealedCount, steps.length);
    }
    apply();
  }

  // ---------------------------------------------------------------------
  // Scenario
  // ---------------------------------------------------------------------

  function enhanceScenario(article) {
    const id = article.id;
    const inputs = qsa('[data-role="sc-choice"]', article);
    const items = qsa(".choice-item", article);
    const submitBtn = qs('[data-role="sc-submit"]', article);
    const retryBtn = qs('[data-role="sc-retry"]', article);
    const resultEl = qs('[data-role="sc-result"]', article);

    function selectedId() {
      const i = inputs.find((x) => x.checked);
      return i ? i.dataset.choiceId : null;
    }
    function updateSubmitEnabled() {
      submitBtn.disabled = !selectedId();
    }
    function applySubmittedView(choiceId) {
      let quality = "";
      items.forEach((li) => {
        const input = qs("input", li);
        if (input.dataset.choiceId === choiceId) {
          quality = input.dataset.quality;
          li.dataset.state = input.dataset.quality;
        } else {
          li.dataset.state = "";
        }
      });
      article.classList.add("is-submitted");
      resultEl.textContent = `You chose the "${quality}" option. Read the feedback and debrief below.`;
    }
    function lock() {
      inputs.forEach((i) => (i.disabled = true));
      submitBtn.hidden = true;
      if (retryBtn) retryBtn.hidden = false;
    }

    inputs.forEach((i) => i.addEventListener("change", updateSubmitEnabled));
    submitBtn.addEventListener("click", () => {
      const choiceId = selectedId();
      if (!choiceId) return;
      applySubmittedView(choiceId);
      lock();
      State.setInteraction(id, { type: "scenario", completed: true, selectedId: choiceId });
      Progress.update();
    });
    if (retryBtn) {
      retryBtn.addEventListener("click", () => {
        inputs.forEach((i) => {
          i.checked = false;
          i.disabled = false;
        });
        items.forEach((li) => (li.dataset.state = ""));
        article.classList.remove("is-submitted");
        resultEl.textContent = "";
        submitBtn.hidden = false;
        retryBtn.hidden = true;
        updateSubmitEnabled();
      });
    }

    const entry = State.interaction(id);
    if (entry && entry.completed && entry.selectedId) {
      const input = inputs.find((i) => i.dataset.choiceId === entry.selectedId);
      if (input) input.checked = true;
      applySubmittedView(entry.selectedId);
      lock();
    }
    updateSubmitEnabled();
  }

  // ---------------------------------------------------------------------
  // Reflection
  // ---------------------------------------------------------------------

  function enhanceReflection(article) {
    const id = article.id;
    const textarea = qs('[data-role="reflection-input"]', article);
    const skipBtn = qs('[data-role="rf-skip"]', article);
    const resetBtn = qs('[data-role="rf-reset"]', article);
    const status = qs('[data-role="rf-status"]', article);
    let debounceHandle = null;

    function persist(extra) {
      State.setInteraction(
        id,
        Object.assign(
          { type: "reflection", text: textarea.value, skipped: false, completed: textarea.value.trim().length > 0 },
          extra || {}
        )
      );
      Progress.update();
    }
    function scheduleSave() {
      if (debounceHandle) window.clearTimeout(debounceHandle);
      debounceHandle = window.setTimeout(() => {
        persist();
        if (status) status.textContent = "Saved locally.";
      }, 600);
    }

    textarea.addEventListener("input", () => {
      if (resetBtn) resetBtn.hidden = textarea.value.trim().length === 0;
      scheduleSave();
    });
    textarea.addEventListener("blur", () => {
      if (debounceHandle) window.clearTimeout(debounceHandle);
      persist();
      if (status) status.textContent = textarea.value.trim() ? "Saved locally." : "";
    });
    skipBtn.addEventListener("click", () => {
      persist({ skipped: true, completed: true });
      if (status) status.textContent = "Skipped.";
    });
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        if (!window.confirm("Clear your note for this reflection? This cannot be undone.")) return;
        textarea.value = "";
        resetBtn.hidden = true;
        persist({ skipped: false, completed: false });
        if (status) status.textContent = "Cleared.";
      });
    }

    const entry = State.interaction(id);
    if (entry) {
      textarea.value = entry.text || "";
      if (resetBtn) resetBtn.hidden = !entry.text;
      if (status) {
        if (entry.skipped) status.textContent = "Skipped.";
        else if (entry.text) status.textContent = "Saved locally.";
      }
    }
  }

  // ---------------------------------------------------------------------
  // Block dispatch
  // ---------------------------------------------------------------------

  const ENHANCERS = {
    knowledge_check: enhanceKnowledgeCheck,
    worked_reveal: enhanceWorkedReveal,
    scenario: enhanceScenario,
    reflection: enhanceReflection,
  };

  function enhanceBlocks() {
    qsa('[data-interactive="true"]').forEach((article) => {
      const type = Object.keys(ENHANCERS).find((t) => article.classList.contains(t));
      const fn = type && ENHANCERS[type];
      if (!fn) return;
      try {
        fn(article);
      } catch (error) {
        reportBlockError(article, error);
      }
    });
  }

  // ---------------------------------------------------------------------
  // Adopting progress recorded elsewhere (an earlier export, or a file)
  // ---------------------------------------------------------------------

  const Restore = (() => {
    // Progress that came from another export can name sections and blocks
    // this document no longer has. Adopting it unfiltered would count ids
    // nothing here can display, so it is always narrowed to what this exact
    // guide contains before anything is stored.
    function filterToDocument(state) {
      const sectionIds = new Set(qsa('main section[data-role="guide-section"]').map((el) => el.id));
      const interactionIds = new Set(qsa('[data-interactive="true"]').map((el) => el.id));
      const out = emptyState();
      out.theme = state.theme;
      out.completedSections = state.completedSections.filter((id) => sectionIds.has(id));
      Object.keys(state.interactions).forEach((id) => {
        if (interactionIds.has(id)) out.interactions[id] = state.interactions[id];
      });
      if (state.lastSection && sectionIds.has(state.lastSection)) out.lastSection = state.lastSection;
      return out;
    }

    function refreshTheme(theme) {
      applyTheme(theme);
      const select = qs('[data-role="theme-select"]');
      if (select) select.value = theme || "system";
    }

    // Reloading is how reset-progress refreshes, and it is the only honest
    // way to rebuild submitted answers, revealed steps and saved notes: each
    // block enhancer reads stored state once, at boot, and re-running them
    // over the live DOM would bind every listener a second time.
    function adopt(state) {
      const filtered = filterToDocument(state);
      if (State.adopt(filtered)) {
        window.location.reload();
        return true;
      }
      // Storage refused the write, so a reload would throw the adopted
      // progress away. Keep it for this viewing and refresh what can be
      // refreshed without re-enhancing the blocks.
      refreshTheme(filtered.theme);
      Progress.update();
      return false;
    }

    return { adopt, filterToDocument };
  })();

  // ---------------------------------------------------------------------
  // Progress files: download the current record, restore a saved one
  // ---------------------------------------------------------------------

  const ProgressFile = (() => {
    let courseId = null;
    let schemaVersion = null;

    function setStatus(message, isError) {
      try {
        const el = qs('[data-role="progress-file-status"]');
        if (!el) return;
        el.textContent = message;
        if (isError) el.dataset.state = "error";
        else delete el.dataset.state;
      } catch (_error) {
        /* the status line must never be the thing that breaks */
      }
    }

    function download() {
      try {
        const payload = {
          format: PROGRESS_FILE_FORMAT,
          version: PROGRESS_FILE_VERSION,
          course_id: courseId,
          schema_version: schemaVersion,
          saved_at: new Date().toISOString(),
          // The in-memory record, so the download still works in browsers
          // that refuse local storage for this file.
          state: State.get(),
        };
        const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${courseId}-progress.json`;
        // Appended only for the duration of the click: some browsers ignore
        // a download from an anchor that was never in the document. No paint
        // happens inside one task, so nothing flashes on screen.
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        // Revoking in the same task can cancel the download the click just
        // started, so let this one finish first.
        window.setTimeout(() => {
          try {
            URL.revokeObjectURL(url);
          } catch (_error) {
            /* already released */
          }
        }, 0);
        setStatus("Progress file downloaded.");
      } catch (_error) {
        setStatus("This browser would not save a progress file here.", true);
      }
    }

    // Reads one chosen file. Every rejection path ends in a visible message
    // and leaves the stored progress exactly as it was.
    function applyText(text) {
      let payload = null;
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        payload = null;
      }
      if (!isPlainObject(payload) || payload.format !== PROGRESS_FILE_FORMAT) {
        setStatus(
          "That is not an Education Pipeline progress file, so nothing was changed.",
          true
        );
        return false;
      }
      const state = validateState(payload.state);
      if (!state) {
        setStatus("That progress file holds no readable progress, so nothing was changed.", true);
        return false;
      }
      const fileCourse = typeof payload.course_id === "string" ? payload.course_id : "";
      if (fileCourse !== courseId) {
        const named = fileCourse ? `"${fileCourse}"` : "another course";
        if (
          !window.confirm(
            `That progress file was saved from ${named}, not this course. Apply it here anyway?`
          )
        ) {
          setStatus("Restore cancelled. Your progress is unchanged.");
          return false;
        }
      }
      setStatus("Progress restored from the file you chose.");
      Restore.adopt(state);
      return true;
    }

    function readChosenFile(input) {
      const file = input.files && input.files[0];
      if (!file) return;
      try {
        const reader = new FileReader();
        reader.onerror = () => {
          input.value = "";
          setStatus("That file could not be read.", true);
        };
        reader.onload = () => {
          applyText(typeof reader.result === "string" ? reader.result : "");
          // Clear the picker so choosing the same file again still fires.
          input.value = "";
        };
        reader.readAsText(file);
      } catch (_error) {
        input.value = "";
        setStatus("That file could not be read.", true);
      }
    }

    function init(course, schema) {
      courseId = course;
      schemaVersion = schema;
      const downloadBtn = qs('[data-role="download-progress"]');
      const restoreBtn = qs('[data-role="restore-progress"]');
      const input = qs('[data-role="progress-file-input"]');
      if (downloadBtn) downloadBtn.addEventListener("click", download);
      if (restoreBtn && input) {
        restoreBtn.addEventListener("click", () => {
          try {
            input.value = "";
            input.click();
          } catch (_error) {
            setStatus("This browser would not open a file picker here.", true);
          }
        });
      }
      if (input) input.addEventListener("change", () => readChosenFile(input));
    }

    return { init };
  })();

  // ---------------------------------------------------------------------
  // Progress carried over from a previous export of the same course
  // ---------------------------------------------------------------------

  const Migration = (() => {
    // Re-exporting after any content change gives the guide a new content
    // hash, so the learner's progress stays behind under the previous key.
    // This offers it -- never imposes it -- and never removes the old key:
    // the older exported file may still be in use somewhere.
    function candidates(courseId, hash, schemaVersion) {
      const prefix = `${STORAGE_NS}:guide:${courseId}:`;
      const suffix = `:v${schemaMajor(schemaVersion)}`;
      const currentKey = storageKey(courseId, hash, schemaVersion);
      const found = [];
      Persistence.keys().forEach((key) => {
        if (key === currentKey || !key.startsWith(prefix) || !key.endsWith(suffix)) return;
        const otherHash = key.slice(prefix.length, key.length - suffix.length);
        // Exactly one segment between course id and schema: anything else is
        // some other product's key that happens to share the prefix.
        if (!otherHash || otherHash.indexOf(":") !== -1) return;
        const state = Persistence.read(key);
        if (state) found.push({ key, state });
      });
      return found;
    }

    function newest(list) {
      return list.reduce((winner, entry) => {
        if (!winner) return entry;
        const at = Number.isFinite(entry.state.updatedAt) ? entry.state.updatedAt : 0;
        const winnerAt = Number.isFinite(winner.state.updatedAt) ? winner.state.updatedAt : 0;
        if (at !== winnerAt) return at > winnerAt ? entry : winner;
        // Same timestamp (or neither has one): prefer the fuller record.
        return entry.state.completedSections.length > winner.state.completedSections.length
          ? entry
          : winner;
      }, null);
    }

    function describe(state) {
      const sections = state.completedSections.length;
      const answers = Object.keys(state.interactions).length;
      return (
        `It records ${sections} completed section${sections === 1 ? "" : "s"} and ` +
        `${answers} saved interaction${answers === 1 ? "" : "s"} that still fit this version.`
      );
    }

    function offer(courseId, hash, schemaVersion) {
      try {
        const banner = qs('[data-role="progress-migration"]');
        if (!banner) return false;
        const winner = newest(candidates(courseId, hash, schemaVersion));
        if (!winner) return false;

        const detail = qs('[data-role="progress-migration-detail"]', banner);
        if (detail) detail.textContent = describe(Restore.filterToDocument(winner.state));
        const resume = qs('[data-role="resume-progress"]', banner);
        const dismiss = qs('[data-role="dismiss-progress"]', banner);
        if (resume) {
          resume.addEventListener("click", () => {
            banner.hidden = true;
            try {
              Restore.adopt(winner.state);
            } catch (_error) {
              /* the guide keeps working with the progress it already had */
            }
          });
        }
        if (dismiss) {
          dismiss.addEventListener("click", () => {
            banner.hidden = true;
            // Persist this export's own (empty) record so the same offer
            // does not come back the next time this file is opened.
            State.save();
          });
        }
        banner.hidden = false;
        return true;
      } catch (_error) {
        // A guide that cannot offer earlier progress is still a whole guide.
        return false;
      }
    }

    return { offer };
  })();

  // ---------------------------------------------------------------------
  // Course controls: theme, progress reset, progress files, nav drawer
  // ---------------------------------------------------------------------

  function applyTheme(pref) {
    const root = document.documentElement;
    if (pref === "light" || pref === "dark") root.dataset.theme = pref;
    else delete root.dataset.theme;
  }

  function enhanceCourseControls(guide) {
    const select = qs('[data-role="theme-select"]');
    if (select) {
      select.value = State.get().theme || "system";
      applyTheme(select.value);
      select.addEventListener("change", () => {
        applyTheme(select.value);
        State.setTheme(select.value);
      });
    }
    const resetBtn = qs('[data-role="reset-progress"]');
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        if (
          !window.confirm(
            "Reset all course progress and reflection notes stored in this browser for this file? This cannot be undone."
          )
        ) {
          return;
        }
        State.resetProgress();
        window.location.reload();
      });
    }
    ProgressFile.init(guide.course.id, guide.schema_version);
    const navToggle = qs('[data-role="nav-toggle"]');
    if (navToggle) navToggle.addEventListener("click", () => Nav.toggleDrawer());
  }

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------

  function boot() {
    const shell = qs("[data-guide-shell]");
    const status = qs("[data-guide-status]");
    const dataEl = document.getElementById("guide-data");
    const expectedSchema = document.documentElement.dataset.guideSchema;
    const expectedRuntime = document.documentElement.dataset.guideRuntime;
    try {
      const rawText = dataEl.textContent;
      const guide = JSON.parse(rawText);
      const supportedSchemas = new Set(["1.0", "1.1"]);
      if (
        !supportedSchemas.has(guide.schema_version) ||
        guide.schema_version !== expectedSchema ||
        expectedRuntime !== "1.0"
      ) {
        throw new Error("unsupported guide schema/runtime version");
      }
      shell.hidden = false;
      status.hidden = true;

      const hash = contentHash(rawText);
      const key = storageKey(guide.course.id, hash, guide.schema_version);
      const loaded = Persistence.read(key);
      State.init(key, loaded || undefined);

      document.documentElement.classList.add("js-enhanced");
      enhanceCourseControls(guide);
      enhanceBlocks();
      Nav.boot();
      installPreviewEvidenceBridge(guide);
      Progress.update();
      // Only when this exact export has nothing stored yet: booting itself
      // records a last section, so the offer is made against the state read
      // before any of that happened.
      if (!loaded) Migration.offer(guide.course.id, hash, guide.schema_version);
    } catch (error) {
      shell.hidden = true;
      status.hidden = false;
      status.textContent =
        `This guide could not be loaded (schema ${expectedSchema || "unknown"}, ` +
        `runtime ${expectedRuntime || "unknown"}). Re-export it with a compatible Education Pipeline version.`;
    }
  }

  boot();
})();
