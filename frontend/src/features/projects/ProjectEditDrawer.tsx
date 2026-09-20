import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { Project } from '../../api'
import { GuidedCreate } from './guide/GuidedCreate'
import type { GuideInfo } from './guide/GuidedCreate'
import './guide/guide.css'

/**
 * 总览·基本信息「编辑」：从右侧拉出抽屉，内嵌引导式创建公共组件（编辑模式）。
 * 各步右下角「保存」→ PATCH 基本信息 + 比例变更走 config，保存成功即关闭。
 */
export function ProjectEditDrawer({ p, onSaved, onClose }: {
  p: Project
  onSaved: (p: Project) => void
  onClose: () => void
}) {
  const save = async (info: GuideInfo, aspect: '16:9' | '9:16') => {
    const projectType = info.project_type || info.tags?.find(Boolean) || p.project_type || 'novel_comic'
    await api.updateProject(p.id, { ...info, project_type: projectType })
    let config = p.config
    const patch: Record<string, unknown> = {}
    if (aspect !== (p.config.aspect_ratio || '16:9')) patch.aspect_ratio = aspect
    if (JSON.stringify(info.tags || []) !== JSON.stringify(p.config.tags || [])) {
      patch.tags = info.tags || []
      patch.project_type = info.project_type || info.tags?.[0] || p.project_type || 'novel_comic'
    }
    if (Object.keys(patch).length) config = (await api.updateConfig(p.id, patch)).config
    // PATCH 响应不带 employees，本地合并而非整体替换
    onSaved({ ...p, ...info, config: { ...p.config, ...config } })
  }

  return createPortal(
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="edit-drawer" onClick={e => e.stopPropagation()}>
        <GuidedCreate mode="edit"
          initialInfo={{
            title: p.title, synopsis: p.synopsis, storyline: p.storyline || '',
            writing_style: p.writing_style, art_style: p.art_style,
            tags: p.config.tags || [], project_type: p.project_type,
          }}
          initialAspect={p.config.aspect_ratio || '16:9'}
          onSave={save} onExit={onClose} />
      </aside>
    </div>,
    document.body,
  )
}
