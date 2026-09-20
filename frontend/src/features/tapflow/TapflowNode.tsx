import { useEffect, useRef, useState } from 'react'
import { Icon, type IconName } from '../../components/Icon'
import type { TapNode } from '../../lib/tapflowData'
import { TapflowNodeMedia } from './TapflowNodeMedia'
import { TapflowNodeText } from './TapflowNodeText'
import { TapflowPort } from './TapflowPort'
import { TapflowStartNode } from './TapflowStartNode'
import { MOUNT_TARGETS, mountTargetLabel, mountTargetMedia } from '../../lib/tapflowData'

const TYPE_ICON: Record<TapNode['type'], IconName> = {
  image: 'image', text: 'text', video: 'video', audio: 'speaker', upload: 'image', gen: 'image',
  start: 'play', qc: 'check', link: 'link', flow: 'workflow', tool: 'tools', condition: 'node', loop: 'loop',
  mount: 'save',
}
/** 高度由内容撑开的节点类型（node.h 仅用于连线锚点，不裁剪内容） */
const SELF_SIZED: TapNode['type'][] = ['start', 'link', 'flow', 'qc', 'condition', 'mount']

/** 来源标题 → 牌子短名：取「·」前的主体段，剥掉「图片生成/视频生成」这类生成词。
 * 「核心要素图片生成 · 都市多场景生活切片」→「核心要素」；无「·」且无生成词则原样返回。 */
const shortMountSource = (title: string): string => {
  const head = title.split('·')[0].trim()
  const stripped = head.replace(/(图片|视频|文本|音频|文案)生成$/, '').trim()
  return stripped || head || title
}
/** 媒体类节点：卡内容由 TapflowNodeMedia 画 */
const MEDIA: TapNode['type'][] = ['image', 'upload', 'gen', 'audio', 'video']
type TapflowLoopPreview = { id: string; src?: string; title?: string }

/**
 * tapflow 节点卡片：内容直出（图片显示图片本体 / 文本直接显示正文 / 视频显示封面或播放占位），
 * 标题行 = 类型图标 + 名称 + 运行完成蓝色对勾徽章。选中的图片/视频节点浮出工具条与生成输入条。
 */
export function TapflowNode({
  node, title, flowName, mode, selected, dropTarget, onSelect, onDrag, onPortDrag,
  onMeasure, onText, editing, onEditDone, onDragEnd, onResize, loopPreview, loopChildCount,
  onUpload, onRemoveRefImage, upstreamUrl, upstreamTitle, takenTargets, mountEditing, onMountPick, onMountEdit, initialUrl,
}: {
  node: TapNode
  /** 该节点引用的工作流名（subflow 节点才有）：画布上标出"引用了哪张流程" */
  flowName?: string
  /** 展示用标题：ui.title 里的 `{{input.x}}` 已按当前入参替换（如「场景介绍 · 浮空灯塔」）。
   * node.title 保持模板原样——它会被原样存回 ui.title,替换过就把某次运行的对象名写死进定义了 */
  title?: string
  /** 编排态=模板（只有入参声明，没有项目）；运行态=带上下文（项目设定 + 实际入参值） */
  mode: 'edit' | 'run'
  selected: boolean
  /** 正被拖来的连线悬停其上、且松手就会连上：描边高亮 */
  dropTarget?: boolean
  /** additive=Shift/⌘ 点击：在多选集合里加/减本节点，而不是重置成只选它 */
  onSelect: (id: string, additive: boolean) => void
  /** 拖动本节点；若它在多选集合里，画布会把整组一起挪 */
  onDrag: (id: string, dx: number, dy: number) => void
  onDragEnd?: (id: string) => void
  /** 右下角拖动改变节点宽高；位移使用屏幕像素，由画布换算缩放比例。 */
  onResize?: (id: string, dx: number, dy: number) => void
  /** 从左右圆点拖出：由画布接管（临时连线 + 松手弹「引用该节点生成」菜单） */
  onPortDrag?: (id: string, side: 'left' | 'right', e: React.PointerEvent, branch?: string) => void
  /** 回传实测高度：卡片高度由内容/图片撑开，连线锚点必须用实测值才落在卡片中线 */
  onMeasure?: (id: string, h: number) => void
  /** 文本节点正文改完（双击或工具条「编辑」进编辑态、失焦提交）。不给则不可编辑 */
  onText?: (id: string, text: string) => void
  /** 由画布控制的编辑态（工具条「编辑」触发）；组件内双击也能进 */
  editing?: boolean
  onEditDone?: () => void
  /** 循环节点的子节点预览；仅影响显示，不改变循环节点的交互或运行语义。 */
  loopPreview?: TapflowLoopPreview[]
  /** 循环母卡当前实际展示的子元素数；运行态由瞬态实例计算，编排态由 body 定义计算。 */
  loopChildCount?: number
  /** 参考图节点：用户选了本地文件（画布负责直传 OSS 并写回节点 src） */
  onUpload?: (id: string, file: File) => void
  /** 出图节点：从卡上移除一张已上传的静态参考图（画布负责从 refImages 清单里去掉） */
  onRemoveRefImage?: (id: string, url: string) => void
  /** 挂载点：最近一根入边上的媒体产物（运行前的实时回显源；落库后仍以 node.mount.url 优先） */
  upstreamUrl?: string
  /** 挂载点：来源节点标题（模板已解析）——牌子的「挂载点：X」与卡内信息栏用它说明素材从哪来 */
  upstreamTitle?: string
  /** 挂载点：入口业务对象的当前产物（如项目现有封面）——连线与运行回显都还没有时的兜底显示 */
  initialUrl?: string
  /** 挂载点：其他挂载点已占用的归宿——列表里禁掉同归宿的第二个挂载点 */
  takenTargets?: string[]
  /** 挂载点正处于「重新选择归宿」状态（工具条「修改」触发） */
  mountEditing?: boolean
  /** 挂载点：点选归宿列表项（画布负责写回节点并关闭选择态） */
  onMountPick?: (id: string, target: string) => void
  /** 挂载点：胶囊上的 ⚙ —— 重新打开归宿选择列表 */
  onMountEdit?: (id: string) => void
}) {
  // “循环”有两层语义：真实 loop 是一种执行节点；被引用的子工作流若
  // 会汇聚多个子产物，只是引用卡片的产物基数状态，绝不能把卡片渲染成 loop。
  const loopAggregate = !!node.loop?.aggregate
  // A multi-output subflow is rendered as its native card type (usually `gen`)
  // but carries aggregate semantics. Treat it like a loop for the transient
  // child stack; otherwise its child products are projected into state but
  // remain invisible in the canvas.
  const structuralLoop = node.type === 'loop' || loopAggregate
  const loopPreviewCards = structuralLoop
    ? Array.from({ length: 3 }, (_, index) => loopPreview?.[index] ?? { id: `empty-${index}` })
    : []
  const ref = useRef<HTMLDivElement>(null)
  // 挂载点回显媒体的原始宽高比（img onLoad / video onLoadedMetadata 读）。
  // 比例 > 3:2 的宽幅媒体切上下布局（媒体满宽在上、信息在下），矩形/竖版保持左右。
  const [mediaRatio, setMediaRatio] = useState<number>()
  const mediaImgRef = useRef<HTMLImageElement>(null)
  // 兼底：缓存命中的图片 load 事件偶发不派发——src 变化后若已解码完，直接读原始宽高
  const mountSrc = upstreamUrl ?? node.mount?.url ?? initialUrl
  useEffect(() => {
    const el = mediaImgRef.current
    if (el?.complete && el.naturalWidth) {
      setMediaRatio(el.naturalWidth / Math.max(1, el.naturalHeight))
    }
  }, [mountSrc])
  useEffect(() => {
    const el = ref.current
    if (!el || !onMeasure) return
    const ro = new ResizeObserver(() => onMeasure(node.id, el.offsetHeight))
    ro.observe(el)
    onMeasure(node.id, el.offsetHeight)
    return () => ro.disconnect()
  }, [node.id, onMeasure])
  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation()
    if (e.button !== 0) return
    const additive = e.shiftKey || e.metaKey
    // 已在选中集合里且不是加选：按下**先不动**选中集，这样按住就能把整组一起拖走；
    // 真没拖动（纯点一下）才在松手时收敛成只选它
    if (additive || !selected) onSelect(node.id, additive)
    const sx = e.clientX, sy = e.clientY
    let lx = sx, ly = sy
    let moved = false
    const move = (ev: PointerEvent) => {
      if (Math.abs(ev.clientX - sx) > 3 || Math.abs(ev.clientY - sy) > 3) moved = true
      onDrag(node.id, ev.clientX - lx, ev.clientY - ly)
      lx = ev.clientX; ly = ev.clientY
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      if (!moved && !additive) onSelect(node.id, false)
      if (moved) onDragEnd?.(node.id)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const onResizePointerDown = (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.button !== 0) return
    let lastX = e.clientX, lastY = e.clientY
    const move = (ev: PointerEvent) => {
      onResize?.(node.id, ev.clientX - lastX, ev.clientY - lastY)
      lastX = ev.clientX
      lastY = ev.clientY
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div
      ref={ref}
      className={'tap-node' + (selected ? ' selected' : '') + (dropTarget ? ' drop-target' : '')
        + (node.type === 'qc' ? ' is-qc' : '') + (node.type === 'tool' ? ' is-tool' : '')
        + (node.type === 'condition' ? ' is-condition' : '')
        + (node.type === 'mount' ? ' is-mount' : '')
        + (node.runtime ? ' runtime-instance' : '')
        // A node enters the running state as soon as the planner accepts the
        // request (stage.tone=run), before the backend media executor reports
        // status=generating. Keep the canvas indicator in lockstep with that
        // lifecycle so hidden planning/dependency work is visible too.
        + (node.status === 'generating' || node.stage?.tone === 'run' ? ' running' : '')
        + (structuralLoop ? ' loop-preview-node' : '')
        + (node.manualSize ? ' manual-sized' : '')}
      style={{ left: node.x, top: node.y, width: node.w }}
      onPointerDown={onPointerDown}>
      <div className="tap-node-title">
        <Icon name={TYPE_ICON[node.type]} />
        <span className="tap-node-title-text">
          {node.type === 'mount' && node.mount?.target
            ? mountTargetLabel(node.mount.target)
            : (title ?? node.title)}
        </span>
        {/* 引用了另一张工作流就标一枚链接图标。不标的话，一个 subflow 节点在画布上
            跟普通文本卡长得一模一样——换没换、引没引用，全看不出来。
            **只留图标**：节点标题已经说清这一步产出什么，把流程名再挂一遍是纯噪声
            （「场景设定描述」旁边挂「单场景设定描述」），要看引的是哪张就 hover。 */}
        {node.bind?.subflow?.slug && (
          <em className="tap-node-ref"
            title={`引用工作流 ${flowName ?? node.bind.subflow.slug}`}>
            <Icon name="link" />
          </em>
        )}
        {node.done && <span className="tap-done"><Icon name="check" /></span>}
      </div>

      {/* 图片/视频封面：宽度定死、高度随内容自适应；文本与无内容占位用声明高度。
          开始/关联/质检/工作流是内容型卡片——高度由内容撑开，node.h 只作连线锚点 */}
      <div
        className={'tap-node-card' + (node.type === 'qc' ? ' tap-card-qc' : '')
          // 执行中一律套流光边框（不再只在「没图」时套）：重出时卡上还挂着上一张图，
          // 但它确实在跑，边框是此刻画布上唯一能说明「跑到这一步了」的东西
          + (node.status === 'generating' || node.stage?.tone === 'run' ? ' flowing-border' : '')}
        style={{
          height: node.manualSize ? node.h : SELF_SIZED.includes(node.type) ? undefined
            : node.type === 'text' || !node.src || node.runtime ? node.h : undefined,
        }}>
        {MEDIA.includes(node.type) && (node.type === 'upload' && onUpload ? (
          /* 参考图节点：整张卡面就是上传入口，点一下选文件；url 存进节点随画布保存，
             连到下游生成节点就是参考图（引擎按入边收） */
          <label className="tap-upload-hit">
            <TapflowNodeMedia node={node} />
            <input type="file" accept="image/*" hidden
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) onUpload(node.id, file)
                e.currentTarget.value = ''
              }} />
          </label>
        ) : <TapflowNodeMedia node={node} />)}
        {node.type === 'text' && (
          <TapflowNodeText node={node} onText={onText}
            editing={editing} onEditDone={onEditDone} />
        )}
        {node.type === 'start' && <TapflowStartNode node={node} mode={mode} />}
        {/* 质检节点：圆点（灰=未跑 / 绿=通过 / 红=未通过）+ 评分 */}
        {node.type === 'qc' && (
          <div className={'tap-qc-dot ' + (node.qc?.state ?? 'idle')}>
            <Icon name={node.qc?.state === 'fail' ? 'cross' : 'check'} />
            <em>{node.qc?.score ?? (node.qc?.state === 'pass' ? '通过'
              : node.qc?.state === 'fail' ? '未通过' : '未运行')}</em>
          </div>
        )}
        {/* 关联节点：落库动作 + 落点（运行态隐藏但自动执行） */}
        {node.type === 'link' && (
          <div className="tap-link-body">
            <span className="tap-link-act">{node.link?.action ?? '—'}</span>
            <span className="tap-link-target"><Icon name="save" /> {node.link?.target ?? ''}</span>
          </div>
        )}
        {/* 挂载点（2026-09-17）：声明产物归宿。没选归宿（或工具条「修改」中）时
            卡面就是归宿点选列表，点选即绑定；选好后上游连进来的产物实时回显——
            图就是那张图，右下角对号 = 这份产物已指向该归宿。 */}
        {node.type === 'mount' && (mountEditing || !node.mount?.target ? (
          <div className="tap-mount-pick">
            <div className="tap-mount-pick-head">
              {node.mount?.target ? '修改归宿' : '产物落到哪'}
            </div>
            {MOUNT_TARGETS.map(t => {
              const taken = !!takenTargets?.includes(t.v)
              const active = node.mount?.target === t.v
              return (
                <button key={t.v} type="button"
                  className={'tap-mount-item' + (active ? ' active' : '') + (taken && !active ? ' taken' : '')}
                  onPointerDown={e => e.stopPropagation()}
                  onClick={() => onMountPick?.(node.id, t.v)}>
                  <span>{t.label}</span>
                  <em>{active ? '当前' : taken ? '已使用' : ''}</em>
                </button>
              )
            })}
          </div>
        ) : (
          <div className={'tap-mount-body' + (mediaRatio && mediaRatio > 1.02 ? ' stack' : '')}>
          {/* 媒体框采用素材原始比例（未知时退 16:9）；素材加 .stack 决定上下/左右 */}
          <div className="tap-mount-figure"
            style={mediaRatio ? { aspectRatio: String(mediaRatio) } : undefined}>
            {(upstreamUrl || node.mount?.url || initialUrl) ? (
              mountTargetMedia(node.mount!.target) === 'video' ? (
                /* 视频归宿（如项目预告片）：mp4 用 video 标签回显——早先不分形态全塞 img，
                   预告片挂载点就成了渲染不出来的图片卡 */
                <>
                  <video src={upstreamUrl ?? node.mount!.url ?? initialUrl} muted loop playsInline
                    preload="metadata" draggable={false}
                    onLoadedMetadata={e => setMediaRatio(
                      e.currentTarget.videoWidth / Math.max(1, e.currentTarget.videoHeight))}
                    onMouseOver={e => { e.currentTarget.play().catch(() => undefined) }}
                    onMouseOut={e => e.currentTarget.pause()} />
                  <span className="tap-play"><Icon name="play" /></span>
                </>
              ) : (
                <img ref={mediaImgRef} src={mountSrc}
                  alt={mountTargetLabel(node.mount!.target)} draggable={false}
                  onLoad={e => setMediaRatio(
                    e.currentTarget.naturalWidth / Math.max(1, e.currentTarget.naturalHeight))} />
              )
            ) : (
              <span className="tap-mount-empty">
                {node.status === 'generating' ? '落库中…' : '把产物节点连过来'}
              </span>
            )}
            </div>
            {/* 右侧信息栏（参考项目卡片）：名称=来源节点完整标题；描述固定说明。
                左媒体右文字，媒体定 16:9 比例 */}
            <div className="tap-mount-info">
              <b>{upstreamTitle ?? mountTargetLabel(node.mount.target)}</b>
              <em>连线素材挂载到核心要素</em>
            </div>
          </div>
        ))}
        {/* 工作流节点：引用另一张已编排流程 */}
        {node.type === 'flow' && (
          <div className="tap-flow-body">
            <span className="tap-flow-ref">
              <Icon name="workflow" /> {node.flow?.name ?? '选择一个已编排的流程…'}
            </span>
            <span className="tap-flow-note">运行时执行该流程并把产物接入下游</span>
          </div>
        )}
        {node.type === 'tool' && (
          <div className="tap-tool-node-body">
            <span className="tap-tool-node-name">
              <Icon name="tools" /> {node.tool?.name || '选择一个系统工具…'}
            </span>
            <span className="tap-tool-node-meta">
              <em>{node.tool?.writes ? '写入工具' : '只读工具'}</em>
              <span>{node.params?.length ?? 0} 入参</span>
              <Icon name="link" />
              <span>{node.outputs?.length ?? 0} 输出</span>
            </span>
            {node.runtimeResult && (
              <pre className="tap-tool-node-result"
                onPointerDown={e => { if (selected) e.stopPropagation() }}>
                {node.runtimeResult.json}
              </pre>
            )}
          </div>
        )}
        {node.type === 'condition' && (
          <div className="tap-condition-body">
            {(node.condition?.branches ?? [
              { id: 'if-1', kind: 'if', clauses: [{ left: '{{input.source.prompt_text}}', operator: 'truthy' as const }] },
              { id: 'else', kind: 'else' as const },
            ]).map(branch => (
              <div className={'tap-condition-row' + (node.condition?.matchedBranch === branch.id ? ' active' : '')} key={branch.id}>
                <span className="tap-condition-label">{branch.kind === 'if' ? '如果' : branch.kind === 'else_if' ? '否则如果' : '否则'}</span>
                {branch.kind !== 'else' && <span className="tap-condition-summary">{branch.clauses?.[0]?.left ?? '设置条件'}</span>}
                <span className="tap-condition-port" onPointerDown={e => { e.stopPropagation(); onPortDrag?.(node.id, 'right', e, branch.id) }}><Icon name="plus" /></span>
              </div>
            ))}
          </div>
        )}
        {structuralLoop && (
          <div className="tap-loop-preview-stack" aria-label="循环子节点预览">
            {loopPreviewCards.map((preview, index) => (
              <div
                key={preview.id}
                className="tap-loop-preview"
                style={{
                  left: (loopPreviewCards.length - index - 1) * 24,
                  top: index * 24,
                  width: `calc(100% - ${(loopPreviewCards.length - 1) * 24}px)`,
                  height: `calc(100% - ${(loopPreviewCards.length - 1) * 24}px)`,
                  zIndex: index + 1,
                }}>
                {preview.src
                  ? <img src={preview.src} alt={preview.title ?? ''} draggable={false} />
                  : <span className="tap-loop-preview-placeholder" />}
              </div>
            ))}
            <span className="tap-folder-count tap-loop-count">
              <Icon name="layers" /> {loopChildCount ?? 0}
            </span>
          </div>
        )}
        {node.starred && <span className="tap-star"><Icon name="sparkles" /></span>}
      </div>

      {/* 出图节点的静态参考图：用户上传的「已有图」清单（随画布保存，引擎收进
          payload.reference_images，排最优先）。放在卡面外面——卡面 overflow:hidden，
          高度也是固定的，缩略图条放里面会被裁。编辑态才可增删。 */}
      {(node.type === 'image' || node.type === 'gen') && mode === 'edit' && (
        <div className="tap-node-refimgs">
          {(node.refImages ?? []).map(url => (
            <span className="tap-refimg" key={url}>
              <img src={url} alt="" draggable={false}
                onError={e => { e.currentTarget.style.visibility = 'hidden' }} />
              <button type="button" className="tap-refimg-del" aria-label="移除参考图"
                onPointerDown={e => e.stopPropagation()}
                onClick={e => { e.stopPropagation(); onRemoveRefImage?.(node.id, url) }}>
                <Icon name="cross" />
              </button>
            </span>
          ))}
          {onUpload && (
            <label className="tap-refimg-add" title="上传参考图：把一张已有图片挂到本节点，生成时优先当参考">
              <Icon name="plus" />
              <span>参考图</span>
              <input type="file" accept="image/*" hidden
                onChange={e => {
                  const file = e.target.files?.[0]
                  if (file) onUpload(node.id, file)
                  e.currentTarget.value = ''
                }} />
            </label>
          )}
        </div>
      )}

      {/* 胶囊：跳过（缺才跑命中）/ 失败。跨在卡片上沿，与生成条那枚「质检中」同一形态。
          必须放在 .tap-node-card **外面**——卡片是 overflow:hidden，放里面只能压着内容。
          跳过必须看得见，否则卡上带个对勾、内容还是上一次的，看着像这轮真跑过。 */}
      {node.badge && (
        <span className={'tap-node-badge ' + (node.badge.tone ?? 'skip')}>
          {node.badge.label}
        </span>
      )}
      {/* 挂载点标识牌：绑定态才出现，骑在卡顶边、水平居中——比标题行大一号，
          画布上一眼认出「这颗是挂载点」。必须挂在 .tap-node 根上而不是卡内——
          卡片 overflow:hidden 会裁掉悬出节点的一半；齿轮点它重开归宿选择（仅编辑模式）。 */}
      {node.type === 'mount' && node.mount?.target && !mountEditing && (
        <span className="tap-mount-flag"
          title={node.mount?.version ? `已落库 v${node.mount.version}` : '已指向本归宿'}>
          <Icon name="save" />
          {/* 牌子显示实际归属：来源节点的主体名（如「核心要素」），无来源时退回归宿名 */}
          <b>挂载点：{upstreamTitle ? shortMountSource(upstreamTitle)
            : mountTargetLabel(node.mount.target)}</b>
          {mode === 'edit' && (
            <button type="button" className="tap-mount-flag-gear" aria-label="修改归宿"
              onPointerDown={e => e.stopPropagation()}
              onClick={e => { e.stopPropagation(); onMountEdit?.(node.id) }}>
              <Icon name="gear" />
            </button>
          )}
        </span>
      )}
      {loopAggregate && (
        <span className="tap-loop-aggregate-badge"
          title={node.loop?.imported ? '引用工作流会聚合多个子产物' : '循环处理多个子项'}>
          <Icon name="loop" />
        </span>
      )}

      {/* 左右透明热区永久存在；加号只在热区内显示并跟随指针。 */}
      <TapflowPort side="left" onDrag={e => onPortDrag?.(node.id, 'left', e)} />
      {node.type !== 'condition' && <TapflowPort side="right" onDrag={e => onPortDrag?.(node.id, 'right', e)} />}
      {selected && <span className="tap-resize-handle" onPointerDown={onResizePointerDown} />}
    </div>
  )
}
