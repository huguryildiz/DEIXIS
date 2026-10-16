"""The Connections page orders the answers of the all-connections read and of a single-connection check per connection
(E7): an older answer that arrives late is dropped. Runs apps/web/src/requestOrder.ts in node, as the label tests do."""

import subprocess
from pathlib import Path


def test_a_late_older_answer_never_covers_a_newer_one_and_a_released_ticket_holds_nothing_back():
    root = Path(__file__).resolve().parents[2]
    script = r"""
const fs = require('fs'), ts = require('typescript'), assert = require('assert');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, file);
const { createRequestOrder } = require('./src/requestOrder.ts');

// two checks of one connection: the second started later, the first answers last
let order = createRequestOrder();
const first = order.start('gemini'), second = order.start('gemini');
assert(order.settle('gemini', second));
assert(!order.settle('gemini', first));

// a single check starts, the read starts, the check answers while the read is pending: the older check is dropped
order = createRequestOrder();
const early1 = order.start('gemini');
const bulk1 = order.start();
assert(!order.settle('gemini', early1));
assert(order.settle('gemini', bulk1));

// the all-connections read starts first, a single check starts after it: the read must not cover the check
order = createRequestOrder();
const bulk = order.start();
const single = order.start('gemini');
assert(order.settle('gemini', single));
assert(!order.settle('gemini', bulk));
assert(order.settle('openai', bulk));  // a connection nobody checked on its own takes the read

// a single check starts first, the read starts after it and answers first: the late check is dropped
order = createRequestOrder();
const early = order.start('gemini');
const later = order.start();
assert(order.settle('gemini', later));
assert(!order.settle('gemini', early));

// another connection is not affected by gemini's tickets
order = createRequestOrder();
const g = order.start('gemini'), o = order.start('openai');
assert(order.settle('gemini', g) && order.settle('openai', o));

// a read that was cancelled or timed out never answered (E25): its ticket stops holding back an older request still pending
order = createRequestOrder();
const older = order.start('gemini');
const hung = order.start('gemini');
order.release(hung);
assert(order.settle('gemini', older));
order = createRequestOrder();
const olderCheck = order.start('gemini');
const hungRead = order.start();
order.release(hungRead);
assert(order.settle('gemini', olderCheck));
// a released ticket does not stand in for a newer one: a ticket started after it still wins
order = createRequestOrder();
const a = order.start('gemini'), b = order.start('gemini'), c = order.start('gemini');
order.release(b);
assert(!order.settle('gemini', a));
assert(order.settle('gemini', c));
"""
    result = subprocess.run(["node", "-e", script], cwd=root / "apps/web", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
