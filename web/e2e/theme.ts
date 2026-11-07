import { expect, type Page } from '@playwright/test'

// The theme is switched from the search palette: ⌘K, then "Toggle dark mode". The palette opens over anything, a drawer
// or an open panel included, and the theme command leaves focus where it was.
export async function switchTheme(page: Page, name: string) {
  const toDark = name === 'Switch to dark mode'
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+k' : 'Control+k')
  await page.getByRole('option', { name: 'Toggle dark mode' }).click()
  await expect.poll(() => page.locator('html').evaluate(el => el.classList.contains('dark')),
    `the theme became ${toDark ? 'dark' : 'light'}`).toBe(toDark)
}
