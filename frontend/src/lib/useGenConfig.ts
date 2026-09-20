import { useEffect, useState } from 'react'
import { api } from '../api'
import type { GenConfig } from '../api'

/** 生成配置（系统级开关）的进程内缓存 hook：整个 SPA 只拉一次，多组件共享。
 * 供项目侧按 allow_project_ark_upload 决定是否显示「加入火山角色库」等入口。
 * 系统配置页保存后调用 primeGenConfig，让同会话内已挂载的组件立即拿到新值（无需刷新）。 */
let cache: GenConfig | null = null
let inflight: Promise<GenConfig> | null = null
const subs = new Set<(c: GenConfig) => void>()

/** 用最新值刷新缓存并通知所有订阅组件（系统配置页即改即存后调用）。 */
export function primeGenConfig(c: GenConfig): void {
  cache = c
  subs.forEach(fn => fn(c))
}

export function useGenConfig(): GenConfig | null {
  const [cfg, setCfg] = useState<GenConfig | null>(cache)
  useEffect(() => {
    subs.add(setCfg)
    if (cache) setCfg(cache)
    else {
      inflight ??= api.getGenConfig().then(c => { cache = c; return c })
      inflight.then(c => primeGenConfig(c)).catch(() => {})
    }
    return () => { subs.delete(setCfg) }
  }, [])
  return cfg
}
