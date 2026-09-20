import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Element, ElementVariant } from '../../api'
import { Icon } from '../../components/Icon'
import { variantsOf, hasVariants, inheritEnabled } from '../../lib/elementVariants'

type Row = { id: string; tag: string; desc: string; inherit_ref: boolean }

// 沿用文案按类型：角色沿用相貌，场景/道具沿用整体风格
const inheritWord = (kind: string) => (kind === 'character' ? '沿用上一张相貌' : '沿用上一张风格')

/** 要素设定图画廊：一要素多张图依次平铺；每张图（或占位）下方一句可空描述（就地改）。
 * 点占位→打开出图弹框生成；点已出图→放大 / 编辑重生成；末尾「添加设定图」追加一张占位。
 * 首张为基准，其余默认沿用它的相貌/风格（可关，用于整容/变身/换景）。
 * desc 就地写、失焦落库；≤1 张时后端折叠回单图并把描述镜像到 meta.sheet_desc（单图也留描述）。 */
export function ElementSheetGallery({ pid, el, generating, busyId, onOpenGen, onEnlarge, onAddImage, onReload }: {
  pid: number
  el: Element
  generating: boolean
  busyId?: string                        // 正在生成的那张图 id（元素级任务，用于占位处显进度）
  onOpenGen: (v: ElementVariant) => void  // 打开出图弹框（生成 / 编辑重生成）
  onEnlarge: (v: ElementVariant) => void  // 放大看图（已出图才有）
  onAddImage: () => void
  onReload: () => void
}) {
  const vs = variantsOf(el)
  const multi = hasVariants(el)
  const genLabel = el.kind === 'character'
    ? '生成角色设定图(三视图)'
    : el.kind === 'scene' ? '生成场景设定图' : '生成道具设定图'
  const [rows, setRows] = useState<Row[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => {   // 切要素 / reload 后按最新图列表重建（保留 tag，避免保存时被清空）
    setRows(variantsOf(el).map(v => ({ id: v.id, tag: v.tag || '', desc: v.desc || '',
      inherit_ref: inheritEnabled(v) })))
  }, [el])

  const descOf = (id: string) => rows.find(r => r.id === id)?.desc ?? ''
  const inheritOf = (id: string) => rows.find(r => r.id === id)?.inherit_ref ?? true

  const commit = async (next: Row[]) => {
    setBusy(true)
    try {
      await api.saveElementVariants(pid, el.id,
        next.map(r => ({ id: r.id, tag: r.tag, desc: r.desc, inherit_ref: r.inherit_ref })))
      onReload()
    } catch (e) { alert(String(e)) } finally { setBusy(false) }
  }
  const setDesc = (id: string, desc: string) =>
    setRows(rs => rs.map(r => (r.id === id ? { ...r, desc } : r)))
  const commitDesc = (id: string) => {   // 仅在描述真的改动后才落库（避免每次失焦空写）
    const r = rows.find(x => x.id === id)
    if (r && (vs.find(v => v.id === id)?.desc || '') !== r.desc) commit(rows)
  }
  const toggleInherit = (id: string) => {
    const next = rows.map(r => (r.id === id ? { ...r, inherit_ref: !r.inherit_ref } : r))
    setRows(next); commit(next)
  }
  const del = (id: string) => {
    if (!confirm('删除这张设定图？')) return
    const next = rows.filter(r => r.id !== id)
    setRows(next); commit(next)
  }

  return (
    <div className="sheet-gallery">
      {vs.map((v, i) => {
        const busyHere = generating && busyId === v.id
        return (
          <div key={v.id} className="sheet-card">
            {v.sheet_url
              ? <div className={'el-media-wrap' + (busyHere ? ' regen' : '')}>
                  <img src={v.sheet_url} alt="设定图" className="sheet-img" onClick={() => onEnlarge(v)} />
                  {busyHere && (
                    <div className="sheet-regen"><Icon name="spinner" spin /> 正在重新生成…</div>
                  )}
                  <div className="el-media-acts">
                    <button className="small ghost" title="放大" onClick={() => onEnlarge(v)}>
                      <Icon name="search" />
                    </button>
                    <button className="small ghost" title="编辑/重生成" onClick={() => onOpenGen(v)}>
                      <Icon name="pen" />
                    </button>
                  </div>
                </div>
              : <button className={'sheet-slot' + (busyHere ? ' regen' : '')} disabled={busyHere}
                  onClick={() => onOpenGen(v)} title="打开出图弹框生成设定图">
                  {busyHere
                    ? <><Icon name="spinner" spin /> 生成中…</>
                    : <><Icon name="image" /> {genLabel}</>}
                </button>}
            <div className="sheet-card-foot">
              <input className="sheet-desc" value={descOf(v.id)}
                placeholder="这张图的描述（可空，如 变身后 / 皇后装 / 雨中）"
                onChange={e => setDesc(v.id, e.target.value)} onBlur={() => commitDesc(v.id)} />
              {multi && (i === 0
                ? <span className="variant-base" title="首张为基准，其余图默认沿用它">基准</span>
                : <>
                    <button className={'variant-inherit' + (inheritOf(v.id) ? ' on' : '')}
                      disabled={busy} onClick={() => toggleInherit(v.id)} title="关掉用于整容/变身/换景">
                      <Icon name={inheritOf(v.id) ? 'link' : 'unlink'} /> {inheritWord(el.kind)}
                    </button>
                    <button className="icon-btn" title="删除" disabled={busy} onClick={() => del(v.id)}>
                      <Icon name="trash" />
                    </button>
                  </>)}
            </div>
          </div>
        )
      })}
      <button className="small ghost sheet-add" disabled={busy || generating} onClick={onAddImage}
        title="加一张设定图">
        <Icon name="plus" /> 添加设定图
      </button>
    </div>
  )
}
