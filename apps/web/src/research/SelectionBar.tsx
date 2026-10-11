import { useEffect, useState } from 'react'
import { ListMinus, ListPlus, Table2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, type TableSummary } from '../api'
import { t } from '../i18n'

// The bar under the Sources list while sources are chosen (D50): a table from them, rows for a table, or removal.
export function SelectionBar({ researchId, count, busy, active, onStartTable, onAddToTable, onRemove, onClear }: { researchId: string; count: number; busy: boolean; active: boolean; onStartTable: () => void; onAddToTable: (table: TableSummary) => void; onRemove: () => void; onClear: () => void }) {
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  useEffect(() => { api.tables(researchId).then(setTables, () => setTables([])) }, [researchId])
  return <div className="selection-bar" role="region" aria-label={t('Chosen sources')}>
    <strong aria-live="polite">{t(count === 1 ? '{n} source chosen' : '{n} sources chosen', { n: count })}</strong>
    <div className="selection-bar-actions">
      <Button size="sm" disabled={busy} onClick={onStartTable}><Table2 size={14} aria-hidden />{t('Start table')}</Button>
      <DropdownMenu>
        <DropdownMenuTrigger disabled={busy || !tables?.length} render={<Button size="sm" variant="outline" />} title={tables && !tables.length ? t('This research has no table yet') : undefined}><ListPlus size={14} aria-hidden />{t('Add to table')}</DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto">{(tables ?? []).map(table => <DropdownMenuItem key={table.id} onClick={() => onAddToTable(table)}><Table2 size={15} />{table.title}</DropdownMenuItem>)}</DropdownMenuContent>
      </DropdownMenu>
      <Button size="sm" variant="outline" disabled={busy || active} title={active ? t('Available when the active run finishes') : undefined} onClick={onRemove}><ListMinus size={14} aria-hidden />{t('Remove from research')}</Button>
      <Button size="sm" variant="ghost" onClick={onClear}>{t('Clear')}</Button>
    </div>
  </div>
}
