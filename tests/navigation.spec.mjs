/**
 * Navigation and back button behavior tests.
 *
 * Tests the useNavigation hook: back button between chats, back from app
 * canvas to chat, drawer open/close via back, and pushState/popstate handling.
 *
 * Run:  npx playwright test tests/navigation.spec.mjs
 */
import { test, expect } from '@playwright/test'

const BASE = process.env.MOBIUS_URL || 'http://localhost:8001'

/** Click the Settings entry in the drawer; assumes drawer is open. */
async function navigateToSettings(page) {
  await page.evaluate(() => {
    const buttons = document.querySelectorAll('.drawer button')
    for (const b of buttons) {
      if (b.textContent.trim() === 'Settings') { b.click(); return }
    }
  })
  await page.evaluate(() => new Promise(r => setTimeout(r, 400)))
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function setup(page, viewport = { width: 412, height: 915 }) {
  await page.setViewportSize(viewport)

  // Intercept agent routes.
  await page.route(/\/api\/chats\/[0-9a-f-]+\/messages$/, route =>
    route.fulfill({ status: 202, body: '{}' })
  )
  await page.route(/\/api\/chats\/[0-9a-f-]+\/stream$/, route =>
    route.fulfill({ status: 204, body: '' })
  )
  await page.route('**/api/chat/stop', route =>
    route.fulfill({ status: 200, body: '{}' })
  )

  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => !!(document.querySelector('.chat__empty-wrap')
          || document.querySelector('.chat__scroll')
          || document.querySelector('.chat__form')),
    { timeout: 10000 }
  )
}

/** Read the current navigation state from the app. */
async function getNavState(page) {
  return page.evaluate(() => {
    const chatScroll = document.querySelector('.chat__scroll')
    const emptyWrap = document.querySelector('.chat__empty-wrap')
    const canvas = document.querySelector('.canvas')
    const drawer = document.querySelector('.drawer')

    return {
      hasChat: !!(chatScroll || emptyWrap),
      hasCanvas: !!canvas,
      drawerOpen: drawer?.classList.contains('drawer--open') ?? false,
      activeChatId: localStorage.getItem('moebius_active_chat'),
      url: window.location.pathname,
    }
  })
}

/** Navigate to a chat by clicking in the drawer. */
async function navigateToChat(page, index = 0) {
  await page.evaluate((idx) => {
    const items = document.querySelectorAll('.drawer__item')
    let chatItems = []
    items.forEach(el => {
      if (el.querySelector('.drawer__item-text') && !el.classList.contains('drawer__item--new')) {
        chatItems.push(el)
      }
    })
    if (chatItems[idx]) chatItems[idx].click()
  }, index)
  await page.evaluate(() => new Promise(r => setTimeout(r, 300)))
}

/** Navigate to an app by clicking in the drawer. */
async function navigateToApp(page, index = 0) {
  await page.evaluate((idx) => {
    const appSection = document.querySelector('.drawer__group:last-of-type .drawer__scroll')
      || document.querySelectorAll('.drawer__scroll')[1]
    if (!appSection) return
    const items = appSection.querySelectorAll('button')
    if (items[idx]) items[idx].click()
  }, index)
  await page.evaluate(() => new Promise(r => setTimeout(r, 500)))
}

/** Open the drawer via the toggle button (aria-expanded attribute). */
async function openDrawer(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('[aria-expanded]')
    if (btn && btn.getAttribute('aria-expanded') !== 'true') btn.click()
  })
  await page.evaluate(() => new Promise(r => setTimeout(r, 400)))
}

/** Close the drawer via the toggle button (without navigating). */
async function closeDrawerToggle(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('[aria-expanded]')
    if (btn && btn.getAttribute('aria-expanded') === 'true') btn.click()
  })
  await page.evaluate(() => new Promise(r => setTimeout(r, 400)))
}

/** Trigger browser back via history.back().
 *  Uses evaluate to fire within the SPA rather than Playwright's page.goBack
 *  which triggers a real page navigation. */
async function goBack(page) {
  await page.evaluate(() => history.back())
  await page.evaluate(() => new Promise(r => setTimeout(r, 500)))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Navigation basics', () => {
  test('1. Initial state — chat view, URL is /', async ({ page }) => {
    await setup(page)
    const state = await getNavState(page)
    expect(state.hasChat).toBe(true)
    expect(state.url).toBe('/')
  })

  test('2. Navigate between two chats — back returns to first', async ({ page }) => {
    await setup(page)
    const state1 = await getNavState(page)
    const firstChatId = state1.activeChatId

    // Open drawer and click a different chat.
    await openDrawer(page)
    await navigateToChat(page, 1)
    const state2 = await getNavState(page)

    // Should be on a different chat now.
    if (firstChatId && state2.activeChatId !== firstChatId) {
      // Go back.
      await goBack(page)
      const state3 = await getNavState(page)
      expect(state3.activeChatId).toBe(firstChatId)
    }
  })

  test('3. Drawer open — back closes drawer', async ({ page }) => {
    await setup(page)
    await openDrawer(page)

    const withDrawer = await getNavState(page)
    expect(withDrawer.drawerOpen).toBe(true)

    await goBack(page)
    await page.evaluate(() => new Promise(r => setTimeout(r, 300)))

    const afterBack = await getNavState(page)
    expect(afterBack.drawerOpen).toBe(false)
  })

  test('4. Navigate chat -> app -> back returns to chat', async ({ page }) => {
    await setup(page)
    const initialState = await getNavState(page)
    expect(initialState.hasChat).toBe(true)

    // Try to navigate to an app.
    await openDrawer(page)
    await navigateToApp(page, 0)
    const appState = await getNavState(page)

    if (appState.hasCanvas) {
      // Back should return to chat.
      await goBack(page)
      const backState = await getNavState(page)
      expect(backState.hasChat).toBe(true)
    }
    // If no apps exist, the test passes vacuously.
  })
})

test.describe('Back button edge cases', () => {
  test('5. Multiple navigations — back pops in LIFO order', async ({ page }) => {
    await setup(page)

    // Navigate: chat A -> open drawer -> chat B -> open drawer -> chat C.
    await openDrawer(page)
    await navigateToChat(page, 0)
    const chatA = (await getNavState(page)).activeChatId

    await openDrawer(page)
    await navigateToChat(page, 1)
    const chatB = (await getNavState(page)).activeChatId

    if (chatA && chatB && chatA !== chatB) {
      // Back should return to chat A.
      await goBack(page)
      const afterBack = await getNavState(page)
      expect(afterBack.activeChatId).toBe(chatA)
    }
  })

  test('6. URL stays at / throughout navigation', async ({ page }) => {
    await setup(page)
    expect((await getNavState(page)).url).toBe('/')

    await openDrawer(page)
    await navigateToChat(page, 0)
    expect((await getNavState(page)).url).toBe('/')

    await goBack(page)
    expect((await getNavState(page)).url).toBe('/')
  })

  test('8. Drawer open/close cycles do not leak history entries', async ({ page }) => {
    // Regression guard: each openDrawer() pushes a sentinel history
    // entry so Chrome's back-forward preview shows a clean state.
    // closeDrawer() funnels through history.back() so handleBack pops
    // the sentinel — otherwise every toggle adds a zombie and the user
    // has to press back once per toggle before the app actually
    // navigates anywhere. After one cycle and after five, history.length
    // must match (no growth per cycle).
    await setup(page)

    await openDrawer(page)
    await closeDrawerToggle(page)
    const afterOne = await page.evaluate(() => history.length)

    for (let i = 0; i < 4; i++) {
      await openDrawer(page)
      await closeDrawerToggle(page)
    }
    const afterFive = await page.evaluate(() => history.length)

    expect(afterFive).toBe(afterOne)

    const state = await getNavState(page)
    expect(state.drawerOpen).toBe(false)
  })

  test('9. Drawer close (toggle) on a non-default view stays on that view', async ({ page }) => {
    // Regression guard for the bug where closeDrawer's history.back()
    // was popping the navStack and yanking the user out of the current
    // view. Sequence: navigate to settings, open drawer, close it via
    // the X button — must stay on settings, not pop back to chat.
    await setup(page)

    // Move to a non-default view (settings) so navStack is non-empty.
    await openDrawer(page)
    await navigateToSettings(page)
    const onSettings = await page.evaluate(
      () => !!document.querySelector('.settings')
    )
    expect(onSettings).toBe(true)

    // Open drawer (sentinel + drawer open) and close via the X button.
    await openDrawer(page)
    expect((await getNavState(page)).drawerOpen).toBe(true)

    await closeDrawerToggle(page)
    const stillOnSettings = await page.evaluate(
      () => !!document.querySelector('.settings')
    )
    const afterClose = await getNavState(page)
    expect(afterClose.drawerOpen).toBe(false)
    expect(stillOnSettings).toBe(true)
  })

  test('10. Drawer back-gesture (popstate) closes drawer without navigating', async ({ page }) => {
    // Same regression as #9 but via OS back gesture rather than X
    // button. From settings + drawer-open, history.back() must close
    // the drawer and leave us on settings (not pop navStack).
    await setup(page)

    await openDrawer(page)
    await navigateToSettings(page)
    const onSettings = await page.evaluate(
      () => !!document.querySelector('.settings')
    )
    expect(onSettings).toBe(true)

    await openDrawer(page)
    expect((await getNavState(page)).drawerOpen).toBe(true)

    await goBack(page)

    const stillOnSettings = await page.evaluate(
      () => !!document.querySelector('.settings')
    )
    const afterBack = await getNavState(page)
    expect(afterBack.drawerOpen).toBe(false)
    expect(stillOnSettings).toBe(true)
  })
})

test.describe('Drawer state machine — extended invariants', () => {
  // These tests pin down each state transition of the navigation/drawer
  // state machine. State variables: activeView, drawerOpen, drawerPushed
  // (sentinel pushed on openDrawer, cleared by handleBack or navTo),
  // navStack (pushed by navTo, popped by handleBack).
  //
  // Each test isolates a single transition or invariant. If you change
  // useNavigation.js and a test fails, that test name describes the
  // exact behavior you broke.

  test('11. openDrawer is idempotent — second open while open is a no-op', async ({ page }) => {
    // Without an idempotency guard, every open pushes another sentinel
    // and the user has to press back N times to exit a "stuck" drawer.
    await setup(page)
    const before = await page.evaluate(() => history.length)
    await openDrawer(page)
    const afterFirst = await page.evaluate(() => history.length)
    await openDrawer(page) // already open — must not push another entry
    const afterSecond = await page.evaluate(() => history.length)
    expect(afterFirst - before).toBe(1)
    expect(afterSecond).toBe(afterFirst)
  })

  test('12. closeDrawer when drawer already closed is a no-op', async ({ page }) => {
    // Defensive: someone wires an extra close into a useEffect cleanup
    // that fires when drawer is already closed. Must not call history.back
    // (which would consume the wrong entry).
    await setup(page)
    const before = await page.evaluate(() => history.length)
    await closeDrawerToggle(page) // drawer is already closed
    const after = await page.evaluate(() => history.length)
    expect(after).toBe(before)
  })

  test('13. Drawer open -> nav-to-settings -> back returns to chat (not drawer)', async ({ page }) => {
    // After navTo, the sentinel is "consumed" semantically — drawerPushedRef
    // is false. Back from settings must pop the navStack, not re-open the
    // drawer.
    await setup(page)
    const startId = (await getNavState(page)).activeChatId

    await openDrawer(page)
    await navigateToSettings(page)
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(true)

    await goBack(page)
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(false)
    const after = await getNavState(page)
    expect(after.drawerOpen).toBe(false)
    expect(after.activeChatId).toBe(startId)
    expect(after.hasChat).toBe(true)
  })

  test('14. Drawer open -> nav-to-settings -> drawer-open -> back closes drawer (stays on settings)', async ({ page }) => {
    // After navTo to settings, opening drawer again pushes a NEW sentinel.
    // Back must close the drawer and stay on settings, not pop to chat.
    await setup(page)

    await openDrawer(page)
    await navigateToSettings(page)
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(true)

    await openDrawer(page) // sentinel #2
    expect((await getNavState(page)).drawerOpen).toBe(true)

    await goBack(page)
    expect((await getNavState(page)).drawerOpen).toBe(false)
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(true)
  })

  test('15. Drawer cycles stabilize at +1 history entry, do not grow', async ({ page }) => {
    // Honest documentation of a known browser-API limitation. After the
    // FIRST open/close cycle, history.length is +1 because history.back()
    // doesn't truncate forward entries — the sentinel sits as a stale
    // forward entry. SUBSEQUENT cycles overwrite that forward entry via
    // pushState's natural truncate-forward behavior, so length stops
    // growing. Net cost: one extra back-press to exit the app after
    // touching the drawer at least once. We accept this rather than
    // synthesizing a more complex push/back dance.
    await setup(page)
    const before = await page.evaluate(() => history.length)
    await openDrawer(page)
    await closeDrawerToggle(page)
    const afterOne = await page.evaluate(() => history.length)
    await openDrawer(page)
    await closeDrawerToggle(page)
    const afterTwo = await page.evaluate(() => history.length)
    // First cycle adds at most one stranded forward sentinel.
    expect(afterOne - before).toBeLessThanOrEqual(1)
    // Subsequent cycles must not grow further.
    expect(afterTwo).toBe(afterOne)
  })

  test('16. Settings -> drawer-open -> nav-to-other-chat -> back returns to settings', async ({ page }) => {
    // navStack should record settings as the "previous view"; back from
    // chat must pop to settings, not deeper.
    await setup(page)

    await openDrawer(page)
    await navigateToSettings(page)
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(true)

    await openDrawer(page)
    await navigateToChat(page, 0) // goes to a chat
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(false)

    await goBack(page)
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(true)
  })

  test('17. activeChatId in localStorage matches the displayed chat after back', async ({ page }) => {
    // Sanity: when handleBack pops navStack, the URL/localStorage and
    // displayed view must agree. Decoupling these silently shows the
    // wrong content with the right URL.
    await setup(page)
    const startId = (await getNavState(page)).activeChatId

    await openDrawer(page)
    await navigateToSettings(page)
    await goBack(page)

    const after = await getNavState(page)
    expect(after.activeChatId).toBe(startId)
    expect(after.hasChat).toBe(true)
  })

  test('18. Triple cycle: chat -> settings -> chat -> back -> back exits cleanly', async ({ page }) => {
    // Stress test: navigate forward several steps and back through them,
    // verifying each pop hits the correct prior view.
    await setup(page)
    const startId = (await getNavState(page)).activeChatId

    await openDrawer(page)
    await navigateToSettings(page)
    await openDrawer(page)
    await navigateToChat(page, 0)

    await goBack(page) // -> settings
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(true)

    await goBack(page) // -> chat
    expect(await page.evaluate(() => !!document.querySelector('.settings'))).toBe(false)
    expect((await getNavState(page)).activeChatId).toBe(startId)
  })

  test('19. closeDrawer via toggle and via popstate produce identical state', async ({ page }) => {
    // The drawer-as-back-stack pattern means both close paths funnel
    // through handleBack. They must converge to the same end state.
    await setup(page)

    await openDrawer(page)
    await closeDrawerToggle(page)
    const viaToggle = await getNavState(page)

    await openDrawer(page)
    await goBack(page)
    const viaBack = await getNavState(page)

    expect(viaToggle.drawerOpen).toBe(viaBack.drawerOpen)
    expect(viaToggle.hasChat).toBe(viaBack.hasChat)
    expect(viaToggle.activeChatId).toBe(viaBack.activeChatId)
  })
})

test.describe('Browser restrictions (documented)', () => {
  test('7. Back gesture cannot be overridden on Chrome Android', async ({ page }) => {
    // This test documents the known limitation rather than testing app code.
    // Chrome Android's back gesture (swipe from edge) triggers a full page
    // navigation that shows the cached BFCache snapshot during the swipe
    // animation.  The Navigation API's intercept() cannot prevent this
    // visual artifact — it can only run code after the gesture completes.
    //
    // The app's workaround: openDrawer() pushes a pushState entry so the
    // cached snapshot shows the clean page (no drawer), not the drawer.
    //
    // This test verifies the pushState entry exists after drawer open.
    await setup(page)
    const historyBefore = await page.evaluate(() => history.length)
    await openDrawer(page)
    const historyAfter = await page.evaluate(() => history.length)
    expect(historyAfter).toBe(historyBefore + 1)
  })
})
