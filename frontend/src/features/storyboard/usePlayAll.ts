import { useCallback, useEffect, useRef, useState } from 'react'
import type { Shot } from '../../api'

export type PlayMode = 'sequence' | 'loop'   // 连续播放 | 单镜循环

/**
 * 播放会话时钟（页面级，随分镜工作台重挂载而重置）。把旧的 playingAll 拆成两个正交状态：
 *  - playMode：连续 / 单镜循环。默认「连续」；切镜保持；工作台重挂载（进详情页/切剧集）时回到「连续」。
 *  - playing：会话是否在播（期望态）。<video> 由它驱动起播/暂停；无视频镜用停留计时器推进。
 * autoPlay（全局偏好）只决定「切镜/进页面是否自动起播」，进而 seed 会话与切镜续播。
 * remain=倒计时；elapsed=已播秒数（驱动悬浮字幕）。setRemain/setElapsed 给 <video> 的 onTimeUpdate 用。
 */
export function usePlayAll(
  shots: Shot[], selId: number | null, setSelId: (id: number) => void, sel: Shot | null, autoPlay: boolean,
) {
  const [remain, setRemain] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [playMode, setPlayMode] = useState<PlayMode>('sequence') // 页面级：挂载即「连续」
  const [playing, setPlaying] = useState(autoPlay)               // 会话在播（初值=自动播放偏好）
  const holdTimer = useRef<number | null>(null)

  const nextShot = useCallback(() => {
    const idx = shots.findIndex(x => x.id === (selId ?? shots[0]?.id))
    const nxt = shots[idx + 1]
    if (nxt) setSelId(nxt.id)
    else setPlaying(false)  // 连续播到最后一镜：停
  }, [shots, selId, setSelId])

  // 切镜（含进页面首帧）：开着自动播放且本镜「有视频」才自动起播。
  // 无视频镜（仅首/尾帧）不在切镜时自动起播——点选时完整看图/首尾帧并列，不进 Ken Burns。
  // 顺序「播放整集」中经过的无视频镜由 playing 保持 true + 停留计时器负责推进，与此处无关
  //（此处只「开」不「关」，故不会打断整集）。
  useEffect(() => {
    if (autoPlay && sel?.meta.video_url) setPlaying(true)
    // 仅依赖 sel?.id：切镜触发；autoPlay 变更不在此起播（由头部开关自身语义处理）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel?.id])

  // 无视频镜的停留时钟：连续模式且在播时，按本镜时长停留后跳下一镜（有视频镜交给 <video>）。
  useEffect(() => {
    if (holdTimer.current) { clearTimeout(holdTimer.current); holdTimer.current = null }
    setRemain(sel ? (sel.meta.duration_s ?? null) : null)
    setElapsed(0)
    if (!playing || !sel || sel.meta.video_url) return
    if (playMode !== 'sequence') return          // 单镜循环 + 无视频：停在本镜（无可循环媒体）
    const dur = Math.max(2, sel.meta.duration_s || 3)
    const start = Date.now()
    holdTimer.current = window.setTimeout(nextShot, dur * 1000)
    const tick = window.setInterval(() => {
      const e = (Date.now() - start) / 1000
      setRemain(Math.max(0, Math.ceil(dur - e)))
      setElapsed(e)
    }, 200)
    return () => {
      if (holdTimer.current) { clearTimeout(holdTimer.current); holdTimer.current = null }
      clearInterval(tick)
    }
  }, [playing, playMode, sel, nextShot])

  return { playMode, setPlayMode, playing, setPlaying, remain, elapsed, setRemain, setElapsed, nextShot }
}
