"""Run the actual spec helpers with synthetic mutation callbacks and navigations."""
import os
from pathlib import Path
import subprocess


def test_toast_cursor_rejects_old_matches_and_observer_survives_navigation():
    root = Path(__file__).resolve().parents[1]
    spec = Path(os.environ.get("RR_B_REPORT_SPEC", root / "apps/web/e2e/report-edit.spec.ts"))
    code = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ts = require(process.argv[2] + '/apps/web/node_modules/typescript');
const source = fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('async function watchToasts('), end=source.indexOf('const dismissToasts',start);
assert.ok(start>=0,'toast recorder missing');
const js=ts.transpileModule(source.slice(start,end),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
let callback, toast=null;
const context={window:{},document:{querySelector:()=>toast}, MutationObserver: class {constructor(cb){callback=cb} observe(){}},
  expect:{poll: call=>({toBe:async value=>assert.strictEqual(await call(),value)})}};
vm.createContext(context);
vm.runInContext(js+'\nglobalThis.helpers={watchToasts,toastSeen,cursor: typeof toastCursor==="undefined" ? null : toastCursor};',context);
const h=context.helpers;
let init;
const page={addInitScript:async fn=>{init=fn},evaluate:async fn=>vm.runInContext('('+fn.toString()+')()',context)};
const mutation=text=>{toast=text===null?null:{textContent:text};callback()};
const observe=(cursor,pattern)=>h.toastSeen.length===3?h.toastSeen(page,cursor,pattern):h.toastSeen(page,pattern);
(async()=>{
 await h.watchToasts(page);vm.runInContext('('+init.toString()+')()',context);
 mutation('Not applied: earlier action');
 const cursor=h.cursor?await h.cursor(page):context.window.__toasts.length;
 await assert.rejects(()=>observe(cursor,/^Not applied:/),'older match must not satisfy a later action');
 mutation('Not applied: current action');mutation('Column added.');
 await observe(cursor,/^Not applied:/); // visible toast is now different, but observed notice remains evidence
 mutation(null);mutation('Column added.');
 assert.strictEqual(context.window.__toasts.length,4,'a repeated notice after dismissal is another observation');
 context.window={};toast=null;vm.runInContext('('+init.toString()+')()',context);
 assert.strictEqual(context.window.__toasts.length,0);
 mutation('Claim saved.');await observe(0,/^Claim saved\.$/);
 console.log('cursor, replacement, repeated text and navigation checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    done = subprocess.run(["node", "-e", code, str(spec), str(root)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
