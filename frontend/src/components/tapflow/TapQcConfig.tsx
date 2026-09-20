import { useState } from 'react'
import { TAP_QC_STAGES, type TapQcConf } from '../../lib/tapflowData'
import { normOption, optionLabel } from '../../lib/tapflowOption'
import type { TapCatalog } from '../../lib/useTapflowCatalog'
import { Switch } from '../Switch'
import { TapPickMenu } from './TapPickMenu'

/**
 * 生成节点的质检段：左标签右控件，一行一项，勾上才展开。
 *
 * 判法（判哪些维度、怎么算分）来自**技能**，事实依据来自知识；
 * 阈值与时机是这条产线的策略——同一套技能，角色卡要 85、场景图 75 就够。
 * 输出结构（合格/得分/问题）由引擎强制，技能不负责，否则回退逻辑读不到结论。
 */
export function TapQcConfig({ qc, catalog, onChange }: {
  qc: TapQcConf | undefined
  /** 质检技能取 catalog.qcSkills（kb 里 agent_code='reviewer' 的条目名），
   * **不是** catalog.skills（skill_packages 的 slug）——引擎按前者找规则正文，
   * 填后者的话下拉永远匹配不上，跟被删掉的「引用最小集」是同一个坑 */
  catalog: TapCatalog
  onChange: (patch: Partial<TapQcConf>) => void
}) {
  const [kbOpen, setKbOpen] = useState(false)
  const on = qc?.on ?? false
  const retry = qc?.retry ?? 0
  const stage = qc?.stage ?? 'prompt'
  const kb = qc?.kb ?? []
  const stageNote = TAP_QC_STAGES.find(s => s.k === stage)?.note

  return (
    <div className="tap-insp-part tap-qc">
      {/* 「质检」与「系统提示词」同级，用同一个分节标题行；开关贴右 */}
      <div className="tap-insp-sec row">
        <span>质检</span>
        <Switch checked={on} label="质检" onChange={v => onChange({ on: v })}>
          {on ? '开启' : '关闭'}
        </Switch>
      </div>

      {!on ? (
        <div className="tap-insp-note">不质检：模型出什么就是什么</div>
      ) : (
        <>
          <div className="tap-qc-row">
            <span className="k">技能</span>
            <select className={'tap-insp-input' + (qc?.skill ? '' : ' warn')} value={qc?.skill ?? ''}
              onChange={e => onChange({ skill: e.target.value })}>
              <option value="">必选…</option>
              {catalog.qcSkills.map(normOption).map(s => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>

          <div className="tap-qc-row">
            <span className="k">知识</span>
            <span className="tap-qc-pick">
              <button type="button" className="tap-qc-pick-btn" onClick={() => setKbOpen(v => !v)}>
                {kb.length ? kb.map(v => optionLabel(catalog.kb, v)).join('、') : '未关联'}
              </button>
              {kbOpen && (
                <TapPickMenu
                  groups={[{
                    title: '判据词表 / 禁忌清单',
                    items: catalog.kb.map(normOption)
                      .map(o => ({ ...o, active: kb.includes(o.value) })),
                  }]}
                  onPick={v => onChange({ kb: kb.includes(v) ? kb.filter(x => x !== v) : [...kb, v] })}
                  onClose={() => setKbOpen(false)} />
              )}
            </span>
          </div>

          {/* 时机就两档，用分段控件；解释放下面一行，不占卡片 */}
          <div className="tap-qc-row">
            <span className="k">时机</span>
            <span className="tap-seg-mini tap-qc-seg">
              {TAP_QC_STAGES.map(s => (
                <button key={s.k} type="button" title={s.tip}
                  className={stage === s.k ? 'on' : ''}
                  onClick={() => onChange({ stage: s.k })}>{s.short}</button>
              ))}
            </span>
          </div>

          <div className="tap-qc-row">
            <span className="k">重试</span>
            <input className="tap-insp-input" type="number" min={0} max={5} value={retry}
              onChange={e => onChange({ retry: Number(e.target.value) })} />
          </div>
          <div className="tap-qc-row">
            <span className="k">合格</span>
            <input className="tap-insp-input" type="number" min={0} max={100}
              value={qc?.threshold ?? 80}
              onChange={e => onChange({ threshold: Number(e.target.value) })} />
          </div>

          {!qc?.skill && <div className="tap-insp-err">勾了质检就必须绑技能，否则保存时会被拦下</div>}
          <div className="tap-insp-note">{stageNote}</div>
          {/* 重试要花钱，把账算在脸上，不能让人以为是免费的 */}
          {!!retry && (
            <div className="tap-insp-note cost">
              重试 {retry} 次 = 最多 {retry + 1} 次{stage === 'image' ? '出图' : '装配'}开销；
              不合格回退上一节点重生成，带上一轮的问题清单
            </div>
          )}
        </>
      )}
    </div>
  )
}
