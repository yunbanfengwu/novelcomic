import type { Element } from '../../api'
import { closeLightbox } from '../../lib/lightbox'
import { Icon } from '../../components/Icon'
import { LightboxInfo } from '../../components/LightboxInfo'

/** 要素设定图放大弹窗的右侧面板：简介/外貌提示词 + 重新生成设定图（角色/场景可生成；
 * 点后收口看图弹窗，打开公共图片生成弹框确认提示词） */
export function ElementSheetPanel({ el, generating, onGenSheet, appearance }: {
  el: Element
  generating: boolean
  onGenSheet: () => void
  appearance?: string   // 多形态：当前形态的外貌提示词（缺省用顶层镜像值）
}) {
  const canGen = el.kind === 'character' || el.kind === 'scene'
  return (
    <div className="kf-panel">
      {canGen && (
        <button className="small" disabled={generating}
          title="打开生成弹框：确认/编辑提示词后重新生成设定图"
          onClick={() => { closeLightbox(); onGenSheet() }}>
          {generating ? <><Icon name="spinner" spin /> 生成中…</> : <><Icon name="refresh" /> 重新生成设定图</>}
        </button>
      )}
      <LightboxInfo sections={[
        { label: '外貌提示词', text: appearance ?? el.meta.外貌提示词 },
      ]} />
    </div>
  )
}
