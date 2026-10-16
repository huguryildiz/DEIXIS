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
  signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
});
const late = () => Object.assign(new Error('late'), { code: 'read_timed_out' });
(async () => {
%s
})().catch(e => { console.error(e); process.exit(1) });
"""


def run_node(body: str):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["node", "-e", PRELUDE % body], cwd=root / "apps/web", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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
