import { Icon } from './Icon'
import { openLightbox } from '../lib/lightbox'
import { REF_ICON, type EditRef } from '../lib/kinds'

/** 生成参考列表（公共图片生成弹框内）：所有素材统一为同尺寸方卡（一行流式排布）——
 * 有图=缩略图，无图（未出设定图的要素）=占位图标，音频=喇叭图标，长相一致。
 * 右上角 ✕：可移除的直接移除、否则停用/启用；悬停有图卡显示「查看 / 直接应用」两钮。
 * 「直接应用」= 把该图直接当作最终成品（跳过生成）。添加参考走右侧素材库面板。 */
export function GenRefList({ refs, off, onToggle, onDelete, onApply }: {
  refs: EditRef[]
  off: Set<string>
  onToggle?: (name: string) => void
  onDelete?: (name: string) => void   // 仅 deletable 项：移除该参考
  onApply?: (url: string) => void     // 直接应用该图为最终成品（缺省不显示该钮）
}) {
  // 单个 ✕：可移除的→移除；否则→停用/启用。首/尾帧改用底部「固定」勾选，不叠 ✕（单一控件）
  const xBtn = (r: EditRef, isOff: boolean) => {
    if (r.kind === 'keyframe' || r.kind === 'lastframe') return null
    if (r.deletable && onDelete) return (
      <button className="ig-ref-x" title="移除该参考" onClick={e => { e.stopPropagation(); onDelete(r.name) }}>✕</button>
    )
    if (onToggle) return (
      <button className="ig-ref-x" title={isOff ? '点击启用' : '点击停用（生成时不使用该参考）'}
        onClick={e => { e.stopPropagation(); onToggle(r.name) }}>✕</button>
    )
    return null
  }
  return (
    <div className="ig-ref-cards">
      {refs.map(r => {
        const isOff = off.has(r.name)
        // 首/尾帧：底部用「固定」勾选替代 ✕——勾选=以首尾帧模式提交 Seedance（锁定该帧），取消=仅提示词描述
        const frame = r.kind === 'keyframe' || r.kind === 'lastframe'
        return (
          <div key={r.name} className={'ig-ref-card' + (isOff ? ' off' : '') + (frame ? ' frame' : '')}
            title={`${r.name}${isOff ? (frame ? '（未固定：生成时仅用提示词描述）' : '（已停用：生成时不使用）') : ''}`}>
            <div className="ig-ref-thumb">
              {r.url
                ? <img src={r.url} alt="" onClick={() => openLightbox(r.url!, r.name)} />
                : <span className="ig-ref-ph"><Icon name={r.kind === 'audio' ? 'speaker' : (REF_ICON[r.kind] ?? 'image')} /></span>}
              {xBtn(r, isOff)}
              {r.url && (
                <div className="ig-ref-ov">
                  <button className="ig-ref-ovbtn" onClick={e => { e.stopPropagation(); openLightbox(r.url!, r.name) }}>查看</button>
                  {onApply && (
                    <button className="ig-ref-ovbtn apply" onClick={e => { e.stopPropagation(); onApply(r.url!) }}>直接应用</button>
                  )}
                </div>
              )}
            </div>
            {frame && onToggle
              ? <label className="ig-ref-lock"
                  title={isOff ? '未固定：生成视频时仅用提示词描述该画面，不锁帧'
                    : '已固定：以首尾帧模式提交 Seedance，视频画面锁定该帧'}>
                  <input type="checkbox" checked={!isOff} onChange={() => onToggle(r.name)} />
                  {r.kind === 'lastframe' ? '固定尾帧' : '固定首帧'}
                </label>
              : <div className="ig-ref-name"><span>{r.name}</span></div>}
          </div>
        )
      })}
    </div>
  )
}
