import type { Shot } from '../api'

/** 字幕不带标点：每个标点/符号替换为空格（\p{P} 标点 + \p{S} 符号，含中英文全角标点） */
function stripPunct(text: string): string {
  return text.replace(/[\p{P}\p{S}]/gu, ' ')
}

/** 从分镜 cuts/dialogue 编译字幕 cue（镜内相对秒）——字幕=分镜数据的编译产物，见 docs/arch/subtitle-design.md */
export function buildCues(s: Shot | null): { start: number; end: number; text: string }[] {
  if (!s) return []
  const cues: { start: number; end: number; text: string }[] = []
  const cuts = s.meta.cuts || []
  if (cuts.length) {
    let t = 0
    for (const c of cuts) {
      const sec = Math.max(1, c.seconds || 2)
      const m = /说：?[“"](.+?)[”"]/.exec(c.action || '')
      if (m) cues.push({ start: t, end: t + sec, text: stripPunct(m[1]) })
      t += sec
    }
    return cues
  }
  const dlg = (s.meta.dialogue || '').trim()
  if (dlg && dlg !== '无') {
    const parts = dlg.split('/').map(x => x.trim()).filter(Boolean)
    const dur = Math.max(2, s.meta.duration_s || 3)
    const per = dur / parts.length
    parts.forEach((p, i) => cues.push({ start: i * per, end: (i + 1) * per, text: stripPunct(p) }))
  }
  return cues
}
