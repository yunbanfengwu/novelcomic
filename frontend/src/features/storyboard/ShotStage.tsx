import { useCallback, useEffect, useRef } from 'react'
import type { Shot } from '../../api'
import type { PlayMode } from './usePlayAll'
import { openLightbox } from '../../lib/lightbox'
import { buildCues } from '../../lib/buildCues'
import { splitSentences } from '../../lib/splitSentences'
import { Icon } from '../../components/Icon'
import { LightboxInfo } from '../../components/LightboxInfo'

// ── Ken Burns：无视频镜「播放整集」时，1:1 图撑满舞台 + 按本镜运镜位移/缩放 ──
// 编辑态不启用（仍 object-fit:contain 看全图、可点击放大）；overflow 轴由画幅比锁死，见 .kb-* keyframes
function kenBurnsClass(s: Shot, ratio: '16:9' | '9:16'): string {
  const m = s.meta.camera_move || ''
  if (m.includes('推')) return 'kb-push'          // 推镜 → 推近
  if (m.includes('拉')) return 'kb-pull'          // 拉镜 → 拉远
  if (m.includes('摇')) return 'kb-pan-h'         // 摇镜 → 横向摇
  if (m.includes('移')) return 'kb-track'         // 移镜 → 横向匀速移
  if (m.includes('跟')) return 'kb-follow'        // 跟拍 → 轻推+微漂
  if (m.includes('升') || m.includes('降')) return 'kb-crane'   // 升降 → 纵向（下→上）
  if (m.includes('晃') || m.includes('手持')) return 'kb-shake' // 手持晃动 → 抖动循环
  if (m.includes('环绕')) return 'kb-orbit'       // 环绕 → 缩放+微旋转漂移
  if (m === '固定') return 'kb-static'            // 固定 → 极缓轻推，仅让画面「活着」
  // 无运镜/未知：按画幅方向兜底（横屏 16:9 纵向、竖屏 9:16 横向）
  return ratio === '9:16' ? 'kb-pan-h' : 'kb-crane'
}

/** 分镜舞台：视频/首帧 + 悬浮字幕 + 划入才现的悬浮控制层。
 * 生产按钮全在右侧详情卡；主预览只管「看」。受控播放：playing（会话期望态）驱动 <video> 起停。
 * 悬浮控制两个都是「动作」钮：[顺序播放]=立即从本镜起连续播；[单镜循环]=立即循环播本镜；
 * 正在播的那个显示为 [停止]。另有 [查看放大]。
 * 关键实现：<video> 不随镜头重挂载（无 key，仅换 src）——同一元素被用户点播过一次后，
 * 浏览器允许它在后续换源时继续有声播放（各视频站标准做法）；换镜自动续播全靠这一点。
 * 声音是全局偏好 soundOn（自动播放钮下拉切换，默认开）；冷进入时有声起播被自动播放策略拒
 * → 静默回落静音起播，用户任意一次控制点击（真实手势）即按偏好恢复有声。 */
export function ShotStage({
  sel, ratio, elapsed, soundOn, playMode, playing, setPlayMode, setPlaying, onNext, setRemain, setElapsed,
  isLast, onRestart, onOpenEditor, busy, onGenVideo,
}: {
  sel: Shot
  ratio: '16:9' | '9:16'
  elapsed: number
  soundOn: boolean            // 全局声音偏好：关=静音播放
  playMode: PlayMode          // 顺序播放 | 单镜循环（页面级，进页面/切剧集重置为顺序）
  playing: boolean            // 会话期望态：是否在播
  setPlayMode: (m: PlayMode) => void
  setPlaying: (v: boolean) => void
  onNext: () => void          // 顺序模式播完本镜 → 下一镜
  setRemain: (n: number | null) => void
  setElapsed: (n: number) => void
  isLast: boolean             // 最后一镜：顺序播放钮变「从头播放」（跳回第一镜连续播）
  onRestart: () => void       // 从第一镜开始顺序播放
  onOpenEditor: (target: 'image' | 'video') => void  // 空态常驻钮 → 生成编辑弹窗（与详情卡同一入口）
  busy: boolean               // 本镜有任务在途：悬浮生成钮转圈禁点（与详情头一键钮同源）
  onGenVideo: () => void      // 悬浮控制层「生成视频」一键直出（依赖 DAG 自动补首帧/提示词）
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  // 稳定 ref 回调（useCallback 恒定身份）：仅真正挂/卸时触发（换 src 不重挂）。
  // 内联 ref 回调每次渲染身份都变，React 会重跑 cleanup 把视频每帧暂停——绝不可内联。
  const setVideoNode = useCallback((node: HTMLVideoElement | null) => {
    videoRef.current = node
    return () => { node?.pause(); if (videoRef.current === node) videoRef.current = null }
  }, [])
  // 起播（含策略回落）：按声音偏好试播；有声被自动播放策略拒 → 静默回落静音重试
  //（静音自动播放恒被允许）；再拒才认停。用户后续任意控制点击会按偏好恢复有声。
  const attemptPlay = useCallback((v: HTMLVideoElement) => {
    v.muted = !soundOn
    v.play().catch(() => {
      if (v.muted) { setPlaying(false); return }
      v.muted = true
      v.play().catch(() => { v.muted = !soundOn; setPlaying(false) })
    })
  }, [setPlaying, soundOn])
  // 声音偏好切换立即应用到在播视频（含解除策略回落的静音）
  useEffect(() => {
    const v = videoRef.current
    if (v) v.muted = !soundOn
  }, [soundOn, sel.id])
  // 受控同步：会话在播 → 保证当前 <video> 在播（换镜换 src 后同样据此续播）；会话停 → 暂停。
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    if (playing) { if (v.paused) attemptPlay(v) }
    else if (!v.paused) v.pause()
  }, [playing, sel.id, attemptPlay])

  // 悬浮字幕：由播放时钟驱动（视频=currentTime；图片停留=计时器）
  const cues = buildCues(sel)
  const cue = cues.find(c => elapsed >= c.start && elapsed < c.end)
  const showSub = !!cue && (playing || !!sel.meta.video_url)

  // 无视频镜的画面来源：首帧 / 尾帧（可能只有其一，也可能都有）
  const kf = sel.meta.keyframe_url
  const lf = sel.meta.last_frame_url
  const bothFrames = !!kf && !!lf
  const holdDur = Math.max(2, sel.meta.duration_s || 3)   // = usePlayAll 停留时钟的本镜时长
  // 播放中的双帧镜：不并列同显，改为依次单帧铺满——首帧占 2/3 时长、尾帧占余下 1/3（splitFrames）。
  // 限连续模式——只有它有停留时钟在推 elapsed；单镜循环下无视频镜 elapsed 恒 0，仍走并列。
  const splitFrames = playing && playMode === 'sequence' && !sel.meta.video_url && bothFrames
  const kfHold = holdDur * 2 / 3                          // 首帧的停留时长（尾帧 = 余下 1/3）
  const showKf = !!kf && (!splitFrames || elapsed < kfHold)
  const showLf = !!lf && (!splitFrames || elapsed >= kfHold)
  // 播放态单帧铺满：首帧套 Ken Burns 运镜；尾帧不做推拉摇移——只挂 .kb（cover 铺满、无运镜类=无动画）静置等切镜
  const fillActive = playing && !sel.meta.video_url && (splitFrames || (!bothFrames && (!!kf || !!lf)))
  const kfCls = fillActive ? `vt-video kb ${kenBurnsClass(sel, ratio)}` : 'vt-video'
  const lfCls = fillActive ? 'vt-video kb' : 'vt-video'
  // 动画时长 = 首帧的实际停留时长（单帧=整镜；双帧分时=前 2/3），令位移在切帧/切镜时刚好走完
  const kbStyle = fillActive ? { animationDuration: `${splitFrames ? kfHold : holdDur}s` } : undefined

  // 两个动作钮共用：点未激活的 → 切到该模式并立即起播；点已激活的 → 停止。
  // 真实点击自带手势 → 顺带按声音偏好解除策略回落的静音。
  const startStop = (mode: PlayMode) => {
    const active = playing && playMode === mode
    if (active) { setPlaying(false); return }
    const v = videoRef.current
    if (v) v.muted = !soundOn
    setPlayMode(mode)
    setPlaying(true)
  }
  // 查看放大：视频放大播（lightbox video），首/尾帧放大看图（附对应提示词）
  const openZoom = () => {
    if (sel.meta.video_url) { openLightbox(sel.meta.video_url, `镜头 ${sel.meta.shot_no} 视频`, undefined, { video: true }); return }
    if (kf) {
      openLightbox(kf, `镜头 ${sel.meta.shot_no} 首帧`,
        <LightboxInfo sections={[{ label: '首帧提示词', text: sel.meta.image_prompt }]} />)
      return
    }
    if (lf) {
      openLightbox(lf, `镜头 ${sel.meta.shot_no} 尾帧`,
        <LightboxInfo sections={[{ label: '尾帧提示词', text: sel.meta.last_image_prompt }]} />)
    }
  }

  const hasMedia = !!(sel.meta.video_url || kf || lf)
  const seqActive = playing && playMode === 'sequence'
  const loopActive = playing && playMode === 'loop'

  // 顺序播放钮（空态常驻/悬浮控制层共用）：正在播=停止；最后一镜=从头播放（跳回第一镜）；其余=从本镜连播
  const seqClick = () => {
    if (seqActive) { setPlaying(false); return }
    if (isLast) {
      const v = videoRef.current
      if (v) v.muted = !soundOn
      onRestart()
      return
    }
    startStop('sequence')
  }
  const seqBtn = (
    <div className="vt-ctrl-item">
      <button className="vt-ctrl" onClick={seqClick}>
        <Icon name={seqActive ? 'pause' : 'playnext'} />
      </button>
      <span className="vt-ctrl-label">{seqActive ? '停止' : isLast ? '从头播放' : '逐镜播放'}</span>
    </div>
  )

  return (
    <div className="vt-main">
      <div className="vt-stage">
        {sel.meta.video_url ? (
          // 无 key：换镜只换 src、不重挂元素——保住该元素上「用户点播过」的播放许可，
          // 换镜/顺序推进的有声续播全靠它。ref 清理仅在真正卸载（离开页面/切到无视频镜）时暂停，
          // 防止被移除的 <video> 在后台继续响。用稳定回调 setVideoNode（内联回调会每帧暂停，见上）。
          <video src={sel.meta.video_url} className="vt-video"
            poster={sel.meta.video_cover_url || sel.meta.keyframe_url || undefined}
            ref={setVideoNode}
            loop={playMode === 'loop'}
            onEnded={() => { if (playMode === 'sequence') onNext() }}
            onTimeUpdate={e => {
              const v = e.currentTarget
              if (v.duration) setRemain(Math.max(0, Math.ceil(v.duration - v.currentTime)))
              setElapsed(v.currentTime)
            }} />
        ) : (kf || lf) ? (
          /* 无视频：首/尾帧完整展示（contain）。选中态两者都有则并列；播放态改为依次单帧铺满
             （splitFrames：首帧 2/3、尾帧 1/3）。左上角常显「首帧图/尾帧图」标签。
             铺满时只有首帧套 Ken Burns，尾帧静置。 */
          <div className="vt-frames">
            {showKf && (
              <div className="vt-frame-cell">
                <span className="vt-frame-tag">首帧图</span>
                <img key={`kf-${sel.id}`} src={kf} alt="首帧" className={kfCls} style={kbStyle} />
              </div>
            )}
            {showLf && (
              <div className="vt-frame-cell">
                <span className="vt-frame-tag">尾帧图</span>
                <img key={`lf-${sel.id}`} src={lf} alt="尾帧" className={lfCls} />
              </div>
            )}
            {/* 分时单显下尾帧要到后 1/3 才挂载：先隐形拉一次，避免切帧白闪 */}
            {splitFrames && showKf && lf && <img src={lf} alt="" aria-hidden className="vt-frame-pre" />}
          </div>
        ) : (
          /* 空态：生产入口常驻（非 hover 才现，且此时无悬浮层遮挡）——
             生成首图 → 生成视频 → 顺序播放/停止，圆钮样式与悬浮控制层一致；下方带分镜脚本摘要 */
          <div className="vt-empty">
            <div className="vt-empty-title">镜{sel.meta.shot_no}：当前暂无画面</div>
            <div className="vt-empty-ctrls">
              <div className="vt-ctrl-item">
                <button className="vt-ctrl" onClick={() => onOpenEditor('image')}>
                  <Icon name="palette" />
                </button>
                <span className="vt-ctrl-label">生成首图</span>
              </div>
              <span className="vt-empty-arrow">→</span>
              <div className="vt-ctrl-item">
                <button className="vt-ctrl" onClick={() => onOpenEditor('video')}>
                  <Icon name="video" />
                </button>
                <span className="vt-ctrl-label">生成视频</span>
              </div>
              <span className="vt-empty-divider" />
              {playing && (
                <div className="vt-ctrl-item">
                  <div className="vt-empty-timer-num">{Math.max(0, Math.ceil((sel.meta.duration_s || 3) - elapsed))}s</div>
                  <span className="vt-ctrl-label">时长/秒</span>
                </div>
              )}
              {seqBtn}
            </div>
            {sel.summary && (
              <div className="vt-empty-script">
                {splitSentences(sel.summary).map((line, i) => <div key={i}>{line}</div>)}
              </div>
            )}
          </div>
        )}
        {showSub && <div className="vt-sub">{cue!.text}</div>}
        {/* 悬浮控制层：划入才现。两个动作钮（正在播的显示「停止」）+ 查看 */}
        {hasMedia && (
          <div className="vt-overlay">
            {/* 顺序播放：从本镜起连播，播完整集自动停；图片镜也参与（按时长停留）；最后一镜=从头播放 */}
            {seqBtn}
            {/* 单镜循环：只循环播本镜（仅视频镜可用） */}
            {sel.meta.video_url && (
              <div className="vt-ctrl-item">
                <button className="vt-ctrl" onClick={() => startStop('loop')}>
                  <Icon name={loopActive ? 'pause' : 'loop'} />
                </button>
                <span className="vt-ctrl-label">{loopActive ? '停止' : '单镜循环'}</span>
              </div>
            )}
            <div className="vt-ctrl-item">
              <button className="vt-ctrl" onClick={openZoom} title="放大查看">
                <Icon name="search" />
              </button>
              <span className="vt-ctrl-label">查看</span>
            </div>
            {/* 未出视频（仅首帧）：一键生成视频——与详情头按钮同源（依赖 DAG 自动补首帧/提示词） */}
            {!sel.meta.video_url && (
              <div className="vt-ctrl-item">
                <button className="vt-ctrl" disabled={busy} onClick={onGenVideo}
                  title="一键生成视频：自动补齐首帧、关联要素、提示词并派发，无需逐步确认">
                  {busy ? <Icon name="spinner" spin /> : <Icon name="zap" />}
                </button>
                <span className="vt-ctrl-label">生成视频</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
