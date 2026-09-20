import { Navigate, Route, Routes } from 'react-router-dom'
import { Lightbox } from './components/Lightbox'
import { TooltipHost } from './components/Tooltip'
import { ChatFab } from './components/chat/ChatFab'
import { ElementPreviewModal } from './components/ElementPreviewModal'
import { UiContextProvider } from './lib/UiContextProvider'
import { ProjectList } from './features/projects/ProjectList'
import { ProjectDetail } from './features/projects/ProjectDetail'
import { AdminView } from './features/admin/AdminView'
import { TapflowWindowPage } from './features/tapflow/TapflowWindowPage'

// ═══════════ 根组件：URL 路由（react-router），页面全部在 features/ 下 ═══════════

export default function App() {
  return (
    <>
      {/* 全站 UI 感知：路由 → 语义位置（页面/项目/弹窗），对话与任务队列都从这里取 */}
      <UiContextProvider />
      <Routes>
        {/* 首页 = 系统桌面（ProjectList 自含整页布局） */}
        <Route path="/" element={<ProjectList />} />
        {/* 章节工作台两种模式各占一条含静态段的路由（video/body），排序优先于泛化的 :section */}
        <Route path="/project/:id/video/:seq" element={<ProjectDetail mode="video" />} />
        <Route path="/project/:id/body/:seq" element={<ProjectDetail mode="body" />} />
        <Route path="/project/:id/:section" element={<ProjectDetail />} />
        <Route path="/project/:id" element={<ProjectDetail />} />
        {/* 系统管理：子菜单即 :tab（可刷新/分享/前进后退），裸 /admin 落到知识库 */}
        <Route path="/admin" element={<Navigate to="/admin/kb" replace />} />
        {/* 模型管理等带内嵌二级列的 tab 用 :sub 定位子页（/admin/modelmgmt/respkg） */}
        <Route path="/admin/:tab/:sub" element={<AdminView />} />
        <Route path="/admin/:tab" element={<AdminView />} />
        <Route path="/tapflow/window" element={<TapflowWindowPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Lightbox />
      <ElementPreviewModal />
      <TooltipHost />
      {/* 右下角全站 AI 对话悬浮：对话 + 任务队列，scope 跟随当前页面 */}
      <ChatFab />
    </>
  )
}
