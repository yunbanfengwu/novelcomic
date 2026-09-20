import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../../components/Icon'
import { openAssetImageCanvas, openAssetVideoCanvas } from '../../lib/tapflowEntries'

type Tab = 'free' | 'image' | 'video'
const TABS: { key: Tab; label: string }[] = [
  { key: 'free', label: '自由设定' }, { key: 'image', label: '生成图片' }, { key: 'video', label: '生成视频' },
]

/** 新增素材弹框（三 tab）：
 * - 自由设定（默认）：单输入框描述生成要求，AI 判断生成一个还是多个要素；留空=依目录生成全部。
 *   点「开始生成」即关弹框、生成交给分区逐个流式长出，不阻塞等待整批完成。
 * - 生成图片 / 生成视频：打开素材画布（画布收编 2026-09-18：asset-image-canvas / asset-video-canvas——
 *   文本/素材节点连线决定生成输入，画布内素材库可任选项目素材，产物落素材库）。
 *   生成是分钟级长任务，走独立窗口不阻塞本页；窗口关闭后 onAssetGenerated 刷新素材库。 */
export function AddElementModal({ pid, hasElements, onClose, onSubmit, onAssetGenerated }: {
  pid: number
  hasElements: boolean
  onClose: () => void
  onSubmit: (requirement: string) => void
  onAssetGenerated?: () => void   // 图/视频画布窗口关闭后回调（宿主可切到「生成/素材库」查看）
}) {
  const [req, setReq] = useState('')
  const [tab, setTab] = useState<Tab>('free')

  // 先关弹框露出页面，再触发生成——要素才能在眼前逐条流式出现，而非被黑幕挡到整批结束
  const submit = () => { const r = req.trim(); onClose(); onSubmit(r) }

  const openAssetCanvas = (video: boolean) => {
    const open = video ? openAssetVideoCanvas : openAssetImageCanvas
    const r = req.trim()
    if (r) open(pid, undefined, r)
    else open(pid)
    onClose()
    onAssetGenerated?.()
  }

  return createPortal(
    <div className="modal-backdrop" onClick={() => onClose()}>
      <div className="modal-card add-elem-card" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <b>新增素材设定</b>
          <button className="icon-btn" onClick={() => onClose()}><Icon name="close" /></button>
        </div>
        <div className="seg" style={{ marginBottom: 12 }}>
          {TABS.map(t => (
            <button key={t.key} type="button"
              className={'seg-btn' + (tab === t.key ? ' active' : '')}
              onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </div>
        {tab === 'free' ? (
          <>
            <label className="modal-label" htmlFor="elem-req">生成要求</label>
            <textarea id="elem-req" className="modal-textarea" value={req} autoFocus
              onChange={e => setReq(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
              placeholder={'例如：新增角色陈砚，主角的隐世师父；或 补充3个修炼场景——生成一个还是多个由系统按要求自动判断。'
                + (hasElements ? '留空则依据目录重新生成全部素材（覆盖同名）' : '留空则依据目录生成全部素材设定')} />
            <div className="modal-actions">
              <button className="small ghost" onClick={() => onClose()}>取消</button>
              <button className="small" onClick={submit}>
                <Icon name="sparkles" /> 开始生成
              </button>
            </div>
          </>
        ) : (
          <div className="pad">
            <div className="dim" style={{ marginBottom: 12 }}>
              {tab === 'video'
                ? '在素材视频画布中生成一段视频：提示词 + 上游参考节点（首帧等）→ 落素材库。'
                : '在素材图片画布中生成一张图：提示词 + 上游参考节点 → 落素材库。'}
              <br />生成在独立画布窗口进行，不阻塞本页；可从素材库拖入项目素材当参考。
            </div>
            <div className="modal-actions">
              <button className="small ghost" onClick={() => onClose()}>取消</button>
              <button className="small" onClick={() => openAssetCanvas(tab === 'video')}>
                <Icon name="workflow" /> 打开{tab === 'video' ? '视频' : '图片'}画布
              </button>
            </div>
          </div>
        )}
      </div>
    </div>, document.body)
}
