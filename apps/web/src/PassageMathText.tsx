import type { ReactNode } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { MathText } from './MathText'

type FormulaRule = { pattern: RegExp; latex: string }

// pypdf flattens super/subscripts and fractions. These deliberately narrow rules
// recover only notation whose complete structure is still identifiable in the
// extracted string. Everything else remains verbatim instead of being guessed.
const FORMULAS: FormulaRule[] = [
  { pattern: /p\s*e\s*=\s*Q\s*\(\s*√\s*2\s*E\s*b\s*(?:\/|\s)\s*N\s*[O0]\s*\)/giu,
    latex: String.raw`p_e = Q\!\left(\sqrt{\frac{2E_b}{N_0}}\right)` },
  { pattern: /E\s*b\s*(?:\/|\s)\s*N\s*[O0]\s*=\s*ψ\s*i\s*j\s*\(\s*l\s*\)\s*G\s*P/giu,
    latex: String.raw`\frac{E_b}{N_0} = \psi_{ij}(l)G_P` },
  { pattern: /p\s*s\s*i\s*j\s*\(\s*l\s*,\s*[ϕφ]\s*\)\s*=\s*\(\s*1\s*[−-]\s*Q\s*\(\s*√\s*16\s*ψ\s*i\s*j\s*\(\s*l\s*\)\s*\)\s*\)\s*8\s*[ϕφ]/giu,
    latex: String.raw`p^s_{ij}(l,\phi)=\left(1-Q\!\left(\sqrt{16\psi_{ij}(l)}\right)\right)^{8\phi}` },
  { pattern: /p\s*f\s*i\s*j\s*\(\s*l\s*,\s*[ϕφ]\s*\)\s*=\s*1\s*[−-]\s*p\s*s\s*i\s*j\s*\(\s*l\s*,\s*[ϕφ]\s*\)/giu,
    latex: String.raw`p^f_{ij}(l,\phi)=1-p^s_{ij}(l,\phi)` },
  { pattern: /p\s*HS\s*,\s*s\s*i\s*j\s*\(\s*l\s*,\s*k\s*\)\s*=\s*p\s*s\s*i\s*j\s*\(\s*l\s*,\s*M\s*P\s*\)\s*[×x]\s*p\s*s\s*j\s*i\s*\(\s*k\s*,\s*M\s*A\s*\)/giu,
    latex: String.raw`p^{\mathrm{HS},s}_{ij}(l,k)=p^s_{ij}(l,M_P)\,p^s_{ji}(k,M_A)` },
  { pattern: /p\s*HS\s*,\s*f\s*i\s*j\s*\(\s*l\s*,\s*k\s*\)\s*=\s*1\s*[−-]\s*p\s*HS\s*,\s*s\s*i\s*j\s*\(\s*l\s*,\s*k\s*\)/giu,
    latex: String.raw`p^{\mathrm{HS},f}_{ij}(l,k)=1-p^{\mathrm{HS},s}_{ij}(l,k)` },
  { pattern: /λ\s*i\s*j\s*\(\s*l\s*,\s*k\s*\)\s*=\s*1\s*(?:\/|\s)\s*p\s*HS\s*,\s*s\s*i\s*j\s*\(\s*l\s*,\s*k\s*\)/giu,
    latex: String.raw`\lambda_{ij}(l,k)=\frac{1}{p^{\mathrm{HS},s}_{ij}(l,k)}` },
  { pattern: /E\s*D\s*t\s*x\s*\(\s*l\s*,\s*M\s*P\s*\)\s*=\s*P\s*c\s*r\s*c\s*t\s*x\s*\(\s*l\s*\)\s*T\s*t\s*x\s*\(\s*M\s*P\s*\)/giu,
    latex: String.raw`E^D_{\mathrm{tx}}(l,M_P)=P^{\mathrm{crc}}_{\mathrm{tx}}(l)T_{\mathrm{tx}}(M_P)` },
]

type Match = { start: number; end: number; latex: string }

export function PassageMathText({ text }: { text: string }) {
  const matches: Match[] = []
  for (const { pattern, latex } of FORMULAS) {
    for (const match of text.matchAll(new RegExp(pattern.source, pattern.flags))) {
      const start = match.index ?? 0
      matches.push({ start, end: start + match[0].length, latex })
    }
  }
  matches.sort((a, b) => a.start - b.start || b.end - a.end)

  const parts: ReactNode[] = []
  let last = 0
  for (const match of matches) {
    if (match.start < last) continue
    if (match.start > last) parts.push(<MathText key={`text-${last}`} text={text.slice(last, match.start)} />)
    const html = katex.renderToString(match.latex, { displayMode: false, throwOnError: false })
    parts.push(<span key={`${match.start}-${match.end}`} className="passage-math" dangerouslySetInnerHTML={{ __html: html }} />)
    last = match.end
  }
  if (last < text.length) parts.push(<MathText key={`text-${last}`} text={text.slice(last)} />)
  return <>{parts}</>
}
