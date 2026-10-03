"""Execute the real inline stop predicates with a JPEG that arrives after 350 ms."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("stage", ["pdf_first_page", "pdf_jump"])
def test_pdf_stop_waits_for_delayed_image_completion(stage):
    script = Path(os.environ.get("RR_B_BROWSER_SCRIPT", Path(__file__).resolve().parents[1] / "scripts/p9/capacity_browser.mjs"))
    code = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8');
const stage = process.argv[2], jump = stage === 'pdf_jump';
const section = source.slice(source.indexOf("await timed('" + stage + "'"));
const predicate = section.match(/await until\(page, `([\s\S]*?)`,/)[1];
let now = 0, rendered = false;
const canvas = { getAttribute: key => key === 'aria-label' ? (jump ? 'p. 400' : 'p. 1') : (rendered ? (jump ? '400' : '1') : null) };
const viewer = {querySelector: key => key === 'canvas' ? canvas : key === '.pdf-document p' ? null : {textContent:'/ 500'}};
const state = {}, first = {};
const context = {performance:{now:()=>now}, document:{querySelector: key => key === '.pdf-viewer' ? viewer : canvas}, window:{
  __h5canvas:()=>({dark:100,digest:rendered?'image':'text',w:100,h:100}), __h5state:state, __h5first:first,
  __h5stable:(key,digest)=>{ if(state[key]!==digest){state[key]=digest;first[key]=now;} return now-first[key]>=100; }
}};
const stop = vm.runInNewContext('(' + predicate + ')', context);
for(now=0;now<=300;now+=50) assert.strictEqual(stop(jump?'old':500),false, 'partial text canvas must not finish while JPEG is loading');
rendered=true;
let result;
for(now=350;now<=500;now+=50) result=stop(jump?'old':500);
assert.ok(result, 'completed image must finish');
console.log(stage + ': waits past delayed JPEG, completed at ' + result.ms + ' ms');
"""
    done = subprocess.run(["node", "-e", code, str(script), stage], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
