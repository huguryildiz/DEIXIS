import { defineConfig } from '@playwright/test'

// A–G browser acceptance run against tests/acceptance/fixture_server.py (synthetic records, scripted model).
const out = process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance'

export default defineConfig({
  testDir: './e2e',
  outputDir: `${out}/artifacts`,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  // A shared GitHub runner is slower and uneven: fewer workers, and one retry so a timing flake shows as flaky, not red.
  workers: process.env.CI ? 2 : 4,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['json', { outputFile: `${out}/results.json` }]],
  use: { channel: 'chrome', headless: true, viewport: { width: 1280, height: 900 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'acceptance' }],
})
