import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { KbEntry, VoiceSample } from '../../api'
import { Icon } from '../../components/Icon'
import { defaultAgeYears } from '../../lib/age'
import { AgeSlider } from '../voice/AgeSlider'
import { EmotionSamples } from '../voice/EmotionSamples'
import { KbWeightControl } from './KbWeightControl'

/** 音色库：卡片列表 + 试听 + 批量样本生成（见 docs/arch/voice-timbre-design.md）。
 * actionsEl：文件夹 header 的挂载点——全局按钮提升到标题同一行。 */
export function VoiceAdmin({ actionsEl }: { actionsEl?: HTMLElement | null }) {
  const [voices, setVoices] = useState<KbEntry[]>([])
  const [busy, setBusy] = useState('')
  const reload = useCallback(() => { api.listVoices().then(setVoices) }, [])
  useEffect(() => { reload() }, [reload])

  const genSamples = async () => {
    setBusy('samples')
    try {
      await api.bindVoicePresets()
      await api.genVoiceSamples()
      alert('批量试听样本任务已入队，生成完成后刷新本页')
    } catch (e) { alert(String(e)) }
    setBusy('')
  }
  const genSample = async (v: KbEntry) => {
    setBusy(`p${v.id}`)
    try {
      await api.genVoiceEmotionSamples(v.id)   // 按角色定制 5 情绪小样，存 meta.samples
      reload()
    } catch (e) { alert(String(e)) }
    setBusy('')
  }
  const setAge = async (v: KbEntry, years: number) => {
    try {
      await api.setVoiceAge(v.id, years)   // 存数字年龄+重推档位+换年龄标签；重生小样后生效于台词
      reload()
    } catch (e) { alert(String(e)) }
  }

  const toolbar = (
    <div className="btns kbv-toolbar">
      <button disabled={busy === 'samples'} onClick={genSamples}
        title="先按性别绑定 CosyVoice2 预置音色，再批量生成缺失的试听样本">
        {busy === 'samples' ? <Icon name="spinner" spin /> : <Icon name="mic" />} 绑定预置并生成全部试听样本
      </button>
      <span className="dim">有情绪小样 {voices.filter(v => Array.isArray(v.meta.samples) && v.meta.samples.length).length} 条</span>
    </div>
  )

  return (
    <div>
      {actionsEl ? createPortal(toolbar, actionsEl) : toolbar}
      <div className="shot-grid">
        {voices.map(v => (
          <div key={v.id} className="shot-card">
            <div className="shot-head">
              <b>{v.name}</b>
              {!!v.meta.gender && <span className="tag">{String(v.meta.gender)}</span>}
              <KbWeightControl entry={v} onSaved={reload} />
            </div>
            <div className="tags" style={{ margin: '4px 0' }}>
              {v.tags.map(t => <span key={t} className="tag accent">{t}</span>)}
            </div>
            <p className="dim">{v.description}</p>
            <AgeSlider value={defaultAgeYears(v.meta)} onCommit={y => setAge(v, y)} />
            {typeof v.meta.voice_type === 'string' && !!v.meta.voice_type &&
              <div className="dim" style={{ fontSize: 12 }}><Icon name="link" /> {String(v.meta.voice_type).split(':').pop()}</div>}
            <div className="btns">
              {Array.isArray(v.meta.samples) && v.meta.samples.length
                ? <EmotionSamples samples={v.meta.samples as VoiceSample[]} />
                : <>
                    {typeof v.meta.sample_audio_url === 'string' && !!v.meta.sample_audio_url &&
                      <audio controls src={String(v.meta.sample_audio_url)} style={{ height: 30, width: '100%' }} />}
                    <span className="dim" style={{ fontSize: 12 }}>尚未生成情绪小样（点「生成情绪小样」补齐）</span>
                  </>}
              <button className="small ghost" disabled={busy === `p${v.id}`} onClick={() => genSample(v)}
                title="按角色定制喜怒哀乐+平 5 句台词并合成情绪试听小样（覆盖旧样本）">
                {busy === `p${v.id}` ? <><Icon name="spinner" spin /> 合成中…</>
                  : (Array.isArray(v.meta.samples) && v.meta.samples.length) ? <><Icon name="refresh" /> 重新生成</> : <><Icon name="speaker" /> 生成情绪小样</>}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
