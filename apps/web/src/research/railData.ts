import { useEffect, useState } from 'react'

// The rail shows from 1100px (mockup `@media (max-width:1100px){.rail{display:none}}`); below it the panels are reached
// from the ⋯ menu (ResearchView), the answer and the keys.
const RAIL_QUERY = '(min-width: 1100px)'
export function useRailWide() {
  const [wide, setWide] = useState(() => window.matchMedia(RAIL_QUERY).matches)
  useEffect(() => {
    const media = window.matchMedia(RAIL_QUERY)
    const onChange = () => setWide(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return wide
}
