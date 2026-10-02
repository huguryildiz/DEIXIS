// An action that removes or disables the control it was pressed with leaves focus on <body>. The caller names the element that now
// carries what the action made; focus goes there once that element exists and focus has been lost. A person who has already moved
// focus elsewhere is not interrupted, the wait ends after `timeout` ms, and it ends at once when the person presses a key or a
// pointer button after it began (a later action of theirs must not be undone by a focus move that was meant for the earlier one). With `follow`, a target that is removed again (a status
// line that goes away when its work is done) is replaced by whatever `find` names next, if focus is lost at that point.
export function focusWhenLost(find: () => HTMLElement | null | undefined, timeout = 2500, follow = false) {
  const end = performance.now() + timeout
  let frame = 0
  let held: HTMLElement | null = null
  const lost = () => { const active = document.activeElement; return !active || active === document.body || !active.isConnected }
  const stop = () => { cancelAnimationFrame(frame); window.removeEventListener('pointerdown', stop, true); window.removeEventListener('keydown', stop, true) }
  window.addEventListener('pointerdown', stop, true)
  window.addEventListener('keydown', stop, true)
  const tick = () => {
    if (held && held.isConnected) { if (performance.now() < end) frame = requestAnimationFrame(tick); else stop(); return }
    held = null
    const target = find()
    if (target && target.getClientRects().length > 0 && lost()) {
      target.focus()
      if (document.activeElement === target) { if (!follow) { stop(); return } held = target }
    }
    if (performance.now() < end) frame = requestAnimationFrame(tick); else stop()
  }
  frame = requestAnimationFrame(tick)
  return stop
}
