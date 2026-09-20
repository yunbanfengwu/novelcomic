/** 项目还没有封面图，用基于 id 的渐变色块代替 */
const COVER_PALETTES: [string, string][] = [
  ['#3b2f63', '#7a5cff'], ['#1d3a5f', '#4fa3ff'], ['#4a2742', '#e06fae'],
  ['#20424a', '#3ec8b4'], ['#4a3a1f', '#e2b45f'], ['#2f1f4a', '#9b6dff'],
]

export const coverStyle = (id: number) => {
  const [a, b] = COVER_PALETTES[id % COVER_PALETTES.length]
  return { background: `radial-gradient(120% 140% at 85% -20%, ${b}66, transparent 60%), linear-gradient(135deg, ${a}, ${b}55)` }
}
