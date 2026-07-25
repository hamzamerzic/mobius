import { test } from 'node:test'
import assert from 'node:assert/strict'
import * as paneModel from '../paneModel.js'
import * as tabModel from '../tabModel.js'

const { makeTab, notificationsTab, settingsTab, NOTIFICATIONS_TAB_KEY } = tabModel

// A one-pane workspace holding a single chat, through the public seed op.
function onePane(chatId = '5') {
  return paneModel.seedFromFlatTabs([makeTab('chat', chatId)])
}

// ── The model accepts the canonical Notifications tab (builder flag ON in
//    tests: no localStorage in node → the '0' kill switch never fires) ────────

test('sanitize/normalize keeps the canonical notifications:notifications tab', () => {
  let ws = onePane()
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: ws.focusedPaneId, activate: true })
  const pane = ws.panes[ws.focusedPaneId]
  assert.ok(pane.tabs.some(t => tabModel.tabKey(t) === NOTIFICATIONS_TAB_KEY),
    'notifications tab present')
  assert.equal(pane.activeTabKey, NOTIFICATIONS_TAB_KEY, 'notifications tab is active')
  assert.equal(paneModel.normalize(ws), ws, 'already-normalized → same reference')
})

test('normalize drops a NON-canonical notifications id (never coerces it)', () => {
  const ws = onePane()
  const corrupt = {
    ...ws,
    panes: {
      [ws.focusedPaneId]: {
        id: ws.focusedPaneId,
        tabs: [makeTab('chat', '5'), { kind: 'notifications', id: 'other' }],
        activeTabKey: 'chat:5',
      },
    },
  }
  const norm = paneModel.normalize(corrupt)
  const keys = norm.panes[norm.focusedPaneId].tabs.map(tabModel.tabKey)
  assert.deepEqual(keys, ['chat:5'], 'foreign notifications id scrubbed, canonical chat kept')
})

// ── focusedContentRoute teaches the derived triple about Notifications ───────

test('focusedContentRoute reports notifications when it is the focused active tab', () => {
  let ws = onePane()
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: ws.focusedPaneId, activate: true })
  const route = paneModel.focusedContentRoute(ws)
  assert.equal(route.view, 'notifications')
  assert.equal(route.chatId, null)
  assert.equal(route.appId, null)
  assert.equal(route.paneId, ws.focusedPaneId, 'route carries the focused pane hint')
})

test('focusedContentRoute ignores a BACKGROUND notifications tab', () => {
  let ws = onePane()
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: ws.focusedPaneId, activate: true })
  ws = paneModel.setActiveTab(ws, ws.focusedPaneId, 'chat:5')
  const route = paneModel.focusedContentRoute(ws)
  assert.equal(route.view, 'chat', 'a non-active notifications tab does not drive the route')
  assert.equal(route.chatId, '5')
})

// ── The single-world slot never seeds from a takeover tab ────────────────────

test('focusedSlotSeed falls back to the concrete tab when Notifications is active', () => {
  let ws = onePane('5')
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: ws.focusedPaneId, activate: true })
  assert.deepEqual(paneModel.focusedSlotSeed(ws), { kind: 'chat', id: '5' },
    'the chat underneath seeds the slot, never the takeover surface')
})

// ── Legacy rollback projection stays chat/app-only ───────────────────────────

test('flattenRollbackPriority excludes the Notifications tab', () => {
  let ws = onePane()
  ws = paneModel.openTab(ws, makeTab('app', 42), { paneId: ws.focusedPaneId, activate: true })
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: ws.focusedPaneId, activate: true })
  const rollback = paneModel.flattenRollbackPriority(ws)
  assert.ok(!rollback.some(tabModel.isNotificationsTab),
    'notifications never mirrored to the legacy key')
  assert.ok(paneModel.flatten(ws).some(tabModel.isNotificationsTab),
    'flatten (the strip projection) keeps it — a real, tappable tab')
})

// ── Compatibility suite (mirrors settingsTab.test.js §7) ─────────────────────

function twoPanes() {
  let ws = paneModel.seedFromFlatTabs([makeTab('chat', 'c')])
  ws = paneModel.splitPaneWithTab(ws, makeTab('app', 42), { paneId: 'p0', edge: 'right' })
  return paneModel.focusPane(ws, 'p0')
}

test('blob round-trip preserves the Notifications tab (v:1, no migration)', () => {
  let ws = paneModel.openTab(onePane('9'), notificationsTab(), { paneId: 'p0', activate: true })
  ws = paneModel.normalize(ws)
  const restored = paneModel.parseWorkspace(paneModel.serializeWorkspace(ws))
  assert.equal(restored.v, 1, 'blob version unchanged — no migration')
  assert.deepEqual(restored, ws, 'exact round-trip')
  assert.ok(paneModel.paneOf(restored, NOTIFICATIONS_TAB_KEY), 'notifications tab survived')
  assert.equal(paneModel.focusedContentRoute(restored).view, 'notifications')
})

test('flag OFF scrubs a persisted Notifications tab before first render', async () => {
  const onWs = paneModel.openTab(onePane('9'), notificationsTab(), { paneId: 'p0', activate: true })
  const blob = paneModel.serializeWorkspace(onWs)
  assert.ok(paneModel.flatten(onWs).some(tabModel.isNotificationsTab), 'flag-on keeps it')

  const prevLS = globalThis.localStorage
  globalThis.localStorage = { getItem: (k) => (k === 'mobius:builder-settings' ? '0' : null) }
  try {
    const pmOff = await import('../paneModel.js?notifications-flag-off')
    assert.equal(pmOff.BUILDER_SETTINGS_ENABLED, false, 'flag read as off')
    const parsed = pmOff.parseWorkspace(blob)
    assert.ok(!pmOff.flatten(parsed).some(t => t.kind === 'notifications'),
      'the Notifications tab is scrubbed like any unknown kind')
    assert.ok(pmOff.flatten(parsed).some(t => t.kind === 'chat' && t.id === '9'),
      'the chat survives the scrub')
  } finally {
    if (prevLS === undefined) delete globalThis.localStorage
    else globalThis.localStorage = prevLS
  }
})

test('reopening Notifications focuses the existing tab (single instance)', () => {
  let state = paneModel.initialWorkspaceState(twoPanes())
  state = paneModel.workspaceReducer(state, {
    type: 'OPEN_TAB', paneId: 'p0', tab: notificationsTab(), activate: true,
  })
  state = paneModel.workspaceReducer(state, { type: 'FOCUS', paneId: 'p1' })
  state = paneModel.workspaceReducer(state, {
    type: 'OPEN_TAB', paneId: 'p1', tab: notificationsTab(), activate: true,
  })
  const notifTabs = paneModel.flatten(state.ws).filter(tabModel.isNotificationsTab)
  assert.equal(notifTabs.length, 1, 'exactly one Notifications tab workspace-wide')
  assert.equal(paneModel.paneOf(state.ws, NOTIFICATIONS_TAB_KEY).id, 'p0', 'stayed in p0')
  assert.equal(state.ws.focusedPaneId, 'p0', 'reopen focused the existing tab')
})

test('Notifications and Settings are DISTINCT canonical tabs that coexist', () => {
  let ws = onePane('5')
  ws = paneModel.openTab(ws, settingsTab(), { paneId: 'p0', activate: true })
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: 'p0', activate: true })
  const kinds = paneModel.flatten(ws).map(t => t.kind).sort()
  assert.deepEqual(kinds, ['chat', 'notifications', 'settings'],
    'one of each — neither dedups the other away')
  assert.equal(paneModel.focusedContentRoute(ws).view, 'notifications',
    'the most recently activated takeover fronts')
})

test('a mode flip (SET_VIEW_MODE) preserves a builder Notifications tab', () => {
  let state = paneModel.initialWorkspaceState(twoPanes())
  state = paneModel.workspaceReducer(state, {
    type: 'OPEN_TAB', paneId: 'p1', tab: notificationsTab(), activate: true,
  })
  state = paneModel.workspaceReducer(state, { type: 'SET_VIEW_MODE', mode: 'single' })
  assert.ok(paneModel.paneOf(state.ws, NOTIFICATIONS_TAB_KEY),
    'notifications tab survives the flip')
})

test('mode-conversion primitives: open adds the tab, close removes it', () => {
  let ws = onePane('5')
  ws = paneModel.openTab(ws, notificationsTab(), { paneId: 'p0', activate: true })
  assert.equal(paneModel.focusedContentRoute(ws).view, 'notifications')
  ws = paneModel.closeTab(ws, NOTIFICATIONS_TAB_KEY)
  assert.equal(paneModel.paneOf(ws, NOTIFICATIONS_TAB_KEY), null, 'the tab is removed')
  assert.equal(paneModel.focusedContentRoute(ws).view, 'chat', 'the chat re-fronts')
  assert.equal(paneModel.focusedContentRoute(ws).chatId, '5')
})
