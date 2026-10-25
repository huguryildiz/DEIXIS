// Interface language. English text is the key; Turkish renderings live in locales/tr.ts and missing ones fall back to English.
// Model output and source records keep their original language; service errors use localized labels.

import { tr } from './locales/tr'

export type UiLanguage = 'en' | 'tr'

const STORAGE_KEY = 'deixis-ui-language'

function readStored(): UiLanguage {
  try { return localStorage.getItem(STORAGE_KEY) === 'tr' ? 'tr' : 'en' } catch { return 'en' }
}

let current: UiLanguage = readStored()

export const uiLanguage = () => current
export const uiLocale = () => (current === 'tr' ? 'tr-TR' : 'en-US')

export function setUiLanguage(next: UiLanguage) {
  current = next
  try { localStorage.setItem(STORAGE_KEY, next) } catch { /* the choice still applies for this tab */ }
}

export function t(text: string, vars?: Record<string, string | number>): string {
  const template = current === 'tr' ? tr[text] ?? text : text
  return vars ? template.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match)) : template
}

// One English word can need two Turkish renderings ("Open" the verb is "Aç", the candidate status is "Açık"). A
// contextual entry `context::English` wins in Turkish; English shows the plain text, and a missing contextual entry
// falls back to the plain one.
export function tc(context: string, text: string, vars?: Record<string, string | number>): string {
  const template = current === 'tr' ? tr[`${context}::${text}`] ?? tr[text] ?? text : text
  return vars ? template.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match)) : template
}
