import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '../../api'
import type { Element, ElementVariant } from '../../api'
import { openLightbox } from '../../lib/lightbox'
import { KIND_META } from '../../lib/kinds'
import { usePendingTasks } from '../../lib/usePendingTasks'
import { activeVariant } from '../../lib/elementVariants'
import { Icon } from '../../components/Icon'
import { isTapflowWindowClosedMessage, openTapflowWindow } from '../../lib/tapflowWindow'
import { VoiceBlock } from '../voice/VoiceBlock'
import { CharacterProfile } from './CharacterProfile'
import { SceneProfileCard } from './SceneProfileCard'
import { ElementBasicInfo } from './ElementBasicInfo'
import { ElementSheetPanel } from './ElementSheetPanel'
import { ElementSheetGallery } from './ElementSheetGallery'

/** 核心要素预览（独立可复用）：标题 + 左主图（可点开图片弹窗）+ 右基本信息/音色/外貌提示词。
 * 自带设定图生成与任务轮询；既内嵌于核心要素页右侧，也可经 openElementPreview() 弹窗加载。
 * actions：调用方可注入的上下文操作（如分镜里的「解除与本镜的关联」）。 */
export function ElementPreview({ pid, el, onReload, actions }: {
  pid: number
  el: Element
  onReload: () => void
  actions?: ReactNode
}) {
  const { pending } = usePendingTasks(pid, onReload)
  const generating = el.id in pending
  const canGen = el.kind === 'character' || el.kind === 'scene' || el.kind === 'prop'
  const isChar = el.kind === 'character'
  // 当前展示/编辑的设定图：切换即换主图与外貌；多图时各 API 均带 variant_id（'default'=单图，传 undefined）
  const [selId, setSelId] = useState<string>()
  // 核心要素图片统一走同一张 production Tapflow，目标用 typed target_ref 传入。
  const tapWindowRequests = useRef(new Set<string>())
  useEffect(() => { setSelId(undefined) }, [el.id])   // 切要素时重置选中图（不同要素图 id 可能重名）
  const active = activeVariant(el, selId)
  const sheetUrl = active.sheet_url ?? undefined
  const appearance = active.外貌提示词 ?? ''

  useEffect(() => {
    const onWindowMessage = (event: MessageEvent) => {
      const requestId = [...tapWindowRequests.current]
        .find(id => isTapflowWindowClosedMessage(event, id))
      if (!requestId) return
      tapWindowRequests.current.delete(requestId)
      onReload()
    }
    window.addEventListener('message', onWindowMessage)
    return () => window.removeEventListener('message', onWindowMessage)
  }, [onReload])

  const openElementImageTapflow = (variantId: string) => {
    const requestId = openTapflowWindow({
      slug: 'core-element-image-generation', variant: 'production',
      inputs: { project_id: pid, target_ref: `element:${el.id}`,
        ...(variantId !== 'default' ? { variant_id: variantId } : {}) },
      subject: { kind: 'element', id: el.id, name: el.name,
        canvasRole: `core-element.image:${variantId}` },
    })
    if (requestId) tapWindowRequests.current.add(requestId)
  }
  // 画廊里点某张图：选中它（右侧外貌随之切换）并打开出图弹框（占位=生成，已出图=编辑重生成）
  const openGenVariant = (v: ElementVariant) => {
    setSelId(v.id)
    openElementImageTapflow(v.id)
  }
  // 画廊里点已出图：放大看图（右侧面板可再触发重生成）
  const enlargeVariant = (v: ElementVariant) => {
    if (!v.sheet_url) return
    openLightbox(v.sheet_url, el.name,
      <ElementSheetPanel el={el} generating={generating}
        onGenSheet={() => openElementImageTapflow(v.id)}
        appearance={v.外貌提示词 ?? ''} />)
  }
  // 添加一张设定图：后端新建一张空图（外貌/档案沿用主图）→ 在画廊里以占位依次呈现，点占位再生成
  const onAddImage = async () => {
    try { const { id } = await api.addElementVariant(pid, el.id); setSelId(id); onReload() }
    catch (e) { alert(String(e)) }
  }
  return (
    <div className="element-preview">
      <div className="preview-head">
        <h2><Icon name={KIND_META[el.kind]?.icon ?? 'puzzle'} /> {KIND_META[el.kind]?.label ?? el.kind} {el.name}</h2>
        <div className="preview-actions">
          {actions}
        </div>
      </div>
      <div className="element-pane-split">
        <div className="element-pane-media">
          {/* 设定图画廊：多张图依次平铺，无图占位、点占位生成，每张图下方一句可空描述 */}
          {canGen
            ? <><ElementSheetGallery pid={pid} el={el} generating={generating}
                busyId={generating ? selId : undefined}
                onOpenGen={openGenVariant} onEnlarge={enlargeVariant}
                onAddImage={onAddImage} onReload={onReload} />
              {isChar && el.meta.hair_sheet_url && (
                <button type="button" className="sheet-hair-card"
                  title="发型与发饰小卡（仅眼睛以上区域）"
                  onClick={() => openLightbox(el.meta.hair_sheet_url!, `${el.name} · 发型发饰`)}>
                  <img src={el.meta.hair_sheet_url} alt={`${el.name}发型发饰`} />
                  <span>发型与发饰</span>
                </button>
              )}</>
            : sheetUrl
            ? <img src={sheetUrl} alt="设定图" className="sheet-img" />
            : <div className="sb-placeholder">（尚无设定图）</div>}
        </div>
        <div className="element-pane-info">
          <ElementBasicInfo pid={pid} el={el} onReload={onReload} />
          {isChar && <CharacterProfile pid={pid} el={el} onReload={onReload} />}
          {el.kind === 'scene' && <SceneProfileCard pid={pid} el={el} onReload={onReload} />}
          {el.kind === 'character' &&
            <VoiceBlock pid={pid} el={el} onChanged={onReload} />}
          {isChar && appearance &&
            <div className="prompt-box"><Icon name="palette" /> {appearance}</div>}
        </div>
      </div>
    </div>
  )
}
