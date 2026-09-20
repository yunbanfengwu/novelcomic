import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Project } from '../../api'
import { Icon } from '../../components/Icon'

/** 项目年代/世界观锚（落 config.era）：角色/场景档案补全据此定妆造——治"古装现代脸"。
 * 留空则由 AI 依梗概/主线/画风自行推断；手填则强制照此。 */
export function EraBar({ pid, p, setP }: {
  pid: number; p: Project; setP: (p: Project) => void
}) {
  const saved = (p.config.era as string) || ''
  const [era, setEra] = useState(saved)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setEra(((p.config.era as string) || '')) }, [p.config.era])

  const save = async () => {
    setBusy(true)
    try {
      await api.updateConfig(pid, { era: era.trim() })
      setP({ ...p, config: { ...p.config, era: era.trim() } })
    } catch (e) { alert(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="era-bar" title="项目年代/世界观：角色与场景生成据此定妆造，留空则 AI 自行推断">
      <span className="era-label"><Icon name="compass" /> 年代</span>
      <input className="era-input" value={era} placeholder="如 古典奇幻·架空王朝 / 民国乱世 / 近未来海洋（留空自动推断）"
        onChange={e => setEra(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') save() }} />
      {era.trim() !== saved && (
        <button className="small" disabled={busy} onClick={save} title="保存年代设定">
          {busy ? <Icon name="spinner" spin /> : <Icon name="save" />}
        </button>
      )}
    </div>
  )
}
