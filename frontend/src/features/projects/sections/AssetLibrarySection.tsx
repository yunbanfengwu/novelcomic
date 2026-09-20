import { useEffect, useMemo, useState } from 'react'
import { api, type AssetItem } from '../../../api'
import { Icon } from '../../../components/Icon'
import { openAssetImageCanvas, useTapflowWindowReload } from '../../../lib/tapflowEntries'
import { openLightbox, closeLightbox } from '../../../lib/lightbox'
import './AssetLibrary.css'

/** 生成/素材库（核心要素左栏入口打开）：项目内全部生成/上传产物（图/视频/音频）+ 封面，分组浏览。
 * 点开看大图/播放；图片可「设为封面」或「用作参考」（以其为参考叠开生成弹框再出一张）。
 * 含 recovered 项：重拆镜后附件级联丢失、仅从 gen_logs 找回的历史首帧/视频（角标「重拆前」标注）。 */
export function AssetLibrarySection({ pid, onSetCover }: {
  pid: number
  onSetCover: (url: string) => void
}) {
  const [items, setItems] = useState<AssetItem[] | null>(null)
  const [err, setErr] = useState('')
  const [group, setGroup] = useState('')
  const [coverBusy, setCoverBusy] = useState('')  // 正在补封面的视频 URL（同时只允许一个）
  const load = () => api.assetLibrary(pid).then(setItems).catch(e => setErr(String(e)))
  useEffect(() => { api.assetLibrary(pid).then(setItems).catch(e => setErr(String(e))) }, [pid])
  // 素材画布窗口关闭（可能已产出新素材）→ 刷新列表
  useTapflowWindowReload(load)

  const groups = useMemo(() => [...new Set((items ?? []).map(i => i.group))], [items])
  const list = (items ?? []).filter(i => !group || i.group === group)

  const setCover = async (url: string) => { await api.updateConfig(pid, { cover_url: url }); onSetCover(url) }
  // 用作参考（画布收编 2026-09-18）：以此图为参考打开素材图片画布（独立窗口），
  // 画布内可从素材库节点补充任意项目素材作参考，产物落素材库；窗口关闭后由调用方刷新
  const genFromRef = (it: AssetItem) => openAssetImageCanvas(pid, it.url)
  // 生成封面：后端 ffmpeg 抽首帧转存 OSS 回写（找回项写回 gen_logs），本地即时替换缩略
  const genCover = async (it: AssetItem) => {
    if (coverBusy) return
    setCoverBusy(it.url)
    try {
      const r = await api.genVideoCover(pid, { attachmentId: it.id, videoUrl: it.url })
      setItems(prev => (prev ?? []).map(x => x.url === it.url ? { ...x, cover_url: r.cover_url } : x))
    } catch (e) { alert(`生成封面失败：${e}`) } finally { setCoverBusy('') }
  }

  const view = (it: AssetItem) => openLightbox(it.url, it.name,
    it.media === 'image' ? (
      <div className="al-acts">
        <button className="small" onClick={async () => { await setCover(it.url); closeLightbox() }}
          title="把这张图设为项目封面"><Icon name="image" /> 设为封面</button>
        <button className="small ghost" onClick={() => { closeLightbox(); genFromRef(it) }}
          title="以此图为参考，叠开生成弹框再出一张"><Icon name="palette" /> 用作参考</button>
      </div>
    ) : undefined,
    it.media === 'image' ? undefined : { video: true })

  if (err) return <div className="empty-hint">{err}</div>
  if (items == null) return <div className="empty-hint"><Icon name="spinner" spin /> 加载素材库…</div>
  if (!items.length) return (
    <div className="empty-hint"><Icon name="folder" /> 暂无素材 —— 生成封面/设定图/首帧/视频或上传参考图后在此汇总</div>
  )
  return (
    <div className="asset-lib">
      <div className="al-filters">
        <button className={'al-tab' + (!group ? ' on' : '')} onClick={() => setGroup('')}>全部（{items.length}）</button>
        {groups.map(g => (
          <button key={g} className={'al-tab' + (group === g ? ' on' : '')} onClick={() => setGroup(g)}>{g}</button>
        ))}
      </div>
      <div className="al-grid">
        {list.map(it => (
          <div key={`${it.kind}:${it.id ?? it.url}`} className="al-item" onClick={() => view(it)} title={it.name}>
            <span className="al-thumb">
              {it.media === 'image'
                ? <img src={it.url} alt="" loading="lazy" />
                : it.media === 'video' && it.cover_url
                  ? <img src={it.cover_url} alt="" loading="lazy" />
                  : <span className="al-media"><Icon name={it.media === 'video' ? 'video' : 'speaker'} /></span>}
              {it.media !== 'image' && <span className="al-badge">{it.media === 'video' ? '视频' : '音频'}</span>}
              {it.recovered && <span className="al-badge al-badge-recovered" title="重拆镜前生成，附件已丢失，从生成日志找回">重拆前</span>}
              {it.media === 'video' && !it.cover_url && (
                <span className={'al-hover-acts' + (coverBusy === it.url ? ' busy' : '')}>
                  <button className="small" disabled={!!coverBusy}
                    onClick={e => { e.stopPropagation(); genCover(it) }} title="截取首帧">
                    <Icon name={coverBusy === it.url ? 'spinner' : 'camera'} spin={coverBusy === it.url} /> 生成封面
                  </button>
                  <button className="small ghost" onClick={e => { e.stopPropagation(); view(it) }} title="播放视频">
                    <Icon name="play" /> 查看
                  </button>
                </span>
              )}
            </span>
            <span className="al-name">{it.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
