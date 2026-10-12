import { spawnSync } from 'node:child_process'

// Fixture-server ports: unique per call and per Playwright worker, so specs can run in parallel workers.
// Each worker gets its own 1000-port block; the counter never hands out the same port twice in a process.
// A port something else already listens on is skipped: a fixture server left running by an earlier or
// another worktree's run would otherwise answer a spec's health check and its requests in place of the
// spec's own server (S23a: followup.spec read a foreign server's providers on 127.0.0.1:33004).
let next = 0
const PROBE = "const s=require('net').createServer();s.once('error',()=>process.exit(1));"
  + "s.listen(Number(process.argv[1]),'127.0.0.1',()=>s.close(()=>process.exit(0)))"

function free(port: number): boolean {
  return spawnSync(process.execPath, ['-e', PROBE, String(port)]).status === 0
}

export function nextPort(): number {
  const worker = Number(process.env.TEST_WORKER_INDEX ?? 0)
  for (;;) {
    const port = 30000 + worker * 1000 + next++
    if (free(port)) return port
  }
}

// Discovery owns automatic inspection. Separate reading runs handle a person's files.
export function readingDone(view: { runs: Array<{ kind: string; status: string }> }): boolean {
  return view.runs.some(r => (r.kind === 'discovery' || r.kind === 'fulltext_adjudication') && r.status === 'completed')
}
