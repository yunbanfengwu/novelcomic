import { useState, type MouseEvent } from 'react'
import { api } from '../../api'
import type { Element } from '../../api'
import { Icon } from '../../components/Icon'

/** 批量补档：为所有缺档案的角色逐个补全（每角色一次独立 LLM 调用，避免单次输出膨胀）。
 * 内联渲染（无外壳），嵌在「角色」分组标题行右侧；只在有缺档角色时出现，进度逐个回显。 */
const PROFILE_KEYS = ['年龄段', '性别', '身份', '时代服饰', '体貌'] as const
const missingProfile = (el: Element) =>
  el.kind === 'character' && !PROFILE_KEYS.some(k => (el.meta.profile?.[k] ?? '').trim())

export function ProfileBatchBar({ pid, elements, onDone }: {
  pid: number; elements: Element[]; onDone: () => void
}) {
  const [prog, setProg] = useState<{ i: number; n: number } | null>(null)
  const missing = elements.filter(missingProfile)
  if (!missing.length && !prog) return null

  const run = async (e: MouseEvent) => {
    e.stopPropagation()   // 嵌在可折叠分组标题行内：点按钮不触发折叠
    const todo = elements.filter(missingProfile)
    setProg({ i: 0, n: todo.length })
    for (let i = 0; i < todo.length; i++) {
      try { await api.genElementProfile(pid, todo[i].id) } catch (e) { alert(String(e)) }
      setProg({ i: i + 1, n: todo.length })
      onDone()
    }
    setProg(null)
  }

  return prog
    ? <span className="dim profile-batch-prog" onClick={e => e.stopPropagation()}><Icon name="spinner" spin /> 补全中 {prog.i}/{prog.n}…</span>
    : <button className="small profile-batch-btn" onClick={run}
        title="为所有缺档角色按项目年代背景补全档案与外貌提示词">
        <Icon name="wand" /> 补全缺档（{missing.length}）
      </button>
}
