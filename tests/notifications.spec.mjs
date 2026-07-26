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

  // Seen-on-open: the idempotent read-all fired and the badge cleared. While
  // the page is active the bell reads as its dismiss control.
  await expect.poll(() => state.readAllCalls).toBeGreaterThan(0)
  await expect(page.locator('.notification-bell__badge')).toHaveCount(0)
  await expect(bell).toHaveAccessibleName('Close notifications')

  // The page is ordinary navigation: browser Back leaves it.
  await page.goBack()
  await expect(page.locator('.notifications')).toBeHidden({ timeout: 8000 })
  await expect(bell).toHaveAccessibleName('Notifications')
})

test('the bell TOGGLES: a second tap returns via a real history pop, no dead entry', async ({ page }) => {
  await mockNotifications(page)
  await setup(page)

  await openNotificationsViaBell(page)

  // Second tap dismisses back to the chat surface.
  await page.locator('.notification-bell').click()
  await expect(page.locator('.notifications')).toBeHidden({ timeout: 8000 })
  await page.waitForFunction(
    () => !!(document.querySelector('.chat__empty-wrap')
          || document.querySelector('.chat__scroll')
          || document.querySelector('.chat__form')),
    { timeout: 8000 },
  )

  // The dismissal was a POP of the entry the open pushed — not a new push.
  // Proof: Forward re-enters the notifications page (a dead-entry dismissal
  // would have buried it), and Back leaves it again.
  await page.goForward()
  await expect(page.locator('.notifications')).toBeVisible({ timeout: 8000 })
  await page.goBack()
  await expect(page.locator('.notifications')).toBeHidden({ timeout: 8000 })

  // And the bell still opens it afresh afterwards.
  await openNotificationsViaBell(page)
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

test('phone header layout: 44×44 bell, 99+ badge, Offline pill, brand — no collisions', async ({ page, context }) => {
  // Widest badge state: 120 unread renders as 99+.
  const rows = Array.from({ length: 120 }, (_, i) => ({
    id: `n-bulk-${i}`,
    source_type: 'agent',
    source_id: null,
    title: `Bulk ${i}`,
    body: null,
    icon: null,
    target: null,
    actions: null,
    sent_at: new Date(Date.now() - i * 1000).toISOString(),
    clicked_at: null,
    read_at: null,
  }))
  await mockNotifications(page, { rows })
  await setup(page) // 412×915 phone viewport

  const bell = page.locator('.notification-bell')
  const badge = page.locator('.notification-bell__badge')
  await expect(badge).toHaveText('99+')

  // Touch-target floor: the button's hit area is at least 44×44.
  const bellBox = await bell.boundingBox()
  expect(bellBox.width).toBeGreaterThanOrEqual(44)
  expect(bellBox.height).toBeGreaterThanOrEqual(44)

  // Surface the Offline pill: cut the network so the reachability probe
  // fails (mocked routes keep fulfilling, so the shell itself stays alive).
  await context.setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  const pill = page.locator('.shell__offline')
  await expect(pill).toBeVisible({ timeout: 15000 })

  // Collision guarantees at phone width: every control sits inside the
  // header, and no pair among {brand, Offline pill, bell, badge} overlaps
  // (the badge may only overlap its own bell button).
  const box = async (locator) => await locator.boundingBox()
  const header = await box(page.locator('.shell__bar'))
  const brand = await box(page.locator('.shell__wordmark'))
  const pillBox = await box(pill)
  const bellBox2 = await box(bell)
  const badgeBox = await box(badge)

  const within = (inner, outer) =>
    inner.x >= outer.x - 0.5
    && inner.y >= outer.y - 0.5
    && inner.x + inner.width <= outer.x + outer.width + 0.5
    && inner.y + inner.height <= outer.y + outer.height + 0.5
  const overlaps = (a, b) =>
    a.x < b.x + b.width && b.x < a.x + a.width
    && a.y < b.y + b.height && b.y < a.y + a.height

  for (const [name, b] of [['brand', brand], ['pill', pillBox], ['bell', bellBox2], ['badge', badgeBox]]) {
    expect(within(b, header), `${name} must stay inside the header`).toBe(true)
  }
  const pairs = [
    ['brand', brand, 'pill', pillBox],
    ['brand', brand, 'bell', bellBox2],
    ['brand', brand, 'badge', badgeBox],
    ['pill', pillBox, 'bell', bellBox2],
    ['pill', pillBox, 'badge', badgeBox],
  ]
  for (const [an, a, bn, b] of pairs) {
    expect(overlaps(a, b), `${an} and ${bn} must not overlap`).toBe(false)
  }
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
