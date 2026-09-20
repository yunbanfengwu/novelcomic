import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { ProjectAsset } from '../api'
import { Icon } from './Icon'
import { Seg } from './Seg'
import { VideoFrameModal } from './VideoFrameModal'
import './AssetPicker.css'

/** 项目资产选择面板（公共图片生成弹框右侧拉出）：列出项目已有的任何图片资产——
 * 要素设定图/宫格故事板/各镜首帧/封面/上传·生成的参考图，分组筛选+按名搜索，点选回调宿主。
 * 顶部两钮：上传参考图（直传 OSS+附件表）/ 生成参考图（onGenerateRef 由宿主叠一层生成弹框）。 */
export function AssetPicker({ pid, exclude, onPick, onGenerateRef }: {
  pid: number
  exclude: string[]   // 已在参考池中的名字（不再列出）
  onPick: (a: ProjectAsset) => void
  onGenerateRef?: () => void   // 宿主提供：叠一层公共图片生成弹框生成独立参考图
}) {
  const [assets, setAssets] = useState<ProjectAsset[] | null>(null)
  const [err, setErr] = useState('')
  const [group, setGroup] = useState('')  // ''=全部
  const [q, setQ] = useState('')
  const [uploading, setUploading] = useState(false)
  const [videoModal, setVideoModal] = useState(false)  // 「从视频中抽」弹窗
  const [capturing, setCapturing] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    api.listProjectAssets(pid).then(setAssets).catch(e => setErr(String(e)))
  }, [pid])

  // 新增一张参考图资产并加为当前参考（上传 / 视频抽帧共用收尾）
  const addAsset = (a: { kind: string; name: string; url: string }) => {
    const item = { group: '参考图', kind: a.kind, name: a.name, url: a.url }
    setAssets(list => [item, ...(list ?? [])])
    onPick(item)
  }

  const upload = async (file: File) => {
    setUploading(true)
    try { addAsset(await api.uploadAsset(pid, file)) }  // 上传即加为当前参考
    catch (e) { alert(String(e)) } finally { setUploading(false) }
  }

  // 视频抽帧：按时间点抽一帧存为项目参考图并加为当前参考（视频源为项目任意视频/上传件）
  const captureFrame = async (p: { videoUrl?: string; file?: File; atSec: number }) => {
    setCapturing(true)
    try {
      addAsset(await api.extractAssetFrameFromVideo(pid, { atSec: p.atSec, videoUrl: p.videoUrl, file: p.file }))
      setVideoModal(false)
    } catch (e) { alert(String(e)) } finally { setCapturing(false) }
  }

  const groups = useMemo(() => [...new Set((assets ?? []).map(a => a.group))], [assets])
  const ex = new Set(exclude)
  const list = (assets ?? [])
    .filter(a => !ex.has(a.name))
    .filter(a => !group || a.group === group)
    .filter(a => !q || a.name.includes(q))
  return (
    <div className="asset-picker">
      <div className="ap-title">素材库</div>
      <input ref={fileRef} type="file" accept="image/*" hidden
        onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = '' }} />
      <div className="ap-filters">
        <Seg items={[{ key: '', label: '全部' }, ...groups.map(g => ({ key: g, label: g }))]}
          active={group} onSelect={setGroup} />
        <input className="ap-search" placeholder="搜索名称…" value={q} onChange={e => setQ(e.target.value)} />
      </div>
      {err && <div className="ap-hint">{err}</div>}
      {/* 上传 / 生成 做成两张动作卡，始终置顶前两位（切 tab / 搜索都在） */}
      <div className="ap-grid">
        <button className="ap-item ap-action" disabled={uploading} onClick={() => fileRef.current?.click()}
          title="上传本地图片作参考（转存并入项目资产库）">
          <span className="ap-empty">{uploading ? <Icon name="spinner" spin /> : <Icon name="upload" />}</span>
          <span className="ap-name">上传</span>
        </button>
        {onGenerateRef && (
          <button className="ap-item ap-action" onClick={onGenerateRef}
            title="叠开生成弹框，按提示词生成一张参考图（存入资产库并加为当前参考）">
            <span className="ap-empty"><Icon name="palette" /></span>
            <span className="ap-name">生成</span>
          </button>
        )}
        {/* 第三张动作卡：从视频中抽——弹窗内选项目任意视频，拖轴/逐帧定位后抽一帧存为参考图 */}
        <button className="ap-item ap-action" onClick={() => setVideoModal(true)}
          title="从项目视频里拖轴/逐帧抽一帧作参考（存入资产库并加为当前参考）">
          <span className="ap-empty"><Icon name="video" /></span>
          <span className="ap-name">从视频中抽</span>
        </button>
        {list.map(a => (
          <button key={`${a.group}:${a.name}`} className="ap-item"
            title={a.url ? `添加「${a.name}」为生成参考` : `「${a.name}」暂无设定图（仍可关联，用其文字设定）`}
            onClick={() => onPick(a)}>
            {a.url ? <img src={a.url} alt="" loading="lazy" />
              : <span className="ap-empty"><Icon name="image" /></span>}
            <span className="ap-name">{a.name}</span>
          </button>
        ))}
      </div>
      {!err && assets == null && <div className="ap-hint"><Icon name="spinner" spin /> 加载项目资产…</div>}
      {/* 从视频中抽：无具名 sources，靠 pid 拉项目全部视频供下拉任选（也可临时上传视频） */}
      <VideoFrameModal open={videoModal} onClose={() => { if (!capturing) setVideoModal(false) }}
        title="从视频中抽一帧作参考" sources={[]} pid={pid} busy={capturing} topmost onCapture={captureFrame} />
    </div>
  )
}
