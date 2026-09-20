import { useState } from 'react'
import { api, type Project } from '../../api'
import { Icon } from '../../components/Icon'
import { useTapflowWindowReload } from '../../lib/tapflowEntries'

/**
 * 先导预告片卡片（封面下方）：15s 硬切蒙太奇（5 镜×3s，开端→结局的命运对比）。
 * 已有成片=内嵌播放器 + 底部「重新生成」；没有=占位按钮。点开打开预告片画布
 * （画布收编 2026-09-18：project-trailer-canvas——蒸馏节点提示词 → 生成 → 回写项目预告片字段，
 * 旧片在挂载点回显）；窗口关闭（可能跑完）后重新拉项目，把最新 url 交给父组件。
 */
export function TrailerCard({ p, vertical, onChange }: {
  p: Project
  vertical: boolean
  onChange: (url: string) => void
}) {
  const url = p.config.trailer_url
  // 窗口关闭即重拉项目（产物落 config.trailer_url；prop 里的 p 是打开时的旧闭包，不能信）
  const [pulling, setPulling] = useState(false)
  const windows = useTapflowWindowReload(() => {
    setPulling(true)
    api.getProject(p.id).then(fresh => onChange(fresh.config.trailer_url ?? ''))
      .catch(() => {})
      .finally(() => setPulling(false))
  })

  const open = () => windows.open({
    slug: 'project-trailer-canvas', variant: 'production',
    inputs: { project_id: p.id },
    subject: { kind: 'project', id: p.id, canvasRole: 'project.trailer' },
    productUrl: url,
  })

  return (
    <div className={`trailer-card${vertical ? ' vertical' : ''}`}>
      {url ? (
        <>
          <video src={url} controls preload="metadata" />
          <div className="trailer-bar">
            <span className="dim"><Icon name="video" /> 先导预告片</span>
            <button className="small ghost" disabled={pulling} onClick={open}
              title="重新生成（在预告片画布内编辑提示词与参考）">
              <><Icon name="wand" /> 重新生成</>
            </button>
          </div>
        </>
      ) : (
        <button type="button" className="trailer-empty" onClick={open} title="生成预告片">
          <span className="dim"><Icon name="video" /> 生成 15 秒先导预告片（开端→结局硬切蒙太奇）</span>
        </button>
      )}
    </div>
  )
}
