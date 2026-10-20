// RFC-0229 S1 (UX #3): Manager control button feedback state machine + live-UI preservation.
// Run: npm run test:manager-controls (frontend-build job, pr-tests.yml).
import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import { test } from "node:test"

import {
  CONTROL_ACTIONS,
  PRESSED_MAX_MS,
  SUCCESS_CLEAR_MS,
  applyProgress,
  createControls,
  dismiss,
  fail,
  filterLines,
  formatElapsed,
  formatLine,
  makeRequestId,
  press,
  resultMessage,
  startWorking,
  succeed,
  tick,
  view,
} from "../backend/app/manager/static/controls.js"

const staticFile = (name) => readFile(new URL(`../backend/app/manager/static/${name}`, import.meta.url), "utf8")

test("press shows pressed at once and becomes working within 100 ms", () => {
  let s = createControls()
  s = press(s, "restart", 1000)
  assert.equal(s.running, "restart")
  assert.equal(view(s, "restart", 1000).phase, "pressed")
  assert.equal(view(s, "restart", 1000).disabled, true)
  assert.equal(tick(s, 1000 + PRESSED_MAX_MS - 1).buttons.restart.phase, "pressed")
  const working = tick(s, 1000 + PRESSED_MAX_MS)
  assert.equal(PRESSED_MAX_MS, 100)
  assert.equal(working.buttons.restart.phase, "working")
  assert.equal(view(working, "restart", 1000 + PRESSED_MAX_MS).spinner, true)
})

test("working shows spinner, phase text and elapsed through a simulated 30 s restart, then success", () => {
  let s = press(createControls(), "restart", 0)
  s = tick(s, 100)
  assert.equal(view(s, "restart", 100).status, "Stopping… 0s")
  s = applyProgress(s, "restart", { active: true, action: "restart", request_id: "ui-1", phase_text: "Waiting for health…" }, "ui-1")
  const mid = view(s, "restart", 30_000)
  assert.equal(mid.spinner, true)
  assert.equal(mid.status, "Waiting for health… 30s")
  // progress of another press never overwrites this one
  const foreign = applyProgress(s, "restart", { active: true, action: "restart", request_id: "ui-2", phase_text: "Starting…" }, "ui-1")
  assert.equal(foreign, s)
  s = succeed(s, "restart", 30_000)
  const done = view(s, "restart", 30_000)
  assert.equal(done.tick, true)
  assert.equal(done.status, "Done in 30s")
  assert.equal(s.running, null)
})

test("success auto-clears after 3 s", () => {
  let s = succeed(tick(press(createControls(), "start", 0), 100), "start", 5000)
  assert.equal(tick(s, 5000 + SUCCESS_CLEAR_MS - 1).buttons.start.phase, "success")
  assert.equal(SUCCESS_CLEAR_MS, 3000)
  assert.equal(tick(s, 5000 + SUCCESS_CLEAR_MS).buttons.start.phase, "idle")
})

test("failed shows the inline message and stays until dismissed", () => {
  let s = fail(tick(press(createControls(), "stop", 0), 100), "stop", "ANZU stop failed (exit code 3); start was not attempted", 2000)
  for (const later of [5000, 60_000, 3_600_000]) {
    s = tick(s, later)
    const v = view(s, "stop", later)
    assert.equal(v.phase, "failed")
    assert.equal(v.message, "ANZU stop failed (exit code 3); start was not attempted")
    assert.equal(v.dismissible, true)
    assert.equal(v.disabled, false) // it can be pressed again, as before
  }
  s = dismiss(s, "stop")
  assert.equal(view(s, "stop", 0).phase, "idle")
  assert.equal(view(s, "stop", 0).message, "")
})

test("other control buttons are disabled with a reason while one runs", () => {
  let s = press(createControls(), "restart", 0)
  for (const other of ["start", "stop"]) {
    const v = view(s, other, 10)
    assert.equal(v.disabled, true)
    assert.equal(v.title, "Restart ANZU is in progress. Wait for it to finish.")
  }
  assert.equal(press(s, "stop", 20), s) // a second press is refused while one runs
  s = succeed(tick(s, 100), "restart", 500)
  for (const other of ["start", "stop"]) assert.equal(view(s, other, 600).disabled, false)
})

test("startWorking, resultMessage, request ids and elapsed formatting", () => {
  const s = startWorking(press(createControls(), "start", 0), "start", 40)
  assert.equal(s.buttons.start.phase, "working")
  assert.equal(resultMessage("start", { ok: true }), "")
  assert.equal(resultMessage("start", { ok: false }), "ANZU did not report healthy before the wait ended.")
  assert.equal(resultMessage("stop", { ok: false }), "ANZU still reports running after Stop.")
  assert.match(makeRequestId(), /^ui-[A-Za-z0-9-]{8,60}$/)
  assert.match(makeRequestId(null), /^ui-[a-z0-9]+-[a-z0-9]+$/)
  assert.equal(formatElapsed(0), "0s")
  assert.equal(formatElapsed(59_999), "59s")
  assert.equal(formatElapsed(250_000), "4m 10s")
  assert.deepEqual(CONTROL_ACTIONS, ["start", "restart", "stop"])
})

test("debug drawer level filter and line formatting", () => {
  const lines = [
    { ts: "t1", level: "DEBUG", event: "press", action: "start", request_id: "ui-1", duration_ms: null, ok: null, detail: null },
    { ts: "t2", level: "INFO", event: "control_end", action: "start", request_id: "ui-1", duration_ms: 1200, ok: true, detail: null },
    { ts: "t3", level: "WARNING", event: "supervisor", action: "restart", request_id: null, duration_ms: null, ok: null, detail: { attempt: 1 } },
  ]
  assert.deepEqual(filterLines(lines, "INFO").map((l) => l.ts), ["t2", "t3"])
  assert.deepEqual(filterLines(lines, "ERROR"), [])
  assert.equal(filterLines(lines, "DEBUG").length, 3)
  assert.equal(formatLine(lines[1]), "t2 · INFO · control_end · start · id=ui-1 · 1200 ms · ok")
  assert.equal(formatLine(lines[2]), 't3 · WARNING · supervisor · restart · {"attempt":1}')
})

test("live Manager UI is preserved: labels, confirm and alert texts, module script tag", async () => {
  const html = await staticFile("index.html")
  for (const fragment of [
    '<span class="eyebrow">LOCAL CONTROL PLANE</span><h1>ANZU Manager</h1><p id="state">Checking local node…</p>',
    '<button data-action="start">Start ANZU</button>',
    '<button data-action="restart">Restart ANZU</button>',
    '<button class="danger" data-action="stop">Stop ANZU</button>',
    '<button class="quiet" id="quit">Quit Manager</button>',
    '<canvas id="field" aria-hidden="true"></canvas>',
    '<section id="cards" aria-live="polite"></section>',
    '<script type="module" src="/assets/app.js"></script>',
  ]) assert.ok(html.includes(fragment), fragment)
  assert.ok(!html.includes('<script src="/assets/app.js">'))
  const app = await staticFile("app.js")
  for (const fragment of [
    "if(!confirm(`${a[0].toUpperCase()+a.slice(1)} ANZU? Active work can be interrupted.`))return;",
    "catch(e){controls=fail(controls,a,e.message,performance.now());renderControls();alert(e.message)}",
    "if(confirm('Quit ANZU Manager? ANZU will keep running.')) window.__TAURI__?.core?.invoke('quit_manager').catch(()=>alert('Use Quit Manager from the tray when using the browser fallback.'))",
    "state.textContent='Manager service is unavailable.'",
    "['Manager','Loopback only · 127.0.0.1:4782']",
    "refresh();setInterval(refresh,5000);",
    "if(!matchMedia('(prefers-reduced-motion: reduce)').matches)draw();",
    "body:'{\"confirm\":true}'",
  ]) assert.ok(app.includes(fragment), fragment)
  assert.match(app, /^import \{[^}]+\} from '\.\/controls\.js';$/m)
})
