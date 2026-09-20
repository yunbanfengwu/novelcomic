import { useEffect, useState } from 'react'

// 全局播放偏好（持久化到 localStorage）：跨分镜、跨剧集、跨进出详情页都保持，
// 不随工作台重挂载重置（与页面级的「播放模式」相反）。
type FlagSetter = (v: boolean | ((p: boolean) => boolean)) => void

function usePersistedFlag(key: string): [boolean, FlagSetter] {
  const [on, setOn] = useState(() => {
    try { return localStorage.getItem(key) !== '0' } catch { return true }  // 默认开
  })
  useEffect(() => { try { localStorage.setItem(key, on ? '1' : '0') } catch { /* 隐私模式：忽略 */ } }, [key, on])
  return [on, setOn]
}

/** 「自动播放」：切镜/进页面是否自动起播 */
export const useAutoPlay = () => usePersistedFlag('nc-autoplay')
/** 「声音」：播放是否带声（自动播放钮的下拉里切换；默认开启） */
export const useSoundOn = () => usePersistedFlag('nc-sound')
