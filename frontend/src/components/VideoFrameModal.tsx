import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Modal } from './Modal'
import { Icon } from './Icon'
import { PLAY_RATES, useVideoScrubber } from '../lib/useVideoScrubber'
import './VideoFrameModal.css'

/** 一个视频源：已有视频给 url，临时上传给 file（宿主抽帧时二选一回传）。 */
export interface FrameVideoSource { label: string; url: string; file?: File }

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}.${String(Math.floor((s % 1) * 100)).padStart(2, '0')}`

/** 视频抽帧弹窗：在 <video> 上播放/拖时间轴/慢放/逐帧定位，点「就用这一帧」把该时刻交给宿主抽帧。
 * 截帧不在前端做（避免 canvas 跨域污染）——只回传 currentTime，宿主调后端 ffmpeg 按时间点抽全分辨率帧。
 * 视频源=宿主传入的已有视频（本镜/邻镜）+ 可选临时上传；上传件仅本地 objectURL 播放，抽帧时才上传。 */
export function VideoFrameModal({ open, title, sources, pid, allowUpload = true, busy, fps = 25, topmost, onCapture, onClose }: {
  open: boolean
  title: string
  sources: FrameVideoSource[]      // 具名视频候选（本镜/邻镜等，可空）——渲染为置顶按钮
  pid?: number                     // 传入则拉取本项目全部视频，供「选择项目视频」下拉任选
  allowUpload?: boolean
  busy?: boolean
  fps?: number
  topmost?: boolean                // 从生成弹框(ElementPreview 栈 z≥1000)内打开时置 true，抬到其上
  onCapture: (payload: { videoUrl?: string; file?: File; atSec: number }) => Promise<void> | void
  onClose: () => void
}) {
  const [uploaded, setUploaded] = useState<{ file: File; url: string } | null>(null)
  const [projVideos, setProjVideos] = useState<FrameVideoSource[]>([])  // 项目全部视频（pid 传入时拉取）
  const [activeKey, setActiveKey] = useState<string>(sources[0]?.url ?? '')
  const scrub = useVideoScrubber(fps)
  const fileInput = useRef<HTMLInputElement | null>(null)

  // 置顶按钮源：具名 sources + 上传件；下拉源：项目视频（去掉与按钮源同 URL 的，按钮优先保留其友好名）
  const btnSources: FrameVideoSource[] = [...sources, ...(uploaded ? [{ label: '上传的视频', url: uploaded.url, file: uploaded.file }] : [])]
  const btnUrls = new Set(btnSources.map(s => s.url))
  const dropdown = projVideos.filter(v => !btnUrls.has(v.url))
  const all: FrameVideoSource[] = [...btnSources, ...dropdown]
  const active = all.find(s => s.url === activeKey) ?? all[0]

  // 关窗时收回上传 objectURL；换上传件时收回旧的，避免泄漏
  useEffect(() => () => { if (uploaded) URL.revokeObjectURL(uploaded.url) }, [uploaded])
  useEffect(() => { if (!open) { setUploaded(null); setActiveKey(sources[0]?.url ?? '') } }, [open, sources])
  // 切换视频源立刻把轴归零：新视频的 onLoadedMetadata 要等网络加载完才归零，这段窗口里
  // scrub.time 仍是上一条（可能更长）视频的旧时刻，若此时抽帧会把旧时刻发给新视频 → 越界。
  // eslint-disable-next-line react-hooks/exhaustive-deps -- scrub.seek 是稳定 useCallback，只需随 activeKey 触发
  useEffect(() => { scrub.seek(0) }, [activeKey])
  // 打开且传了 pid：拉本项目全部视频（资产库过滤 media=video）供下拉任选；关窗清空
  useEffect(() => {
    if (!open || pid == null) { setProjVideos([]); return }
    let alive = true
    api.assetLibrary(pid).then(items => {
      if (!alive) return
      setProjVideos(items.filter(i => i.media === 'video' && i.url)
        .map(i => ({ label: i.name, url: i.url })))
    }).catch(() => { if (alive) setProjVideos([]) })
    return () => { alive = false }
  }, [open, pid])

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''  // 允许连续选同名文件
    if (!f) return
    if (uploaded) URL.revokeObjectURL(uploaded.url)
    const url = URL.createObjectURL(f)
    setUploaded({ file: f, url })
    setActiveKey(url)
  }

  const capture = async () => {
    if (!active || busy) return
    // 以当前 <video> 元素的实况时间为准（而非可能滞后的 scrub.time 状态），并夹进本条视频
    // 真实时长内——切源后未及归零、或拖到末尾时，防止把越界/过期的时刻发给后端抽帧。
    const v = scrub.ref.current
    const dur = v?.duration
    let atSec = v ? v.currentTime : scrub.time
    if (dur && isFinite(dur)) atSec = Math.min(Math.max(0, atSec), Math.max(0, dur - 1 / fps))
    await onCapture(active.file
      ? { file: active.file, atSec }
      : { videoUrl: active.url, atSec })
  }

  return (
    <Modal open={open} onClose={onClose} title={title} wide topmost={topmost} closeOnBackdrop={!busy}>
      <div className="vf-body">
        {(btnSources.length > 0 || allowUpload || dropdown.length > 0) && (
          <div className="vf-sources">
            {btnSources.map(s => (
              <button key={s.url} type="button"
                className={'seg-btn' + (s.url === active?.url ? ' active' : '')}
                onClick={() => setActiveKey(s.url)}>{s.label}</button>
            ))}
            {allowUpload && (
              <button type="button" className="seg-btn" onClick={() => fileInput.current?.click()}>
                <Icon name="upload" /> 上传视频
              </button>
            )}
            {/* 项目视频下拉：可能很多，用 select 而非按钮墙——选中即设为当前抽帧源 */}
            {dropdown.length > 0 && (
              <select className="vf-project-select"
                value={dropdown.some(v => v.url === active?.url) ? (active?.url ?? '') : ''}
                onChange={e => e.target.value && setActiveKey(e.target.value)}>
                <option value="">项目视频…（{dropdown.length}）</option>
                {dropdown.map(v => <option key={v.url} value={v.url}>{v.label}</option>)}
              </select>
            )}
            <input ref={fileInput} type="file" accept="video/*" hidden onChange={onPickFile} />
          </div>
        )}

        {active ? (
          <>
            <div className="vf-stage">
              {/* 关闭原生控件：播放/拖轴/慢放/逐帧全走下方自定义控件，画面无浮层遮挡取景 */}
              <video {...scrub.videoProps} src={active.url} className="vf-video" playsInline
                onClick={scrub.toggle} preload="auto" />
            </div>

            <input className="vf-timeline" type="range" min={0} max={scrub.duration || 0} step={0.001}
              value={scrub.time} onChange={e => scrub.seek(Number(e.target.value))} />

            <div className="vf-controls">
              <button type="button" className="ghost small" onClick={scrub.toggle} title={scrub.playing ? '暂停' : '播放'}>
                <Icon name={scrub.playing ? 'pause' : 'play'} />
              </button>
              <button type="button" className="ghost small" onClick={() => scrub.step(-1)} title="上一帧">‹ 帧</button>
              <button type="button" className="ghost small" onClick={() => scrub.step(1)} title="下一帧">帧 ›</button>
              <span className="vf-rates">
                {PLAY_RATES.map(r => (
                  <button key={r} type="button" className={'seg-btn' + (scrub.rate === r ? ' active' : '')}
                    onClick={() => scrub.setRate(r)}>{r}×</button>
                ))}
              </span>
              <span className="vf-time dim">{fmt(scrub.time)} / {fmt(scrub.duration || 0)}</span>
            </div>
          </>
        ) : (
          <div className="vf-empty dim">
            <Icon name="video" /> 暂无可抽帧的视频，请上传一段视频。
          </div>
        )}

        <div className="vf-foot">
          <span className="dim vf-hint">拖时间轴 / 慢放 / 逐帧定位到想要的画面，点右侧按钮抽取该帧。</span>
          <button type="button" className="vf-capture" disabled={!active || busy} onClick={capture}>
            {busy ? <Icon name="spinner" spin /> : <Icon name="camera" />}
            {busy ? ' 抽取中…' : ' 就用这一帧'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
