import { useCallback, useMemo, useRef, useState } from 'react'

/** 慢放档位：1×正常 / 0.5×半速 / 0.25×四分之一，供逐帧对齐时看清瞬间动作 */
export const PLAY_RATES = [1, 0.5, 0.25] as const

/** 视频拖轴/逐帧/慢放的纯交互逻辑 hook：托管一个 <video> 元素，对外给状态与控制方法。
 * 播放/拖轴/慢放/逐帧全在浏览器 <video> 上白拿（不需要 CORS）；真正抽帧由宿主拿 time 交给后端。
 * 用法：把 videoProps 铺到 <video>，seek 绑时间轴 range，step(±1) 逐帧，setRate 切慢放。 */
export function useVideoScrubber(fps = 25) {
  const ref = useRef<HTMLVideoElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [rate, setRateState] = useState<number>(1)
  const rateRef = useRef(1)

  const seek = useCallback((t: number) => {
    const v = ref.current
    if (!v) return
    const clamped = Math.max(0, Math.min(t, v.duration || 0))
    v.currentTime = clamped
    setTime(clamped)
  }, [])

  const step = useCallback((frames: number) => {
    const v = ref.current
    if (!v) return
    v.pause()
    seek((v.currentTime || 0) + frames / fps)
  }, [fps, seek])

  const toggle = useCallback(() => {
    const v = ref.current
    if (!v) return
    if (v.paused) void v.play()
    else v.pause()
  }, [])

  const setRate = useCallback((r: number) => {
    rateRef.current = r
    setRateState(r)
    if (ref.current) ref.current.playbackRate = r
  }, [])

  // 事件处理器铺到 <video>：元数据就绪重置时长/进度并复用当前倍速；换源时同样走这里归零
  const videoProps = useMemo(() => ({
    ref,
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLVideoElement>) => {
      const v = e.currentTarget
      v.playbackRate = rateRef.current
      setDuration(v.duration || 0)
      setTime(v.currentTime || 0)
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLVideoElement>) => setTime(e.currentTarget.currentTime || 0),
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
  }), [])

  return { ref, playing, time, duration, rate, videoProps, seek, step, toggle, setRate }
}
