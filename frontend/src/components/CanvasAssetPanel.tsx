import type { ProjectAsset } from '../api'
import { AssetPicker } from './AssetPicker'

/** 无限画布右侧素材库抽屉：包一层深色面板复用 AssetPicker（选现有/上传/从视频中抽），
 * 点选素材回传画布转成节点（有图=图片节点，无图=文字参考节点）。 */
export function CanvasAssetPanel({ pid, exclude, onPick, onClose }: {
  pid: number
  exclude: string[]                  // 画布上已有的节点名（不再列出）
  onPick: (a: ProjectAsset) => void
  onClose: () => void
}) {
  return (
    <aside className="imc-asset-panel">
      <button className="imc-asset-close" aria-label="关闭素材库" title="关闭素材库" onClick={onClose}>×</button>
      <AssetPicker pid={pid} exclude={exclude} onPick={onPick} />
    </aside>
  )
}
