"""The Connections page orders the answers of the all-connections read and of a single-connection check per connection
(E7): an older answer that arrives late is dropped. Runs apps/web/src/requestOrder.ts in node, as the label tests do."""

import subprocess
from pathlib import Path


def test_a_late_older_answer_never_covers_a_newer_one():
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
"""
    result = subprocess.run(["node", "-e", script], cwd=root / "apps/web", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
