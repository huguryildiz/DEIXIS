// Fixture-server ports: unique per call and per Playwright worker, so specs can run in parallel workers.
// Each worker gets its own 1000-port block; the counter never hands out the same port twice in a process.
let next = 0

export function nextPort(): number {
  const worker = Number(process.env.TEST_WORKER_INDEX ?? 0)
  return 30000 + worker * 1000 + next++
}

// True once the reading of an sw research's works is settled: the separate fulltext_adjudication run of the legacy
// path, or the discovery run itself when it carries the small-batch inspection (D237, the default since D239).
export function readingDone(view: { runs: Array<{ kind: string; status: string; budget?: { inspection?: { policy?: string } } }> }): boolean {
  return view.runs.some(r => (r.kind === 'fulltext_adjudication' && r.status === 'completed')
    || (r.kind === 'discovery' && r.status === 'completed' && String(r.budget?.inspection?.policy ?? '').startsWith('small_batch')))
}

// The acceptance run can pin the inspection mode for every fixture server it spawns
// (DEIXIS_SMALL_BATCH_INSPECTION=on|off); unset, the fixture follows the product default.
export const modeEnv: Record<string, string> = process.env.DEIXIS_SMALL_BATCH_INSPECTION
  ? { DEIXIS_SMALL_BATCH_INSPECTION: process.env.DEIXIS_SMALL_BATCH_INSPECTION } : {}
