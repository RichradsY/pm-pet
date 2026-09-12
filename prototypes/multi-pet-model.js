/* PM Pet interaction model. Sample data only; no agent control or network activity. */
(function (root) {
  'use strict';
  const THEMES = Object.freeze(['sage', 'sky', 'lilac', 'rose', 'sand']);
  const MAX_ENABLED = 5;
  const RUNNING_PHASES = new Set(['planning', 'building', 'checking']);
  const PHASES = new Set(['idle', ...RUNNING_PHASES, 'waiting', 'complete']);
  const copy = value => JSON.parse(JSON.stringify(value));
  const fail = error => ({ ok: false, error });
  const defaultSteps = () => ['Agree the scope', 'Design the interaction', 'Build the core flow', 'Connect the pieces', 'Verify the result']
    .map((label, index) => ({ id: 'step-' + index, label, done: index < 2 }));

  function normalizeSteps(steps) {
    if (!Array.isArray(steps)) return defaultSteps();
    const seen = new Set();
    return steps.filter(step => step && typeof step.id === 'string' && !seen.has(step.id) && seen.add(step.id))
      .map(step => ({ id: step.id, label: String(step.label || step.id), done: step.done === true }));
  }

  function normalizeQuota(input) {
    const windows = {};
    for (const value of Object.values(input && input.windows || {})) {
      if (!value || !Number.isFinite(value.remainingPercent)) continue;
      const key = value.windowDurationMins === 300 ? 'five' : value.windowDurationMins === 10080 ? 'week' : null;
      if (!key) continue;
      windows[key] = {
        remainingPercent: Math.max(0, Math.min(100, value.remainingPercent)),
        windowDurationMins: value.windowDurationMins,
        resetsAt: Number.isFinite(value.resetsAt) ? value.resetsAt : null
      };
    }
    return { windows, observedAt: input && input.observedAt || null, source: 'sample' };
  }

  function createStore(options = {}) {
    let saved = options.saved;
    if (typeof saved === 'string') {
      try { saved = JSON.parse(saved); } catch (_) { saved = null; }
    }
    if (!saved || saved.version !== 1 || !Array.isArray(saved.pets)) saved = null;
    const registry = new Map();
    let hasCreatedPet = Boolean(saved && saved.hasCreatedPet);
    let quota = normalizeQuota(saved && saved.quota);

    function register(input, restoring) {
      if (!input || typeof input.id !== 'string' || !input.id || registry.has(input.id)) return;
      const enabled = restoring && input.enabled === true;
      const initialized = restoring && (input.hasBeenEnabled === true || enabled);
      const steps = normalizeSteps(input.steps);
      const phase = PHASES.has(input.phase) ? input.phase : 'building';
      const question = input.question && typeof input.question.text === 'string' ? copy(input.question) : null;
      registry.set(input.id, {
        id: input.id,
        title: String(input.title || 'Untitled conversation'),
        project: String(input.project || ''),
        theme: THEMES.includes(input.theme) ? input.theme : THEMES[registry.size % THEMES.length],
        enabled,
        hasBeenEnabled: initialized,
        quotaVisible: initialized && input.quotaVisible === true,
        panelOpen: input.panelOpen === true,
        size: Number.isFinite(input.size) ? Math.max(75, Math.min(150, input.size)) : 100,
        position: input.position && Number.isFinite(input.position.x) && Number.isFinite(input.position.y)
          ? { x: input.position.x, y: input.position.y } : null,
        phase: question ? 'waiting' : phase === 'waiting' ? 'building' : phase,
        steps,
        question,
        phaseBeforeQuestion: RUNNING_PHASES.has(input.phaseBeforeQuestion) ? input.phaseBeforeQuestion : 'building',
        decisionHistory: restoring && Array.isArray(input.decisionHistory) ? copy(input.decisionHistory) : [],
        questionSequence: Number.isInteger(input.questionSequence) ? input.questionSequence : 0
      });
      if (initialized) hasCreatedPet = true;
    }

    if (saved) saved.pets.forEach(pet => register(pet, true));
    (options.sampleConversations || []).forEach(pet => register(pet, false));

    // Recover edited/old saved data without permitting duplicate active themes or >5 windows.
    const usedThemes = new Set();
    for (const pet of registry.values()) {
      if (!pet.enabled) continue;
      if (usedThemes.size === MAX_ENABLED) { pet.enabled = false; continue; }
      if (usedThemes.has(pet.theme)) pet.theme = THEMES.find(theme => !usedThemes.has(theme));
      usedThemes.add(pet.theme);
    }

    function mutate(id, action, requireEnabled = false) {
      const pet = registry.get(id);
      if (!pet) return fail('not-found');
      if (requireEnabled && !pet.enabled) return fail('disabled');
      const error = action(pet);
      return error ? fail(error) : { ok: true, pet: copy(pet) };
    }

    function nextPhase(pet) {
      const pending = pet.steps.filter(step => !step.done);
      return pending.length === 0 && pet.steps.length ? 'complete' : pending.length === 1 ? 'checking' : 'building';
    }

    return {
      list({ enabledOnly = false } = {}) {
        return copy([...registry.values()].filter(pet => !enabledOnly || pet.enabled));
      },
      get(id) { return registry.has(id) ? copy(registry.get(id)) : null; },
      enable(id) {
        return mutate(id, pet => {
          if (pet.enabled) return;
          const active = [...registry.values()].filter(item => item.enabled);
          if (active.length >= MAX_ENABLED) return 'capacity';
          const occupied = new Set(active.map(item => item.theme));
          if (occupied.has(pet.theme)) pet.theme = THEMES.find(theme => !occupied.has(theme));
          if (!pet.hasBeenEnabled) {
            pet.quotaVisible = !hasCreatedPet;
            pet.hasBeenEnabled = true;
            hasCreatedPet = true;
          }
          pet.enabled = true;
        });
      },
      disable(id) { return mutate(id, pet => { pet.enabled = false; }); },
      setQuotaVisible(id, visible) {
        return mutate(id, pet => {
          if (typeof visible !== 'boolean') return 'invalid-value';
          pet.quotaVisible = visible;
        }, true);
      },
      setPanelOpen(id, open) {
        return mutate(id, pet => {
          if (typeof open !== 'boolean') return 'invalid-value';
          pet.panelOpen = open;
        });
      },
      setSize(id, size) {
        return mutate(id, pet => {
          if (!Number.isFinite(size)) return 'invalid-value';
          pet.size = Math.max(75, Math.min(150, size));
        });
      },
      setPosition(id, position) {
        return mutate(id, pet => {
          if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) return 'invalid-value';
          pet.position = { x: position.x, y: position.y };
        });
      },
      clearPosition(id) { return mutate(id, pet => { pet.position = null; }); },
      advance(id) {
        return mutate(id, pet => {
          if (pet.phase === 'waiting') return 'waiting';
          const step = pet.steps.find(item => !item.done);
          if (!step) return 'complete';
          step.done = true;
          pet.phase = nextPhase(pet);
        }, true);
      },
      setPlan(id, steps) {
        return mutate(id, pet => {
          if (pet.phase === 'waiting') return 'waiting';
          if (!Array.isArray(steps)) return 'invalid-value';
          pet.steps = normalizeSteps(steps);
          pet.phase = nextPhase(pet);
        }, true);
      },
      setPhase(id, phase) {
        return mutate(id, pet => {
          if (pet.phase === 'waiting') return 'waiting';
          if (!PHASES.has(phase) || phase === 'waiting') return 'invalid-value';
          if (phase === 'complete' && pet.steps.some(step => !step.done)) return 'unfinished';
          pet.phase = phase;
        }, true);
      },
      ask(id, text) {
        return mutate(id, pet => {
          if (pet.question) return 'waiting';
          if (typeof text !== 'string' || !text.trim()) return 'invalid-value';
          pet.phaseBeforeQuestion = pet.phase;
          pet.questionSequence += 1;
          pet.question = { id: pet.id + ':question:' + pet.questionSequence, text: text.trim() };
          pet.phase = 'waiting';
          pet.panelOpen = true;
        }, true);
      },
      resolve(id, answer) {
        return mutate(id, pet => {
          if (!pet.question) return 'no-question';
          if (typeof answer !== 'string' || !answer.trim()) return 'invalid-value';
          pet.decisionHistory.push({ ...pet.question, answer: answer.trim() });
          pet.question = null;
          pet.phase = pet.phaseBeforeQuestion === 'idle' ? 'idle' : nextPhase(pet);
        }, true);
      },
      progress(id) {
        const pet = registry.get(id);
        if (!pet) return null;
        const done = pet.steps.filter(step => step.done).length;
        return { done, total: pet.steps.length, percent: pet.steps.length ? Math.round(done / pet.steps.length * 100) : 0 };
      },
      setQuota(snapshot) { quota = normalizeQuota(snapshot); return copy(quota); },
      getQuota() { return copy(quota); },
      pollIntervalMs() {
        const active = [...registry.values()].filter(pet => pet.enabled);
        if (!active.some(pet => pet.quotaVisible)) return null;
        return 60000;
      },
      toJSON() { return { version: 1, hasCreatedPet, pets: copy([...registry.values()]), quota: copy(quota) }; }
    };
  }

  const api = { createStore, THEMES, MAX_ENABLED };
  root.PMPetModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
