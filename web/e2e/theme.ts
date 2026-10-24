import { expect, type Page } from '@playwright/test'

// The theme button sits in the sidebar's user row (mockup v24, parity S1). On a phone the sidebar is a drawer that is
// inert while closed, so the drawer is opened, the button pressed, and the drawer closed again (focus returns to the
// menu button).
export async function switchTheme(page: Page, name: string) {
  const menu = page.getByRole('button', { name: 'Open navigation' })
  const phone = await menu.isVisible()
  if (phone) await menu.click()
  await page.getByRole('button', { name, exact: true }).click()
  if (phone) {
    await page.getByRole('button', { name: 'Close navigation' }).click()
    await expect(menu).toBeFocused()
  }
}
