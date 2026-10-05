// Fixture-server ports: unique per call and per Playwright worker, so specs can run in parallel workers.
// Each worker gets its own 1000-port block; the counter never hands out the same port twice in a process.
let next = 0

export function nextPort(): number {
  const worker = Number(process.env.TEST_WORKER_INDEX ?? 0)
  return 30000 + worker * 1000 + next++
}
