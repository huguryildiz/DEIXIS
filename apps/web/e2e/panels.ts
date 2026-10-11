import { expect, type Locator, type Page } from '@playwright/test'

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
const MENU_ROWS: Record<PanelName, RegExp> = {
  sources: /^Sources\b/, queue: /^Awaiting your decision\b/, pdfs: /^Get more full text\b/, table: /^Evidence table\b/,
  watch: /^Follow-up\b/, cands: /^Candidates\b/, activity: /^Activity\b/,
}

// The open panel with this title: a labelled region beside the thread on a desktop, a modal dialog at 820px and below.
// A string title matches exactly; panels whose title carries a count take a RegExp.
export function panel(page: Page, title: string | RegExp): Locator {
  const name = typeof title === 'string' ? { name: title, exact: true } : { name: title }
  return page.locator('[data-split-panel]').and(page.getByRole('region', name).or(page.getByRole('dialog', name)))
}

// Opens a panel the way a person does, from the topbar's Research actions menu, and returns it once it shows.
export async function openPanel(page: Page, name: PanelName): Promise<Locator> {
  await page.getByRole('button', { name: 'Research actions' }).click()
  await page.getByRole('menuitem', { name: MENU_ROWS[name] }).click()
  const opened = panel(page, PANEL_TITLES[name])
  await expect(opened).toBeVisible()
  return opened
}

// Closes the open panel with its Close button.
export async function closePanel(page: Page) {
  await page.locator('[data-split-panel]').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.locator('[data-split-panel]')).toHaveCount(0)
}
