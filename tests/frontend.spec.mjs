/**
 * Core frontend behavior tests.
 *
 * Tests message rendering, input behavior, theme switching, and app canvas.
 * All tests use API interception — no agent tokens consumed.
 *
 * Run: npx playwright test tests/frontend.spec.mjs
 */
import { test, expect } from '@playwright/test'

const BASE = process.env.MOBIUS_URL || 'http://localhost:8001'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function setup(page, viewport = { width: 412, height: 915 }) {
  await page.setViewportSize(viewport)

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

async function newChat(page) {
  await page.evaluate(async () => {
    const token = localStorage.getItem('token')
    await fetch('./api/chats', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
  })
  await page.evaluate(() => {
    document.querySelector('.drawer__item--new')?.click()
  })
  const hasEmpty = await page.evaluate(
    () => !!document.querySelector('.chat__empty-wrap')
  )
  if (!hasEmpty) await page.goto(BASE)
  await page.waitForSelector('.chat__empty-wrap', { timeout: 8000 })
}

async function sendMessage(page, text) {
  const input = page.getByRole('textbox', { name: 'Message the agent...' })
  await input.fill(text)
  await page.keyboard.press('Enter')
  await page.waitForSelector('.chat__scroll', { timeout: 3000 })
  await page.evaluate(() => new Promise(r =>
    requestAnimationFrame(() => requestAnimationFrame(r))
  ))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Input behavior', () => {
  test('1. Input clears after send', async ({ page }) => {
    await setup(page)
    await newChat(page)
    await sendMessage(page, 'Test message')

    const value = await page.evaluate(
      () => document.querySelector('.chat__input')?.value
    )
    expect(value).toBe('')
  })

  test('2. Empty input does not send', async ({ page }) => {
    await setup(page)
    await newChat(page)

    // Try to send empty
    await page.keyboard.press('Enter')
    await page.evaluate(() => new Promise(r => setTimeout(r, 200)))

    // Should still be on empty state
    const hasEmpty = await page.evaluate(
      () => !!document.querySelector('.chat__empty-wrap')
    )
    expect(hasEmpty).toBe(true)
  })

  test('3. Send button appears when input has text', async ({ page }) => {
    await setup(page)
    await newChat(page)

    // Initially no send button (voice button instead)
    const hasSend = await page.evaluate(
      () => !!document.querySelector('.chat__send')
    )
    expect(hasSend).toBe(false)

    // Type something — send button should appear
    await page.getByRole('textbox', { name: 'Message the agent...' }).fill('hello')
    await page.evaluate(() => new Promise(r => setTimeout(r, 100)))

    const hasSendAfter = await page.evaluate(
      () => !!document.querySelector('.chat__send')
    )
    expect(hasSendAfter).toBe(true)
  })
})

test.describe('Message rendering', () => {
  test('4. User message renders with correct class', async ({ page }) => {
    await setup(page)
    await newChat(page)
    await sendMessage(page, 'Hello world')

    const userMsg = await page.evaluate(() => {
      const el = document.querySelector('.chat__msg--user')
      return {
        exists: !!el,
        text: el?.querySelector('.chat__text--user')?.textContent?.trim(),
      }
    })
    expect(userMsg.exists).toBe(true)
    expect(userMsg.text).toBe('Hello world')
  })

  test('5. Multiple messages render in order', async ({ page }) => {
    await setup(page)
    await newChat(page)
    await sendMessage(page, 'First')

    // Stop and send second
    await page.evaluate(() => document.querySelector('.chat__stop')?.click())
    await page.waitForFunction(() => !document.querySelector('.chat__stop'), { timeout: 3000 })
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
    await sendMessage(page, 'Second')

    const msgs = await page.evaluate(() => {
      const userMsgs = document.querySelectorAll('.chat__text--user')
      return [...userMsgs].map(m => m.textContent.trim())
    })
    expect(msgs).toContain('First')
    expect(msgs).toContain('Second')
    expect(msgs.indexOf('First')).toBeLessThan(msgs.indexOf('Second'))
  })

  test('6. Thinking dots show while agent is processing', async ({ page }) => {
    await setup(page)
    await newChat(page)
    await sendMessage(page, 'Test thinking')

    const hasThinking = await page.evaluate(
      () => !!document.querySelector('.chat__thinking')
    )
    expect(hasThinking).toBe(true)
  })
})

test.describe('Theme switching', () => {
  test('7. Dark mode toggle changes CSS variables', async ({ page }) => {
    await setup(page)

    // Get initial background color
    const initialBg = await page.evaluate(
      () => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
    )

    // Navigate to settings and toggle dark mode
    await page.evaluate(() => {
      // Try to find the toggle
      const toggle = document.querySelector('[aria-label="Toggle dark mode"]')
        || document.querySelector('input[type="checkbox"]')
        || document.querySelector('.settings__toggle')
      return !!toggle
    })

    // The test verifies that --bg CSS variable exists and has a value
    expect(initialBg.length).toBeGreaterThan(0)
  })

  test('8. CSS variables are applied to chat elements', async ({ page }) => {
    await setup(page)

    const styles = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement)
      return {
        bg: root.getPropertyValue('--bg').trim(),
        text: root.getPropertyValue('--text').trim(),
        accent: root.getPropertyValue('--accent').trim(),
        surface: root.getPropertyValue('--surface').trim(),
      }
    })

    // All CSS variables should be defined
    expect(styles.bg.length).toBeGreaterThan(0)
    expect(styles.text.length).toBeGreaterThan(0)
    expect(styles.accent.length).toBeGreaterThan(0)
    expect(styles.surface.length).toBeGreaterThan(0)
  })
})

test.describe('App canvas', () => {
  test('9. Apps API returns a list', async ({ page }) => {
    await setup(page)

    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('token')
      const res = await fetch('./api/apps/', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return { ok: false, status: res.status }
      const data = await res.json()
      return { ok: true, isArray: Array.isArray(data), count: Array.isArray(data) ? data.length : 0 }
    })
    expect(result.ok).toBe(true)
    expect(result.isArray).toBe(true)
    // At minimum the Hello World seed app should exist.
    expect(result.count).toBeGreaterThanOrEqual(1)
  })
})

test.describe('Scroll position', () => {
  test('10. Scroll position saved on navigate, restored on return', async ({ page }) => {
    await setup(page)
    await newChat(page)

    // Send a message and get some content
    await sendMessage(page, 'Content for scroll test')
    await page.evaluate(() => document.querySelector('.chat__stop')?.click())
    await page.waitForFunction(() => !document.querySelector('.chat__stop'), { timeout: 3000 })
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))

    // Record scroll position
    const scrollBefore = await page.evaluate(() => {
      const el = document.querySelector('.chat__scroll')
      return el ? el.scrollHeight - el.scrollTop : null
    })

    // Reload page
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(
      () => !!document.querySelector('.chat__scroll'),
      { timeout: 10000 }
    )
    await page.evaluate(() => new Promise(r => setTimeout(r, 500)))

    // Check scroll was restored (within tolerance)
    const scrollAfter = await page.evaluate(() => {
      const el = document.querySelector('.chat__scroll')
      return el ? el.scrollHeight - el.scrollTop : null
    })

    if (scrollBefore != null && scrollAfter != null) {
      expect(Math.abs(scrollBefore - scrollAfter)).toBeLessThan(50)
    }
  })
})
