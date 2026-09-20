import { useEffect, useState } from 'react'
import { api, type ModelProfile } from '../../api'
import { Icon } from '../Icon'
import type { TapNode, TapUpstreamVar } from '../../lib/tapflowData'
import type { TapCatalog } from '../../lib/useTapflowCatalog'
import { Switch } from '../Switch'
import { TapPickerField } from './TapPickerField'
import { TapPromptEditor } from './TapPromptEditor'
import { TapPromptRefs } from './TapPromptRefs'
import { TapQcConfig } from './TapQcConfig'

type Bind = NonNullable<TapNode['bind']>

/** 节点「怎么来」的配置：查询数据（走内置工具取数） ⇄ LLM 生成（系统提示词 + 技能/知识库/工具）。
 * 两态互斥，切换即换整段表单；宿主只给 bind 和 onChange。
 *
 * **出图节点也有这一层**：charter + 技能正文 + 知识库正文组成 anchor 段（约束层），
 * 由引擎 `_anchor_from_config` 读取；配了就以它为准，没配才回落到装配器的硬编码 anchor。
 * 出图模型没有 system 通道，所以这里配的不是"系统消息"，是**拼进提示词的约束段**。 */
export function TapGenConfig({ bind, catalog, showQc, genMode, upstream = [], onChange }: {
  bind: Bind
  /** 技能/知识库/工具的真目录（后端 /api/agents/assets） */
  catalog: TapCatalog
  /** 生成节点才有质检段（装配 + 质检 + 出图三合一） */
  showQc?: boolean
  /** 出图节点：没有「查询/LLM」这一档——出图永远是装配后出图，引擎也不读 mode。
   * 系统提示词在这里的含义是**约束（anchor）段**，不是聊天的 system 消息。 */
  genMode?: boolean
  /** 沿连线回溯的上游输出变量：「+ 引用」的候选 */
  upstream?: TapUpstreamVar[]
  onChange: (patch: Partial<Bind>) => void
}) {
  const mode = genMode ? 'llm' : (bind.mode ?? 'llm')
  const [imageModels, setImageModels] = useState<ModelProfile[]>([])
  useEffect(() => {
    if (genMode) api.listModels().then(models => setImageModels(models.filter(m => m.purpose === 'image')))
  }, [genMode])
  // 智能添加（2026-09-17）：按节点提示词让模型从目录里挑能力，有就选、没有别硬选。
  // 结果与现有配置**取并集**——这个按钮只会加东西，永远不会清掉人勾过的项。
  const [aiBusy, setAiBusy] = useState(false)
  const [aiHint, setAiHint] = useState('')
  const smartAdd = async () => {
    if (aiBusy) return
    setAiBusy(true); setAiHint('')
    try {
      const r = await api.smartCapabilities({
        charter: bind.charter ?? '', skills: bind.skills ?? [],
        kb: bind.kb ?? [], tools: bind.tools ?? [] })
      const union = (cur?: string[], got?: string[]) => Array.from(new Set([...(cur ?? []), ...(got ?? [])]))
      const n = r.skills.length + r.kb.length + r.tools.length
      if (n > 0) onChange({
        skills: union(bind.skills, r.skills),
        kb: union(bind.kb, r.kb),
        tools: union(bind.tools, r.tools) })
      setAiHint(n > 0 ? `已添加 ${n} 项` : (r.reason || '没有合适的能力'))
    } catch (e) {
      setAiHint(String(e))
    } finally {
      setAiBusy(false)
      setTimeout(() => setAiHint(''), 4000)
    }
  }
  return (
    <div className="tap-insp-part">
      {/* 出图节点没有这一档：出图永远是「装配→出图」，引擎不读 mode，
          摆个切换在那儿只会让人以为能切成"查询" */}
      {!genMode && (
        <div className="tap-insp-sec row">
          <span>显示</span>
          <span className="tap-seg-mini">
            <button type="button" className={mode === 'query' ? 'on' : ''}
              onClick={() => onChange({ mode: 'query' })}>查询</button>
            <button type="button" className={mode === 'llm' ? 'on' : ''}
              onClick={() => onChange({ mode: 'llm' })}>LLM</button>
          </span>
        </div>
      )}

      {genMode && (
        <div className="tap-insp-sec">
          <label className="tap-insp-label">出图模型</label>
          <select className="tap-insp-input" value={bind.modelProfileId ?? ''}
            onChange={e => onChange({ modelProfileId: e.target.value ? Number(e.target.value) : undefined })}>
            <option value="">系统默认图片模型</option>
            {imageModels.map(model => <option key={model.id} value={model.id}>
              {model.name} · {model.provider}{model.is_active ? '（当前默认）' : ''}
            </option>)}
          </select>
        </div>
      )}

      {mode === 'query' ? (
        <TapPickerField title="查询工具" note="直接读库出数据，不进模型（只列不写库的工具）"
          groups={[{ key: 'tools', icon: 'tools', options: catalog.queryTools, value: bind.tools ?? [] }]}
          onChange={(_, tools) => onChange({ tools })} />
      ) : (
        <>
          <div className="tap-insp-sec row">
            <span>提示词生成约束</span>
            <Switch checked={bind.onlyMissing ?? true}
              onChange={v => onChange({ onlyMissing: v })}>缺才跑</Switch>
          </div>
          {genMode && (
            <div className="tap-insp-note">
              <b>这段不进出图模型</b>，它是用来<b>写提示词</b>的。
              提示词生成约束连同下面的技能 / 知识库 / 工具驱动一次文本生成，
              产出的就是生成条里那段最终提示词——之后才由它去出图。
              所以这里写的是「怎么写好这段提示词」的规则，不是画面内容本身。
              留空则不跑这一步，直接用装配器按实体拼出来的提示词。
            </div>
          )}
          {/* 系统提示词是一个整体：引用方块在上（超出换行）、正文居中、
              专业能力（技能/知识库/工具）在下——三样都是「喂给模型的东西」，不该散在框外。
              引用解析后拼进 user 段，system 段保持稳定可复用 */}
          <div className="tap-charter-box">
            <TapPromptRefs refs={bind.refs ?? []} upstream={upstream}
              onChange={refs => onChange({ refs })} />
            <TapPromptEditor
              value={bind.charter ?? ''} refs={bind.refs ?? []} upstream={upstream}
              placeholder="该节点生成时的角色与规则（charter）…打 @ 插入引用"
              onChange={charter => onChange({ charter })}
              onAddRef={r => {
                const cur = bind.refs ?? []
                if (!cur.some(x => x.token === r.token)) onChange({ refs: [...cur, r] })
              }} />
            {/* 技能 / 知识 / 工具合成一个区域：一个「+ 添加」，浮窗里分三组挑；
                样式仍是一行一个，看得清各自来源 */}
            <div className="tap-charter-foot">
              {/* 三类都给：这段配置驱动的是**写提示词的那次文本调用**，
                  不是拼给出图模型的。技能是方法论文档、工具用来取数，
                  文本模型都读得懂、用得上。 */}
              {/* 上下文获取交给 AI（2026-09-17）：开了就不再依赖人工把 project_info
                  这类取数工具逐个勾上——模型按提示词自己决定查什么、查多深。 */}
              <div className="tap-insp-sec row" style={{ gap: 8 }}>
                <span className="tap-insp-label" style={{ margin: 0 }}>上下文获取</span>
                <Switch checked={bind.autoContext ?? false}
                  onChange={v => onChange({ autoContext: v })}>AI 自主规划</Switch>
                <button type="button" className="small ghost" style={{ marginLeft: 'auto' }}
                  disabled={aiBusy} onClick={smartAdd}
                  title="按节点提示词，由 AI 从技能/知识库/工具目录里挑专业能力（有就选，没有别硬选）">
                  <Icon name="sparkles" /> {aiBusy ? '挑选中…' : '智能添加'}
                </button>
                {aiHint && <span className="tap-insp-note" style={{ margin: 0, flexBasis: '100%' }}>{aiHint}</span>}
              </div>
              <TapPickerField title="专业能力"
                groups={[
                  { key: 'skills', title: '技能', icon: 'zap', options: catalog.skills, value: bind.skills ?? [] },
                  { key: 'kb', title: '知识', icon: 'book', options: catalog.kb, value: bind.kb ?? [] },
                  { key: 'tools', title: '工具', icon: 'tools', options: catalog.tools, value: bind.tools ?? [] },
                ]}
                onChange={(key, next) => onChange({ [key]: next })} />
            </div>
          </div>
        </>
      )}

      {/* 质检段：生成节点专有。不同工作流的质检规则不一样，所以判法绑技能而不是写死 */}
      {showQc && mode === 'llm' && (
        <TapQcConfig qc={bind.qc} catalog={catalog}
          onChange={p => onChange({ qc: { on: false, ...bind.qc, ...p } })} />
      )}
    </div>
  )
}
