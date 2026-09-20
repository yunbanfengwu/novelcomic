import { useRef, useState } from 'react'
import type { EpisodeFlashMode, Shot } from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'

/** 预览区的总览视图（时间轴首卡选中时）：固定宫格平铺每镜首帧（横屏 3×3=9 格/页，竖屏 4×2=8 格/页），
 * 未生成的留灰占位格；超一页时右侧竖排页码切换。母带类章级动作收在右上角更多菜单，
 * 高频的「批量场景 / 批量首帧」与「逐镜播放」并排常驻悬浮控制层。 */
export function OverviewStage({ shots, ratio, pendingCount, bdBusy, groupBusy, sceneBusy, flashPromptBusy,
  flashVideoBusy, hasFlashDraft, onBreakdown, onEpisodeFlashPrompt, onEpisodeFlash,
  onBatchScenes, onBatchKeyframes, onReplanScenes, onPlayAll }: {
  shots: Shot[]
  ratio: '16:9' | '9:16'
  pendingCount: number
  bdBusy: boolean
  groupBusy: boolean    // 本章「批量首帧·组图」章级任务在途
  sceneBusy: boolean    // 本章场景图（含空间规划）章级任务在途
  flashPromptBusy: boolean
  flashVideoBusy: boolean
  hasFlashDraft: boolean
  onBreakdown: () => void
  onEpisodeFlashPrompt: (mode: EpisodeFlashMode) => void
  onEpisodeFlash: () => void
  onBatchScenes: () => void      // 本集缺场景图的场景组一次派发（未做空间规划时先跑规划）
  onBatchKeyframes: () => void   // 打开批量首帧·组图画布（整集按场景分组，可按组或全部生成）
  onReplanScenes: () => void     // 强制重跑场景空间规划（忽略指纹缓存）
  onPlayAll: () => void
}) {
  const perPage = ratio === '9:16' ? 8 : 9
  const pages = Math.ceil(shots.length / perPage)
  const [page, setPage] = useState(0)
  const cur = Math.min(page, Math.max(pages - 1, 0))
  const view = shots.slice(cur * perPage, (cur + 1) * perPage)

  // 多页时鼠标滚轮换页：累积滚动量到阈值(100)再翻一页（反向即清零），避免一格触发跳多页
  const wheelAcc = useRef(0)
  const onWheel = (e: React.WheelEvent) => {
    if (pages <= 1) return
    if ((wheelAcc.current > 0) !== (e.deltaY > 0)) wheelAcc.current = 0
    wheelAcc.current += e.deltaY
    const step = 100
    if (wheelAcc.current > step) { wheelAcc.current = 0; setPage(Math.min(cur + 1, pages - 1)) }
    else if (wheelAcc.current < -step) { wheelAcc.current = 0; setPage(Math.max(cur - 1, 0)) }
  }

  const breakdownBtn = (
    <button className={shots.length ? 'small ghost' : 'small'} disabled={bdBusy} onClick={onBreakdown}
      title={shots.length ? '重拆分镜（会作废现有分镜；拆完自动逐镜生成提示词+质检）' : '由分镜员工动态拆镜（拆完自动逐镜生成提示词+质检）'}>
      {bdBusy ? <><Icon name="spinner" spin /> 拆镜中…</>
        : <><Icon name="clapper" /> {shots.length ? '重新拆分镜' : '动态生成分镜'}</>}
    </button>
  )

  if (!shots.length) {
    return (
      <div className="vt-ov">
        <div className="vt-empty">
          <div style={{ fontSize: 40 }}><Icon name="clapper" /></div>
          <div className="dim">
            {bdBusy ? '分镜员工拆镜中（拆完自动逐镜生成提示词+质检）…'
              : '本章尚无分镜 —— 由分镜员工动态拆镜（拆完可逐镜生成首帧与视频）'}
          </div>
          <div className="btns">
            {breakdownBtn}
          </div>
        </div>
        <div className="ov-actions">
          <button className="ov-actions-trigger" aria-label="更多章级操作" aria-haspopup="menu"
            title="更多章级操作">
            <Icon name="more" />
          </button>
          <div className="ov-actions-menu" role="menu">
            <div className="ov-actions-title">母带操作</div>
            <button className="small ghost" disabled={bdBusy || flashPromptBusy || flashVideoBusy}
              role="menuitem"
              onClick={() => onEpisodeFlashPrompt('flash20')}
              title="按约8分钟本章剧情生成5秒20镜、每镜0.25秒的分段母带提示词">
              {flashPromptBusy ? <><Icon name="spinner" spin /> 提示词生成中…</>
                : <><Icon name="clip" /> 20镜闪回提示词</>}
            </button>
            <button className="small ghost" disabled={bdBusy || flashPromptBusy || flashVideoBusy}
              role="menuitem"
              onClick={() => onEpisodeFlashPrompt('sampled_story')}
              title="把约10分钟剧情按时间顺序抽取代表画面，生成5秒超级加速母带提示词">
              <><Icon name="clip" /> 10分钟抽帧式提示词</>
            </button>
            <button className="small ghost" disabled={bdBusy || flashPromptBusy || flashVideoBusy}
              role="menuitem"
              onClick={() => onEpisodeFlashPrompt('timeline_supercut')}
              title="把超过5分钟剧情拆成带原时间标记的分镜提示词，合并为一次480p、5秒超级加速请求">
              <><Icon name="clip" /> 分镜时间轴合并·480p</>
            </button>
            <button className="small ghost" disabled={bdBusy || flashPromptBusy || flashVideoBusy}
              role="menuitem"
              onClick={() => onEpisodeFlashPrompt('adaptive_groups')}
              title="由大模型按实际剧情自动判断关键切换与分组，每组不超过15次；各组母带均保留">
              <><Icon name="clip" /> 自动分组·≤15次/组</>
            </button>
            <button className="small ghost" disabled={bdBusy || flashPromptBusy || flashVideoBusy}
              role="menuitem"
              onClick={() => onEpisodeFlashPrompt('adaptive_duration')}
              title="不限制15次切换；按5秒/15次的稳定均值计算所需时长，并向上取整为整数秒">
              <><Icon name="clip" /> 切换数自适应·整数秒</>
            </button>
            <button className="small ghost" disabled={bdBusy || flashPromptBusy || flashVideoBusy || !hasFlashDraft}
              role="menuitem"
              onClick={onEpisodeFlash}
              title={hasFlashDraft ? '依据右侧当前草稿的切换数、分组与动态时长生成母带；不改正式分镜' : '请先生成母带提示词'}>
              {flashVideoBusy ? <><Icon name="spinner" spin /> 母带生成中…</>
                : <><Icon name="video" /> 按当前提示词生成母带</>}
            </button>
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className="vt-ov">
      <div className="ov-wrap" onWheel={onWheel}>
        <div className={'ov-grid' + (ratio === '9:16' ? ' portrait' : '')}>
          {view.map(s => s.meta.keyframe_url ? (
            <div key={s.id} className="ov-cell"
              style={{ backgroundImage: `url(${s.meta.keyframe_url})` }}
              onClick={() => openLightbox(s.meta.keyframe_url!, `镜${s.meta.shot_no} 首帧`)}>
              <span className="ov-cell-no">镜{s.meta.shot_no}</span>
            </div>
          ) : (
            <div key={s.id} className="ov-cell ov-cell-empty">
              <span className="ov-cell-no">镜{s.meta.shot_no}</span>
            </div>
          ))}
        </div>
        {/* 右侧竖排页码：仅超一页时显示 */}
        {pages > 1 && (
          <div className="ov-pages">
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} className={'ov-page' + (i === cur ? ' active' : '')}
                title={`第${i + 1}页`} onClick={() => setPage(i)}>{i + 1}</button>
            ))}
          </div>
        )}
      </div>
      {/* 悬浮控制层（划入显示）：逐镜播放整章 + 两个高频批量入口（下方常显标签即说明，不挂 tooltip）。
          在途时圆钮内换转圈图标，标签不变——按钮位置固定，不因状态跳动。 */}
      <div className="vt-overlay">
        <div className="vt-ctrl-item">
          <button className="vt-ctrl" onClick={onPlayAll}>
            <Icon name="playnext" />
          </button>
          <span className="vt-ctrl-label">逐镜播放</span>
        </div>
        <div className="vt-ctrl-item">
          <button className="vt-ctrl" onClick={onBatchScenes} disabled={sceneBusy}>
            <Icon name={sceneBusy ? 'spinner' : 'scene'} spin={sceneBusy} />
          </button>
          <span className="vt-ctrl-label">批量场景</span>
        </div>
        <div className="vt-ctrl-item">
          <button className="vt-ctrl" onClick={onBatchKeyframes}>
            <Icon name={groupBusy || pendingCount > 0 ? 'spinner' : 'palette'}
              spin={groupBusy || pendingCount > 0} />
          </button>
          <span className="vt-ctrl-label">批量首帧</span>
        </div>
      </div>
      {/* 母带类章级动作收进右上角更多菜单，避免遮挡主预览；批量场景/批量首帧已提到悬浮控制层，不在此重复。
          「重新拆分镜」已下线——重拆会作废现有分镜且无版本，误点即丢历史，暂不提供。 */}
      <div className="ov-actions">
        <button className="ov-actions-trigger" aria-label="更多章级操作" aria-haspopup="menu"
          title="更多章级操作">
          <Icon name="more" />
        </button>
        <div className="ov-actions-menu" role="menu">
          <div className="ov-actions-title">共 {shots.length} 镜 · 章级操作</div>
          {/* 重跑空间规划：此前它只在「批量场景」发现本集没有分组时才会触发，已有分组就再也
              跑不到——而旧单阶段场景组缺 empty_prompt 时，出图恰恰要求先重跑它，等于死循环。
              这里给它一个常驻入口，force 忽略指纹（剧本没改也要按新版提示词重规划）。 */}
          <button className="small ghost" role="menuitem" disabled={sceneBusy}
            onClick={onReplanScenes}
            title="按当前版本重跑本章场景分组与站位规划；已生成的场景图不作废">
            {sceneBusy ? <><Icon name="spinner" spin /> 规划中…</>
              : <><Icon name="scene" /> 重跑场景空间规划</>}
          </button>
          <button className="small ghost" role="menuitem" disabled={flashPromptBusy || flashVideoBusy}
            onClick={() => onEpisodeFlashPrompt('flash20')}
            title="生成约8分钟剧情的20镜闪回提示词；现有分镜和历史母带均不改动">
            {flashPromptBusy ? <><Icon name="spinner" spin /> 提示词生成中…</>
              : <><Icon name="clip" /> 20镜闪回提示词</>}
          </button>
          <button className="small ghost" role="menuitem" disabled={flashPromptBusy || flashVideoBusy}
            onClick={() => onEpisodeFlashPrompt('sampled_story')}
            title="生成约10分钟剧情的抽帧式超级加速提示词；历史数据均保留">
            <><Icon name="clip" /> 10分钟抽帧式提示词</>
          </button>
          <button className="small ghost" role="menuitem" disabled={flashPromptBusy || flashVideoBusy}
            onClick={() => onEpisodeFlashPrompt('timeline_supercut')}
            title="把超过5分钟剧情的分镜按原时间标记合并提交，输出480p、5秒超级加速母带">
            <><Icon name="clip" /> 分镜时间轴合并·480p</>
          </button>
          <button className="small ghost" role="menuitem" disabled={flashPromptBusy || flashVideoBusy}
            onClick={() => onEpisodeFlashPrompt('adaptive_groups')}
            title="由大模型按实际剧情自动判断关键切换与分组，每组不超过15次；各组母带均保留">
            <><Icon name="clip" /> 自动分组·≤15次/组</>
          </button>
          <button className="small ghost" role="menuitem" disabled={flashPromptBusy || flashVideoBusy}
            onClick={() => onEpisodeFlashPrompt('adaptive_duration')}
            title="不限制15次切换；按5秒/15次的稳定均值计算所需时长，并向上取整为整数秒">
            <><Icon name="clip" /> 切换数自适应·整数秒</>
          </button>
          <button className="small ghost" role="menuitem"
            disabled={flashPromptBusy || flashVideoBusy || !hasFlashDraft}
            onClick={onEpisodeFlash} title="依据当前草稿的切换数、分组与动态时长生成新母带；不改现有分镜">
            {flashVideoBusy ? <><Icon name="spinner" spin /> 新批次生成中…</>
              : <><Icon name="video" /> 按提示词生成母带</>}
          </button>
        </div>
      </div>
    </div>
  )
}
