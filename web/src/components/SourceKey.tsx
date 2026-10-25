import { t } from '../lib/i18n'

// A work's author–year–title key such as "nakano2013molecular" (D59, D38): one per work across the library, shown wherever the work is.
export function SourceKey({ value, className = '' }: { value: string | null | undefined; className?: string }) {
  return value ? <span className={`source-key ${className}`.trim()} title={`${t('Source key')}: ${value}`}>{value}</span> : null
}
