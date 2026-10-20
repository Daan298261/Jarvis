// RFC-0229 S1: pure, DOM-free button state machine for the Manager controls.
// idle -> pressed (<=100 ms) -> working (spinner + elapsed + phase) -> success (3 s) | failed (until dismissed)
// app.js renders these views; manager-controls.test.mjs exercises them under node --test.

export const PRESSED_MAX_MS = 100
export const SUCCESS_CLEAR_MS = 3000
export const CONTROL_ACTIONS = ['start', 'restart', 'stop']
export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']

const LABELS = { start: 'Start ANZU', restart: 'Restart ANZU', stop: 'Stop ANZU' }
const DEFAULT_PHASE = { start: 'Starting…', restart: 'Stopping…', stop: 'Stopping…' }

export function createControls(actions = CONTROL_ACTIONS) {
  const buttons = {}
  for (const action of actions) buttons[action] = { phase: 'idle' }
  return { running: null, buttons }
}

function withButton(state, action, button, running = state.running) {
  return { running, buttons: { ...state.buttons, [action]: button } }
}

// A press is accepted only when no other control runs. Returns the same state when refused.
export function press(state, action, now) {
  if (state.running || !(action in state.buttons)) return state
  return withButton(state, action, { phase: 'pressed', pressedAt: now, phaseText: DEFAULT_PHASE[action] }, action)
}

export function startWorking(state, action, now) {
  const b = state.buttons[action]
  if (!b || (b.phase !== 'pressed' && b.phase !== 'working')) return state
  return withButton(state, action, { ...b, phase: 'working', workingAt: b.workingAt ?? now })
}

// Phase text reported by GET /api/manager/v1/control/progress for this press only.
export function applyProgress(state, action, progress, requestId) {
  const b = state.buttons[action]
  if (!b || (b.phase !== 'pressed' && b.phase !== 'working')) return state
  if (!progress || !progress.active || progress.action !== action || progress.request_id !== requestId) return state
  if (!progress.phase_text || progress.phase_text === b.phaseText) return state
  return withButton(state, action, { ...b, phaseText: progress.phase_text })
}

export function succeed(state, action, now) {
  const b = state.buttons[action]
  if (!b || state.running !== action) return state
  return withButton(state, action, { phase: 'success', pressedAt: b.pressedAt, finishedAt: now }, null)
}

export function fail(state, action, message, now) {
  const b = state.buttons[action]
  if (!b || state.running !== action) return state
  return withButton(state, action, { phase: 'failed', pressedAt: b.pressedAt, finishedAt: now, message: String(message || 'Failed') }, null)
}

export function dismiss(state, action) {
  const b = state.buttons[action]
  if (!b || b.phase !== 'failed') return state
  return withButton(state, action, { phase: 'idle' })
}

// Time-driven transitions: pressed becomes working after at most 100 ms; success clears after 3 s.
export function tick(state, now) {
  let next = state
  for (const [action, b] of Object.entries(state.buttons)) {
    if (b.phase === 'pressed' && now - b.pressedAt >= PRESSED_MAX_MS) next = startWorking(next, action, b.pressedAt + PRESSED_MAX_MS)
    else if (b.phase === 'success' && now - b.finishedAt >= SUCCESS_CLEAR_MS) next = withButton(next, action, { phase: 'idle' })
  }
  return next
}

export function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return minutes ? `${minutes}m ${String(seconds).padStart(2, '0')}s` : `${seconds}s`
}

// Everything app.js needs to render one control button.
export function view(state, action, now) {
  const b = state.buttons[action]
  const other = state.running && state.running !== action ? state.running : null
  const base = { phase: b.phase, disabled: false, title: '', status: '', message: '', spinner: false, tick: false, dismissible: false }
  if (other) {
    return { ...base, disabled: true, title: `${LABELS[other] || other} is in progress. Wait for it to finish.` }
  }
  switch (b.phase) {
    case 'pressed':
      return { ...base, disabled: true, status: b.phaseText }
    case 'working':
      return { ...base, disabled: true, spinner: true, status: `${b.phaseText} ${formatElapsed(now - b.pressedAt)}` }
    case 'success':
      return { ...base, tick: true, status: `Done in ${formatElapsed(b.finishedAt - b.pressedAt)}` }
    case 'failed':
      return { ...base, message: b.message, dismissible: true }
    default:
      return base
  }
}

// Message for a control that returned 200 but did not reach the wanted state.
export function resultMessage(action, body) {
  if (body && body.ok) return ''
  return action === 'stop' ? 'ANZU still reports running after Stop.' : 'ANZU did not report healthy before the wait ended.'
}

export function makeRequestId(crypto = globalThis.crypto) {
  if (crypto && typeof crypto.randomUUID === 'function') return `ui-${crypto.randomUUID()}`
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

// Debug drawer: keep lines at or above the chosen level.
export function filterLines(lines, minLevel) {
  const floor = LOG_LEVELS.indexOf(minLevel)
  if (floor < 0) return lines.slice()
  return lines.filter((line) => LOG_LEVELS.indexOf(line.level) >= floor)
}

export function formatLine(line) {
  const parts = [line.ts, line.level, line.event]
  if (line.action) parts.push(line.action)
  if (line.request_id) parts.push(`id=${line.request_id}`)
  if (line.duration_ms !== null && line.duration_ms !== undefined) parts.push(`${line.duration_ms} ms`)
  if (line.ok !== null && line.ok !== undefined) parts.push(line.ok ? 'ok' : 'failed')
  if (line.detail !== null && line.detail !== undefined) parts.push(JSON.stringify(line.detail))
  return parts.filter((part) => part !== null && part !== undefined && part !== '').join(' · ')
}
