/**
 * Service worker contract — locks in the vite-plugin-pwa migration.
 *
 * The SW source (`frontend/src/sw.js`) is processed by the plugin
 * at build time:
 *   - `precacheAndRoute(self.__WB_MANIFEST)` gets populated with
 *     content-hashed shell assets (no manual VERSION bump).
 *   - Workbox routing rules cover `/vendor/*`, `esm.sh/*`, and
 *     `/api/proxy?url=*.{img/font}` (SWR).
 *   - Push + notificationclick handlers are kept verbatim.
 *
 * What this test guards against: any future refactor that
 * accidentally drops precache injection or runtime caching, or
 * any plugin upgrade that changes the SW URL or cache shape.
 *
 * Run: npx playwright test tests/sw-pwa.spec.mjs
 */
import { test, expect } from '@playwright/test'

const BASE = process.env.MOBIUS_URL || 'http://localhost:8001'


test.describe('Service worker — vite-plugin-pwa contract', () => {

  test('sw.js is served and registers on page load', async ({ page }) => {
    // The SW itself must be reachable at /sw.js and contain the
    // Workbox precache marker. A plugin misconfig that produces
    // an empty SW (or a different filename) would surface here.
    const res = await page.request.get(`${BASE}/sw.js`)
    expect(res.status()).toBe(200)
    const body = await res.text()
    // Workbox precache + routing artifacts visible in the bundled
    // SW. Without precacheAndRoute, the migration is incomplete.
    expect(body).toContain('precache')
    expect(body).toMatch(/mobius-vendor|mobius-esm|mobius-proxy/)
    expect(body).toContain('notificationclick')
  })

  test('manifest is reachable', async ({ page }) => {
    const res = await page.request.get(`${BASE}/manifest.webmanifest`)
    expect(res.status()).toBe(200)
    const m = JSON.parse(await res.text())
    // Bare minimum so a browser will treat the page as installable.
    expect(m.name || m.short_name).toBeTruthy()
    expect(m.icons?.length || 0).toBeGreaterThan(0)
    expect(m.start_url).toBeTruthy()
  })

  test('SW registers + activates after a normal navigation', async ({ page }) => {
    await page.setViewportSize({ width: 412, height: 915 })
    await page.route(/\/api\/chats\/[0-9a-f-]+\/messages$/, route =>
      route.fulfill({ status: 202, body: '{}' })
    )
    await page.route(/\/api\/chats\/[0-9a-f-]+\/stream$/, route =>
      route.fulfill({ status: 204, body: '' })
    )
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    // Wait for the SW to register and reach 'activated'. `ready`
    // resolves at install→activating; activate handlers
    // (cleanupOutdatedCaches + the legacy-cache sweep in our SW)
    // still need to finish before state becomes 'activated'. Poll
    // briefly so we don't race on slower CI runs.
    const swState = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return 'unsupported'
      const reg = await navigator.serviceWorker.ready
      const deadline = Date.now() + 3000
      while (Date.now() < deadline) {
        if (reg.active?.state === 'activated') return 'activated'
        await new Promise(r => setTimeout(r, 50))
      }
      return reg.active?.state ?? 'no-active'
    })
    expect(swState).toBe('activated')

    // The precache cache must exist with at least the shell entry.
    // Workbox names its precache `workbox-precache-v2-<scope>`.
    const cacheStats = await page.evaluate(async () => {
      const keys = await caches.keys()
      const precache = keys.find(k => k.startsWith('workbox-precache'))
      if (!precache) return { keys, precache: null, entries: 0 }
      const c = await caches.open(precache)
      const requests = await c.keys()
      return {
        keys,
        precache,
        entries: requests.length,
        sampleUrls: requests.slice(0, 3).map(r => r.url),
      }
    })
    expect(cacheStats.precache).toBeTruthy()
    // Shell precache should hold the index.html + the bundle +
    // icons. The exact count depends on the build, but >5 is a
    // reasonable floor that catches "manifest injection failed".
    expect(cacheStats.entries).toBeGreaterThan(5)
  })
})
