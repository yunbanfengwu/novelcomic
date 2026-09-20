import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { setRouteLocation } from './uiContext'

// 系统管理子页的展示名（未收录的 tab 直接显示 key）
const ADMIN_TABS: Record<string, string> = {
  kb: '知识库', modelmgmt: '模型管理', agents: '智能体', skills: '技能',
  projects: '项目', users: '用户', genlog: '生成日志', vendors: '服务商',
}

/** 全站 UI 感知 Provider：App.tsx 挂一次，把路由解析成语义页面位置
 * （页面名 / 项目 id / 管理子页 / 画布窗口），路由切换零埋点自动更新。
 * 弹窗感知不在这里——components/Modal 一处埋点；深度上下文由各页面
 * registerChatContributor 注册（见 lib/uiContext）。纯副作用组件。 */
export function UiContextProvider() {
  const loc = useLocation()
  useEffect(() => {
    const p = loc.pathname
    let page = '桌面'
    let detail: string | undefined
    let projectId: number | undefined
    let m = p.match(/^\/project\/(\d+)(?:\/(video|body))?(?:\/(\d+))?/)
    if (m) {
      projectId = Number(m[1])
      page = '章节工作台'
      const seg = m[2] === 'video' ? '视频模式' : m[2] === 'body' ? '图文模式' : undefined
      detail = `项目 ${m[1]}${seg ? ` · ${seg}` : ''}${m[3] ? ` · 第 ${m[3]} 章` : ''}`
      // 记住最近活跃项目：任务队列在全站（桌面/管理页）跟随它
      try { localStorage.setItem('ui-last-pid', String(projectId)) } catch { /* 隐私模式忽略 */ }
    } else if ((m = p.match(/^\/admin\/([^/]+)/))) {
      page = '系统管理'
      detail = ADMIN_TABS[m[1]] ?? decodeURIComponent(m[1])
    } else if (p.startsWith('/tapflow/window')) {
      page = '画布窗口'
      const q = new URLSearchParams(loc.search)
      detail = `画布 ${q.get('slug') ?? ''}${q.get('version') ? ` v${q.get('version')}` : ''}`
        + (q.get('variant') === 'production' ? ' · 生产态' : ' · 编排态')
    } else if (p.startsWith('/canvas')) {
      page = '绘图画布'
    }
    setRouteLocation({ route: p, page, detail, projectId })
  }, [loc.pathname, loc.search])
  return null
}
