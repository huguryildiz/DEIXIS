import { defineConfig } from '@playwright/test'

// A–G browser acceptance run against tests/acceptance/fixture_server.py (synthetic records, scripted model).
const out = process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance'

export default defineConfig({
  testDir: './e2e',
  outputDir: `${out}/artifacts`,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [['list'], ['json', { outputFile: `${out}/results.json` }]],
  use: { channel: 'chrome', headless: true, viewport: { width: 1280, height: 900 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
