import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api'
import type { Chapter, Element, Memory, Project, Volume } from '../../api'
import { resolveEntrySection } from '../../lib/entrySection'
import { getLastSeq, setLastSeq } from '../../lib/lastChapter'
import { useTaskDone } from '../../lib/useTaskDone'
import { SidebarLayout } from '../../components/SidebarLayout'
import { WorkbenchTabs, type SectionKey } from './WorkbenchTabs'
import { OverviewSection } from './sections/OverviewSection'
import { VideoSection } from './sections/VideoSection'
import { NovelSection } from './sections/NovelSection'
import { ElementsSection } from './sections/ElementsSection'
import './projects.css'
import './sections.css'

// ═══════════ 项目详情：URL 路由容器（/project/:id[/:section]，或 /body|/video/:seq） ═══════════

// 顶栏可直达的分区（视频经「正文/视频」组进入，不在此列；资料已并入总览）
const SECTION_KEYS: SectionKey[] = ['overview', 'novel', 'elements']

/** 容器：加载项目/目录/要素/记忆，持有顶栏与动作插槽，按 URL 分派到某个分区 */
export function ProjectDetail({ mode }: { mode?: 'body' | 'video' }) {
  const params = useParams()
  const navigate = useNavigate()
  const id = Number(params.id)
  // 章节工作台：/body|/video/:seq（mode 由路由注入）；旧链 /project/:id/video（无 seq）兜底为视频模式
  const inChapter = mode != null || params.section === 'video'
  // 裸路径 /project/:id：按项目进度决定落点（信息缺失→总览；无正文→正文；有正文→视频）
  const bare = !inChapter && params.section == null
  const section: SectionKey = inChapter ? 'video'
    : (SECTION_KEYS.includes(params.section as SectionKey) ? params.section as SectionKey : 'overview')
  const chapterMode: 'body' | 'video' = mode ?? 'video'
  const seqParam = params.seq != null ? Number(params.seq) : undefined

  const [p, setP] = useState<Project | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [volumes, setVolumes] = useState<Volume[]>([])
  const [elements, setElements] = useState<Element[]>([])
  const [memories, setMemories] = useState<Memory[]>([])
  // 顶栏右侧动作插槽：由 WorkbenchTabs 提供节点，分区子件 portal 到此
  const [headSlot, setHeadSlot] = useState<HTMLDivElement | null>(null)

  // 裸路径只做重定向（replace，不留历史）；落点路由重挂后再走常规取数
  useEffect(() => {
    if (!bare) return
    let on = true
    Promise.all([api.getProject(id), api.getOutline(id), api.getElements(id)])
      .then(([proj, chs, els]) => { if (on) navigate(`/project/${id}/${resolveEntrySection(proj, chs, els, getLastSeq(id))}`, { replace: true }) })
      .catch(console.error)
    return () => { on = false }
  }, [bare, id, navigate])

  // 依赖含 section/chapterMode：每次切换分区 tab（总览/核心要素/剧集/视频）都重新取数，
  // 后台任务（架构大纲/目录/要素生成）完成后切回即见最新，不需要手动刷新页面
  useEffect(() => {
    if (bare) return
    api.getProject(id).then(setP).catch(console.error)
    api.getOutline(id).then(setChapters).catch(console.error)
    api.getVolumes(id).then(setVolumes).catch(console.error)
    api.getElements(id).then(setElements).catch(console.error)
    api.listMemories(id).then(setMemories).catch(console.error)
  }, [id, bare, section, chapterMode])

  // 续写会改变卷内集数，故刷章节时一并刷卷
  const reloadChapters = useCallback(() => {
    api.getOutline(id).then(setChapters).catch(console.error)
    api.getVolumes(id).then(setVolumes).catch(console.error)
  }, [id])
  const reloadVolumes = useCallback(() => { api.getVolumes(id).then(setVolumes).catch(console.error) }, [id])
  const reloadElements = useCallback(() => { api.getElements(id).then(setElements).catch(console.error) }, [id])
  const reloadMemories = useCallback(() => { api.listMemories(id).then(setMemories).catch(console.error) }, [id])

  // 后台补拟任务（基本信息/架构大纲/要素类型）结束 → SSE 驱动刷新项目数据；
  // 大纲刚就绪且尚无核心要素时，从总览自动进入「核心要素」页（渐进式引导下一步）
  const onGenTaskDone = useCallback((kind: string) => {
    api.getProject(id).then(np => {
      setP(np)
      if (kind !== 'gen_outline_md' || !np.outline_md) return
      api.getElements(id).then(els => {
        setElements(els)
        if (!els.length && section === 'overview' && !inChapter) navigate(`/project/${id}/elements`)
      }).catch(console.error)
    }).catch(console.error)
  }, [id, section, inChapter, navigate])
  useTaskDone(id, ['gen_project_info', 'gen_outline_md', 'gen_element_kinds'], onGenTaskDone)

  // 门禁兜底：无大纲时除总览外的分区（含直接敲 URL）一律拉回总览
  const locked = !!p && !p.outline_md
  useEffect(() => {
    if (locked && (section !== 'overview' || inChapter)) navigate(`/project/${id}/overview`, { replace: true })
  }, [locked, section, inChapter, id, navigate])

  // 记住本会话内在本项目停留的集号：下次从裸路径 /project/:id 进入时回到这一集（默认第一集）
  useEffect(() => {
    if (inChapter && seqParam != null) setLastSeq(id, seqParam)
  }, [inChapter, seqParam, id])

  const activeSeq = seqParam ?? chapters[0]?.seq ?? 1
  // 小说：尚无成书数据/接口——功能就绪前不显示小说 tab（接入后置为有内容判断）
  const hasNovel = false
  const chapter = inChapter ? chapters.find(c => c.seq === activeSeq) : undefined
  // 标题区：正文/视频阶段显示章节名，其余分区显示项目名
  const title = inChapter ? (chapter ? `第${chapter.seq}章 ${chapter.title}` : '') : (p?.title ?? '')

  return (
    <SidebarLayout sidebar={null}>
      <div className="board-main">
        <WorkbenchTabs id={id} activeSection={section} mode={inChapter ? chapterMode : undefined}
          activeSeq={activeSeq} hasNovel={hasNovel} locked={locked} title={title} setHeadSlot={setHeadSlot} />
        {!p ? (
          <div className="section-scroll">加载中…</div>
        ) : section === 'overview' ? (
          <OverviewSection id={id} p={p} setP={setP} memories={memories} onMemoriesChange={reloadMemories} />
        ) : section === 'novel' ? (
          <NovelSection />
        ) : section === 'elements' ? (
          <ElementsSection pid={id} p={p} setP={setP} elements={elements} onElementsChange={reloadElements} />
        ) : (
          <VideoSection pid={id} chapters={chapters} volumes={volumes} project={p} seq={activeSeq}
            mode={chapterMode} elements={elements} headSlot={headSlot} onChaptersChange={reloadChapters}
            onVolumesChange={reloadVolumes} onElementsChange={reloadElements} />
        )}
      </div>
    </SidebarLayout>
  )
}
