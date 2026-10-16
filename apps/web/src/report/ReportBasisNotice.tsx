import type { ReportBasis } from '../api'
import { t } from '../i18n'
import { Notice } from '../Notice'

// The report's basis note (D68): what the table was read from, which cells could not be verified against a quote
// and whose they are, and the advice to upload PDFs. The exports print the same sentences.
export function ReportBasisNotice({ basis }: { basis: ReportBasis }) {
  const short = basis.abstract_only + basis.metadata_only
  return <Notice tone={short || basis.cells_unverified ? 'attention' : 'info'}>
    <p>
      {t(basis.sources === 1 ? 'Basis of this report: {full} of {n} source was read from full text and {short} from the abstract or metadata only.'
        : 'Basis of this report: {full} of {n} sources were read from full text and {short} from the abstract or metadata only.', { full: basis.full_text, n: basis.sources, short })}
      {basis.cells_unverified > 0 && <> {t(basis.cells_total === 1 ? '{u} of {total} table cell could not be verified against a quote; the report does not cite them. They belong to the sources listed below.'
        : '{u} of {total} table cells could not be verified against a quote; the report does not cite them. They belong to the sources listed below.', { u: basis.cells_unverified, total: basis.cells_total })}</>}
      {short > 0 && <> {t('Upload the PDFs of the sources read from the abstract or metadata for a more detailed report.')}</>}
    </p>
    {basis.unverified_sources.length > 0 && <ul>{basis.unverified_sources.map(row => <li key={row.source_version_id}>
      {row.source_key || row.title}: {t('{u} of {total} cells not verified', { u: row.cells_unverified, total: row.cells_total })}</li>)}</ul>}
  </Notice>
}
