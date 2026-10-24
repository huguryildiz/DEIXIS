// Scrolling the page for the reader moves smoothly, unless the reader asked the system to reduce motion.
export const scrollBehavior = (): ScrollBehavior => window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
