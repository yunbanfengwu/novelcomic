// 属性面板的候选目录：技能 / 知识库文件夹 / 工具。
//
// **唯一目录源是后端 `GET /api/agents/assets`**，前端不再留任何写死数组——
// 此前 tapflowData.ts 顶上那几个 TAP_SKILLS/TAP_KB/TAP_TOOLS 是假数据，
// 面板上挑得再欢，跟引擎实际认的技能 slug、知识库 folder_id 对不上，
// 存进 graph 就是一条跑不起来的配置（2026-08-01 收敛）。
//
// value 一律是**引擎认的那个值**（技能=slug、知识库=folder_id 字符串、工具=name），
// label 才是给人看的名字；反向 adapter 写 graph 时直接取 value，不做二次翻译。
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { AgentTool } from '../api'
import type { TapOption } from './tapflowOption'

export interface TapCatalog {
  skills: TapOption[]
  /** 知识库文件夹：value 是 folder_id 的字符串形式（config.folder_ids 要 number） */
  kb: TapOption[]
  tools: TapOption[]
  /** 工具节点使用的完整入/出参合同；与 tools 选项来自同一个响应。 */
  toolSpecs: AgentTool[]
  /** 取数模式的候选：工具目录里带 writes=false 的那些（只读取数，不改库） */
  queryTools: TapOption[]
  /** 质检技能：kb 条目名，与上面的 skills（skill_packages）**不是同一类东西** */
  qcSkills: TapOption[]
  /** 生成步骤（执行体）：gen 节点 config.step 的合法取值 */
  steps: TapOption[]
  loaded: boolean
}

const EMPTY: TapCatalog = {
  skills: [], kb: [], tools: [], toolSpecs: [], queryTools: [], qcSkills: [], steps: [], loaded: false }

/** 全局取一次就够：目录是系统级配置，不随节点变。失败静默成空目录——
 * 面板照常打得开，只是挑不出东西，比整块白屏好。 */
let cache: TapCatalog | null = null

export function useTapflowCatalog(): TapCatalog {
  const [cat, setCat] = useState<TapCatalog>(cache ?? EMPTY)
  useEffect(() => {
    if (cache) return
    api.agentAssets().then(a => {
      const next: TapCatalog = {
        skills: (a.skills ?? []).map(s => ({ value: s.slug, label: s.name || s.slug })),
        kb: (a.folders ?? []).map(f => ({
          value: String(f.id),
          label: f.title || f.name,
          note: f.entry_count ? `${f.entry_count} 条` : undefined,
        })),
        tools: (a.tools ?? []).map(t => ({
          value: t.name, label: t.title || t.name, note: t.description,
        })),
        toolSpecs: a.tools ?? [],
        queryTools: (a.tools ?? []).filter(t => !t.writes).map(t => ({
          value: t.name, label: t.title || t.name, note: t.description,
        })),
        qcSkills: (a.qc_skills ?? []).map(q => ({
          value: q.name, label: q.name, note: q.description || undefined,
        })),
        steps: (a.steps ?? []).map(st => ({
          value: st.kind, label: st.kind, note: `${st.group}${st.note ? ' · ' + st.note : ''}`,
          group: st.group,
        })),
        loaded: true,
      }
      cache = next
      setCat(next)
    }).catch(() => setCat({ ...EMPTY, loaded: true }))
  }, [])
  return cat
}
