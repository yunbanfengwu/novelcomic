import { useState } from 'react'
import { api } from '../../api'
import type { Shot } from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'
import { VideoFrameModal, type FrameVideoSource } from '../../components/VideoFrameModal'

/** 首帧/尾帧卡「取邻镜帧」页签：
 * ① 一键从相邻镜视频抽首/尾帧（target=first 抽上一镜尾帧、last 抽下一镜首帧，与邻镜无缝衔接）；
 * ② 「打开视频抽取」弹窗：在 <video> 上拖时间轴/慢放/逐帧，精确挑任意一帧（本镜/邻镜/上传视频）。
 * 两者都同步落库（后端 ffmpeg 秒级抽帧），onDone 重载后本页签展示抽取结果图。
 * 只有 meta.*_source 标记为抽取来源（prev_video/next_video/extracted）时才在此展示，不与生图产物混淆。 */
export function NeighborFramePane({ pid, shot, target, onDone, ownVideoUrl, neighborVideoUrl }: {
  pid: number; shot: Shot; target: 'first' | 'last'; onDone: () => void
  ownVideoUrl?: string       // 本镜自己的视频（可回挑某一帧作首/尾帧）
  neighborVideoUrl?: string  // 相邻镜视频（first=上一镜 / last=下一镜）
}) {
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const first = target === 'first'
  const url = first ? shot.meta.keyframe_url : shot.meta.last_frame_url
  const src = first ? shot.meta.keyframe_source : shot.meta.last_frame_source
  const extracted = (src === 'prev_video' || src === 'next_video' || src === 'extracted') ? url : undefined
  const neighborLabel = first ? '上一镜视频' : '下一镜视频'
  const sources: FrameVideoSource[] = [
    ...(neighborVideoUrl ? [{ label: neighborLabel, url: neighborVideoUrl }] : []),
    ...(ownVideoUrl ? [{ label: '本镜视频', url: ownVideoUrl }] : []),
  ]

  const extract = async () => {
    setBusy(true)
    try { await api.extractNeighborFrame(pid, shot.id, target); onDone() }
    catch (e) { alert(String(e)) }
    finally { setBusy(false) }
  }

  const capture = async (p: { videoUrl?: string; file?: File; atSec: number }) => {
    setCapturing(true)
    try {
      await api.extractFrameFromVideo(pid, shot.id, { target, atSec: p.atSec, videoUrl: p.videoUrl, file: p.file })
      setModal(false); onDone()
    } catch (e) { alert(String(e)) }
    finally { setCapturing(false) }
  }

  return (
    <div className="nf-pane">
      <div className="dim nf-hint">
        {first
          ? '抽取上一镜视频的最后一帧作本镜首帧，画面与上镜收尾无缝衔接。'
          : '抽取下一镜视频的第一帧作本镜尾帧，本镜收束到下镜开场画面。'}
        {extracted && '已抽取，可重新抽取覆盖。'}
      </div>
      <div className="btns">
        <button className="small" disabled={busy} onClick={extract}
          title={first ? '需要上一镜已生成视频' : '需要下一镜已生成视频'}>
          {busy ? <Icon name="spinner" spin /> : <Icon name="wand" />}
          {busy ? ' 抽取中…' : extracted ? ' 重新抽取' : (first ? ' 抽取上一镜尾帧' : ' 抽取下一镜首帧')}
        </button>
        <button className="ghost small" onClick={() => setModal(true)} title="拖轴/慢放/逐帧手抽">
          <Icon name="video" /> 打开视频抽取
        </button>
      </div>
      {extracted && (
        <div className="ref-chips">
          <span className="ref-chip kf-chip"
            title="点击看大图"
            onClick={() => openLightbox(extracted, `镜头 ${shot.meta.shot_no} ${first ? '首帧' : '尾帧'}（视频抽帧）`)}>
            <img src={extracted} alt="" />
            {first ? '首帧' : '尾帧'}
          </span>
        </div>
      )}
      <VideoFrameModal open={modal} onClose={() => { if (!capturing) setModal(false) }}
        title={`视频抽帧 · 本镜${first ? '首' : '尾'}帧`}
        sources={sources} pid={pid} busy={capturing} onCapture={capture} />
    </div>
  )
}
