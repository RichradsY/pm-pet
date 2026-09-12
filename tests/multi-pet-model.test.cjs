const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createStore, THEMES, MAX_ENABLED } = require('../prototypes/multi-pet-model.js');

const conversations = () => Array.from({ length: 6 }, (_, index) => ({
  id: 'conversation-' + index, title: 'Build ' + index, project: 'One shared project'
}));
const make = () => createStore({ sampleConversations: conversations() });
const id = index => 'conversation-' + index;

test('enable is explicit and idempotent at capacity; overflow never evicts', () => {
  const store = make();
  assert.equal(store.list({ enabledOnly: true }).length, 0);
  for (let index = 0; index < MAX_ENABLED; index++) assert.equal(store.enable(id(index)).ok, true);
  assert.equal(new Set(store.list({ enabledOnly: true }).map(pet => pet.theme)).size, 5);
  const full = store.toJSON();
  assert.equal(store.enable(id(0)).ok, true);
  assert.deepEqual(store.enable(id(5)), { ok: false, error: 'capacity' });
  assert.deepEqual(store.toJSON(), full);
  assert.equal(store.enable('unknown').error, 'not-found');
});

test('progress, decisions and preferences are isolated between same-project conversations', () => {
  const store = make();
  store.enable(id(0)); store.enable(id(1));
  const second = store.get(id(1));
  store.ask(id(0), 'Close registration or add a waitlist?');
  assert.equal(store.advance(id(0)).error, 'waiting');
  assert.equal(store.setPhase(id(0), 'building').error, 'waiting');
  assert.equal(store.setPlan(id(0), []).error, 'waiting');
  assert.deepEqual(store.get(id(1)), second);
  assert.equal(store.advance(id(1)).ok, true);
  assert.deepEqual(store.progress(id(0)), { done: 2, total: 5, percent: 40 });
  assert.deepEqual(store.progress(id(1)), { done: 3, total: 5, percent: 60 });
  assert.equal(store.resolve(id(0), ' ').error, 'invalid-value');
  assert.equal(store.resolve(id(0), 'Add a waitlist').ok, true);
  assert.equal(store.advance(id(0)).ok, true);
  assert.equal(store.get(id(0)).decisionHistory[0].answer, 'Add a waitlist');
  assert.equal(store.get(id(1)).decisionHistory.length, 0);
  store.disable(id(0));
  assert.equal(store.advance(id(0)).error, 'disabled');
});

test('only first ever enabled Pet defaults to quota; owner never migrates', () => {
  const store = make();
  store.enable(id(2));
  assert.equal(store.get(id(2)).quotaVisible, true);
  store.disable(id(2));
  store.enable(id(0));
  assert.equal(store.get(id(0)).quotaVisible, false);
  assert.equal(store.pollIntervalMs(), null);
  store.enable(id(2));
  assert.equal(store.get(id(2)).quotaVisible, true);
  store.setQuotaVisible(id(2), false);
  store.disable(id(2)); store.enable(id(2));
  assert.equal(store.get(id(2)).quotaVisible, false);
  store.enable(id(1));
  assert.equal(store.get(id(1)).quotaVisible, false);
  assert.equal(store.pollIntervalMs(), null);
});

test('all-off and per-Pet explicit quota choices persist across restarts and re-enable', () => {
  const store = make();
  store.enable(id(0)); store.enable(id(1));
  store.setQuotaVisible(id(0), false);
  store.setQuotaVisible(id(1), true);
  store.setSize(id(1), 125);
  store.setPosition(id(1), { x: 45, y: 67 });
  store.disable(id(1));
  const restored = createStore({ saved: JSON.stringify(store.toJSON()), sampleConversations: conversations() });
  assert.equal(restored.get(id(0)).quotaVisible, false);
  assert.equal(restored.pollIntervalMs(), null);
  restored.enable(id(1));
  assert.equal(restored.get(id(1)).quotaVisible, true);
  assert.equal(restored.get(id(1)).size, 125);
  assert.deepEqual(restored.get(id(1)).position, { x: 45, y: 67 });
  assert.equal(restored.get(id(1)).theme, store.get(id(1)).theme);
  restored.setQuotaVisible(id(1), false);
  const allOff = createStore({ saved: restored.toJSON() });
  allOff.enable(id(2));
  assert.equal(allOff.list({ enabledOnly: true }).some(pet => pet.quotaVisible), false);
});

test('all five Pets may show quota explicitly without creating five snapshots', () => {
  const store = make();
  for (let index = 0; index < 5; index++) {
    store.enable(id(index)); store.setQuotaVisible(id(index), true);
  }
  store.setQuota({ windows: { week: { remainingPercent: 82, windowDurationMins: 10080 } }, observedAt: 'sample-time' });
  assert.equal(store.list({ enabledOnly: true }).filter(pet => pet.quotaVisible).length, 5);
  assert.deepEqual(Object.keys(store.getQuota().windows), ['week']);
  assert.equal(store.getQuota().windows.five, undefined);
  assert.equal(store.list().some(pet => Object.hasOwn(pet, 'quota')), false);
  const snapshot = store.getQuota();
  snapshot.windows.week.remainingPercent = 3;
  assert.equal(store.getQuota().windows.week.remainingPercent, 82);
  store.setQuota({ windows: { week: { remainingPercent: 71, windowDurationMins: 10080 } }, observedAt: 'new-sample-time' });
  assert.equal(store.toJSON().quota.windows.week.remainingPercent, 71);
});

test('poll cadence is shared at 60s whenever an enabled Pet shows quota, independent of activity', () => {
  const store = make();
  assert.equal(store.pollIntervalMs(), null);
  store.enable(id(0));
  assert.equal(store.pollIntervalMs(), 60000);
  for (const phase of ['planning', 'building', 'checking', 'idle', 'complete']) {
    store.setPhase(id(0), phase);
    assert.equal(store.pollIntervalMs(), 60000, phase + ' does not change the shared cadence');
  }
  store.setPhase(id(0), 'idle');
  store.enable(id(1)); // A hidden running Pet does not change the visible account-wide cadence.
  assert.equal(store.pollIntervalMs(), 60000);
  store.ask(id(1), 'Choose the billing policy');
  assert.equal(store.pollIntervalMs(), 60000);
  store.setQuotaVisible(id(0), false);
  assert.equal(store.pollIntervalMs(), null);
  store.setQuotaVisible(id(1), true);
  assert.equal(store.pollIntervalMs(), 60000);
  store.resolve(id(1), 'Monthly billing');
  assert.equal(store.pollIntervalMs(), 60000);
  store.disable(id(1));
  assert.equal(store.pollIntervalMs(), null);
  store.disable(id(0));
  assert.equal(store.pollIntervalMs(), null);
});

test('all visible Pet copies share one cadence and preserve quota when hidden or disabled', () => {
  const store = make();
  for (let index = 0; index < 5; index++) {
    store.enable(id(index));
    store.setQuotaVisible(id(index), true);
    store.setPhase(id(index), 'idle');
  }
  const snapshot = store.setQuota({ windows: { week: { remainingPercent: 72, windowDurationMins: 10080 } }, observedAt: 'synthetic-observation' });
  assert.equal(store.pollIntervalMs(), 60000);
  for (let index = 0; index < 5; index++) store.setQuotaVisible(id(index), false);
  assert.equal(store.pollIntervalMs(), null);
  assert.deepEqual(store.getQuota(), snapshot);
  store.setQuotaVisible(id(4), true);
  assert.equal(store.pollIntervalMs(), 60000);
  for (let index = 0; index < 5; index++) store.disable(id(index));
  assert.equal(store.pollIntervalMs(), null);
  assert.deepEqual(store.getQuota(), snapshot);
});

test('getters and persistence snapshots cannot mutate state; replacing plan changes honest progress', () => {
  const store = make(); store.enable(id(0));
  const pet = store.get(id(0)); pet.steps[0].done = false;
  const data = store.toJSON(); data.pets[0].theme = 'invalid';
  assert.equal(store.progress(id(0)).done, 2);
  assert.equal(THEMES.includes(store.get(id(0)).theme), true);
  store.setPlan(id(0), [...store.get(id(0)).steps, { id: 'waitlist', label: 'Add waitlist', done: false }]);
  assert.deepEqual(store.progress(id(0)), { done: 2, total: 6, percent: 33 });
  assert.equal(store.progress(id(1)).total, 5);
});

test('released slots accept another conversation while active colors remain distinct', () => {
  const store = make();
  for (let index = 0; index < 5; index++) store.enable(id(index));
  store.disable(id(0));
  assert.equal(store.enable(id(5)).ok, true);
  assert.equal(store.get(id(5)).quotaVisible, false);
  store.disable(id(1));
  assert.equal(store.enable(id(0)).ok, true);
  assert.equal(new Set(store.list({ enabledOnly: true }).map(pet => pet.theme)).size, 5);
});

test('Arrange pets can clear a position without changing another Pet or other preferences', () => {
  const store = make();
  store.setPosition(id(0), { x: 50, y: 80 });
  store.setPosition(id(1), { x: 70, y: 90 });
  store.setSize(id(0), 125);
  assert.equal(store.clearPosition(id(0)).ok, true);
  assert.equal(store.get(id(0)).position, null);
  assert.equal(store.get(id(0)).size, 125);
  assert.deepEqual(store.get(id(1)).position, { x: 70, y: 90 });
  assert.equal(store.clearPosition('unknown').error, 'not-found');
});

test('saved state with duplicate active colors and overflow recovers five distinct active Pets', () => {
  const saved = make().toJSON();
  saved.pets.forEach(pet => {
    pet.enabled = true;
    pet.hasBeenEnabled = true;
    pet.theme = 'sage';
    pet.quotaVisible = false;
  });
  const store = createStore({ saved });
  const active = store.list({ enabledOnly: true });
  assert.equal(active.length, 5);
  assert.deepEqual(active.map(pet => pet.id), conversations().slice(0, 5).map(pet => pet.id));
  assert.equal(new Set(active.map(pet => pet.theme)).size, 5);
  assert.equal(store.get(id(5)).enabled, false);
  assert.equal(store.get(id(5)).title, 'Build 5');
  assert.equal(store.list().some(pet => pet.quotaVisible), false);
  saved.pets[0].steps[0].label = 'External mutation';
  assert.notEqual(store.get(id(0)).steps[0].label, 'External mutation');
});

test('list, decision, mutation-result and quota getters never expose mutable state', () => {
  const store = make();
  const enabled = store.enable(id(0));
  enabled.pet.title = 'Changed';
  store.ask(id(0), 'Choose a policy');
  const asked = store.get(id(0));
  asked.question.text = 'Changed';
  store.resolve(id(0), 'Monthly');
  const pets = store.list();
  pets[0].decisionHistory[0].answer = 'Changed';
  pets[0].steps[0].label = 'Changed';
  pets.pop();
  const quota = store.setQuota({ windows: { week: { remainingPercent: 82, windowDurationMins: 10080 } } });
  quota.windows.week.remainingPercent = 0;
  const actual = store.get(id(0));
  assert.equal(actual.title, 'Build 0');
  assert.equal(actual.decisionHistory[0].text, 'Choose a policy');
  assert.equal(actual.decisionHistory[0].answer, 'Monthly');
  assert.notEqual(actual.steps[0].label, 'Changed');
  assert.equal(store.list().length, 6);
  assert.equal(store.getQuota().windows.week.remainingPercent, 82);
});

test('quota windows are identified by duration; absent or unsupported windows stay omitted', () => {
  const store = make();
  store.setQuota({ windows: { five: { remainingPercent: 82, windowDurationMins: 10080 } } });
  assert.deepEqual(Object.keys(store.getQuota().windows), ['week']);
  assert.equal(store.getQuota().windows.five, undefined);
  store.setQuota({ windows: {
    primary: { remainingPercent: 45, windowDurationMins: 300 },
    secondary: { remainingPercent: 71, windowDurationMins: 10080 },
    week: { remainingPercent: 90, windowDurationMins: 1440 },
    five: { remainingPercent: 50 }
  } });
  assert.deepEqual(Object.keys(store.getQuota().windows), ['five', 'week']);
  assert.equal(store.getQuota().windows.five.remainingPercent, 45);
  assert.equal(store.getQuota().windows.week.remainingPercent, 71);
  store.setQuota({ windows: { five: { remainingPercent: 50 } } });
  assert.deepEqual(store.getQuota().windows, {});
});
