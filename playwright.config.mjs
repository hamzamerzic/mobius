import { defineConfig } from '@playwright/test'

const AUTH_FILE = 'tests/.auth/state.json'

export default defineConfig({
  testDir: './tests',
  timeout: 60000,
  retries: 0,
  use: {
    headless: true,
    ignoreHTTPSErrors: true,
    channel: 'chrome',
  },
  projects: [
    { name: 'auth', testMatch: /auth\.setup\.mjs/ },
    {
      name: 'tests',
      testMatch: /\.spec\.mjs$/,
      dependencies: ['auth'],
      use: { storageState: AUTH_FILE },
    },
  ],
})
