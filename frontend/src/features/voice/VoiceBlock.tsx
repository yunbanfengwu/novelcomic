import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Element, VoiceSample } from '../../api'
import { Icon } from '../../components/Icon'
import { defaultAgeYears } from '../../lib/age'
import { AgeSlider } from './AgeSlider'
import { EmotionSamples } from './EmotionSamples'
import './VoiceBlock.css'

/** 角色音色块：捏音色（指令可空=按性格自主设计）+ 生成样本（保存到音色条目）+ 试听（播已存样本，零合成） */
export function VoiceBlock({ pid, el, onChanged }: { pid: number; el: Element; onChanged: () => void }) {
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState('')
  const [audio, setAudio] = useState('')
  const [sampleUrl, setSampleUrl] = useState<string | null>(null)
  const [samples, setSamples] = useState<VoiceSample[]>([])
  const v = el.meta.voice

  // 绑定变化时取音色条目里已保存的试听样本（5 情绪小样优先，回退单条）
  const kbId = v?.kb_voice_id
  useEffect(() => {
    setAudio(''); setSampleUrl(null); setSamples([])
    if (!kbId) return
    let on = true
    api.getVoice(kbId).then(kb => {
      if (!on) return
      setSampleUrl(typeof kb.meta.sample_audio_url === 'string' ? kb.meta.sample_audio_url : null)
      setSamples(Array.isArray(kb.meta.samples) ? kb.meta.samples : [])
    }).catch(() => {})
    return () => { on = false }
  }, [kbId])

  const design = async () => {
    setBusy('design')
    try {
      const res = await api.designVoice(pid, el.id, instruction.trim() || undefined)
      setInstruction(''); setAudio('')
      onChanged()
      if (res.spec?.description) console.info('音色设计:', res.spec.description)
    } catch (e) { alert(String(e)) } finally { setBusy('') }
  }
  const genSample = async () => {
    if (!v) return
    setBusy('sample')
    try {
      const res = await api.genVoiceEmotionSamples(v.kb_voice_id)
      setSamples(res.samples || [])
      if (res.samples?.[0]) { setSampleUrl(res.samples[0].url); setAudio('') }
    } catch (e) { alert(String(e)) } finally { setBusy('') }
  }
  const setAge = async (years: number) => {
    try {
      await api.setElementAge(pid, el.id, years)   // 捏音色/外貌补档的最优先年龄依据
      onChanged()
    } catch (e) { alert(String(e)) }
  }

  return (
    <div className="voice-block">
      <AgeSlider label="角色年龄" value={defaultAgeYears(el.meta)} onCommit={setAge} disabled={!!busy} />
      <div className="voice-line">
        <span className="dim"><Icon name="mic" /> 音色</span>
        {v ? <span className="tag accent">{v.name}</span> : <span className="dim">未绑定</span>}
        {v && !samples.length && sampleUrl && <button className="small" disabled={!!busy}
          onClick={() => setAudio(sampleUrl)}>▶ 试听</button>}
        {v && <button className="small ghost" disabled={!!busy} onClick={genSample}
          title="按角色定制喜怒哀乐+平 5 句台词并合成情绪试听小样（覆盖旧样本）">
          {busy === 'sample' ? <><Icon name="spinner" spin /> 合成中…</>
            : samples.length ? <><Icon name="refresh" /> 重新生成情绪小样</> : <><Icon name="speaker" /> 生成情绪小样</>}</button>}
      </div>
      {v && !!samples.length && <EmotionSamples samples={samples} />}
      <div className="voice-line">
        <input value={instruction} onChange={e => setInstruction(e.target.value)}
          placeholder="可选指令，如“再冷一点 / 像老船长”；留空按性格自主设计"
          onKeyDown={e => { if (e.key === 'Enter' && !busy) design() }} />
        <button className="small" disabled={!!busy} onClick={design}>
          {busy === 'design' ? <><Icon name="spinner" spin /> 设计中…</> : v ? '重新捏音色' : <><Icon name="mic" /> 捏音色</>}
        </button>
      </div>
      {audio && <audio src={audio} controls autoPlay className="voice-audio" />}
    </div>
  )
}
