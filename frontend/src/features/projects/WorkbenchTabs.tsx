import { useNavigate } from 'react-router-dom'
import { Icon } from '../../components/Icon'
import { Seg } from '../../components/Seg'
import { useFullscreen } from '../../lib/useFullscreen'

export type SectionKey = 'overview' | 'video' | 'novel' | 'elements'

/** 分区导航 tab（不含视频——视频经「正文/视频」组进入；资料已并入总览） */
const SECTIONS: { key: Exclude<SectionKey, 'video'>; label: string }[] = [
  { key: 'overview', label: '总览' },
  { key: 'novel', label: '小说' },
  { key: 'elements', label: '素材库' },
]

const LOCK_HINT = '请先生成大纲（总览页会自动生成）'

/**
 * 工作台顶栏：三栏——左侧标题区 | 居中 tab（分区组 + 间隔 + 正文/视频 组）| 右侧动作插槽。
 * 标题区在正文/视频阶段显示章节名，其余分区显示项目名。
 * 分区与模式切换全部走 URL（不用 useState 切页）。小说无内容时隐藏其 tab（hasNovel=false）。
 * locked=项目尚无架构大纲：除总览外全部 tab 禁用（hover 提示先生成大纲）。
 * 右侧 wb-actions 为分区子件的动作 portal 目标（回调 ref 交由容器持有）。
 */
export function WorkbenchTabs({ id, activeSection, mode, activeSeq, hasNovel, locked, title, setHeadSlot }: {
  id: number
  activeSection: SectionKey
  mode?: 'body' | 'video'
  activeSeq: number
  hasNovel: boolean
  locked?: boolean
  title?: string
  setHeadSlot: (el: HTMLDivElement | null) => void
}) {
  const navigate = useNavigate()
  const sections = SECTIONS.filter(s => s.key !== 'novel' || hasNovel)
    .map(s => ({ ...s, disabled: locked && s.key !== 'overview', title: locked && s.key !== 'overview' ? LOCK_HINT : undefined }))
  const { isFull, toggle } = useFullscreen()

  return (
    // 外层 100% 宽可横向滚动；内层设最小宽度——窄屏（移动端）整条横滑，不再换行挤压
    <div className="wb-tabbar-wrap">
    <div className="wb-tabbar">
      {/* 左：标题区（章节名 / 项目名） */}
      <div className="wb-title" title={title}>{title}</div>
      {/* 中：所有 tab 居中——分区组 + 间隔 + 正文/视频 组（公共 Seg 组件） */}
      <div className="wb-tabs">
        <Seg items={sections} active={activeSection}
          onSelect={k => navigate(`/project/${id}/${k}`)} />
        <Seg items={[
          { key: 'body' as const, label: '剧集', disabled: locked, title: locked ? LOCK_HINT : undefined },
          { key: 'video' as const, label: '视频', disabled: locked, title: locked ? LOCK_HINT : undefined },
        ]} active={mode}
          onSelect={k => navigate(`/project/${id}/${k}/${activeSeq}`)} />
      </div>
      {/* 右：分区动作插槽（子件 portal 注入）+ 全局「全屏/收起」 */}
      <div className="wb-right">
        <div className="wb-actions" ref={setHeadSlot} />
        <div className="seg wb-action-seg">
          <button className="seg-btn icon" onClick={toggle} title={isFull ? '收起' : '全屏'}>
            <Icon name={isFull ? 'collapse' : 'fullscreen'} />
          </button>
        </div>
      </div>
      {/* 任务队列在顶栏之外：自身 portal 成 body 级可拖动浮标（全屏弹窗也盖不住）。
          挂在这里只为提供 pid——它在顶栏里不占位、不渲染任何东西。 */}
    </div>
    </div>
  )
}
