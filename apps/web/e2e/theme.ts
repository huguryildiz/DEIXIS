import { type Page } from '@playwright/test'

// The theme button sits in the sidebar's user row (mockup v24, parity S1). On a phone the sidebar is an off-canvas
// drawer, so the button is pressed by a dispatched click there: opening the drawer would change the page under test.
export async function switchTheme(page: Page, name: string) {
  const button = page.getByRole('button', { name, exact: true })
  if (await page.getByRole('button', { name: 'Open navigation' }).isVisible()) await button.dispatchEvent('click')
  else await button.click()
}
