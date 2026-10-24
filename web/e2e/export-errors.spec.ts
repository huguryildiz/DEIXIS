import { expect, test } from '@playwright/test'
import { api, ApiError } from '../src/api'
import { setUiLanguage } from '../src/i18n'

// Client unit tests run in the Playwright runner, without a server, browser, or provider.
for (const format of ['markdown', 'latex'] as const) {
  test(`failed ${format} export returns the Turkish coded-error sentence`, async () => {
    const originalFetch = globalThis.fetch
    setUiLanguage('tr')
    globalThis.fetch = async (input) => {
      expect(String(input)).toContain(`export?format=${format}`)
      return new Response(JSON.stringify({ code: 'disk_full', detail: 'DEIXIS could not save because the disk is full. Free some space and try again.' }), { status: 507 })
    }
    try {
      const call = format === 'markdown' ? api.reportMarkdown : api.reportLatex
      await expect(call('synthetic-research', 'synthetic-report')).rejects.toMatchObject({
        status: 507,
        message: 'Disk dolu olduğu için DEIXIS kaydedemedi. Biraz yer açıp yeniden deneyin.',
      })
    } finally { globalThis.fetch = originalFetch; setUiLanguage('en') }
  })
}

test('export errors retain validation lists, conflict reasons, uncoded detail and non-JSON fallback', async () => {
  const originalFetch = globalThis.fetch
  setUiLanguage('tr')
  try {
    for (const [body, expected] of [
      [{ detail: { errors: ['first', 'second'] } }, { message: 'first · second', errors: ['first', 'second'], reason: null }],
      [{ detail: { message: 'changed', reason: 'row_changed' } }, { message: 'changed', errors: [], reason: 'row_changed' }],
      [{ detail: 'Uncoded provider text' }, { message: 'Uncoded provider text', errors: [], reason: null }],
    ] as const) {
      globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 422 })
      await expect(api.reportMarkdown('r', 'p')).rejects.toMatchObject(expected)
    }
    globalThis.fetch = async () => new Response('not JSON', { status: 503, statusText: 'Unavailable' })
    await expect(api.reportLatex('r', 'p')).rejects.toBeInstanceOf(ApiError)
    await expect(api.reportLatex('r', 'p')).rejects.toMatchObject({ status: 503, message: 'Unavailable' })
  } finally { globalThis.fetch = originalFetch; setUiLanguage('en') }
})
