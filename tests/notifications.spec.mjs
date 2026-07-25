/**
 * Notification bell + notifications page.
 *
 * Contract under test (bell → page → seen-on-open):
 *   - the header bell shows the unread count on desktop AND mobile (shared
 *     header markup — same element, both form factors);
 *   - clicking it opens the notifications page as a first-class view;
 *   - opening fires the idempotent read-all (seen-on-open) and the badge
 *     clears;
 *   - browser Back leaves the page like any navigation;
 *   - a row click deep-links through the whitelist parser; a row whose
 *     target fails the parser (app tokens write targets free-form) renders
 *     UNCLICKABLE rather than navigating anywhere.
 *
 * All /api/notifications* traffic is route-mocked (mutable closure state),
 * so the spec neither reads nor writes any backend rows.
 *
 * Run:  scripts/playwright-local.sh --allow-local-e2e tests/notifications.spec.mjs
 */
import { test, expect } from '@playwright/test'

const BASE = process.env.MOBIUS_URL || 'http://localhost:8001'

const CHAT_ID = '20000000-0000-4000-8000-000000000001'
const CHATS = [{
  id: CHAT_ID,
  title: 'Notify Target Chat',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  activity_at: '2026-01-01T00:00:00Z',
  pinned_at: null,
  created_by_app_id: null,
  has_messages: true,
  running: false,
  run_status: null,
}]

function notifRows(now = Date.now()) {
  return [
    {
      id: 'n-chat-target',
      source_type: 'agent',
      source_id: CHAT_ID,
      title: 'Agent finished your task',
      body: 'The summary you asked for is ready.',
      icon: null,
      target: `/shell/?chat=${CHAT_ID}`,
      actions: null,
      sent_at: new Date(now - 60_000).toISOString(),
      clicked_at: null,
      read_at: null,
    },
    {
      id: 'n-hostile-target',
      source_type: 'app',
      source_id: '999',
      title: 'Totally legitimate prize',
      body: 'Click to claim.',
      icon: 'https://evil.example/icon.png',
      target: 'https://evil.example/phish',
      actions: null,
      sent_at: new Date(now - 120_000).toISOString(),
      clicked_at: null,
      read_at: null,
    },
  ]
}

/**
 * Mock the full notification surface with mutable state so read-all actually
 * transitions unread → 0 like the real backend. Returns the state handle.
 */
async function mockNotifications(page, { rows = notifRows() } = {}) {
  const state = {
    rows,
    get unread() { return this.rows.filter(r => r.read_at == null).length },
    readAllCalls: 0,
  }
  await page.route(/\/api\/notifications\/unread-count$/, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ count: state.unread }),
  }))
  await page.route(/\/api\/notifications\/read-all$/, route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const updated = state.unread
    const stamp = new Date().toISOString()
    state.rows = state.rows.map(r => (r.read_at == null ? { ...r, read_at: stamp } : r))
    state.readAllCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ updated }),
    })
  })
  await page.route(/\/api\/notifications(?:\?.*)?$/, route => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(state.rows),
    })
  })
  return state
}

async function setup(page, viewport = { width: 412, height: 915 }) {
  await page.setViewportSize(viewport)
  await page.addInitScript(chatId => {
    localStorage.setItem('moebius_active_chat', chatId)
  }, CHAT_ID)
  await page.route(/\/api\/chats(?:\?.*)?$/, route => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(CHATS),
    })
  })
  await page.route(/\/api\/chats\/([0-9a-f-]+)(?:\?.*)?$/, route => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        messages: [], total: 0, offset: 0, running: false, pending_messages: [],
      }),
    })
  })
  await page.route(/\/api\/chats\/[0-9a-f-]+\/stream$/, route =>
    route.fulfill({ status: 204, body: '' })
  )
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => !!(document.querySelector('.chat__empty-wrap')
          || document.querySelector('.chat__scroll')
          || document.querySelector('.chat__form')),
    { timeout: 10000 },
  )
}

async function openNotificationsViaBell(page) {
  await page.locator('.notification-bell').click()
  await expect(page.locator('.notifications')).toBeVisible()
}

// ---------------------------------------------------------------------------

test('bell badge → page → seen-on-open clears it → Back returns (mobile)', async ({ page }) => {
  const state = await mockNotifications(page)
  await setup(page)

  // The badge reflects the unread count and names it for AT.
  const bell = page.locator('.notification-bell')
  await expect(bell).toBeVisible()
  await expect(page.locator('.notification-bell__badge')).toHaveText('2')
  await expect(bell).toHaveAccessibleName('Notifications, 2 unread')

  await openNotificationsViaBell(page)
  await expect(page.locator('.notifications__row-title').first())
    .toHaveText('Agent finished your task')

  // Seen-on-open: the idempotent read-all fired and the badge cleared.
  await expect.poll(() => state.readAllCalls).toBeGreaterThan(0)
  await expect(page.locator('.notification-bell__badge')).toHaveCount(0)
  await expect(bell).toHaveAccessibleName('Notifications')

  // The page is ordinary navigation: browser Back leaves it.
  await page.goBack()
  await expect(page.locator('.notifications')).toBeHidden({ timeout: 8000 })
})

test('a row with a valid target deep-links; a hostile target is unclickable', async ({ page }) => {
  await mockNotifications(page)
  await setup(page)
  await openNotificationsViaBell(page)

  // The hostile row (cross-origin target, app-authored) renders as plain
  // content — no link affordance exists at all, so there is nothing to click.
  const hostile = page.locator('.notifications__row-item', {
    hasText: 'Totally legitimate prize',
  })
  await expect(hostile.locator('.notifications__row--link')).toHaveCount(0)
  // And its app-authored icon URL is never rendered as an image.
  await expect(page.locator('.notifications img')).toHaveCount(0)

  // The valid row navigates to its chat through the shared parser.
  await page.locator('.notifications__row--link', {
    hasText: 'Agent finished your task',
  }).click()
  await expect(page.locator('.notifications')).toBeHidden({ timeout: 8000 })
  await page.waitForFunction(
    (id) => localStorage.getItem('moebius_active_chat') === id
      && !!(document.querySelector('.chat__empty-wrap')
        || document.querySelector('.chat__scroll')
        || document.querySelector('.chat__form')),
    CHAT_ID,
    { timeout: 8000 },
  )
})

test('the same bell → page → clear flow works at a desktop viewport', async ({ page }) => {
  const state = await mockNotifications(page)
  await setup(page, { width: 1280, height: 800 })

  await expect(page.locator('.notification-bell__badge')).toHaveText('2')
  await openNotificationsViaBell(page)
  await expect(page.locator('.notifications__row-title').first())
    .toHaveText('Agent finished your task')
  await expect.poll(() => state.readAllCalls).toBeGreaterThan(0)
  await expect(page.locator('.notification-bell__badge')).toHaveCount(0)
})
