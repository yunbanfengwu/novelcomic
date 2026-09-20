import { Icon } from '../../components/Icon'
import { TapGenConfig } from '../../components/tapflow/TapGenConfig'
import { TapVarList } from '../../components/tapflow/TapVarList'
import {
  isGenType, MOUNT_TARGETS, TAP_QC_RULES, toolInputParams, toolOutputParams,
  type TapNode, type TapUpstreamVar,
} from '../../lib/tapflowData'
import { TAP_FLOW_KIND_LABEL, type TapFlowKind } from '../../lib/tapflowKind'
import { TAP_CANVAS_IMAGE_STEP, TAP_CANVAS_VIDEO_STEP } from '../../lib/tapflowCustomNode'
import { useTapflowCatalog } from '../../lib/useTapflowCatalog'

/** 出图/出视频/出音频节点各自只该挑对应分组的 Step。
 * 把 19 个 Step 全列出来，`breakdown_chapter（拆镜）` 这种放在图片节点上根本跑不通，
 * 挑中了也只是存下一条跑起来必报错的配置。当前已选值即使不在分组内也保留，
 * 免得历史配置被下拉悄悄吞掉。 */
/** 可生成的节点类型：属性面板核心是「怎么生成」（生成配置段） */
const GENERATABLE: TapNode['type'][] = ['text', 'image', 'video', 'audio', 'gen', 'flow']

/** 属性面板 body（合并面板的「属性」tab 内容）：编排态点节点看的不是「它是什么」，
 * 而是「它怎么生成」——生成配置（最小集/系统提示词/技能/知识库/工具）为主体；
 * 开始/质检/关联各有专属段；通用段：上游输入 / 下游引用 / 节点 ID。
 * 编辑即回写画布节点。外壳（header + tab）由 TapflowSidePanel 统一提供。 */
export function TapflowInspectorBody({ node, mode, upstream, flows, smartCall, onSmartCall,
                                        inEdges, onRemoveEdge, onPatch }: {
  node: TapNode | null
  /** 编排态看「怎么配」（输入/输出变量）；运行态看「跑在什么上下文里」（项目设定） */
  mode: 'edit' | 'run'
  /** 可被输入变量引用的上游输出变量（画布按连线算好传入） */
  upstream: TapUpstreamVar[]
  /** subflow 节点可引用的**真实**工作流（按 slug+version 引用，不是演示流程） */
  flows: { slug: string; version: number; name: string; kind?: TapFlowKind }[]
  /** 整张流程的能力开关，挂在开始节点上——开始节点就是这张流程对外的签名，
   * 「被别人怎么调用」属于签名的一部分，不属于任何一个中间节点。 */
  smartCall?: boolean
  onSmartCall?: (on: boolean) => void
  /** 这个节点的入边（谁连过来的）。画布上的线是 3px 的细东西，点不准很常见——
   * 属性面板里逐条断开是保底入口，不靠像素命中。 */
  inEdges?: { id: string; from: string; fromTitle: string }[]
  onRemoveEdge?: (id: string) => void
  onPatch: (id: string, patch: Partial<TapNode>) => void
}) {
  const catalog = useTapflowCatalog()
  if (!node) {
    return <div className="tap-insp-empty">在画布上选择一个节点查看属性</div>
  }
  const patch = (p: Partial<TapNode>) => onPatch(node.id, p)

  return (
    <div className="tap-insp-body">
      {/* 头部就是标题输入框本身——不再另起一行显示节点类型（合并面板的
          header 让给了「属性 | 执行」tab 切换，标题输入框落回 body 顶部） */}
      <input className="tap-insp-input tap-insp-title-input" value={node.title}
        placeholder="节点标题" onChange={e => patch({ title: e.target.value })} />

      {/* 上游连线：逐条断开。运行态也显示——拖端口建错边就是运行态的事 */}
      {!!inEdges?.length && onRemoveEdge && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">上游连线</div>
          {inEdges.map(e => (
            <div key={e.id} className="tap-insp-field">
              <span className="k">{e.fromTitle}</span>
              <button type="button" className="tap-insp-edge-del" title="断开这条连线"
                onClick={() => onRemoveEdge(e.id)}><Icon name="cross" /></button>
            </div>
          ))}
          <div className="tap-insp-note">画布上点连线选中后按 Delete 也能删。</div>
        </div>
      )}

      {/* 开始 · 运行态：本次运行落在什么项目设定下（编排态不关心，画布卡上已有） */}
      {node.type === 'start' && mode === 'run' && node.project && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">项目设定</div>
          <div className="tap-insp-note">本次运行落在该项目设定下；修改请到项目页</div>
          <div className="tap-insp-field"><span className="k">项目</span><span className="v">{node.project.title}</span></div>
          <div className="tap-insp-field"><span className="k">画风</span><span className="v">{node.project.artStyle}</span></div>
          <div className="tap-insp-field"><span className="k">主线</span><span className="v">{node.project.storyline}</span></div>
          <div className="tap-insp-field"><span className="k">比例</span><span className="v">{node.project.aspect}</span></div>
          <div className="tap-insp-field">
            <span className="k">角色类型</span>
            <span className="v">{node.project.characterMode === 'real' ? '真人' : '虚拟形象'}</span>
          </div>
        </div>
      )}
      {/* 开始 · 流程能力：这张流程被别的画布当节点引用时怎么调用。
          关掉（默认）= 引用卡只能整流程跑，点开也没有输入框——因为「点生成到底
          生成子图里的哪几个节点」答不上来；打开 = 卡片可炸开输入提示词，由规划
          模型逐节点判复用还是重生成。按 slug 全版本生效，点一下即时落库。 */}
      {node.type === 'start' && onSmartCall && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">流程能力</div>
          <label className="tap-insp-switch">
            <input type="checkbox" checked={!!smartCall}
              onChange={e => onSmartCall(e.target.checked)} />
            <span>支持智能调用</span>
          </label>
          <div className="tap-insp-note">
            {smartCall
              ? '被别的画布引用时可炸开输入提示词，由大模型规划本流程里哪几个节点重生成、哪几个复用已有产物'
              : '被别的画布引用时只能整流程运行，卡片不提供提示词输入框'}
          </div>
        </div>
      )}
      {/* 开始 · 编排态：入参声明（可增删；运行态填值走右侧执行面板） */}
      {mode === 'edit' && (
        <>
          <TapVarList title="输入" vars={node.params ?? []} upstream={upstream}
            note={node.type === 'start'
              ? '编排是项目无关的模板——这里只声明要哪些参数；取值在运行时给'
              : undefined}
            onChange={params => patch({ params })} />
          {node.type === 'tool' ? (
            <div className="tap-insp-part tap-tool-outputs">
              <div className="tap-insp-sec">输出</div>
              <div className="tap-insp-note">由系统工具注册合同自动提供，下游可直接引用</div>
              {(node.outputs ?? []).map(output => (
                <div className="tap-tool-output" key={output.k}>
                  <span className="tap-tool-output-name">{output.k}</span>
                  <span className="tap-tool-output-type">{output.type ?? 'JSON'}</span>
                  {output.itemFields?.length ? (
                    <span className="tap-tool-output-items">
                      循环项：{output.itemFields.map(field => field.k).join('、')}
                    </span>
                  ) : null}
                </div>
              ))}
              {!node.outputs?.length && <div className="tap-insp-note">尚未选择工具或工具没有声明输出</div>}
            </div>
          ) : (
            <TapVarList title="输出" vars={node.outputs ?? []} valueless
              note="本节点产出的变量，下游可引用"
              onChange={outputs => patch({ outputs })} />
          )}
        </>
      )}

      {node.type === 'tool' && (
        <div className="tap-insp-part tap-tool-config">
          <div className="tap-insp-sec">系统工具</div>
          <select className={'tap-insp-input' + (node.tool?.name ? '' : ' warn')}
            value={node.tool?.name ?? ''}
            onChange={e => {
              const spec = catalog.toolSpecs.find(item => item.name === e.target.value)
              if (!spec) { patch({ tool: {}, params: [], outputs: [] }); return }
              const inputs = toolInputParams(spec, node.params ?? []).map(param => {
                if (param.source === 'ref' || param.v) return param
                const sameName = upstream.find(item => item.k === param.k
                  && (!item.type || item.type === 'ctx' || item.type === param.type))
                return sameName
                  ? { ...param, source: 'ref' as const, ref: { node: sameName.nodeId, k: sameName.k } }
                  : param
              })
              patch({
                title: spec.title || spec.name,
                tool: { name: spec.name, writes: spec.writes, description: spec.description },
                params: inputs,
                outputs: toolOutputParams(spec),
              })
            }}>
            <option value="">选择一个工具…</option>
            {catalog.toolSpecs.map(spec => (
              <option key={spec.name} value={spec.name}>
                {spec.title || spec.name} · {spec.name}
              </option>
            ))}
          </select>
          {!catalog.loaded && <div className="tap-insp-note">正在读取系统工具目录…</div>}
          {node.tool?.description && <div className="tap-insp-note">{node.tool.description}</div>}
          {!node.tool?.name && <div className="tap-insp-err">未选择工具：图可以保存，但运行到此节点会报错</div>}
        </div>
      )}

      {node.type === 'condition' && (() => {
        const branches = node.condition?.branches ?? [
          { id: 'if-1', kind: 'if' as const, clauses: [{ left: '{{input.source.prompt_text}}', operator: 'truthy' as const }] },
          { id: 'else', kind: 'else' as const },
        ]
        const update = (next: typeof branches) => patch({ condition: { ...node.condition, branches: next } })
        return <div className="tap-insp-part tap-condition-config">
          <div className="tap-insp-sec">条件分支</div>
          {branches.map((branch, index) => <div className="tap-condition-edit-row" key={branch.id}>
            <strong>{branch.kind === 'if' ? '如果' : branch.kind === 'else_if' ? '否则如果' : '否则'}</strong>
            {branch.kind !== 'else' && <>
              <input className="tap-insp-input" value={branch.clauses?.[0]?.left ?? ''} placeholder="{{上游.字段}}"
                onChange={e => update(branches.map(item => item.id !== branch.id ? item : { ...item, clauses: [{ ...(item.clauses?.[0] ?? { operator: 'truthy' as const }), left: e.target.value }] }))} />
              <select className="tap-insp-input" value={branch.clauses?.[0]?.operator ?? 'truthy'}
                onChange={e => update(branches.map(item => item.id !== branch.id ? item : { ...item, clauses: [{ ...(item.clauses?.[0] ?? { left: '' }), operator: e.target.value as 'truthy' | 'equals' | 'not_equals' | 'contains' | 'empty' }] }))}>
                <option value="truthy">有值</option><option value="equals">等于</option><option value="not_equals">不等于</option><option value="contains">包含</option><option value="empty">为空</option>
              </select>
              {['equals', 'not_equals', 'contains'].includes(branch.clauses?.[0]?.operator ?? '') && <input className="tap-insp-input" value={String(branch.clauses?.[0]?.right ?? '')} placeholder="比较值"
                onChange={e => update(branches.map(item => item.id !== branch.id ? item : { ...item, clauses: [{ ...(item.clauses?.[0] ?? { left: '', operator: 'equals' as const }), right: e.target.value }] }))} />}
            </>}
            {branch.kind === 'else_if' && <button type="button" className="tap-tool" title="删除分支" onClick={() => update(branches.filter(item => item.id !== branch.id))}><Icon name="cross" /></button>}
            {branch.kind === 'else' && <button type="button" className="tap-tool" title="插入否则如果" onClick={() => update([...branches.slice(0, index), { id: `else-if-${Date.now()}`, kind: 'else_if', clauses: [{ left: '', operator: 'truthy' }] }, branch])}><Icon name="plus" /></button>}
          </div>)}
        </div>
      })()}
      {node.type === 'loop' && (
        <div className="tap-insp-part tap-loop-config">
          <div className="tap-insp-sec">循环配置</div>
          <label className="tap-insp-label">数据源</label>
          <select className={'tap-insp-input' + (node.loop?.source ? '' : ' warn')}
            value={node.loop?.source ?? ''}
            onChange={e => {
              const source = upstream.find(item => `{{${item.nodeId === 'start' ? 'input' : item.nodeId}.${item.k}}}` === e.target.value)
              patch({ loop: {
                ...node.loop, source: e.target.value,
                itemFields: source?.itemFields,
              } })
            }}>
            <option value="">选择上游数组输出…</option>
            {upstream.filter(item => item.type === 'json' || item.itemFields?.length).map(item => (
              <option key={`${item.nodeId}:${item.k}`} value={`{{${item.nodeId === 'start' ? 'input' : item.nodeId}.${item.k}}}`}>
                {item.nodeTitle} · {item.label || item.k}{item.type === 'json' ? '（JSON/数组）' : ''}
              </option>
            ))}
          </select>
          <input className="tap-insp-input" value={node.loop?.source ?? ''}
            placeholder="也可填写 {{工具.数组输出}}"
            onChange={e => patch({ loop: { ...node.loop, source: e.target.value } })} />
          <label className="tap-insp-label">并发数</label>
          <input className="tap-insp-input" type="number" min={1} max={8}
            value={node.loop?.concurrency ?? 1}
            onChange={e => patch({ loop: { ...node.loop, concurrency: Math.max(1, Math.min(8, Number(e.target.value) || 1)) } })} />
          <div className="tap-insp-note">
            循环体包含 {(node.loop?.body ?? []).length} 个节点；体内可引用「当前循环项」字段。
          </div>
          {!node.loop?.source && <div className="tap-insp-err">未配置数组数据源：运行时无法展开循环</div>}
        </div>
      )}

      {/* 引用另一张工作流：存成 subflow 节点的 slug+version。
          工作流节点固然要选，库里本来就是 subflow 的节点（如「场景介绍」）也要能改。 */}
      {(node.type === 'flow' || node.bind?.subflow) && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">引用流程</div>
          <select className={'tap-insp-input' + (node.bind?.subflow?.slug ? '' : ' warn')}
            value={node.bind?.subflow?.slug ?? ''}
            onChange={e => {
              const f = flows.find(x => x.slug === e.target.value)
              patch({
                bind: { ...node.bind, subflow: f ? { slug: f.slug, version: f.version } : undefined },
                ...(f && node.type === 'flow' ? { title: f.name } : {}),
              })
            }}>
            <option value="">选择工作流…</option>
            {flows.map(f => (
              <option key={f.slug} value={f.slug}>
                {f.name}（{TAP_FLOW_KIND_LABEL[f.kind ?? 'image']} · {f.slug} v{f.version}）
              </option>
            ))}
          </select>
          {/* 被引用流程「产出什么类型」——节点按它投影成文本卡/图片卡。
              类型声明在工作流自己的 tags 上，不由引用方猜。 */}
          {node.bind?.subflow?.slug && (() => {
            const f = flows.find(x => x.slug === node.bind!.subflow!.slug)
            return (
              <div className="tap-insp-field">
                <span className="k">呈现类型</span>
                <span className="v">
                  {TAP_FLOW_KIND_LABEL[f?.kind ?? 'image']}
                  {f ? '' : '（该流程不在已发布清单里）'}
                </span>
              </div>
            )
          })()}
          {!node.bind?.subflow?.slug && (
            <div className="tap-insp-err">没选工作流：图存得下，但运行到这个节点会报错</div>
          )}
        </div>
      )}

      {/* 可生成节点：核心——这个节点怎么来（查询数据 / LLM 生成） */}
      {GENERATABLE.includes(node.type) && (
        <TapGenConfig bind={node.bind ?? {}} upstream={upstream} catalog={catalog}
          // 出媒体的四种类型是一回事（后端都是 type=gen）：只认 'gen' 的话，
          // 画布上拖出来的「图片」节点就没有质检段、还多出一档跑不通的「查询」
          showQc={isGenType(node.type)} genMode={isGenType(node.type)}
          onChange={p => patch({ bind: { ...node.bind, ...p } })} />
      )}
      {node.error && <div className="tap-insp-err">{node.error}</div>}

      {mode === 'run' && node.runtimeResult && (
        <div className="tap-insp-part tap-runtime-result">
          <div className="tap-insp-sec">本次运行返回</div>
          <div className="tap-insp-note">{node.runtimeResult.summary}</div>
          <pre className="tap-runtime-json">{node.runtimeResult.json}</pre>
        </div>
      )}

      {/* 质检：判据 + 当前状态 */}
      {node.type === 'qc' && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">判据</div>
          <select className="tap-insp-input" value={node.qc?.rule ?? TAP_QC_RULES[0]}
            onChange={e => patch({ qc: { state: 'idle', ...node.qc, rule: e.target.value } })}>
            {TAP_QC_RULES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <div className="tap-insp-field">
            <span className="k">状态</span>
            <span className={'v tap-qc-state ' + (node.qc?.state ?? 'idle')}>
              {node.qc?.state === 'pass' ? `通过${node.qc.score ? ` · ${node.qc.score}` : ''}`
                : node.qc?.state === 'fail' ? `未通过${node.qc.score ? ` · ${node.qc.score}` : ''}`
                : '未运行'}
            </span>
          </div>
          {node.error && <div className="tap-insp-err">{node.error}</div>}
        </div>
      )}

      {/* 关联：落库动作与落点（运行态隐藏但自动执行） */}
      {node.type === 'link' && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">落库动作</div>
          <div className="tap-insp-field"><span className="k">动作</span><span className="v mono">{node.link?.action ?? '—'}</span></div>
          <div className="tap-insp-field"><span className="k">落点</span><span className="v">{node.link?.target ?? '—'}</span></div>
          <div className="tap-insp-note">产物图片始终自动入附件库；本节点只负责把结果关联到项目资产。运行视图中隐藏但照常执行。</div>
        </div>
      )}

      {/* 挂载点（2026-09-17）：产物归宿。节点画在哪里不重要，重要的是它声明
          「产物存到哪」——卡上点选、这里下拉，改的是同一份 target；
          选成空就回到卡上的归宿点选列表。 */}
      {node.type === 'mount' && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">产物归宿</div>
          <select className="tap-insp-input" value={node.mount?.target ?? ''}
            onChange={e => patch({ mount: { ...node.mount, target: e.target.value } })}>
            <option value="">未选归宿</option>
            {MOUNT_TARGETS.map(t => <option key={t.v} value={t.v}>{t.label}</option>)}
          </select>
          <div className="tap-insp-field">
            <span className="k">业务对象</span>
            <span className="v">{node.mount?.subject
              ? `${node.mount.subject.kind === 'element' ? '要素'
                : node.mount.subject.kind === 'content_node' ? '内容节点' : node.mount.subject.kind}
                #${node.mount.subject.id}`
              : '按运行入参推断'}</span>
          </div>
          <div className="tap-insp-field">
            <span className="k">当前产物</span>
            <span className="v">{node.mount?.url
              ? (node.mount.version ? `已落库 v${node.mount.version}` : '已指向')
              : '未落库'}</span>
          </div>
          <div className="tap-insp-note">
            把产物节点连到它，它显示的就是这份产物；同一归宿一整张画布只能有一个挂载点。
          </div>
        </div>
      )}

      {/* 装配结果不在这里另放一份只读回显——它就填在生成条里（选中节点炸开可见、可改）。
          两处都放会让人不知道以哪份为准，改了哪份生效。 */}

      {/* 产物（放在最后）：这个节点产出什么、落到哪里，以及当前那份产物。
          落库口就是选中的生成步骤——附件挂靠、meta 回写、指纹全焊在它的 next 里。
          装配器只读：它决定「从哪取数、组织成哪几段」，是节点身份而不是措辞；
          目前注册表里能当 assemble 用的只有 element.layers 一个，没得选。
          两段合并是刻意的——否则末尾会连着出现「产物」和「当前产物」两个标题。 */}
      {(isGenType(node.type) || node.src) && (
        <div className="tap-insp-part">
          <div className="tap-insp-sec">产物</div>
          {/* 出媒体的四种类型都要给执行体下拉：画布上拖出来的「图片」节点是 tap=image，
              只认 'gen' 的话它就永远没有落点可选——节点存得下也跑不了 */}
          {isGenType(node.type) && (
            <>
              <div className="tap-insp-sec">产物落点</div>
              <select className="tap-insp-input" value={node.bind?.outputSlot?.role ?? ''}
                onChange={e => patch({ bind: { ...node.bind, outputSlot: e.target.value
                  ? { role: e.target.value, variant: node.bind?.outputSlot?.variant } : undefined } })}>
                <option value="">仅项目素材库</option>
                <option value="scene.sheet">要素设定图</option>
                <option value="shot.keyframe">镜头关键帧</option>
                <option value="reference.image">要素参考图</option>
              </select>
              {node.bind?.outputSlot?.role === 'scene.sheet' && (
                <input className="tap-insp-input" placeholder="变体 ID（留空为默认）"
                  value={node.bind.outputSlot.variant ?? ''}
                  onChange={e => patch({ bind: { ...node.bind, outputSlot: {
                    role: 'scene.sheet', variant: e.target.value || undefined } } })} />
              )}
              <div className="tap-insp-field">
                <span className="k">生成操作</span>
                <span className="v mono">{node.bind?.step ?? '未配置'}</span>
              </div>
              {node.bind?.assemble && (
                <div className="tap-insp-field">
                  <span className="k">装配器</span><span className="v mono">{node.bind.assemble}</span>
                </div>
              )}
              <div className="tap-insp-note">
                产物落点决定附件挂靠与 meta 回写；装配器决定从哪取数（只读，由后端定义）
              </div>
              {!node.bind?.step && (
                <>
                  <div className="tap-insp-err">没选产物落点：图存得下，但运行到这个节点会报错</div>
                  {/* 补救入口（2026-09-18）：gen_canvas_video 上线前存的视频卡，以及其它没绑上
                      执行体的卡，在这里一键补默认执行体——否则这张卡永远跑不了。音频没有
                      画布自由执行体，不给按钮。 */}
                  {node.type !== 'audio' && (
                    <button type="button" className="tap-insp-fix-btn"
                      onClick={() => patch({ bind: { ...node.bind, step: node.type === 'video'
                        ? TAP_CANVAS_VIDEO_STEP : TAP_CANVAS_IMAGE_STEP } })}>
                      绑定画布{node.type === 'video' ? '视频' : '图片'}生成
                    </button>
                  )}
                </>
              )}
            </>
          )}
          {node.src && <img className="tap-insp-thumb" src={node.src} alt={node.title} />}
        </div>
      )}
    </div>
  )
}
