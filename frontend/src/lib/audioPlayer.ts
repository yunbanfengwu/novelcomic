/** 全局单例音频试听：再次点击（同一 url）暂停，点别的自动切换——避免多段小样叠着播。 */
let current: HTMLAudioElement | null = null
let currentUrl = ''

export function playAudio(url: string): void {
  if (current) {
    current.pause()
    const same = currentUrl === url
    current = null
    currentUrl = ''
    if (same) return  // 再点正在播的 → 停
  }
  const audio = new Audio(url)
  current = audio
  currentUrl = url
  audio.onended = () => { if (current === audio) { current = null; currentUrl = '' } }
  audio.play().catch(() => { if (current === audio) { current = null; currentUrl = '' } })
}
