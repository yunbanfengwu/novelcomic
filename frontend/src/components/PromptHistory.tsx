import { useEffect, useState } from 'react'
import { Icon } from './Icon'
import { historyKey, listPromptVersions, type PromptTarget, type PromptVersion } from '../lib/promptHistory'
import './PromptHistory.css'

const REASON_LABEL: Record<PromptVersion['reason'], string> = {
  generate: '生成时', 'ai-edit': 'AI 改写前', save: '手改前', regen: '重生成前',
}
const fmt = (ts: number) =>
  new Date(ts).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

/** 提示词版本回退面板：列出（项目, 对象, 类型）在 IndexedDB/sessionStorage 里的历史快照（新→旧）。
 * 首帧/视频/尾帧按镜头、要素设定图按要素、封面按项目归类。点「回退」把该版本回填编辑框
 * （不落库、不生成，由用户确认后再保存/生成）。bump 变化即重拉。 */
export function PromptHistory({ pid, id, target, bump, current, onRestore }: {
  pid: number
  id: number          // 归类对象 id：镜头 id / 要素 id / 项目 id
  target: PromptTarget
  bump: number
  current: string
  onRestore: (prompt: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<PromptVersion[]>([])
  useEffect(() => {
    let alive = true
    listPromptVersions(historyKey(pid, id, target)).then(v => { if (alive) setList(v) })
    return () => { alive = false }
  }, [pid, id, target, bump])
  if (!list.length) return null
  return (
    <div className="pe-hist">
      <button type="button" className="pe-hist-toggle" onClick={() => setOpen(o => !o)}
        title="本对象本类型的提示词历史快照（存于浏览器 IndexedDB），可回退到任一版本">
        <Icon name="history" /> 版本历史（{list.length}）<span className="pe-hist-caret">{open ? '▾' : '›'}</span>
      </button>
      {open && (
        <ul className="pe-hist-list">
          {list.map(v => {
            const isCur = v.prompt.trim() === current.trim()
            return (
              <li key={v.ts} className={isCur ? 'cur' : ''}>
                <div className="pe-hist-meta">
                  <span className="tag">{REASON_LABEL[v.reason]}</span>
                  <span className="dim">{fmt(v.ts)}</span>
                  {isCur && <span className="dim">· 当前</span>}
                </div>
                <p className="pe-hist-text">{v.prompt}</p>
                <button type="button" className="small ghost" disabled={isCur} onClick={() => onRestore(v.prompt)}
                  title="把该版本回填到上方编辑框（需再点保存/开始生成才生效）">
                  <Icon name="refresh" /> 回退到此版本
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
