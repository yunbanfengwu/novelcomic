// tapflow 真实运行上下文:项目/卷章镜/要素候选(替换假数据 ctxOptions),
// 以及选中项目的设定卡带出。数据源与智能体编排同一套 /api/agents/context。
import { useCallback, useEffect, useState } from 'react'
import { api, type CtxElement, type CtxNode } from '../api'
import type { TapCtxKey, TapParam, TapProjectInfo } from './tapflowData'

/** 「25 · 北境灯塔」形式存值:显示友好,取 id 只需 parseInt 前缀 */
const fmt = (id: number, title: string) => `${id} · ${title}`

export function useTapflowCtx(enabled: boolean, projectParamValue: string | undefined) {
  const [projects, setProjects] = useState<{ id: number; title: string }[]>([])
  const [nodes, setNodes] = useState<CtxNode[]>([])
  const [elements, setElements] = useState<CtxElement[]>([])
  const [project, setProject] = useState<TapProjectInfo | null>(null)
  const pid = projectParamValue ? parseInt(projectParamValue, 10) || null : null

  useEffect(() => {
    if (!enabled) return
    api.agentProjects().then(r => setProjects(r.projects)).catch(() => setProjects([]))
  }, [enabled])

  // 换了项目:候选与项目设定卡一起换
  useEffect(() => {
    if (!enabled || !pid) { setNodes([]); setElements([]); setProject(null); return }
    api.agentCtxNodes(pid)
      .then(r => { setNodes(r.nodes); setElements(r.elements) })
      .catch(() => { setNodes([]); setElements([]) })
    api.getProject(pid).then(p => setProject({
      id: p.id, title: p.title,
      artStyle: p.art_style || '', storyline: p.storyline || '',
      aspect: p.config?.aspect_ratio === '9:16' ? '9:16' : '16:9',
      characterMode: p.config?.character_mode === 'real' ? 'real' : 'virtual',
      writingStyle: p.writing_style || '',
      // 画风示意图取项目封面：它就是这个项目当下的画面基准
      styleImage: p.config?.cover_url || '',
    })).catch(() => setProject(null))
  }, [enabled, pid])

  /** ctx 参数候选:项目=下拉必选;场景/角色=已有要素名(datalist,可手填新名);
   * 卷/章/镜=content_nodes 层级 */
  const optionsFor = useCallback((ctx: TapCtxKey, params: TapParam[]): { list: string[]; free: boolean } => {
    if (ctx === 'project_id') return { list: projects.map(p => fmt(p.id, p.title)), free: false }
    if (ctx === 'target_ref') {
      const p = params.find(x => x.ctx === 'target_ref')
      const kinds = p?.resourceKinds ?? ['element', 'content_node']
      const list: string[] = []
      if (kinds.includes('element')) list.push(...elements.map(e => `element:${e.id} · ${e.name}`))
      if (kinds.includes('content_node')) list.push(...nodes.map(n => `content_node:${n.id} · ${n.title}`))
      // `content_node:shot` is a typed resource contract, not a workflow-specific
      // label: any canvas may restrict a generic content-node selector to shots.
      if (kinds.includes('content_node:shot')) {
        list.push(...nodes.filter(n => n.kind === 'shot').map(n => `content_node:${n.id} · ${n.title}`))
      }
      return { list, free: false }
    }
    if (ctx === 'scene_id') return { list: elements.filter(e => e.kind === 'scene').map(e => e.name), free: true }
    if (ctx === 'character_id') return { list: elements.filter(e => e.kind === 'character').map(e => e.name), free: true }
    if (ctx === 'prop_id') {
      return { list: elements.filter(e => e.kind !== 'scene' && e.kind !== 'character').map(e => e.name), free: true }
    }
    if (ctx === 'volume_id') return { list: nodes.filter(n => n.kind === 'volume').map(n => fmt(n.id, n.title)), free: false }
    if (ctx === 'chapter_id') return { list: nodes.filter(n => n.kind === 'chapter').map(n => fmt(n.id, n.title)), free: false }
    // 镜挂在章下面：选了章就只给这一章的镜，没选章（如业务入口只带 project_id/shot_id）
    // 才回退给全项目的镜——否则章一填上,原先带进来的那条镜若不属于它就再也选不中
    const chapterVal = params.find(p => p.ctx === 'chapter_id')?.v ?? ''
    const chapterId = chapterVal ? parseInt(chapterVal, 10) : null
    const shots = nodes.filter(n => n.kind === 'shot')
    return {
      list: (chapterId ? shots.filter(n => n.parent_id === chapterId) : shots).map(n => fmt(n.id, n.title)),
      free: false,
    }
  }, [projects, nodes, elements])

  return { project, optionsFor }
}
