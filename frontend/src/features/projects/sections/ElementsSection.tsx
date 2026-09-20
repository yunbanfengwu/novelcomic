import { useEffect, useRef, useState } from 'react'
import { api } from '../../../api'
import type { Element, Project } from '../../../api'
import { KIND_LABEL, KIND_META, groupByKind } from '../../../lib/kinds'
import { useLiveKinds } from '../../../lib/useTaskDone'
import { Icon } from '../../../components/Icon'
import { ElementPreview } from '../ElementPreview'
import { EraBar } from '../EraBar'
import { ProfileBatchBar } from '../ProfileBatchBar'
import { AddElementModal } from '../AddElementModal'
import { NameModal } from '../NameModal'
import { ElementsEmpty } from '../ElementsEmpty'
import { AssetLibrarySection } from './AssetLibrarySection'
import { MaterialsSection } from './MaterialsSection'

/** 素材库分区左栏的两个菜单项（点击在右侧预览区展示，取代核心要素详情）：
 * library=生成/素材库（项目内全部产物 + 找回项）；materials=参考资料（项目级知识库）。 */
type RightView = 'element' | 'library' | 'materials'

/** 核心要素分区：左侧分组列表（参考正文左栏，底部新增/生成）+ 右侧选中详情（角色含音色块）。
 * 渐进式引导：尚无要素且未判定要素类型 → 自动发 gen_element_kinds 后台任务
 * （AI 按剧情从知识库内置类型中挑选分组，写入 config.element_kinds）。 */
export function ElementsSection({ pid, p, setP, elements, onElementsChange }: {
  pid: number
  p: Project
  setP: (p: Project) => void
  elements: Element[]
  onElementsChange: () => void
}) {
  const [selId, setSelId] = useState<number | null>(null)
  const [rightView, setRightView] = useState<RightView>('element')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [addOpen, setAddOpen] = useState(false)
  const [catOpen, setCatOpen] = useState(false)
  const [gen, setGen] = useState(false)
  const elementKinds = p.config.element_kinds ?? []
  const kindsBusy = useLiveKinds(pid, ['gen_element_kinds']).size > 0
  const listRef = useRef<HTMLDivElement>(null)
  const pendingScroll = useRef(false)

  // 新增分类后分组已刷新（分类数变化）→ 自动滚到底部，露出刚建的空分组。
  // 直接在 effect 里滚（此时 DOM 已布局），不用 rAF——后台标签页 rAF 可能不触发
  useEffect(() => {
    if (!pendingScroll.current) return
    pendingScroll.current = false
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [elementKinds.length])

  const sel = elements.find(e => e.id === selId) ?? null
  useEffect(() => {
    if (selId == null && elements.length) setSelId(elements[0].id)
  }, [elements, selId])

  // 自动判定要素类型：有大纲、无要素、类型未判定才发（服务端幂等去重；失败不自动重发，
  // 空态里留手动「判定要素类型」按钮兜底）。完成由容器 SSE 刷新项目数据带入
  useEffect(() => {
    if (p.outline_md && !elements.length && !elementKinds.length)
      api.genElementKinds(pid).catch(console.error)
  }, [pid, p.outline_md, elements.length, elementKinds.length])

  // 按要求 AI 流式生成（一个还是多个由模型判断；留空=依目录生成全部）：弹框已关，生成在分区里跑，
  // 后端解析到一个要素落库一个并推送，前端逐个刷新——要素在列表里实时逐条长出；gen 标记驱动「生成中」提示
  const generate = async (requirement: string) => {
    setGen(true)
    try {
      await api.addElementsAIStream(pid, requirement, { onElement: () => onElementsChange() })
      onElementsChange()
    } catch (e) { alert(String(e)) }
    finally { setGen(false) }
  }

  // 新增分类：把一个空分组写进 config.element_kinds（生成一个不与现有冲突的 code），
  // 之后「新增要素」生成的要素可归入该类；空分类先占位展示（计数 0）
  const addCategory = async (label: string) => {
    const existing = new Set(elementKinds.map(k => k.code))
    let code = ''
    do { code = 'k_' + Math.random().toString(36).slice(2, 8) } while (existing.has(code))
    const next = [...elementKinds, { code, label }]
    try {
      await api.updateConfig(pid, { element_kinds: next })
      pendingScroll.current = true
      setP({ ...p, config: { ...p.config, element_kinds: next } })
    } catch (e) { alert(String(e)) }
  }

  // 空态：不显示左栏分组列表——类型判定中/已建分组/兜底三形态（见 ElementsEmpty）
  if (!elements.length) {
    return (
      <>
        <ElementsEmpty p={p} kindsBusy={kindsBusy} generating={gen}
          onGenerate={() => setAddOpen(true)}
          onRetryKinds={() => api.genElementKinds(pid).catch(e => alert(String(e)))} />
        {addOpen && <AddElementModal pid={pid} hasElements={false}
          onClose={() => setAddOpen(false)} onSubmit={generate} />}
      </>
    )
  }

  // 分组渲染顺序：先按已判定分类顺序（含新增的空分类，占位展示），再追加未归类的其它 kind
  const kindCodes = elementKinds.map(k => k.code)
  const grouped = new Map(groupByKind(elements, kindCodes))
  const orderedKinds = [...kindCodes, ...[...grouped.keys()].filter(k => !kindCodes.includes(k))]

  return (
    <div className="elements-split">
      <nav className="elements-list">
        <EraBar pid={pid} p={p} setP={setP} />
        {/* 菜单项（样式同总览二级菜单，一行一条）：点击在右侧预览区展示，取代核心要素详情 */}
        <div className="elem-menu">
          <button className={`subnav-item${rightView === 'library' ? ' active' : ''}`}
            onClick={() => setRightView('library')}>
            <span className="subnav-ico"><Icon name="folder" /></span><span>生成/素材库</span>
          </button>
          <button className={`subnav-item${rightView === 'materials' ? ' active' : ''}`}
            onClick={() => setRightView('materials')}>
            <span className="subnav-ico"><Icon name="clip" /></span><span>参考资料</span>
          </button>
        </div>
        <div className="cat-list" ref={listRef}>
          {orderedKinds.map(kind => {
            const items = grouped.get(kind) ?? []
            const isCollapsed = !!collapsed[kind]
            const label = KIND_META[kind]?.label ?? elementKinds.find(k => k.code === kind)?.label ?? kind
            return (
              <div key={kind} className="elem-group">
                <div className="group-head" onClick={() => setCollapsed(g => ({ ...g, [kind]: !g[kind] }))}>
                  <span className="group-caret">{isCollapsed ? '▸' : '▾'}</span>
                  <span className="group-label"><Icon name={KIND_META[kind]?.icon ?? 'puzzle'} /> {label}</span>
                  {kind === 'character' &&
                    <ProfileBatchBar pid={pid} elements={elements} onDone={onElementsChange} />}
                  <span className="group-count">{items.length}</span>
                </div>
                {!isCollapsed && !items.length && <div className="vol-empty">暂无要素</div>}
                {!isCollapsed && items.map(el => (
                  <div key={el.id} className={`chapter-row elem-row${rightView === 'element' && sel?.id === el.id ? ' active' : ''}`}
                    onClick={() => { setSelId(el.id); setRightView('element') }}>
                    {el.meta.sheet_url
                      ? <img className="elem-thumb" src={el.meta.sheet_url} alt={el.name} />
                      : <div className="chapter-seq">{(KIND_LABEL[el.kind] || el.kind).slice(0, 2)}</div>}
                    <div>
                      <div className="chapter-title">{el.name}</div>
                      <div className="dim">{el.brief}</div>
                    </div>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
        {/* 底部动作条（tab 样式，参考正文/视频）：前置文件夹=新增分类 + 新增要素（AI 生成） */}
        <div className="seg elem-foot">
          <button className="seg-btn cat-folder" onClick={() => setCatOpen(true)}
            title="新增素材分类" aria-label="新增分类">
            <Icon name="folderplus" />
          </button>
          <button className="seg-btn active cat-main" disabled={gen} onClick={() => setAddOpen(true)} title="新增素材设定（输入要求，AI 按要求生成）">
            {gen ? <><Icon name="spinner" spin /> 生成中…</> : <><Icon name="pen" /> 新增素材</>}
          </button>
        </div>
      </nav>
      <div className="elements-detail">
        {rightView === 'library'
          ? <AssetLibrarySection pid={pid}
              onSetCover={url => setP({ ...p, config: { ...p.config, cover_url: url } })} />
          : rightView === 'materials'
          ? <MaterialsSection />
          : sel
          ? <ElementPreview pid={pid} el={sel} onReload={onElementsChange} />
          : <div className="placeholder-pane">
              <div style={{ fontSize: 40 }}><Icon name="puzzle" /></div>
              <div>生成要素</div>
              <button className="placeholder-btn" onClick={() => setAddOpen(true)}>
                <Icon name="sparkles" /> AI 生成素材设定
              </button>
            </div>}
      </div>
      {addOpen && <AddElementModal pid={pid} hasElements={!!elements.length}
        onClose={() => setAddOpen(false)} onSubmit={generate}
        onAssetGenerated={() => setRightView('library')} />}
      {catOpen && <NameModal title="新增素材分类" label="分类名称" submitLabel="新建分类" icon="folderplus"
        placeholder="例如：关键道具、势力组织、地点场景…"
        onClose={() => setCatOpen(false)} onSubmit={addCategory} />}
    </div>
  )
}
