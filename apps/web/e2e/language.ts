import { expect, type Page } from '@playwright/test'

// The interface language is a command of the search palette (plan §2.4, parity S1): open it with the shortcut, type
// "language", choose the language by its own name. The palette closes and focus goes back to where it was.
export async function chooseLanguage(page: Page, language: 'tr' | 'en') {
  if (await page.locator('html').getAttribute('lang') === language) return  // already shown in it, as pressing the chosen button was
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: /^(Search|Ara)$/ })
  await expect(palette).toBeVisible()
  await palette.getByRole('combobox').fill('language')
  await palette.getByRole('option', { name: language === 'tr' ? 'Türkçe' : 'English', exact: true }).click()
  await expect(palette).toHaveCount(0)
}
