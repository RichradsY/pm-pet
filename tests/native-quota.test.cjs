const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = readFileSync(path.join(__dirname, '../native/Resources/pet.html'), 'utf8');
const block = (start, end) => {
  assert.equal(html.split(start).length, 2);
  assert.equal(html.split(end).length, 2);
  return html.split(start)[1].split(end)[0];
};
const stateSource = block('/* PET_STATE_START */', '/* PET_STATE_END */');
const viewSource = block('/* PET_QUOTA_VIEW_START */', '/* PET_QUOTA_VIEW_END */');
const state = vm.runInNewContext(`${stateSource}\n({quotaState})`, {}, { timeout: 1000 });
const now = Date.parse('2026-01-01T12:00:00Z');
const fixture = overrides => ({
  windows: { week: { remainingPercent: 47, windowDurationMins: 10080 } },
  observedAt: '2026-01-01T11:59:00Z', source: 'codex-desktop-account', ...overrides
});
const model = (quota, at = now, visible = true) => JSON.parse(JSON.stringify(state.quotaState(quota, { quotaVisible: visible }, at)));

test('weekly-only accounts show their remaining value without inventing a five-hour window', () => {
  const result = model(fixture());
  assert.deepEqual(result.windows, [{ key: 'week', label: 'Weekly', value: 47, tone: 'mid' }]);
  assert.equal(result.freshness, 'Remaining · Account · 1m ago');
  assert.equal(result.stale, false);
  assert.doesNotMatch(result.freshness, /live/i);
  assert.match(result.tooltip, /2026-01-01T11:59:00.000Z/);
  assert.match(result.tooltip, /Ask Codex to check current usage/);
});

test('quota color thresholds and clamping are preserved independently from freshness', () => {
  for (const [value, expected, tone] of [[-2, 0, 'low'], [0, 0, 'low'], [20, 20, 'low'], [21, 21, 'mid'], [69, 69, 'mid'], [70, 70, 'high'], [100, 100, 'high'], [101, 100, 'high']]) {
    const result = model(fixture({ windows: { five: { remainingPercent: value } }, observedAt: '2026-01-01T10:00:00Z' }));
    assert.deepEqual(result.windows, [{ key: 'five', label: '5h', value: expected, tone }]);
    assert.equal(result.stale, true);
  }
});

test('missing or invalid values remain unavailable, while a supplied zero is valid', () => {
  for (const quota of [null, {}, fixture({ windows: {} }), fixture({ windows: { week: { remainingPercent: '47' }, five: { remainingPercent: NaN } } })]) {
    const result = model(quota);
    assert.deepEqual(result.windows, []);
    assert.equal(result.freshness, 'Waiting for usage');
    assert.match(result.tooltip, /No quota values/);
  }
  assert.equal(model(fixture({ windows: { week: { remainingPercent: 0 } } })).windows[0].value, 0);
});

test('every source becomes clearly cached after five minutes, even authoritative account data', () => {
  for (const source of ['codex-desktop-account', 'codex-cli-verified', 'transcript', 'session', 'app-server', 'unknown']) {
    const quota = fixture({ source, observedAt: new Date(now).toISOString() });
    assert.equal(model(quota, now + 300000).stale, false);
    const aged = model(quota, now + 300001);
    assert.equal(aged.stale, true);
    assert.equal(aged.freshness, 'Remaining · Cached · 5m ago');
    assert.match(aged.tooltip, /Cached snapshot/);
  }
});

test('snapshot age changes without updating quota values or their observed timestamp', () => {
  const quota = fixture({ source: 'transcript', observedAt: new Date(now).toISOString() });
  const saved = JSON.stringify(quota);
  assert.equal(model(quota).freshness, 'Remaining · Chat · just now');
  assert.equal(model(quota, now + 8 * 60000).freshness, 'Remaining · Cached · 8m ago');
  assert.equal(model(quota, now + 50 * 60000).freshness, 'Remaining · Cached · 50m ago');
  assert.equal(model(quota, now + 90 * 60000).ageLabel, '1h ago');
  assert.equal(model(quota, now + 2 * 86400000).ageLabel, '2d ago');
  assert.equal(model(quota, now + 50 * 60000).windows[0].value, 47);
  assert.equal(JSON.stringify(quota), saved);
});

test('unknown, invalid, or future timestamps never make an old number look fresh', () => {
  for (const observedAt of [null, '', 'invalid', new Date(now + 60000).toISOString()]) {
    const result = model(fixture({ observedAt }));
    assert.equal(result.stale, true);
    assert.equal(result.ageMs, null);
    assert.equal(result.freshness, 'Remaining · Cached · age unknown');
    assert.match(result.tooltip, /Ask Codex to check current usage/);
  }
});

test('epoch seconds and milliseconds preserve timestamp provenance; a new snapshot clears stale state', () => {
  for (const observedAt of [now / 1000, now, new Date(now).toISOString()]) {
    assert.equal(model(fixture({ observedAt })).observedAt, '2026-01-01T12:00:00.000Z');
  }
  const old = fixture({ observedAt: new Date(now - 50 * 60000).toISOString() });
  assert.equal(model(old).stale, true);
  const current = fixture({ observedAt: new Date(now).toISOString(), windows: { week: { remainingPercent: 42 } } });
  assert.equal(model(current).stale, false);
  assert.equal(model(current).windows[0].value, 42);
  assert.equal(model(current, now, false).visible, false);
});

test('verified automatic source names the last Desktop match and the actual polling interval', () => {
  for (const [intervalSeconds, cadence] of [[60, /every 60 seconds while working/], [300, /every 5 minutes while idle/], [120, /every 120 seconds/]]) {
    const quota = fixture({ source: 'codex-cli-verified', refresh: { mode: 'automatic', intervalSeconds, nextAttemptAt: '2026-01-01T12:01:00Z' } });
    const result = model(quota);
    assert.equal(result.provenance, 'Auto');
    assert.equal(result.freshness, 'Remaining · Auto · 1m ago');
    assert.match(result.tooltip, /Codex CLI, matched to the last Desktop account check/);
    assert.match(result.tooltip, cadence);
    assert.doesNotMatch(result.tooltip, /permanent|live/i);
    assert.deepEqual(result.windows, model(fixture()).windows);
  }
});

test('refreshing and paused states keep the last observed quota age and value', () => {
  for (const [mode, label] of [['refreshing', 'Checking'], ['paused', 'Paused']]) {
    const result = model(fixture({ source: 'codex-cli-verified', observedAt: '2026-01-01T11:52:00Z', refresh: { mode, intervalSeconds: mode === 'paused' ? null : 60, nextAttemptAt: null } }));
    assert.equal(result.freshness, `Remaining · ${label} · 8m ago`);
    assert.equal(result.stale, true);
    assert.equal(result.windows[0].value, 47);
    assert.equal(result.observedAt, '2026-01-01T11:52:00.000Z');
    assert.match(result.tooltip, mode === 'paused' ? /checks are paused/ : /check is in progress/);
    if (mode === 'paused') assert.doesNotMatch(result.tooltip, /Checks every/);
  }
});

test('a transport failure shows retry only when the bridge actually schedules one', () => {
  const refresh = { mode: 'error', intervalSeconds: 60, nextAttemptAt: '2026-01-01T12:01:00Z', lastAttemptAt: '2026-01-01T12:00:00Z', errorCode: 'timeout' };
  const quota = fixture({ source: 'codex-cli-verified', observedAt: '2026-01-01T11:52:00Z', refresh });
  const saved = JSON.stringify(quota);
  const scheduled = model(quota);
  assert.equal(scheduled.freshness, 'Remaining · Retry · 8m ago');
  assert.equal(scheduled.retryPending, true);
  assert.equal(scheduled.stale, true);
  assert.match(scheduled.tooltip, /Cached snapshot/);
  assert.match(scheduled.tooltip, /timed out/);
  assert.match(scheduled.tooltip, /Next attempt 2026-01-01T12:01:00.000Z/);
  assert.equal(model(quota, now + 60000).ageLabel, '9m ago', 'A failed attempt must not refresh the snapshot timestamp');
  const unscheduled = model({ ...quota, refresh: { ...refresh, nextAttemptAt: null } });
  assert.equal(unscheduled.freshness, 'Remaining · Check failed · 8m ago');
  assert.equal(unscheduled.retryPending, false);
  assert.match(unscheduled.tooltip, /no retry is scheduled/);
  assert.equal(JSON.stringify(quota), saved);
});

test('account verification failures and waiting states remain unavailable without imaginary quota', () => {
  for (const refresh of [
    { mode: 'waiting_for_account', intervalSeconds: null, nextAttemptAt: null },
    ...['account_mismatch', 'auth_metadata_unavailable', 'auth_required', 'account_changed'].map(errorCode => ({ mode: 'error', intervalSeconds: null, nextAttemptAt: null, errorCode }))
  ]) {
    const result = model(fixture({ windows: {}, observedAt: null, refresh }));
    assert.deepEqual(result.windows, []);
    assert.equal(result.accountCheckNeeded, true);
    assert.equal(result.freshness, 'Account check needed');
    assert.equal(result.retryPending, false);
    assert.match(result.tooltip, /Check current usage in Codex/);
    assert.doesNotMatch(result.tooltip, /Checks every|Retry pending/);
  }
  assert.equal(model(fixture({ windows: {}, refresh: { mode: 'error', errorCode: 'server_unavailable', nextAttemptAt: '2026-01-01T12:01:00Z' } })).freshness, 'Usage check failed · Retry pending');
});

test('unrecognized refresh data does not claim a schedule or leak raw error details', () => {
  const result = model(fixture({ refresh: { mode: 'unknown', intervalSeconds: '60', nextAttemptAt: 'invalid', errorCode: 'untrusted raw details' } }));
  assert.equal(result.refreshMode, null);
  assert.equal(result.intervalSeconds, null);
  assert.equal(result.freshness, 'Remaining · Account · 1m ago');
  assert.doesNotMatch(result.tooltip, /every|untrusted raw details/);
});

// Run the shipped view/timer code against a tiny in-memory DOM. This verifies
// idle aging, node preservation, and visibility without a browser or real Pet.
class Element {
  constructor() { this.children = []; this.dataset = {}; this.attributes = {}; this.hidden = false; this.textContent = ''; this.className = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (child.className === selector.slice(1)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}
function viewHarness(surface = 'owl') {
  let clock = now, nextTimer = 0, measurements = 0;
  const timers = new Map(), commands = [];
  const wrap = new Element(), row = new Element(), unavailable = new Element(), freshness = new Element();
  row.className = 'pp-usage-row'; unavailable.className = 'pp-unavailable'; freshness.className = 'native-freshness';
  wrap.append(row, unavailable, freshness);
  const context = vm.createContext({
    surface, currentPet: { quotaVisible: true },
    Date: class extends Date { static now() { return clock; } },
    document: { createElement: () => new Element() },
    $: selector => selector === '.native-quota' ? wrap : wrap.querySelector(selector),
    text: (selector, value) => { wrap.querySelector(selector).textContent = value; },
    measure: () => { measurements++; }, send: command => commands.push(command),
    setInterval: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearInterval: id => timers.delete(id)
  });
  vm.runInContext(`${stateSource}\n${viewSource}\nthis.renderSnapshot = quota;`, context, { timeout: 1000 });
  return {
    wrap, row, freshness, unavailable, timers, commands,
    get measurements() { return measurements; },
    render: (quota, visible = true) => { context.currentPet = { quotaVisible: visible }; context.renderSnapshot(quota, context.currentPet); },
    tick: at => { clock = at; for (const timer of timers.values()) timer.callback(); }
  };
}

test('the native view ages a weekly-only figure while idle without another bridge snapshot', () => {
  const view = viewHarness();
  const quota = fixture({ observedAt: new Date(now).toISOString() });
  view.render(quota);
  const pills = view.row.querySelectorAll('.pp-usage-pill');
  assert.equal(pills.length, 1);
  assert.equal(pills[0].children[0].textContent, 'Weekly');
  assert.equal(pills[0].querySelector('.quota-cache-mark').hidden, true);
  assert.equal(view.timers.size, 1);
  assert.equal([...view.timers.values()][0].delay, 30000);
  const close = view.row.querySelector('.native-quota-close');
  view.tick(now + 8 * 60000);
  assert.equal(view.freshness.textContent, 'Remaining · Cached · 8m ago');
  assert.equal(pills[0].querySelector('.quota-cache-mark').hidden, false);
  assert.match(pills[0].attributes['aria-label'], /47%.*Cached snapshot, 8m ago/);
  assert.match(pills[0].title, /2026-01-01T12:00:00.000Z/);
  assert.equal(view.row.querySelector('.native-quota-close'), close, 'Aging must preserve focused controls');
  assert.ok(view.measurements >= 2, 'Native glass bounds must follow the small stale marker');
  close.onclick();
  assert.equal(view.commands[0].action, 'hideQuota');
});

test('hiding stops the idle timer, restoring recomputes age, and fresh data removes the marker', () => {
  const view = viewHarness();
  const old = fixture({ observedAt: new Date(now).toISOString() });
  view.render(old);
  view.render(old, false);
  assert.equal(view.timers.size, 0);
  assert.equal(view.wrap.hidden, true);
  view.tick(now + 50 * 60000);
  view.render(old);
  assert.equal(view.wrap.hidden, false);
  assert.equal(view.timers.size, 1);
  assert.equal(view.freshness.textContent, 'Remaining · Cached · 50m ago');
  view.render(fixture({ observedAt: new Date(now + 50 * 60000).toISOString(), windows: { week: { remainingPercent: 42 } } }));
  assert.equal(view.row.querySelector('.quota-cache-mark').hidden, true);
  assert.equal(view.row.querySelector('.pp-usage-pill').children[1].textContent, '42%');
  assert.equal(view.freshness.textContent, 'Remaining · Account · just now');
  assert.equal(view.timers.size, 1, 'Snapshot updates must not duplicate the clock');
});

test('unavailable quota and the hidden panel surface do not run redundant clocks', () => {
  const owl = viewHarness(); owl.render(fixture()); owl.render(null);
  assert.equal(owl.row.hidden, true);
  assert.equal(owl.unavailable.hidden, false);
  assert.equal(owl.timers.size, 0);
  const panel = viewHarness('panel'); panel.render(fixture());
  assert.equal(panel.timers.size, 0);
});

test('refresh-only view updates change status without rewriting figures or resetting their age', () => {
  const view = viewHarness();
  const quota = fixture({ source: 'codex-cli-verified', refresh: { mode: 'automatic', intervalSeconds: 60 } });
  view.render(quota);
  const pill = view.row.querySelector('.pp-usage-pill');
  assert.equal(view.freshness.textContent, 'Remaining · Auto · 1m ago');
  view.render({ ...quota, refresh: { mode: 'error', errorCode: 'timeout', intervalSeconds: 60, nextAttemptAt: '2026-01-01T12:01:00Z', lastAttemptAt: '2026-01-01T12:00:00Z' } });
  assert.equal(view.row.querySelector('.pp-usage-pill'), pill);
  assert.equal(pill.children[1].textContent, '47%');
  assert.equal(view.freshness.textContent, 'Remaining · Retry · 1m ago');
  assert.match(pill.title, /matched to the last Desktop account check/);
  assert.match(view.freshness.title, /timed out/);
  assert.equal(view.timers.size, 1);
  view.render({ windows: {}, observedAt: null, refresh: { mode: 'waiting_for_account', intervalSeconds: null } });
  assert.equal(view.row.hidden, true);
  assert.equal(view.unavailable.hidden, false);
  assert.equal(view.freshness.textContent, 'Account check needed');
  assert.equal(view.timers.size, 0);
});
