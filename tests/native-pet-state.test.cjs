const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the functions shipped in the native view, without a DOM or a second
// implementation of the state rules. Fixtures contain no real conversations.
const html = readFileSync(path.join(__dirname, '../native/Resources/pet.html'), 'utf8');
const start = '/* PET_STATE_START */';
const end = '/* PET_STATE_END */';
assert.equal(html.split(start).length, 2, 'Native view must expose one state block');
assert.equal(html.split(end).length, 2, 'Native view must expose one state block');
const source = html.split(start)[1].split(end)[0];
const state = vm.runInNewContext(
  `${source}\n({ attentionKind, completedTransitions, roadmapState, compactRoadmap })`,
  {},
  { filename: 'native/Resources/pet.html:PET_STATE', timeout: 1000 }
);
const plain = value => JSON.parse(JSON.stringify(value));
const model = pet => plain(state.roadmapState(pet));
const compact = pet => plain(state.compactRoadmap(pet));
const transitions = (previous, next) => plain(state.completedTransitions(previous, next));
const step = (id, done = false, label = id) => ({ id, done, label });
const pet = overrides => ({
  id: 'synthetic-conversation-a', generation: 1, phase: 'building',
  sourceStatus: 'reported', question: null, roadmapNeedsUpdate: false,
  currentStepId: 'build', currentStep: 'Build the app',
  steps: [step('spec', true), step('build', false, 'Build the app'), step('verify')],
  ...overrides
});
const statuses = snapshot => model(snapshot).all.map(item => [item.id, item.status]);

test('roadmap assigns completed, current, and pending semantic statuses independently', () => {
  assert.deepEqual(statuses(pet()), [
    ['spec', 'done'], ['build', 'current'], ['verify', 'pending']
  ]);
});

test('an explicit currentStepId takes precedence over an ambiguous or stale label', () => {
  const snapshot = pet({ currentStepId: 'verify', currentStep: 'Build the app' });
  assert.deepEqual(statuses(snapshot), [
    ['spec', 'done'], ['build', 'pending'], ['verify', 'current']
  ]);
  snapshot.steps[1].label = snapshot.steps[2].label = 'Same label';
  snapshot.currentStep = 'Same label';
  assert.equal(model(snapshot).all.find(item => item.status === 'current').id, 'verify');
});

test('older reports can locate a pending current item by label', () => {
  const snapshot = pet({ currentStepId: null, currentStep: 'Verify the app' });
  snapshot.steps[2].label = 'Verify the app';
  assert.equal(model(snapshot).all.find(item => item.status === 'current').id, 'verify');
});

test('a completed or missing current ID never makes completed work active', () => {
  for (const id of ['spec', 'absent']) {
    const snapshot = pet({ currentStepId: id, currentStep: 'Unknown item' });
    assert.equal(model(snapshot).all.find(item => item.status === 'current').id, 'build');
    assert.equal(model(snapshot).all[0].status, 'done');
  }
});

test('a decision marks its selected pending step, rather than the current step', () => {
  const snapshot = pet({ question: { id: 'q', text: 'Choose a rule', kind: 'decision', stepId: 'verify' } });
  assert.equal(state.attentionKind(snapshot), 'decision');
  assert.deepEqual(statuses(snapshot), [
    ['spec', 'done'], ['build', 'pending'], ['verify', 'decision']
  ]);
});

test('information requests use the input status for every supported destination', () => {
  for (const destination of ['codex', 'system', 'terminal']) {
    const snapshot = pet({ question: { id: 'q', text: 'Provide information', kind: 'input', destination, stepId: 'verify' } });
    assert.equal(state.attentionKind(snapshot), 'input');
    assert.deepEqual(statuses(snapshot), [
      ['spec', 'done'], ['build', 'pending'], ['verify', 'input']
    ]);
  }
});

test('an untyped legacy question defaults to a decision and uses the current pending item', () => {
  const snapshot = pet({ question: { id: 'q', text: 'Choose a rule' } });
  assert.equal(state.attentionKind(snapshot), 'decision');
  assert.equal(model(snapshot).all[1].status, 'decision');
  assert.equal(state.attentionKind(pet()), null);
});

test('a question cannot mark a completed step as blocked or create an active step', () => {
  const snapshot = pet({ question: { id: 'q', text: 'Choose a rule', kind: 'decision', stepId: 'spec' } });
  const result = model(snapshot);
  assert.equal(result.all[0].status, 'done');
  assert.equal(result.all[1].status, 'decision');
  assert.equal(result.all.filter(item => item.status === 'current').length, 0);
});

test('a fully complete roadmap has no fabricated active item even during a running turn', () => {
  for (const phase of ['building', 'checking', 'complete', 'idle']) {
    const snapshot = pet({ phase, steps: [step('a', true), step('b', true)] });
    assert.deepEqual(model(snapshot).all.map(item => item.status), ['done', 'done']);
  }
});

test('idle, paused, and complete phases do not label unfinished items as active', () => {
  for (const phase of ['idle', 'paused', 'complete', 'error']) {
    assert.deepEqual(model(pet({ phase })).all.map(item => item.status), ['done', 'pending', 'pending']);
  }
});

test('an unavailable, disconnected, or failed source never invents active progress', () => {
  for (const sourceStatus of ['unavailable', 'disconnected', 'error']) {
    assert.deepEqual(model(pet({ sourceStatus })).all.map(item => item.status), ['done', 'pending', 'pending']);
  }
});

test('a roadmap awaiting review keeps known completion but does not assert current work', () => {
  const result = model(pet({ roadmapNeedsUpdate: true }));
  assert.equal(result.reviewing, true);
  assert.deepEqual(result.all.map(item => item.status), ['done', 'pending', 'pending']);
});

test('no reported roadmap produces no synthetic delivery step', () => {
  for (const steps of [[], null, undefined]) {
    const result = model(pet({ steps }));
    assert.deepEqual(result.visible, []);
    assert.equal(result.before, 0);
    assert.equal(result.after, 0);
  }
});

test('the compact view holds at most seven items and accounts for every omitted item', () => {
  for (let count = 0; count <= 100; count++) {
    const steps = Array.from({ length: count }, (_, index) => step(`s${index}`));
    for (const focus of [0, Math.floor(count / 2), count - 1]) {
      const result = model(pet({ steps, currentStepId: `s${focus}` }));
      assert.equal(result.visible.length, Math.min(7, count));
      assert.equal(result.before + result.visible.length + result.after, count);
      assert.ok(result.before >= 0 && result.after >= 0);
      if (count) assert.ok(result.visible.some(item => item.id === `s${focus}`));
    }
  }
});

test('focus windows show correct earlier/later counts at the beginning, middle, and end', () => {
  const steps = Array.from({ length: 20 }, (_, index) => step(`s${index}`));
  for (const [focus, before, after] of [[0, 0, 13], [10, 7, 6], [19, 13, 0]]) {
    const result = model(pet({ steps, currentStepId: `s${focus}` }));
    assert.equal(result.before, before);
    assert.equal(result.after, after);
    assert.equal(result.visible[0].index, before);
  }
});

test('the question step, not an earlier current item, anchors the compact focus window', () => {
  const steps = Array.from({ length: 20 }, (_, index) => step(`s${index}`));
  const result = model(pet({ steps, currentStepId: 's0', question: {
    id: 'q', text: 'Provide information', kind: 'input', stepId: 's18'
  } }));
  assert.equal(result.before, 13);
  assert.equal(result.after, 0);
  assert.equal(result.visible.find(item => item.id === 's18').status, 'input');
});

test('a question after a completed plan remains visible as standalone decision or input attention', () => {
  const steps = Array.from({ length: 20 }, (_, index) => step(`s${index}`, true));
  for (const kind of ['decision', 'input']) {
    const result = compact(pet({ steps, question: { id: 'q', text: 'Needs your response', kind } }));
    assert.equal(result.visible.length, 1);
    assert.equal(result.visible[0].status, kind);
    assert.equal(result.visible[0].label, 'Needs your response');
    assert.equal(result.before, 0);
    assert.equal(result.after, 0);
    assert.ok(result.all.every(item => item.status === 'done'));
  }
});

test('a question without a roadmap has a visible attention item without a fabricated delivery index', () => {
  const result = compact(pet({ steps: [], question: { id: 'q', text: 'Choose the direction', kind: 'decision' } }));
  assert.equal(result.visible.length, 1);
  assert.equal(result.visible[0].status, 'decision');
  assert.equal(result.visible[0].index, undefined);
  assert.deepEqual(result.all, []);
});

test('reviewing a new request replaces old completed dots and overflow with one review signal', () => {
  const steps = Array.from({ length: 20 }, (_, index) => step(`s${index}`, true));
  const result = compact(pet({ steps, roadmapNeedsUpdate: true }));
  assert.equal(result.reviewing, true);
  assert.deepEqual(result.visible.map(item => item.status), ['review']);
  assert.equal(result.before, 0);
  assert.equal(result.after, 0);
  assert.equal(result.all.length, 20, 'Previous roadmap remains available for context');
});

test('an unanswered question takes priority over a generic roadmap review signal', () => {
  for (const steps of [[], [step('a', true)], [step('a')]]) {
    const result = compact(pet({ steps, roadmapNeedsUpdate: true,
      question: { id: 'q', text: 'Information needed', kind: 'input' } }));
    assert.ok(result.visible.some(item => item.status === 'input'));
    assert.ok(result.visible.every(item => item.status !== 'review'));
  }
});

test('ordinary compact roadmaps retain semantic statuses, focus, and overflow counts', () => {
  const snapshot = pet({ steps: Array.from({ length: 20 }, (_, index) => step(`s${index}`)), currentStepId: 's10' });
  assert.deepEqual(compact(snapshot), model(snapshot));
});

test('same completion count can celebrate a different item that actually finished', () => {
  const previous = pet({ steps: [step('a', true), step('b')] });
  const next = pet({ steps: [step('a'), step('b', true)] });
  assert.deepEqual(transitions(previous, next), ['b']);
});

test('newly introduced completed items do not generate a completion celebration', () => {
  const previous = pet({ steps: [step('a'), step('b', true)] });
  const next = pet({ steps: [step('a'), step('b', true), step('new', true)] });
  assert.deepEqual(transitions(previous, next), []);
  next.steps[0].done = true;
  assert.deepEqual(transitions(previous, next), ['a']);
});

test('reordering, removing, or reopening items does not fabricate new completions', () => {
  const previous = pet({ steps: [step('a', true), step('b'), step('c', true)] });
  const next = pet({ steps: [step('c', true), step('b'), step('a')] });
  assert.deepEqual(transitions(previous, next), []);
  assert.deepEqual(transitions(previous, pet({ steps: [step('c', true)] })), []);
});

test('initial connection, replacement conversation, and a new binding generation suppress replay', () => {
  const previous = pet({ steps: [step('a')] });
  const next = pet({ steps: [step('a', true)] });
  assert.deepEqual(transitions(null, next), []);
  assert.deepEqual(transitions(previous, { ...next, id: 'synthetic-conversation-b' }), []);
  assert.deepEqual(transitions(previous, { ...next, generation: 2 }), []);
  assert.deepEqual(transitions(previous, next), ['a']);
});

test('a new question or pending roadmap review suppresses completion motion', () => {
  const previous = pet({ steps: [step('a')] });
  const next = pet({ steps: [step('a', true)] });
  for (const kind of ['decision', 'input']) {
    assert.deepEqual(transitions(previous, { ...next, question: { id: 'q', text: 'Needs a response', kind } }), []);
  }
  assert.deepEqual(transitions(previous, { ...next, roadmapNeedsUpdate: true }), []);
});

test('state derivation leaves the reported roadmap and prior snapshot unchanged', () => {
  const previous = pet();
  const next = pet({ currentStepId: 'verify', question: { id: 'q', text: 'Choose a rule' } });
  const before = JSON.stringify([previous, next]);
  model(next);
  transitions(previous, next);
  assert.equal(JSON.stringify([previous, next]), before);
});
