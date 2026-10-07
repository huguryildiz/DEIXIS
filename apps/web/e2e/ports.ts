// Fixture-server ports: unique per call and per Playwright worker, so specs can run in parallel workers.
// Each worker gets its own 1000-port block; the counter never hands out the same port twice in a process.
let next = 0

export function nextPort(): number {
  const worker = Number(process.env.TEST_WORKER_INDEX ?? 0)
  return 30000 + worker * 1000 + next++
}

// Discovery owns automatic inspection. Separate reading runs handle a person's files.
export function readingDone(view: { runs: Array<{ kind: string; status: string }> }): boolean {
  return view.runs.some(r => (r.kind === 'discovery' || r.kind === 'fulltext_adjudication') && r.status === 'completed')
}
