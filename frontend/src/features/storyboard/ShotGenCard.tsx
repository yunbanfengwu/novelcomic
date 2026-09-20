import { useState, type ReactNode } from 'react'
import type { PromptReview } from '../../api'
import { ClampText } from '../../components/ClampText'
import { Icon } from '../../components/Icon'
import { ReviewTag } from './ReviewTag'
import { REF_ICON, type EditRef } from '../../lib/kinds'

/** 生成卡（视频/首帧/尾帧共用）：同一张深色圆角卡，标题栏右侧「质检标签 + 画布按钮」同框
 * （tab 样式，非大圆角）；点「画布」弹出无限画布看图/编技术提示词/开始生成——技术提示词不在卡上直显。
 * variant=video：卡体正文=分镜脚本 → 其他参考容器（要素/音频/手选 + ＋添加）→ 首尾帧行（各自向下
 * 连线对接下方首帧卡/尾帧卡）；variant=first/last：卡体正文=首/尾帧画面提示词（拆镜产物，非技术
 * 提示词）+ 关联要素（帧图本身不重复展示，已在视频卡首尾帧行大图 + 主预览可见）。 */
export function ShotGenCard({
  title, icon, review, edited, busy, prompt, emptyHint, body, refs, off, onOpen, onOpenRef,
  variant = 'first', frames, onAdd, altTab, note, onToggleFrame,
}: {
  title: string
  icon: string
  review?: PromptReview
  edited?: boolean
  busy: boolean
  prompt?: string
  emptyHint?: string
  body?: ReactNode      // 卡体正文，替代提示词展示（视频卡放分镜脚本，提示词收进星星弹框）
  refs: EditRef[]
  off: string[]
  onOpen: () => void
  onOpenRef: (r: EditRef) => void
  variant?: 'video' | 'first' | 'last'  // first/last 挂连线锚点类，向上对接视频卡首尾帧行
  frames?: EditRef[]   // 仅 video：首帧+尾帧（未出图=虚线空占位，点击直达对应编辑弹框）
  onAdd?: () => void   // 仅 video：其他参考容器的「＋添加」（打开视频编辑弹框的资产面板）
  // 仅 video：首/尾帧「固定」勾选切换（勾选=以首尾帧模式提交 Seedance；取消=仅提示词描述）
  onToggleFrame?: (name: string) => void
  // 首帧/尾帧卡页签：alt=「取前镜尾帧/取后镜首帧」（pane 为其内容），main=「新生成」（现有卡体）
  altTab?: { alt: string; main: string; pane: ReactNode }
  note?: string        // 参考区下方补充说明（如"已剔除：X（本镜剧本无出场）"）
}) {
  const [tab, setTab] = useState<'main' | 'alt'>('main')
  // 视频区正文已上移到分镜脚本/前置条件（body/prompt/emptyHint 皆空时不占位）
  const promptBody = body ?? (prompt ? <ClampText text={prompt} />
    : emptyHint ? <div className="dim">{emptyHint}</div> : null)
  const head = (
    <div className="aux-title prompt-card-head">
      <Icon name={icon} /> {title}
      {edited && <span className="tag" title="已手动编辑：自动装配不覆盖">手编</span>}
      {busy && <Icon name="spinner" spin />}
      {/* 右侧 tab 组（seg 样式，同「正文/视频」）：左=质检评分（仅上色、无胶囊），右=「画布」常高亮
          （active）。画布=打开本帧的无限画布看图/编提示词/开始生成（技术提示词按需装配，不在卡上直显） */}
      <span className="seg card-edit-seg">
        <ReviewTag r={review} plain />
        {variant !== 'video' && (
          <button type="button" className="seg-btn active" disabled={busy}
            onClick={() => !busy && onOpen()}
            title="进入本帧的无限画布编辑模式">
            <Icon name="workflow" /> 画布
          </button>
        )}
      </span>
    </div>
  )
  const chip = (r: EditRef) => {
    const isOff = off.includes(r.name)
    // 首帧/尾帧：未出图渲染为虚线空占位，点击直达对应编辑弹框（尾帧可选，留空即不带）
    const frame = r.kind === 'keyframe' || r.kind === 'lastframe'
    const empty = frame && !r.url
    // 音频声线卡：有小样=可试听（叠播放角标）；无小样=未生成（虚线态，点击按角色特征捏音色）
    const audio = r.kind === 'audio'
    const audioGen = audio && !!r.audioUrl
    // 要素占位（设定图未生成）：同款虚线空占位，点击进要素预览可直接生成
    const ph = !frame && !audio && !r.url
    const base = audio
      ? (r.busy ? `${r.name}——正在按角色特征生成音色…`
        : audioGen ? `${r.name}——点击试听配音小样（再点停止）`
        : `${r.name}——尚未生成，点击按角色特征/年龄自动捏音色并生成小样`)
      : frame
      ? (empty
        ? (r.kind === 'lastframe'
          ? '尾帧未生成（可选，留空则本镜不带尾帧）——点击打开尾帧生成弹框（对应下方尾帧卡）'
          : '首帧未生成——点击打开首帧生成弹框（对应下方首帧卡）')
        : `${r.name}${isOff ? '（已停用：生成时不使用）' : ''}——点击打开生成弹框（看图/编提示词/重生成）`)
      : `${r.name}${isOff ? '（已停用：生成时不使用）' : ''}——${ph ? '设定图未生成：点击打开要素预览可直接生成' : '启停与删除在「查看」弹框内'}`
    return (
      <span key={r.name}
        className={'ref-chip' + (isOff ? ' off' : '') + (frame ? ' kf-chip' : '')
          + (empty ? ' kf-empty' : '') + (ph ? ' ref-ph' : '')
          + (audio ? ' audio-chip' : '') + (audio && !audioGen && !r.busy ? ' audio-off' : '')}
        title={r.hint ? `${base}。${r.hint}` : base}
        onClick={() => onOpenRef(r)}>
        {audio
          ? <Icon name={r.busy ? 'spinner' : 'speaker'} spin={r.busy} />
          : r.url ? <img src={r.url} alt="" /> : <Icon name={REF_ICON[r.kind] ?? 'image'} />}
        {audioGen && !r.busy && <span className="audio-play"><Icon name="play" /></span>}
        {/* 带勾选框的帧不再单独显示帧名，名由下方勾选标签承载（固定X帧 / X帧参考），避免重复 */}
        {!(frame && !empty && onToggleFrame) && r.name}
        {/* 首/尾帧「固定」勾选：仅已出图的帧显示——勾选=以首尾帧模式提交 Seedance（画面锁定该帧），
            取消=仅用提示词描述该画面、不锁帧。点勾选不冒泡到 chip（避免误开生成弹框）。
            标签文字随勾选态：已固定=「固定X帧」，未固定=「X帧参考」（同时替代上面的帧名）。 */}
        {frame && !empty && onToggleFrame && (
          <label className="kf-lock" onClick={e => e.stopPropagation()}
            title={isOff
              ? '未固定：生成视频时仅用提示词描述该画面，不把此帧作为锁定帧'
              : '已固定：以首尾帧模式提交 Seedance，视频画面锁定该帧'}>
            <input type="checkbox" checked={!isOff} onChange={() => onToggleFrame(r.name)} />
            {isOff
              ? (r.kind === 'lastframe' ? '尾帧参考' : '首帧参考')
              : (r.kind === 'lastframe' ? '固定尾帧' : '固定首帧')}
          </label>
        )}
      </span>
    )
  }
  // 视频卡：其他参考独立容器（要素/音频/手选 + ＋添加）在上，首尾帧行在下。
  // 两者可拆成两块分别放（本镜参考上移到分镜脚本下方、首尾帧留在首帧卡上方对接连线）：
  // 不传 frames=只渲染参考容器；无 refs 且无 onAdd=只渲染首尾帧行（小标题由卡头承载，不重复）
  const framesOnly = variant === 'video' && !refs.length && !onAdd
  const chips = variant === 'video' ? (
    <>
      {!framesOnly && (
        <div className="ref-chips vc-others">
          {refs.map(chip)}
          {onAdd && (
            <span className="ref-chip vc-add" onClick={onAdd}
              title="添加参考：打开视频编辑弹框，从项目资产（设定图/首帧/故事板/封面等）中挑选">
              <span className="vc-add-box">＋</span>
              添加
            </span>
          )}
        </div>
      )}
      {frames && (
        <>
          {/* 与参考容器同框时才需要小标题区分；单独成块时卡头已是「首尾帧」 */}
          {!framesOnly && <div className="aux-title vc-frames-title"><Icon name="palette" /> 首尾帧</div>}
          <div className="ref-chips vc-frames">{frames.map(chip)}</div>
        </>
      )}
    </>
  ) : (
    <div className="ref-chips">
      {refs.map(chip)}
      {refs.length === 0 && <span className="dim" style={{ fontSize: 12 }}>无参考</span>}
    </div>
  )
  // 首帧/尾帧卡页签行：「取邻镜帧」（抽取）/「新生成」（现有生成卡体），按次序 alt 在前
  const tabs = altTab && (
    <div className="gen-tabs">
      <span className={'gen-tab' + (tab === 'alt' ? ' active' : '')}
        onClick={() => setTab('alt')}>{altTab.alt}</span>
      <span className={'gen-tab' + (tab === 'main' ? ' active' : '')}
        onClick={() => setTab('main')}>{altTab.main}</span>
    </div>
  )
  // 三卡同用一张深色圆角卡（背景一致），从上到下：标题+按钮 →（页签）→ 提示词 → 参考素材
  return (
    <div className="aux-block">
      {/* 视频区挂 vc-cell（尾帧连线段1从其下沿垂出）+ vc-flat（去卡片底色，只剩参考容器自己的框）；
          首帧卡挂 kf-cell / 尾帧卡挂 lkf-cell：向上引连线对接视频区首尾帧行对应格位 */}
      <div className={'film-cell' + (variant === 'first' ? ' kf-cell'
        : variant === 'last' ? ' lkf-cell' : ' vc-cell vc-flat')}>
        {head}
        {tabs}
        {altTab && tab === 'alt' ? altTab.pane : (
          <>
            {promptBody && <div className="film-mid">{promptBody}</div>}
            {chips}
            {note && <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{note}</div>}
          </>
        )}
      </div>
    </div>
  )
}
