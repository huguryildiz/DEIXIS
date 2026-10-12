import { expect, type Locator, type Page } from '@playwright/test'
import { switchTheme } from './theme'

// The research page shows one side panel beside the thread (UI parity S7a). Specs open panels and find them through
// these helpers instead of the old research tabs. A panel's URL segment is its name; the old tab names still open
// the same panel (waiting → pdfs, evidence → table, followup → watch, candidates → cands).
export const PANEL_TITLES = {
  sources: 'Sources',
  queue: /^Awaiting your decision \(\d+\)$/,
  pdfs: 'Get more full text',
  table: 'Evidence table',
  watch: 'Follow-up',
  cands: 'Candidates',
  activity: 'Activity',
} as const
export type PanelName = keyof typeof PANEL_TITLES

// The menu row that opens each panel (its name ends with the panel's count, when it has one).
export const MENU_ROWS: Record<PanelName, RegExp> = {
  sources: /^Sources\b/, queue: /^Awaiting your decision\b/, pdfs: /^Get more full text\b/, table: /^Evidence table\b/,
  watch: /^Follow-up\b/, cands: /^Candidates\b/, activity: /^Activity\b/,
}

// The open panel with this title: a labelled region beside the thread on a desktop, a modal dialog at 820px and below.
// A string title matches exactly; panels whose title carries a count take a RegExp.
export function panel(page: Page, title: string | RegExp): Locator {
  const name = typeof title === 'string' ? { name: title, exact: true } : { name: title }
  return page.locator('[data-split-panel]').and(page.getByRole('region', name).or(page.getByRole('dialog', name)))
}

// Opens a panel the way a person does, from the topbar's Research actions menu, and returns it once it shows. In another
// interface language the menu row and the panel title are given: `{ row, title, menu }` (the menu button's name).
export async function openPanel(page: Page, name: PanelName, localized?: { row: RegExp; title: string | RegExp; menu?: string }): Promise<Locator> {
  const opened = panel(page, localized?.title ?? PANEL_TITLES[name])
  // The panel is already open (the URL named it before a reload): nothing to open.
  if (await opened.count()) { await expect(opened).toBeVisible(); return opened }
  // At 820px and below an open panel is a dialog over the top bar, so the menu is reached only once it is closed.
  if (await page.locator('[data-split-panel][role="dialog"]').count()) await closePanel(page)
  await page.getByRole('button', { name: localized?.menu ?? 'Research actions' }).click()
  await page.getByRole('menuitem', { name: localized?.row ?? MENU_ROWS[name] }).click()
  await expect(opened).toBeVisible()
  return opened
}

// Closes the open panel with its Close button (the last control of the panel's head, in any interface language).
export async function closePanel(page: Page) {
  await page.locator('[data-split-panel] .split-panel-head').getByRole('button').last().click()
  await expect(page.locator('[data-split-panel]')).toHaveCount(0)
}

// The open report (an answer's document) and the open source: the panel's content as the old report sheet and Source
// details dialog showed it. Only the panel on top is mounted, so a source opened from the report replaces the report
// until Back.
export const reportPanel = (page: Page) => page.locator('[data-split-panel]').filter({ has: page.locator('.report-document') })
export const sourcePanel = (page: Page) => panel(page, 'Source details')

// Back to the panel below (the report a source was opened from). Escape would end the whole stack.
export async function backPanel(page: Page) {
  await page.locator('[data-split-panel]').getByRole('button', { name: 'Back', exact: true }).click()
}

// The answer sits in the thread, so "going to the Answer" means no panel covers the thread's side.
export async function showAnswer(page: Page) {
  if (await page.locator('[data-split-panel]').count()) await closePanel(page)
}

// The same, by keyboard alone: focus the Research actions button, open its menu with Enter, walk down to the row with
// ArrowDown, and activate it with Enter. Returns once the panel shows.
export async function openPanelByKeyboard(page: Page, name: PanelName): Promise<Locator> {
  const more = page.getByRole('button', { name: 'Research actions' })
  await more.focus()
  await page.keyboard.press('Enter')
  const row = page.getByRole('menuitem', { name: MENU_ROWS[name] })
  await expect(row).toBeVisible()
  for (let i = 0; i < 12 && !(await row.evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('ArrowDown')
  await expect(row).toBeFocused()
  await page.keyboard.press('Enter')
  const opened = panel(page, PANEL_TITLES[name])
  await expect(opened).toBeVisible()
  return opened
}

// A panel's count, which the old tab carried, now sits on its row of the Research actions menu.
export async function expectMenuCount(page: Page, name: PanelName, count: number | string) {
  await page.getByRole('button', { name: 'Research actions' }).click()
  const row = page.getByRole('menuitem', { name: MENU_ROWS[name] })
  await expect(row.locator('.research-tab-count')).toHaveText(String(count))
  await page.keyboard.press('Escape')
  await expect(row).toHaveCount(0)
}

// The theme button, for a spec that is checking something else at a narrow width. At 820px and below an open panel is a dialog over the
// whole screen, and the menu button that opens the drawer holding the theme button is under it, so the click goes to the button directly
// there; with nothing over it, the theme helper presses it the way a person does.
export async function chooseTheme(page: Page, theme: 'light' | 'dark') {
  const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
  if (dark === (theme === 'dark')) return
  const name = dark ? 'Switch to light mode' : 'Switch to dark mode'
  if (await page.locator('[data-split-panel][role="dialog"]').count()) await page.locator(`button[aria-label="${name}"]`).evaluate(el => (el as HTMLElement).click())
  else await switchTheme(page, name)
}
