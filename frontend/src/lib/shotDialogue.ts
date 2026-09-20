// 台词逐切归位（纯逻辑，零 JSX）。
// 数据现状：台词只有整镜一串 meta.dialogue（"阿砚：（焦急）… / 岚音：（专注）…"），cuts 无台词字段。
// 这里复刻后端装配期的落位规则（backend/app/services/storyboard.py 的 fit_cuts_for_prompt ①）：
//   ① 某切 action 里已经含这句（取前 6 字比对）→ 台词就属于那一切；
//   ② 否则找「主体名与说话人同名、且该切还没有台词」的切当宿主；
//   ③ 都匹配不上 → 落到 rest（装配时后端会为它新开一切，界面上单独列出，不静默丢掉）。
// 与后端同规则 = 界面展示的分派和最终进提示词的分派一致。

export interface DialogueLine { speaker: string; text: string }
/** 只取展示需要的两个字段，避免与 api.ts 的 Shot 类型耦合 */
export interface CutLike { subject?: string; action?: string }

// "阿澈：无" 这类是舞台指示不是对白（注入会让角色念出"无"）
const MUTE = ['无', '沉默', '不回答', '沉默不语', '不语', '无对白']
const SPEAKER = /^([^：:“”"，。？！\s]{1,12})[：:]\s*([\s\S]+)$/
// 同段里混多个 "说话人：" 标记（粗拆常见）→ 按标记再切
const MULTI = /\s+(?=[^：:\s，。？！“”"]{1,12}[：:])/
const SAY = /说：?[“"](.+?)[”"]/
const PAREN = /[（(][^（）()]*[）)]/g

/** 角色名去括号备注："沉默老船长（黑衣人）"→"沉默老船长" */
const baseName = (name?: string) => (name ?? '').replace(PAREN, '').trim() || (name ?? '').trim()
/** 基名互相包含即同一角色——脚本常用短名"老船长"指代要素原名"沉默老船长（黑衣人）" */
const namesMatch = (a?: string, b?: string) => {
  const x = baseName(a), y = baseName(b)
  return !!x && !!y && (x.includes(y) || y.includes(x))
}

/** meta.dialogue → [{说话人, 台词}]；分隔符 " / "，"无" 视为没有台词 */
export function parseDialogue(dlg?: string): DialogueLine[] {
  const out: DialogueLine[] = []
  for (const part of (dlg ?? '').split(/\s*\/\s*/)) {
    if (!part.trim() || part.trim() === '无') continue
    for (const seg of part.trim().split(MULTI)) {
      const s = seg.trim()
      if (!s) continue
      const m = SPEAKER.exec(s)
      const speaker = m ? m[1] : ''
      const text = (m ? m[2] : s).trim().replace(/^[“"]|[”"]$/g, '')
      if (!text || MUTE.includes(text)) continue
      out.push({ speaker, text })
    }
  }
  return out
}

/** 把整镜台词分派到各 cut：perCut[i] = 第 i 切的台词；rest = 说话人对不上任何切主体的台词。
 * 与后端的一点差异：同一角色的第 2、3 句这里仍挂在他那一切下（同一说话人的话连着看更顺），
 * 后端装配时会按念词时长为多出来的句子新开切——所以切的时间轴以装配结果为准。 */
export function assignDialogue(dlg: string | undefined, cuts: CutLike[]) {
  const perCut: DialogueLine[][] = cuts.map(() => [])
  const rest: DialogueLine[] = []
  const taken = cuts.map(c => SAY.test(c.action ?? ''))
  for (const line of parseDialogue(dlg)) {
    const key = line.text.slice(0, 6)
    const inAction = key ? cuts.findIndex(c => (c.action ?? '').includes(key)) : -1
    // 优先落到「还没台词」的同名切（A/B 对话自然分到两切），都满了再回落到同名切复用
    const fresh = cuts.findIndex((c, i) => !taken[i] && namesMatch(line.speaker, c.subject))
    const reuse = cuts.findIndex(c => namesMatch(line.speaker, c.subject))
    const host = inAction >= 0 ? inAction : fresh >= 0 ? fresh : reuse
    if (host >= 0) { perCut[host].push(line); taken[host] = true } else rest.push(line)
  }
  return { perCut, rest }
}
