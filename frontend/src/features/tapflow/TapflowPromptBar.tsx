import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import type { TapNode } from '../../lib/tapflowData'
import { api, type ModelCapabilities } from '../../api'

export type TapPromptSendMode = 'rewrite_generate' | 'rewrite_only' | 'on_demand'

const SEND_MODES: { mode: TapPromptSendMode; menuLabel: string; label: string }[] = [
  { mode: 'rewrite_generate', menuLabel: '先优化提示词再生成', label: '提示词＋生成' },
  { mode: 'rewrite_only', menuLabel: '仅优化提示词', label: '仅优化提示词' },
  { mode: 'on_demand', menuLabel: '按需生成', label: '按需生成' },
]
const EMPTY_ISSUES: string[] = []

/**
 * 选中节点下方的生成输入条：参考图缩略图 + prompt 输入框 + 模型/参数/发送。
 * 提示词就地可改（回写节点）；发送 = 指令投递给对话面板自动发出（通用下发方案），
 * 由 AI 流式规划执行——不弹属性/运行面板，思考与执行全程在对话区可见。
 */
export function TapflowPromptBar({
  gen, textOnly, stage, inherited = [], refNodes = [], refMenu,
  businessRefs = [], onBusinessRefAdd, onBusinessRefRemove,
  onSend, onPromptChange, onIssueChange, onRefAdd, onRefRemove, onRegen, regenBusy,
  mentionCandidates, onMentionPick, modality,
}: {
  gen: NonNullable<TapNode['gen']>
  /** 产物形态（投影自节点 config.modality）：决定能力档案拉生图还是生视频——
   * 视频节点显示 active 视频模型名，而不是永远显示 active 生图模型 */
  modality?: 'image' | 'video'
  /** 产出是文字的节点（文本/质检）：不显示实体参考图与画面参数 */
  textOnly?: boolean
  /** 已选的上游参考节点（画布解析好的：有图给缩略图，没图给标题） */
  refNodes?: { id: string; title: string; src?: string }[]
  /** 「+」弹出的候选浮窗（由画布渲染，这里只留位置） */
  refMenu?: ReactNode
  /** 可 @ 提及的上游节点（画布解析好的：no=选中后将占的参考序号，插入 @图片N 用） */
  mentionCandidates?: { id: string; title: string; src?: string; no?: number }[]
  /** @ 弹层选中：画布把该节点并入参考（refNodes）——图随提示词一起提交 */
  onMentionPick?: (id: string) => void
  /** 业务对象的统一参考关系；与面板和旧无限画布同源，不属于 Tapflow 图结构。 */
  businessRefs?: { id: number; name: string; src?: string | null }[]
  onBusinessRefAdd?: () => void
  onBusinessRefRemove?: (id: number) => void
  onRefAdd?: () => void
  onRefRemove?: (id: string) => void
  /** 右上角徽标：节点内部跑到哪一段（装配/质检/出图），跑完留质检得分 */
  stage?: TapNode['stage']
  /** 哪几个参数是从项目设定继承来的（比例/画风）：标灰，点了也改不了 */
  inherited?: string[]
  onSend?: (mode: TapPromptSendMode) => void
  onPromptChange?: (v: string) => void
  /** 提示词检查分析可就地修订；重新生成会直接使用修订后的内容。 */
  onIssueChange?: (index: number, value: string) => void
  /** 质检未通过时的「重新生成」：把原提示词 + 质检原因交给模型重写并复判 */
  onRegen?: () => void
  /** 重写进行中：按钮转圈禁用 */
  regenBusy?: boolean
}) {
  // 质检问题清单：不合格默认摊开——判不过却看不到为什么，用户只能瞎改重试；
  // 通过时收起（分数就够了），点徽标随时开合。
  const issues = stage?.issues ?? EMPTY_ISSUES
  const [openQc, setOpenQc] = useState(stage?.tone === 'err')
  useEffect(() => { setOpenQc(stage?.tone === 'err' && (stage.issues?.length ?? 0) > 0) },
    [stage?.tone, stage?.label, stage?.issues?.length])

  // 提示词框随内容长高（到上限再滚）：装配出来的提示词动辄十几行，
  // 钉死 3 行等于让人隔着门缝校对自己要改的东西。
  // 生成模式：左侧标签每次点击都打开菜单，选项本身立即执行；右侧闪电始终按需生成。
  const [sendMode, setSendMode] = useState<TapPromptSendMode>('on_demand')
  const [sendMenuOpen, setSendMenuOpen] = useState(false)
  const sendMenuRef = useRef<HTMLSpanElement>(null)
  // 能力档案（2026-09-17）：当前 active 模型的真实名称与参考图上限，
  // 来自 /api/models/capabilities——系统管理里切换模型后 30s 内这里自动跟上。
  // 按**产物形态**拉对应 purpose：视频节点显示 active 视频模型，而不是把
  // 生图模型名盖在视频节点上（用户看到“视频节点怎么是图片节点”的根源）
  const [modelCaps, setModelCaps] = useState<ModelCapabilities | null>(null)
  const capsPurpose = modality === 'video' ? 'video' : 'image'
  useEffect(() => {
    api.getModelCapabilities(capsPurpose)
      .then(d => setModelCaps(d.active))
      .catch(() => { /* 拉不到就退回 gen.model 的默认显示，不挡生成 */ })
  }, [capsPurpose])
  const sendLabel = SEND_MODES.find(x => x.mode === sendMode)?.label ?? '按需生成'
  // The node stage is the only execution indicator; this button stays static.
  const send = (mode: TapPromptSendMode) => {
    setSendMode(mode)
    setSendMenuOpen(false)
    onSend?.(mode)
  }
  useEffect(() => {
    if (!sendMenuOpen) return
    const close = (e: PointerEvent) => {
      if (!sendMenuRef.current?.contains(e.target as Node)) setSendMenuOpen(false)
    }
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSendMenuOpen(false)
    }
    document.addEventListener('pointerdown', close, true)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', close, true)
      document.removeEventListener('keydown', escape)
    }
  }, [sendMenuOpen])
  const ta = useRef<HTMLDivElement>(null)
  const issueTextareas = useRef<(HTMLTextAreaElement | null)[]>([])
  // @ 提及（2026-09-17）：输入 @ 弹上游参考列表，选中后插入胶囊——
  // 胶囊内是圆形小缩略图 + 「@图片N」，N 与提交参考图顺序一一对应
  const [mention, setMention] = useState<{ q: string } | null>(null)
  const mentionList = mention
    ? (mentionCandidates ?? [])
        .filter(c => !mention.q || c.title.toLowerCase().includes(mention.q.toLowerCase()))
        .slice(0, 8)
    : []
  // ---- 胶囊编辑器（contenteditable）：gen.prompt 仍是纯文本（后端协议不变），
  // 「@图片N」只在渲染层映射成带缩略图的胶囊；序列化时胶囊还原回文本
  const serializePrompt = (el: HTMLElement) => {
    let out = ''
    el.childNodes.forEach(n => {
      if (n.nodeType === Node.TEXT_NODE) out += n.textContent ?? ''
      else if (n instanceof HTMLElement && n.dataset.mention) out += n.dataset.label || ''
    })
    return out
  }
  const makeChip = (label: string, src?: string) => {
    const chip = document.createElement('span')
    chip.className = 'tap-chip'
    chip.contentEditable = 'false'
    chip.dataset.mention = '1'
    chip.dataset.label = label
    if (src) {
      const img = document.createElement('img')
      img.src = src; img.alt = ''; img.draggable = false
      chip.appendChild(img)
    }
    const b = document.createElement('b')
    b.textContent = label
    chip.appendChild(b)
    return chip
  }
  const renderInto = (el: HTMLElement, text: string) => {
    el.innerHTML = ''
    const re = /@图片\d+/g
    let last = 0, m: RegExpExecArray | null
    while ((m = re.exec(text))) {
      if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)))
      // 胶囊里的圆形小图按编号取参考区同位的那张（@图片N ↔ 参考图第 N 个）
      const ref = refNodes[Number(m[0].slice(3)) - 1]
      el.appendChild(makeChip(m[0], ref?.src))
      last = m.index + m[0].length
    }
    if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)))
  }
  // 外部回填（预检/生成完回写）与参考区变化 → 重渲胶囊；自己打字时
  // 序列化结果与 prompt 一致，不重渲，光标不动
  useLayoutEffect(() => {
    const el = ta.current
    if (!el) return
    if (serializePrompt(el) !== gen.prompt) renderInto(el, gen.prompt)
  }, [gen.prompt, refNodes])
  const checkMention = () => {
    const el = ta.current
    const sel = window.getSelection()
    if (!el || !sel || !sel.isCollapsed || !sel.anchorNode || !el.contains(sel.anchorNode)
      || sel.anchorNode.nodeType !== Node.TEXT_NODE) { setMention(null); return }
    const before = (sel.anchorNode.textContent || '').slice(0, sel.anchorOffset)
    const m = /(?:^|\s)@([^\s@]*)$/.exec(before)
    setMention(m ? { q: m[1] } : null)
  }
  const pickMention = (c: { id: string; title: string; no?: number }) => {
    const el = ta.current
    const sel = window.getSelection()
    if (!el || !sel || !sel.anchorNode || sel.anchorNode.nodeType !== Node.TEXT_NODE) return
    const node = sel.anchorNode
    const off = sel.anchorOffset
    const text = node.textContent || ''
    const before = text.slice(0, off)
    const m = /(?:^|\s)@([^\s@]*)$/.exec(before)
    if (!m) return
    // 编号与提交参考图顺序一一对应（模型按图1/图2 对图）；胶囊不参与编辑，
    // 整体删除/光标跳过是浏览器对 contenteditable=false 元素的默认行为
    const label = c.no ? `@图片${c.no}` : `@${c.title}`
    node.textContent = before.slice(0, before.length - m[0].length)
    const chip = makeChip(label, refNodes[(c.no ?? 0) - 1]?.src)
    const tail = document.createTextNode(' ' + text.slice(off))
    node.parentNode?.insertBefore(chip, node.nextSibling)
    node.parentNode?.insertBefore(tail, chip.nextSibling)
    const r = document.createRange()
    r.setStart(tail, 1); r.collapse(true)
    sel.removeAllRanges(); sel.addRange(r)
    onPromptChange?.(serializePrompt(el))
    onMentionPick?.(c.id)
    setMention(null)
  }
  useLayoutEffect(() => {
    issueTextareas.current.forEach(el => {
      if (!el) return
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight}px`
    })
  }, [issues, openQc])

  return (
    <div className="tap-prompt-bar"
      onPointerDown={e => e.stopPropagation()}
      // 生成框是独立操作面板，悬停其上时滚轮不得冒泡成画布平移/缩放。
      onWheel={e => e.stopPropagation()}>
      {/* 右上角状态徽标：装配提示词 / 质检中 / 图片生成中 → 跑完留质检得分 */}
      {stage && (issues.length
        ? (
          <button type="button" title={openQc ? '收起质检原因' : '查看质检原因'}
            className={'tap-stage-badge clickable ' + (stage.tone ?? 'run')}
            onClick={() => setOpenQc(v => !v)}>
            {stage.label}
            <em className={'tap-stage-caret' + (openQc ? ' up' : '')}>▾</em>
          </button>
        )
        : (
          <span className={'tap-stage-badge ' + (stage.tone ?? 'run')}>
            {(stage.tone ?? 'run') === 'run' && <Icon name="spinner" spin />}
            {stage.label}
          </span>
        ))}
      {/* 参考条：文本卡也要有——重新生成时同样需要「参考上游哪几个节点」。
          存的是节点 id 不是 url：节点重跑后产物会变，存 id 才永远指向最新的那份。 */}
      <div className="tap-prompt-refs">
        {!textOnly && (
          <span className="tap-prompt-ref-fixed">
            <button type="button" className="tap-ref-auto" title="自动参考"><Icon name="wand" /></button>
            <span className="tap-tool-sep" />
          </span>
        )}
        {!textOnly && businessRefs.length === 0
          // 与参考节点同图的静态预览不重复展示：@/手选挂了上游节点后，
          // 预检回填的 gen.refs 里会多出同一张 url（2026-09-17 用户实测），跳过它
          && gen.refs.filter(r => !refNodes.some(n => n.src && n.src === r))
            .map((r, i) => <img key={i} src={r} alt="" draggable={false} />)}
        {businessRefs.map(r => (
          <span key={`business-${r.id}`} className={'tap-ref-node ' + (r.src ? 'img' : 'txt')}
            title={r.name} data-business-reference="true">
            {r.src ? <img src={r.src} alt={r.name} draggable={false} />
              : <><Icon name="image" /><em>{r.name}</em></>}
            <button type="button" className="tap-ref-del" title={`移除参考：${r.name}`}
              onClick={() => onBusinessRefRemove?.(r.id)}>×</button>
          </span>
        ))}
        {refNodes.map((r, i) => (
          <span key={r.id} className={'tap-ref-node ' + (r.src ? 'img' : 'txt')} title={r.title}>
            {r.src
              ? <><img src={r.src} alt="" draggable={false} /><i className="tap-ref-no">{i + 1}</i></>
              : <><Icon name="text" /><em>{r.title}</em></>}
            <button type="button" className="tap-ref-del" title="移除"
              onClick={() => onRefRemove?.(r.id)}>×</button>
          </span>
        ))}
        <span className="tap-prompt-ref-fixed right">
          <span className="tap-ref-add-wrap">
          <button type="button" className="tap-ref-add" title="添加参考"
            onClick={() => onRefAdd?.()}><Icon name="plus" /></button>
          {refMenu}
          </span>
          {onBusinessRefAdd && <button type="button" className="tap-ref-add"
          title="从项目素材库添加统一参考" aria-label="从项目素材库添加统一参考"
            onClick={onBusinessRefAdd}><Icon name="folder" /></button>}
          {!!businessRefs.length && <span className="tap-ref-count" title="统一参考资产数量">
            {businessRefs.length} 项
          </span>}
        </span>
      </div>
      {/* 质检原因：就摊在提示词正上方——判据说了什么，紧挨着要改的那段文字，
          不用去别的面板里找。清单长了自己滚动，不把整条生成条撑到满屏。 */}
      {openQc && !!issues.length && (
        <div className="tap-qc-why">
          <div className="tap-qc-why-head">
            <Icon name="alert" /> 提示词检查分析
          </div>
          <ul>{issues.map((x, i) => (
            <li key={i}>
              <textarea
                ref={el => { issueTextareas.current[i] = el }}
                className="tap-qc-issue-edit"
                rows={1}
                value={x}
                aria-label={`提示词检查分析 ${i + 1}`}
                onChange={e => onIssueChange?.(i, e.target.value)}
                onKeyDown={e => e.stopPropagation()}
                onWheel={e => e.stopPropagation()} />
            </li>
          ))}</ul>
          {/* 重新生成 = 按质检原因重写，再强制单点出图并复判。 */}
          {onRegen && (
            <div className="tap-qc-why-foot">
              <button type="button" className="tap-qc-regen" disabled={regenBusy}
                title="按提示词检查分析修复并重新生成" onClick={onRegen}>
                <Icon name={regenBusy ? 'spinner' : 'refresh'} spin={regenBusy} />
                {regenBusy ? ' 生成中…' : ' 修复生成'}
              </button>
              <span className="tap-qc-hint">将按质检原因重写并复检</span>
            </div>
          )}
        </div>
      )}
      <span className="tap-mention-host">
        {mention && mentionList.length > 0 && (
          <span className="tap-mention-menu" role="listbox" aria-label="提及上游参考">
            {mentionList.map(c => (
              <button type="button" key={c.id} className="tap-mention-item" role="option"
                onMouseDown={e => { e.preventDefault(); pickMention(c) }}>
                {c.src
                  ? <img src={c.src} alt="" draggable={false} />
                  : <Icon name={textOnly ? 'text' : 'image'} />}
                <em>{c.title}</em>
              </button>
            ))}
            <span className="tap-mention-hint">选中即挂为参考图</span>
          </span>
        )}
        <div
          ref={ta} className="tap-prompt-edi" contentEditable suppressContentEditableWarning
          role="textbox" aria-multiline="true" aria-label="提示词"
          data-ph="描述你的需求，@可提及上游参考，如：@图片1 在吃汉堡"
          // 这里只写**用户自己的需求**（如「一只小猫在等待空气炸锅产出的鸡腿」）。
          // 项目画风/画布上文/技能是系统隐式挂载：实跑时自动拼给大模型按需规划，
          // 不回显、不占输入框；改过的内容照常冻结（预检不再覆盖用户输入）。
          // @图片N 渲染成胶囊（渲染层）；序列化仍是纯文本，后端协议不变
          onInput={() => { const el = ta.current; if (el) onPromptChange?.(serializePrompt(el)); checkMention() }}
          onKeyUp={checkMention}
          // 输入框里的按键/滚轮别冒泡给画布（否则空格平移、滚轮缩放）
          onKeyDown={e => { e.stopPropagation(); if (e.key === 'Escape') setMention(null) }}
          onBlur={() => { setTimeout(() => setMention(null), 120) }}
          onWheel={e => e.stopPropagation()}
          // 粘贴一律当纯文本，避免外部富文本带进标签；粘进来的 @图片N 文本
          // 在微任务里补成胶囊（光标不敏感场景，可接受）
          onPaste={e => {
            e.preventDefault()
            const t = e.clipboardData.getData('text/plain')
            if (!t) return
            document.execCommand('insertText', false, t)
            setTimeout(() => {
              const el = ta.current
              if (!el) return
              // 粘进来的 @图片N 是裸文本 → 补成胶囊（含胶囊时序列化结果不变，
              // 只在确有裸 token 时重渲）
              const text = serializePrompt(el)
              if (/@图片\d+/.test(text) && !el.querySelector('.tap-chip')) {
                renderInto(el, text); onPromptChange?.(text)
              }
            }, 0)
          }} />
      </span>
      <div className="tap-prompt-foot">
        <span className="tap-foot-left">
          {/* 模型名来自能力档案：显示真实档名（如 qwen-image-edit-plus），拉不到才退回旧文案 */}
          <span className="tap-model"><Icon name="blocks" />
            <span>{modelCaps?.name || gen.model}</span></span>
          {/* 参考图能力徽标：当前模型支持几张、什么角色（档案驱动，系统管理切换自动变） */}
          {modelCaps && modelCaps.capabilities.refs.max > 0 && (
            <span className="tap-param inherit"
              title={modelCaps.capabilities.refs.kind === 'edit_base'
                ? '图像编辑模型：首张参考图作底图，出图比例跟随它'
                : '当前模型的参考图上限'}>
              <span>参考图 ≤{modelCaps.capabilities.refs.max}</span></span>
          )}
          {/* 上限 0 的档（如 wanx-v1）：挂着参考节点的图也不会传给模型——
              明说，别让用户以为参考生效了（2026-09-17 用户实测）。
              仅图片语境显示：视频参考图走后端提示词引用句装配，不吃这条生图口径 */}
          {modelCaps && modality !== 'video' && modelCaps.capabilities.refs.max === 0 && refNodes.length > 0 && (
            <span className="tap-param inherit"
              title="当前出图模型是纯文生图，画布上游参考图不会传给模型；要照图出图，请在系统管理切换到支持参考图的模型（如图像编辑模型）">
              <span>模型不吃参考图</span></span>
          )}
          {modelCaps && !modelCaps.capabilities.aspects && modelCaps.capabilities.refs.max > 0 && (
            <span className="tap-param inherit" title="该模型不支持指定比例，出图比例跟随参考图">比例随参考图</span>
          )}
        {/* 比例与画风来自开始节点的项目设定，不是本节点自己的参数——标出来，
            免得让人以为能在这里改（改要去项目页） */}
          {gen.params.map(p => (
            <span key={p} className={'tap-param' + (inherited.includes(p) ? ' inherit' : '')}
              title={inherited.includes(p) ? '项目设定' : undefined}><span>{p}</span></span>
        ))}
        </span>
        <span className="tap-foot-right">
          {/* 左侧选择并立即执行生成模式；右侧圆形按钮不受当前标签影响，始终按需生成。 */}
          <span className="tap-send-group" ref={sendMenuRef}>
          <button type="button" className="tap-rewrite"
            aria-haspopup="menu" aria-expanded={sendMenuOpen}
            title="选择生成方式" onClick={() => setSendMenuOpen(v => !v)}>
            <span className={'tap-rewrite-caret' + (sendMenuOpen ? ' open' : '')} aria-hidden="true">▾</span>
            <span>{sendLabel}</span>
          </button>
          {sendMenuOpen && (
            <span className="tap-send-menu" role="menu" aria-label="生成方式">
              {SEND_MODES.map(item => (
                <button type="button" key={item.mode}
                  className={'tap-send-menu-item' + (item.mode === sendMode ? ' selected' : '')}
                  role="menuitemradio" aria-checked={item.mode === sendMode}
                  onClick={() => send(item.mode)}>
                  <span>{item.menuLabel}</span>
                  {item.mode === sendMode && <span className="tap-send-menu-check">✓</span>}
                </button>
              ))}
            </span>
          )}
          <button type="button" className="tap-send-btn"
            title="按需生成"
            onClick={() => send('on_demand')}><Icon name="zap" /></button>
          </span>
        </span>
      </div>
    </div>
  )
}
