import { t } from './i18n'

// A work's short author–year key such as "Nakano13" (D59): one per work across the library, shown wherever the work is.
export function SourceKey({ value, className = '' }: { value: string | null | undefined; className?: string }) {
  return value ? <span className={`source-key ${className}`.trim()} title={t('Source key')}>{value}</span> : null
}
