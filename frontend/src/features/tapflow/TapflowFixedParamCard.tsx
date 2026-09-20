import { useEffect, useRef, useState } from 'react'
import {
  api, type AssetTypeInfo, type CtxElement, type CtxNode, type Project,
  type SmartInputSelection,
} from '../../api'
import { Icon } from '../../components/Icon'
import type { TapParam } from '../../lib/tapflowData'

const ELEMENT_KIND_LABEL: Record<string, string> = {
  scene: '场景', character: '角色', prop: '道具',
}

const friendlyId = (value: string | undefined) => Number.parseInt(value ?? '', 10) || 0

export function TapflowFixedParamCard({
  params, workflowSlug, workflowVersion, disabled = false, onParam, onParams, onLabels,
}: {
  params: TapParam[]
  workflowSlug?: string
  workflowVersion?: number
  disabled?: boolean
  onParam: (key: string, value: string) => void
  onParams?: (values: Record<string, string>) => void
  onLabels?: (labels: Record<string, string>) => void
}) {
  const projectParam = params.find(param => param.ctx === 'project_id' || param.k === 'project_id')
  const assetParam = params.find(param => param.k === 'asset_type')
  const targetParam = params.find(param => param.ctx === 'target_ref' || param.k === 'target_ref')
  const materialRefParam = params.find(param => param.k === 'material_ref')
  const materialKindParam = params.find(param => param.k === 'material_kind')
  const allowedTypes = assetParam?.allowedValues ?? []

  const [projects, setProjects] = useState<Project[]>([])
  const [assetTypes, setAssetTypes] = useState<AssetTypeInfo[]>([])
  const [nodes, setNodes] = useState<CtxNode[]>([])
  const [elements, setElements] = useState<CtxElement[]>([])
  const [projectId, setProjectId] = useState(() => friendlyId(projectParam?.v))
  const [assetType, setAssetType] = useState(assetParam?.v ?? '')
  const [volumeId, setVolumeId] = useState(0)
  const [chapterId, setChapterId] = useState(0)
  const [shotId, setShotId] = useState(0)
  const [materialKind, setMaterialKind] = useState(materialKindParam?.v ?? '')
  const [materialId, setMaterialId] = useState(0)
  const paramsRef = useRef(params)
  const resolveRevision = useRef(0)
  const lastMapped = useRef<Record<string, string>>({})
  paramsRef.current = params

  const selectableTypes = allowedTypes.length
    ? assetTypes.filter(item => allowedTypes.includes(item.code)) : assetTypes
  const selectedType = assetTypes.find(item => item.code === assetType)
  const volumes = nodes.filter(node => node.kind === 'volume')
  const chapters = nodes.filter(node => node.kind === 'chapter' && (!volumeId || node.parent_id === volumeId))
  const shots = nodes.filter(node => node.kind === 'shot' && (!chapterId || node.parent_id === chapterId))
  const materials = elements.filter(element => selectedType?.target_ref_kind !== 'element'
    || !selectedType.target_content_kind || element.kind === selectedType.target_content_kind)
  const materialKinds = [...new Set(materials.map(element => element.kind))]
  const filteredMaterials = materials.filter(element => !materialKind || element.kind === materialKind)

  const smartSelection = (overrides: Partial<SmartInputSelection> = {}): SmartInputSelection => ({
    project_id: projectId || undefined,
    asset_type: assetType || undefined,
    volume_id: volumeId || undefined,
    chapter_id: chapterId || undefined,
    shot_id: shotId || undefined,
    material_kind: materialKind || undefined,
    material_ref: materialId ? `element:${materialId}` : undefined,
    ...overrides,
  })

  const resolveAndApply = (selection: SmartInputSelection) => {
    if (!workflowSlug) return
    const revision = ++resolveRevision.current
    void api.resolveSmartInputs(workflowSlug, workflowVersion, selection).then(result => {
      if (revision !== resolveRevision.current) return
      onLabels?.(result.labels)
      const current = paramsRef.current
      const values: Record<string, string> = { ...result.inputs }
      // Newer backends expose the canonical `material_kind` input. Older
      // workflow schemas only have `filters`; keep those deployments working
      // by carrying the same selection through the legacy filter contract.
      const selectedKind = selection.material_kind?.trim()
      if (selectedKind && !('material_kind' in values)
        && current.some(param => param.k === 'material_kind')) {
        values.material_kind = selectedKind
      }
      if (selectedKind && !current.some(param => param.k === 'material_kind')) {
        const filtersParam = current.find(param => param.k === 'filters')
        if (filtersParam) {
          let filters: Record<string, unknown> = {}
          const raw = values.filters ?? filtersParam.v
          if (typeof raw === 'string' && raw.trim()) {
            try {
              const parsed = JSON.parse(raw)
              if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                filters = parsed as Record<string, unknown>
              }
            } catch { /* keep an invalid legacy value from blocking selection */ }
          }
          values.filters = JSON.stringify({ ...filters, kinds: [selectedKind] })
        }
      }
      for (const [key, previous] of Object.entries(lastMapped.current)) {
        if (key in values) continue
        const actual = current.find(param => param.k === key)
        if (actual?.v === previous) values[key] = ''
      }
      const matched = Object.fromEntries(Object.entries(values)
        .filter(([key]) => current.some(param => param.k === key)))
      lastMapped.current = Object.fromEntries(
        Object.entries(values).filter(([, value]) => value !== ''))
      if (!Object.keys(matched).length) return
      if (onParams) onParams(matched)
      else Object.entries(matched).forEach(([key, value]) => onParam(key, value))
    }).catch(() => { /* 无法规范反查时保留实际参数，用户仍可手动填写 */ })
  }

  const ancestors = (node: CtxNode) => {
    const result: CtxNode[] = []
    const seen = new Set<number>()
    let parent = node.parent_id ? nodes.find(item => item.id === node.parent_id) : undefined
    while (parent && !seen.has(parent.id)) {
      seen.add(parent.id)
      result.push(parent)
      parent = parent.parent_id ? nodes.find(item => item.id === parent!.parent_id) : undefined
    }
    return result
  }

  useEffect(() => {
    void Promise.all([api.listProjects(), api.assetTypes()]).then(([projectRows, typeRows]) => {
      setProjects(projectRows)
      setAssetTypes(typeRows)
    }).catch(() => { setProjects([]); setAssetTypes([]) })
  }, [])

  useEffect(() => {
    if (!workflowSlug || !onLabels) return
    let active = true
    void api.resolveSmartInputs(workflowSlug, workflowVersion, {}).then(result => {
      if (active) onLabels(result.labels)
    }).catch(() => { /* 中文名回查失败不影响实际参数编辑 */ })
    return () => { active = false }
  }, [workflowSlug, workflowVersion, onLabels])

  useEffect(() => {
    if (!projectId) { setNodes([]); setElements([]); return }
    let active = true
    void api.agentCtxNodes(projectId).then(data => {
      if (!active) return
      setNodes(data.nodes)
      setElements(data.elements)
    }).catch(() => { if (active) { setNodes([]); setElements([]) } })
    return () => { active = false }
  }, [projectId])

  useEffect(() => {
    const actual = friendlyId(projectParam?.v)
    if (actual !== projectId) setProjectId(actual)
  }, [projectParam?.v]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if ((assetParam?.v ?? '') !== assetType) setAssetType(assetParam?.v ?? '')
  }, [assetParam?.v]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (materialKindParam && materialKindParam.v !== materialKind) {
      setMaterialKind(materialKindParam.v)
    }
  }, [materialKindParam?.v]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (assetType || allowedTypes.length !== 1) return
    const code = allowedTypes[0]
    setAssetType(code)
    resolveAndApply(smartSelection({ asset_type: code }))
  }, [allowedTypes, assetType]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const actualVolume = params.find(param => param.ctx === 'volume_id')
    const actualChapter = params.find(param => param.ctx === 'chapter_id')
    const actualShot = params.find(param => param.ctx === 'shot_id')
    if (actualVolume) setVolumeId(friendlyId(actualVolume.v))
    if (actualChapter) setChapterId(friendlyId(actualChapter.v))
    if (actualShot) setShotId(friendlyId(actualShot.v))
  }, [params])

  useEffect(() => {
    if (!nodes.length && !elements.length) return
    const ref = (materialRefParam?.v || targetParam?.v)?.split(' · ', 1)[0] ?? ''
    const [kind, rawId] = ref.split(':', 2)
    const id = Number.parseInt(rawId ?? '', 10) || 0
    if (kind === 'content_node' && id) {
      const node = nodes.find(item => item.id === id)
      if (!node) return
      const chain = ancestors(node)
      if (node.kind === 'shot') setShotId(node.id)
      if (node.kind === 'chapter') setChapterId(node.id)
      const chapter = chain.find(item => item.kind === 'chapter')
      const volume = chain.find(item => item.kind === 'volume')
      if (chapter) setChapterId(chapter.id)
      if (volume) setVolumeId(volume.id)
    } else if (kind === 'element' && elements.some(item => item.id === id)) {
      const material = elements.find(item => item.id === id)
      setMaterialId(id)
      if (material) setMaterialKind(material.kind)
    }
  }, [nodes, elements, materialRefParam?.v, targetParam?.v]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="tap-fixed-params tap-insp-part" aria-label="智能参数">
      <header className="tap-fixed-head">
        <div className="tap-fixed-title"><Icon name="sparkles" />智能参数</div>
      </header>

      <div className="tap-fixed-field">
        <label className="tap-fixed-label" htmlFor="tap-fixed-project">项目</label>
        <select id="tap-fixed-project" className="tap-insp-input tap-fixed-select"
          value={projectId || ''} disabled={disabled}
          onChange={event => {
            const id = Number(event.target.value) || 0
            setProjectId(id); setVolumeId(0); setChapterId(0); setShotId(0)
            setMaterialKind(''); setMaterialId(0)
            resolveAndApply(smartSelection({
              project_id: id || undefined,
              volume_id: undefined, chapter_id: undefined, shot_id: undefined,
              material_kind: undefined, material_ref: undefined,
            }))
          }}>
          <option value="">未选择</option>
          {!!projectId && !projects.some(item => item.id === projectId) && (
            <option value={projectId}>{projectParam?.v || projectId}</option>
          )}
          {projects.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
      </div>

      <div className="tap-fixed-field">
        <label className="tap-fixed-label" htmlFor="tap-fixed-asset-type">资产类型</label>
        <select id="tap-fixed-asset-type" className="tap-insp-input tap-fixed-select"
          value={assetType} disabled={disabled}
          onChange={event => {
            const code = event.target.value
            setAssetType(code)
            setMaterialKind(''); setMaterialId(0)
            resolveAndApply(smartSelection({
              asset_type: code || undefined, material_kind: undefined, material_ref: undefined,
            }))
          }}>
          <option value="">未选择</option>
          {!!assetType && !selectableTypes.some(item => item.code === assetType) && (
            <option value={assetType}>{assetType}</option>
          )}
          {selectableTypes.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select>
      </div>

      <div className="tap-fixed-field">
        <label className="tap-fixed-label" htmlFor="tap-fixed-volume">剧集</label>
        <div className="tap-fixed-cascade">
          <select id="tap-fixed-volume" aria-label="卷" className="tap-insp-input tap-fixed-select"
            value={volumeId || ''} disabled={disabled || !projectId}
            onChange={event => {
              const id = Number(event.target.value) || 0
              setVolumeId(id); setChapterId(0); setShotId(0)
              resolveAndApply(smartSelection({
                volume_id: id || undefined, chapter_id: undefined, shot_id: undefined,
              }))
            }}>
            <option value="">卷（未选择）</option>
            {volumes.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
          <span className="tap-fixed-divider">/</span>
          <select aria-label="章" className="tap-insp-input tap-fixed-select"
            value={chapterId || ''} disabled={disabled || !projectId}
            onChange={event => {
              const id = Number(event.target.value) || 0
              setChapterId(id); setShotId(0)
              resolveAndApply(smartSelection({ chapter_id: id || undefined, shot_id: undefined }))
            }}>
            <option value="">章（未选择）</option>
            {chapters.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
        </div>
      </div>

      <div className="tap-fixed-field">
        <label className="tap-fixed-label" htmlFor="tap-fixed-shot">分镜</label>
        <select id="tap-fixed-shot" className="tap-insp-input tap-fixed-select"
          value={shotId || ''} disabled={disabled || !projectId}
          onChange={event => {
            const id = Number(event.target.value) || 0
            const shot = shots.find(item => item.id === id)
            const chapter = shot ? nodes.find(item => item.id === shot.parent_id) : undefined
            const volume = chapter ? ancestors(chapter).find(item => item.kind === 'volume') : undefined
            setShotId(id)
            if (chapter) setChapterId(chapter.id)
            if (volume) setVolumeId(volume.id)
            resolveAndApply(smartSelection({
              volume_id: volume?.id || volumeId || undefined,
              chapter_id: chapter?.id || chapterId || undefined,
              shot_id: id || undefined,
            }))
          }}>
          <option value="">未选择</option>
          {shots.map(item => {
            const chapter = nodes.find(node => node.id === item.parent_id)
            return <option key={item.id} value={item.id}>
              {chapter ? `${chapter.title} / ` : ''}{item.title}
            </option>
          })}
        </select>
      </div>

      <div className="tap-fixed-field">
        <label className="tap-fixed-label" htmlFor="tap-fixed-material-kind">素材</label>
        <div className="tap-fixed-cascade">
          <select id="tap-fixed-material-kind" aria-label="素材类型"
            className="tap-insp-input tap-fixed-select"
            value={materialKind} disabled={disabled || !projectId}
            onChange={event => {
              const kind = event.target.value
              setMaterialKind(kind); setMaterialId(0)
              resolveAndApply(smartSelection({
                material_kind: kind || undefined, material_ref: undefined,
              }))
            }}>
            <option value="">类型（未选择）</option>
            {!!materialKind && !materialKinds.includes(materialKind) && (
              <option value={materialKind}>{ELEMENT_KIND_LABEL[materialKind] ?? materialKind}</option>
            )}
            {materialKinds.map(kind => <option key={kind} value={kind}>
              {ELEMENT_KIND_LABEL[kind] ?? kind}
            </option>)}
          </select>
          <span className="tap-fixed-divider">/</span>
          <select id="tap-fixed-material" aria-label="素材" className="tap-insp-input tap-fixed-select"
            value={materialId || ''} disabled={disabled || !projectId}
            onChange={event => {
              const id = Number(event.target.value) || 0
              const material = materials.find(item => item.id === id)
              setMaterialId(id)
              if (material) setMaterialKind(material.kind)
              resolveAndApply(smartSelection({
                material_kind: material?.kind || materialKind || undefined,
                material_ref: id ? `element:${id}` : undefined,
              }))
            }}>
            <option value="">素材（未选择）</option>
            {filteredMaterials.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
      </div>
    </section>
  )
}
