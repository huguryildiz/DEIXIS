// An action that removes or disables the control it was pressed with leaves focus on <body>. The caller names the element that now
// carries what the action made; focus goes there once that element exists and focus has been lost. A person who has already moved
// focus elsewhere is not interrupted: the wait ends when another connected element takes focus or after `timeout` ms.
// With `follow`, a target removed again (a status line when its work ends) is replaced by whatever `find` names next,
// if focus is lost at that point. A key or pointer press that leaves focus in place does not end the wait.
export function focusWhenLost(find: () => HTMLElement | null | undefined, timeout = 2500, follow = false, origin: Element | null = document.activeElement) {
  const end = performance.now() + timeout
  let frame = 0
  let held: HTMLElement | null = null
  // `origin` is the control the action was pressed with (a caller whose request is slow passes the element that had focus before it, not the one at the end);
  // it is about to be removed or disabled, so focus still on it is not a move.
  const lost = () => { const active = document.activeElement; return !active || active === document.body || !active.isConnected || active.matches(':disabled') }
  const moved = () => !lost() && document.activeElement !== held && document.activeElement !== origin
  const stop = () => { cancelAnimationFrame(frame); window.removeEventListener('focusin', onFocus, true) }
  const onFocus = () => { if (moved()) stop() }
  window.addEventListener('focusin', onFocus, true)
  const tick = () => {
    if (moved()) { stop(); return }
    if (held && held.isConnected) { if (performance.now() < end) frame = requestAnimationFrame(tick); else stop(); return }
    held = null
    const target = find()
    if (target && target.getClientRects().length > 0 && lost()) {
      held = target
      target.focus()
      if (document.activeElement === target && !follow) { stop(); return }
      if (document.activeElement !== target) held = null
    }
    if (performance.now() < end) frame = requestAnimationFrame(tick); else stop()
  }
  frame = requestAnimationFrame(tick)
  return stop
}
