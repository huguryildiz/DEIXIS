"""Settings reads are cancelled when the page is left and end with a "did not answer" error when they take too long (E25).
Runs apps/web/src/readLimit.ts in node, as test_request_order.py does. Writes do not go through it (their results are
kept); the browser-level checks are in apps/web/e2e/settings.spec.ts."""

import subprocess
from pathlib import Path

PRELUDE = r"""
const fs = require('fs'), ts = require('typescript'), assert = require('assert');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, file);
const { limited, isLeft, gaveNoAnswer } = require('./src/readLimit.ts');
// A read that waits for its signal, as a fetch does: it rejects with an AbortError when the signal fires.
const hang = signal => new Promise((resolve, reject) => {
  const abort = () => reject(new DOMException('aborted', 'AbortError'));
  if (signal.aborted) return abort();  // a fetch given an already-aborted signal rejects at once
  signal.addEventListener('abort', abort, { once: true });
});
const late = () => Object.assign(new Error('late'), { code: 'read_timed_out' });
(async () => {
%s
  console.log('FINISHED');
})().catch(e => { console.error(e); process.exit(1) });
"""


def run_node(body: str):
    root = Path(__file__).resolve().parents[2]
    # Node exits 0 when the script ends with a promise still pending, so the script must say it ran to the end.
    result = subprocess.run(["node", "-e", PRELUDE % body], cwd=root / "apps/web", capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "FINISHED" in result.stdout, "the script did not run to its end"


def test_leaving_cancels_a_pending_read_with_an_abort_not_a_timeout():
    run_node(r"""
const leaving = new AbortController();
const read = limited(hang, leaving.signal, 5000, late);
leaving.abort();
await assert.rejects(read, e => isLeft(e) && gaveNoAnswer(e));
// a read made after the page was left never starts
const gone = new AbortController(); gone.abort();
await assert.rejects(limited(hang, gone.signal, 5000, late), isLeft);
""")


def test_a_hung_read_ends_with_the_did_not_answer_error_not_a_hang():
    run_node(r"""
const started = Date.now();
await assert.rejects(limited(hang, undefined, 40, late), e => e.code === 'read_timed_out' && gaveNoAnswer(e) && !isLeft(e));
assert(Date.now() - started < 1000);
// leaving first, then the time limit passing: the read stays a cancelled one
const leaving = new AbortController();
const read = limited(hang, leaving.signal, 40, late);
leaving.abort();
await assert.rejects(read, isLeft);
""")


def test_an_answer_in_time_passes_through_and_an_ordinary_failure_is_not_a_timeout():
    run_node(r"""
assert.strictEqual(await limited(async () => 7, undefined, 1000, late), 7);
const boom = new Error('HTTP 500');
await assert.rejects(limited(async () => { throw boom }, undefined, 1000, late), e => e === boom && !gaveNoAnswer(e));
""")


def test_a_read_with_no_limit_is_never_cut_however_slow_the_answer_is():
    # Connections, a connection's check, the local tools and the tool checks run CLIs: they are passed `null` and no timer exists.
    run_node(r"""
const real = global.setTimeout, timers = [];
global.setTimeout = (fn, ms, ...rest) => { timers.push(ms); return real(fn, ms, ...rest) };
let finish;
const slow = limited(() => new Promise(resolve => { finish = resolve }), undefined, null, late);
await new Promise(resolve => real(resolve, 50));
assert.deepStrictEqual(timers, []);  // nothing was scheduled that could end the read with "did not answer"
finish('an 80 s health answer');
assert.strictEqual(await slow, 'an 80 s health answer');
// leaving still cancels it
const leaving = new AbortController();
const read = limited(hang, leaving.signal, null, late);
leaving.abort();
await assert.rejects(read, isLeft);
global.setTimeout = real;
""")
    api = (Path(__file__).resolve().parents[2] / "apps/web/src/api.ts").read_text()
    for method in ("connections:", "modelConnection:", "localTools:", "ocr:", "toolUpdate:"):
        line = next(x for x in api.splitlines() if x.strip().startswith(method) and "read<" in x)
        assert line.rstrip().rstrip(",").endswith("null),") or ", null)" in line, line
