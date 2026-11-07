// Renders scripts/hero.html to the four README and social hero images in assets/.
//
//     node scripts/hero_shot.mjs [outDir]
//
// Four files, two treatments at two sizes: hero.png and hero-16x9.png are the tilted cut,
// hero-flat.png and hero-flat-16x9.png the straight-on one. The app picture inside them is
// site/shots/answer-dark.jpg, so re-shooting the site screenshots is enough to refresh these.
import { chromium } from '../web/node_modules/playwright/index.mjs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const page_url = 'file://' + resolve(here, 'hero.html')
const out = process.argv[2] ?? resolve(here, '..', 'assets')

const JOBS = [
  { file: 'hero.png', width: 2400, height: 1200, tilt: true },
  { file: 'hero-16x9.png', width: 2560, height: 1440, tilt: true },
  { file: 'hero-flat.png', width: 2400, height: 1200, tilt: false },
  { file: 'hero-flat-16x9.png', width: 2560, height: 1440, tilt: false },
]

const browser = await chromium.launch()
for (const job of JOBS) {
  const page = await browser.newPage({ viewport: { width: job.width, height: job.height }, deviceScaleFactor: 1 })
  await page.goto(page_url, { waitUntil: 'networkidle' })
  if (job.tilt) await page.evaluate(() => document.body.classList.add('tilt'))
  await page.waitForTimeout(400)
  await page.screenshot({ path: resolve(out, job.file) })
  await page.close()
  console.log(job.file, `${job.width}x${job.height}`)
}
await browser.close()
