import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Project, StyleOption } from '../../api'
import { Icon } from '../../components/Icon'
import { Seg } from '../../components/Seg'
import { joinPromptSegments } from '../../lib/promptFields'
import { openAssetImageCanvas } from '../../lib/tapflowEntries'
import { TapflowLaunch } from '../tapflow/TapflowLaunch'
import { OutlinePane } from './OutlinePane'
import { ProjectVisualAnchors } from './ProjectVisualAnchors'
import { TrailerCard } from './TrailerCard'
import { TagPicker } from '../admin/TagPicker'

/**
 * 基本信息：左封面图（按画幅比例，默认取所选画风预览图，点击放大可重新生成）+
 * 右侧概览（梗概/文风/画风/主线/尺寸比例），下方内嵌大纲。右上「编辑」拉出引导式编辑抽屉。
 */
export function InfoPane({ p, onAspectChange, onRealisticChange, onTagsChange, onEdit, onCoverChange, onTrailerChange, onOutlineChange }: {
  p: Project
  onAspectChange: (r: '16:9' | '9:16') => void
  onRealisticChange?: (v: 'enable' | 'disable' | 'follow') => void
  onTagsChange?: (tags: string[]) => void | Promise<void>
  onEdit?: () => void
  onCoverChange?: (url: string) => void
  onTrailerChange?: (url: string) => void
  onOutlineChange?: (md: string) => void
}) {
  // 画风存「名称——内容」：按名称匹配画风库 → 预览图兜底封面 + 提示词
  const [artOpt, setArtOpt] = useState<StyleOption | null>(null)
  const [coverBusy, setCoverBusy] = useState(false)   // 打开封面弹框时正在蒸馏「关键视觉」
  // 绑定封面画布的 slug：点「生成封面」后直接挂 TapflowLaunch（它自带 Radix Portal 全屏）。
  // 不能包进 openElementPreview：那层外壳卡会被 portal 抽空 children，塌缩成一条空浮条悬在画布上。
  const [coverFlow, setCoverFlow] = useState<{ slug: string; ref?: string } | null>(null)
  useEffect(() => {
    api.styleLibrary('art')
      .then(opts => setArtOpt(opts.find(o => p.art_style.startsWith(o.name)) ?? null))
      .catch(() => setArtOpt(null))
  }, [p.art_style])

  const vertical = (p.config.aspect_ratio || '16:9') === '9:16'
  const cover = p.config.cover_url || artOpt?.thumbnail_url || null
  // 封面生成走无限画布：提示词/参考连线决定生成输入，画布内可从素材库任选项目素材；
  // 提示词与本次使用的参考图落 project.config（复用 updateConfig 合并，不新增专用端点）
  const openCover = async () => {
    // 绑定封面画布优先（2026-09-17）：存在已发布画布声明 end.store.target=project_cover 时，
    // 「生成封面」直接打开它（素材库生成场景图同款 TapflowLaunch）——提示词怎么写、
    // 上下文查什么、产物存哪全部由画布内 AI 自主规划，本页不再拼任何封面专用逻辑。
    // 没有绑定画布才回落到下面的无限画布弹框。
    try {
      const flows = await api.listWorkflows()
      const bound = flows.find(w => w.status === 'published' && w.bindings?.includes('project_cover'))
      if (bound) {
        // subject 实例作用域：每个项目一张专属副本，节点产物/入参随实例积累——
        // 不传的话每次都开干净模板，历史既不隔离也不恢复（北境灯塔看不到上次画布产物就是这个原因）。
        // ref_url：项目现有封面（旧路径生成的）作为参考图带入，重绘时保持连贯。
        setCoverFlow({ slug: bound.slug,
          ref: p.config.cover_url || undefined })
        return
      }
    } catch { /* 画布目录拉不到 → 走素材画布 */ }
    // 回落（画布收编 2026-09-18）：素材图片画布（独立窗口），现有封面为参考带入；
    // 提示词优先上次落库值，否则蒸馏剧情专属「海报级关键视觉」（失败退回本地拼）。
    let initial = joinPromptSegments(
      p.config.cover_prompt_user, p.config.cover_prompt_anchor, p.config.cover_prompt)
    if (!initial) {
      setCoverBusy(true)
      try { initial = (await api.coverKeyVisual(p.id)).prompt }
      catch {
        const firstLine = (p.synopsis || '').split(/[。！？\n]/)[0]
        initial = joinPromptSegments(
          `${firstLine}。电影海报级关键视觉，前景主角突出、身后场景呼应`,
          `完整单幅，构图饱满，no text, no watermark。${artOpt?.positive || artOpt?.content || p.art_style}`)
      } finally { setCoverBusy(false) }
    }
    openAssetImageCanvas(p.id, cover ?? undefined, initial || undefined)
  }

  return (
    <div className="info-pane">
      <div className="info-pane-head">
        <h2><Icon name="book" /> 项目概览</h2>
        {onEdit && <button className="small ghost" onClick={onEdit}><Icon name="pen" /> 编辑</button>}
      </div>
      <div className="info-split">
        <div className="info-left">
          <button type="button" className={`info-cover${vertical ? ' vertical' : ''}`}
            title="点击打开封面生成弹框（可编辑提示词后重新生成）" onClick={openCover} disabled={coverBusy}>
            {coverBusy ? <span className="dim"><Icon name="spinner" spin /> 生成关键视觉…</span>
              : cover ? <img src={cover} alt={p.title} /> : <span className="dim">暂无封面</span>}
          </button>
          <TrailerCard p={p} vertical={vertical}
            onChange={url => onTrailerChange?.(url)} />
        </div>
        <div className="info-main">
          <p className="dim">{p.synopsis}</p>
          <p><b><Icon name="pen" /> 文风：</b><span className="dim">{p.writing_style}</span></p>
          <p><b><Icon name="palette" /> 画风：</b><span className="dim">{p.art_style}</span></p>
          {p.storyline && <p><b><Icon name="compass" /> 主线：</b><span className="dim">{p.storyline}</span></p>}
          {onTagsChange && <TagPicker value={p.config.tags || []} onChange={onTagsChange} />}
          <div className="info-row">
            <b><Icon name="ruler" /> 尺寸比例：</b>
            <Seg items={[
              { key: '16:9', label: <><Icon name="monitor" /> 横屏 16:9</> },
              { key: '9:16', label: <><Icon name="phone" /> 竖屏 9:16</> },
            ]} active={p.config.aspect_ratio || '16:9'} onSelect={onAspectChange} />
          </div>
          {onRealisticChange && (
            <div className="info-row">
              <b><Icon name="user" /> 项目角色类型：</b>
              <Seg items={[
                { key: 'enable', label: <><Icon name="user" /> 真人</>, title: '五官绑定系统备案角色；角色卡只生成服化道与动作造型' },
                { key: 'disable', label: <><Icon name="wand" /> 虚拟形象</>, title: '角色卡包含完整虚拟人物外貌与造型' },
              ]} active={(p.config.character_mode === 'real' || p.config.realistic_character === 'enable') ? 'enable' : 'disable'} onSelect={onRealisticChange} />
            </div>
          )}
        </div>
      </div>
      <ProjectVisualAnchors projectId={p.id} />
      <div className="info-outline">
        <OutlinePane p={p} onChange={md => onOutlineChange?.(md)} />
      </div>
      {coverFlow && <TapflowLaunch slug={coverFlow.slug}
        inputs={{ project_id: p.id, ...(coverFlow.ref ? { ref_url: coverFlow.ref } : {}) }}
        subject={{ kind: 'project', id: p.id, name: p.title, canvasRole: 'project.cover' }}
        productUrl={p.config.cover_url || undefined}
        onClose={async () => {
          // 画布跑完产物已落 config.cover_url：重拉项目回填封面（没有就置空走兜底图）
          setCoverFlow(null)
          const fresh = await api.getProject(p.id).catch(() => null)
          onCoverChange?.(fresh?.config.cover_url || '')
        }} />}
    </div>
  )
}
