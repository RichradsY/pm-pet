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
  `${source}\n({ attentionKind, questionState, setupDeferRequest, setupDeferralState, completedTransitions, roadmapState, compactRoadmap })`,
  {},
  { filename: 'native/Resources/pet.html:PET_STATE', timeout: 1000 }
);
const plain = value => JSON.parse(JSON.stringify(value));
const model = pet => plain(state.roadmapState(pet));
const compact = pet => plain(state.compactRoadmap(pet));
const questionModel = pet => plain(state.questionState(pet));
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
  questionModel(next);
  transitions(previous, next);
  assert.equal(JSON.stringify([previous, next]), before);
});

const automaticQuestion = overrides => ({
  id: 'input:synthetic-call', origin: 'codex-input-tool', callId: 'synthetic-call',
  kind: 'input', destination: 'codex', status: 'awaiting_reply',
  text: 'The first question',
  items: [
    { index: 0, questionItemId: 'synthetic-item-a', text: 'The first question', answered: false },
    { index: 1, questionItemId: 'synthetic-item-b', text: 'The second question', answered: false }
  ],
  ...overrides
});

test('question presentation is absent without an active question, even with a queued question', () => {
  assert.equal(questionModel(pet({ pendingQuestions: [automaticQuestion()] })), null);
});

test('legacy questions still await a reply and retain their appropriate action', () => {
  for (const [kind, destination, action] of [
    ['decision', 'codex', 'answer'], ['input', 'codex', 'provide_info'],
    ['input', 'system', 'open_codex'], ['input', 'terminal', 'open_codex']
  ]) {
    const result = questionModel(pet({ question: { id: 'legacy', text: 'A question', kind, destination } }));
    assert.equal(result.status, 'awaiting_reply');
    assert.equal(result.canAnswer, true);
    assert.equal(result.reviewing, false);
    assert.equal(result.action, action);
    assert.equal(result.attention, kind);
    assert.equal(result.itemIndex, null);
  }
});

test('answering one item changes display identity to the next item within the same tool call', () => {
  const first = pet({ question: automaticQuestion() });
  const second = structuredClone(first);
  second.question.items[0].answered = true;
  second.question.items[0].answeredAt = '2026-01-01T12:00:00Z';
  const before = questionModel(first), after = questionModel(second);
  assert.equal(first.question.id, second.question.id);
  assert.equal(before.itemIndex, 0);
  assert.equal(after.itemIndex, 1);
  assert.notEqual(before.key, after.key, 'The view must reset its question scroll for the next item');
  assert.equal(after.text, 'The second question', 'The active item wins over a stale aggregate text');
  assert.equal(after.canAnswer, true);
});

test('ordinary updates and queue changes do not reset the current question scroll identity', () => {
  const before = pet({ question: automaticQuestion() });
  const after = structuredClone(before);
  after.sourceUpdatedAt = '2026-01-01T12:00:00Z';
  after.pendingQuestions = [automaticQuestion({ id: 'input:another-call' })];
  after.question.items[1].answeredAt = '2026-01-01T12:00:01Z';
  assert.equal(questionModel(before).key, questionModel(after).key);
});

test('missing item IDs still distinguish successive questions by their item index', () => {
  const before = pet({ question: automaticQuestion({ items: [
    { index: 4, text: 'First item', answered: false },
    { index: 5, text: 'Second item', answered: false }
  ] }) });
  const after = structuredClone(before);
  after.question.items[0].answered = true;
  assert.notEqual(questionModel(before).key, questionModel(after).key);
  assert.equal(questionModel(after).itemIndex, 5);
});

test('an acknowledged reply awaits review without asking the user to answer again', () => {
  const before = pet({ question: automaticQuestion() });
  const after = structuredClone(before);
  after.question.items.forEach(item => { item.answered = true; });
  after.question.status = 'awaiting_review';
  const result = questionModel(after);
  assert.equal(result.status, 'awaiting_review');
  assert.equal(result.reviewing, true);
  assert.equal(result.canAnswer, false);
  assert.equal(result.action, 'open_codex');
  assert.equal(result.attention, 'review');
  assert.equal(result.itemIndex, null);
  assert.notEqual(result.key, questionModel(before).key);
  assert.deepEqual(statuses(after), [['spec', 'done'], ['build', 'review'], ['verify', 'pending']]);
  assert.deepEqual(after.steps, before.steps, 'Reply review must not complete a delivery item');
  assert.deepEqual(transitions(before, after), [], 'Reply review must not celebrate a completion');
});

test('reviewing a reply hides instructions to supply input in a system window or terminal', () => {
  for (const destination of ['system', 'terminal']) {
    const before = pet({ question: automaticQuestion({ destination }) });
    const after = pet({ question: automaticQuestion({ destination, status: 'awaiting_review' }) });
    assert.equal(questionModel(before).showDestinationHint, true);
    assert.equal(questionModel(after).showDestinationHint, false);
    assert.equal(questionModel(after).action, 'open_codex');
  }
});

test('reviewing a reply without pending delivery work has one review marker and no fabricated step', () => {
  for (const steps of [[], [step('already-done', true)]]) {
    const snapshot = pet({ steps, question: automaticQuestion({ status: 'awaiting_review' }) });
    const result = compact(snapshot);
    assert.equal(result.visible.length, 1);
    assert.equal(result.visible[0].status, 'review');
    assert.equal(result.visible[0].label, 'Reviewing reply');
    assert.equal(result.visible[0].index, undefined);
    assert.equal(model(snapshot).all.filter(item => item.status === 'current').length, 0);
  }
});

const optionalSetup = overrides => pet({ question: {
  id: 'optional-setup', text: 'Configure the optional helper?', kind: 'decision',
  purpose: 'setup', optional: true, status: 'awaiting_reply', ...overrides
} });
const deferRequest = snapshot => plain(state.setupDeferRequest(snapshot));
const deferState = (previous, event) => plain(state.setupDeferralState(previous, event));
const beginDefer = (snapshot = optionalSetup(), token = 'attempt-a') => deferState(null, { type: 'start', pet: snapshot, token });

test('only explicitly optional setup gets Not now, while ordinary questions stay unchanged', () => {
  const result = questionModel(optionalSetup());
  assert.equal(result.setup, true);
  assert.equal(result.optionalSetup, true);
  assert.equal(result.canDefer, true);
  assert.equal(result.action, 'open_codex');
  for (const override of [{ purpose: 'product' }, { purpose: undefined }, { optional: false }, { optional: undefined }, { optional: 'true' }]) {
    assert.equal(questionModel(optionalSetup(override)).canDefer, false);
    assert.equal(deferRequest(optionalSetup(override)), null);
  }
  assert.equal(questionModel(pet({ question: { id: 'ordinary', text: 'Choose a feature' } })).action, 'answer');
});

test('deferral requests identify the current question and binding without approving anything', () => {
  const snapshot = optionalSetup();
  const before = JSON.stringify(snapshot);
  assert.deepEqual(deferRequest(snapshot), {
    action: 'deferSetup', questionId: 'optional-setup', generation: 1
  });
  assert.equal(JSON.stringify(snapshot), before);
  for (const generation of [undefined, null, -1, '1', 1.5]) assert.equal(deferRequest({ ...snapshot, generation }), null);
  assert.equal(deferRequest(optionalSetup({ id: '' })), null);
});

test('reviewing an optional setup reply still waits for review and cannot be deferred again', () => {
  const result = questionModel(optionalSetup({ status: 'awaiting_review' }));
  assert.equal(result.reviewing, true);
  assert.equal(result.canDefer, false);
  assert.equal(result.action, 'open_codex');
  assert.equal(deferRequest(optionalSetup({ status: 'awaiting_review' })), null);
});

test('a pending setup deferral ignores repeated clicks and mismatched acknowledgments', () => {
  const pending = beginDefer();
  assert.equal(pending.status, 'pending');
  assert.deepEqual(deferState(pending, { type: 'start', pet: optionalSetup(), token: 'duplicate-click' }), pending);
  for (const patch of [{ token: 'old-attempt' }, { questionId: 'another-question' }, { generation: 2 }]) {
    assert.deepEqual(deferState(pending, { type: 'finish', token: pending.token, questionId: pending.questionId, generation: pending.generation, ok: true, ...patch }), pending);
  }
});

test('failed setup deferral can retry and a late earlier acknowledgment cannot finish the retry', () => {
  const pending = beginDefer();
  const failed = deferState(pending, { type: 'finish', token: pending.token, questionId: pending.questionId, generation: pending.generation, ok: false });
  assert.equal(failed.status, 'failed');
  assert.match(failed.error, /defer setup/i);
  assert.doesNotMatch(failed.error, /save.*name/i);
  const retry = deferState(failed, { type: 'start', pet: optionalSetup(), token: 'attempt-b' });
  assert.equal(retry.status, 'pending');
  assert.equal(retry.error, null);
  assert.deepEqual(deferState(retry, { type: 'finish', token: pending.token, questionId: pending.questionId, generation: pending.generation, ok: true }), retry);
});

test('both missing acknowledgment and missing state readback restore the setup action after timeout', () => {
  const pending = beginDefer();
  const confirmed = deferState(pending, { type: 'finish', token: pending.token, questionId: pending.questionId, generation: pending.generation, ok: true });
  assert.equal(confirmed.status, 'confirmed');
  for (const waiting of [pending, confirmed]) {
    const expired = deferState(waiting, { type: 'timeout', token: waiting.token });
    assert.equal(expired.status, 'unconfirmed');
    assert.match(expired.error, /unconfirmed/);
    assert.equal(deferState(expired, { type: 'start', pet: optionalSetup(), token: 'retry' }).status, 'pending');
  }
});

test('deferral UI clears on a changed question or binding without touching unrelated questions', () => {
  const pending = beginDefer();
  for (const snapshot of [pet(), optionalSetup({ id: 'new-question' }), optionalSetup({ optional: false }), { ...optionalSetup(), generation: 2 }]) {
    assert.equal(deferState(pending, { type: 'sync', pet: snapshot }), null);
  }
  assert.deepEqual(deferState(pending, { type: 'sync', pet: optionalSetup() }), pending);
});

test('confirmed setup deferral waits for authoritative roadmap review rather than completing work', () => {
  const snapshot = optionalSetup();
  const before = JSON.stringify(snapshot);
  const pending = beginDefer(snapshot);
  const confirmed = deferState(pending, { type: 'finish', token: pending.token, questionId: pending.questionId, generation: pending.generation, ok: true });
  assert.equal(JSON.stringify(snapshot), before);
  assert.equal(questionModel(snapshot).canDefer, true, 'Acknowledgment alone does not rewrite the snapshot');
  const bridgeUpdate = { ...snapshot, question: null, roadmapNeedsUpdate: true };
  assert.equal(deferState(confirmed, { type: 'sync', pet: bridgeUpdate }), null);
  assert.deepEqual(model(bridgeUpdate).all.map(item => item.status), ['done', 'pending', 'pending']);
  assert.deepEqual(transitions(snapshot, bridgeUpdate), []);
});


test('native ack timeout reports an unconfirmed attempt, permits retry, and accepts authoritative readback', () => {
  const snapshot = optionalSetup();
  const pending = beginDefer(snapshot);
  // This is the native eight-second ack callback, not the JS watchdog timer.
  const callback = { type: 'finish', token: pending.token, questionId: pending.questionId,
    generation: pending.generation, outcome: 'unconfirmed', ok: false };
  const uncertain = deferState(pending, callback);
  assert.equal(uncertain.status, 'unconfirmed');
  assert.match(uncertain.error, /unconfirmed/i);
  assert.doesNotMatch(uncertain.error, /could not defer|failed|save.*name/i);
  assert.equal(deferState(uncertain, { type: 'sync', pet: snapshot }).status, 'unconfirmed');
  const retry = deferState(uncertain, { type: 'start', pet: snapshot, token: 'retry-after-native-timeout' });
  assert.equal(retry.status, 'pending');
  assert.notEqual(retry.token, pending.token);
  const eventualBridgeState = { ...snapshot, question: null, roadmapNeedsUpdate: true };
  assert.equal(deferState(uncertain, { type: 'sync', pet: eventualBridgeState }), null);
  assert.equal(deferState(retry, { type: 'sync', pet: eventualBridgeState }), null);
  assert.deepEqual(eventualBridgeState.steps, snapshot.steps);
});

test('a definite native rejection remains distinct from timeout uncertainty', () => {
  const pending = beginDefer();
  const result = deferState(pending, { type: 'finish', token: pending.token,
    questionId: pending.questionId, generation: pending.generation, outcome: 'failed' });
  assert.equal(result.status, 'failed');
  assert.match(result.error, /Could not defer setup/);
});
