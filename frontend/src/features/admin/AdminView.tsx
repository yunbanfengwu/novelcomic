import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Shell } from '../../components/Shell'
import { SubNav } from '../../components/SubNav'
import { Icon } from '../../components/Icon'
import { KnowledgeBase } from './KnowledgeBase'
import { CharacterLibrary } from './CharacterLibrary'
import { VoiceAdmin } from './VoiceAdmin'
import { ModelManagement } from './ModelManagement'
import { GenLogPanel } from './GenLogPanel'
import { LearningMaterials } from './LearningMaterials'
import { SystemConfig } from './SystemConfig'
import { TagManager } from './TagManager'
import { TapflowPage } from '../tapflow/TapflowPage'
import { SkillsAdmin } from './SkillsAdmin'
import { AgentsAdmin } from './AgentsAdmin'
import { TestAdmin } from './TestAdmin'
import { ToolsAdmin } from './ToolsAdmin'
import { CapabilityCatalog } from './CapabilityCatalog'
import { AssetTypesAdmin } from './AssetTypesAdmin'
import './admin.css'

// 子菜单 = URL 的 :tab 段（/admin/kb、/admin/tapflow…），可直接分享/刷新/前进后退
const TAB_KEYS = ['kb', 'chars', 'voice', 'agents', 'skill', 'tools', 'caps', 'tapflow',
  'assettypes', 'tags', 'modelmgmt', 'genlogs', 'test', 'learning', 'sysconfig'] as const
type TabKey = typeof TAB_KEYS[number]

// 改名遗留：tapnow / tapnow-flow 时期的旧 tab key，别让老书签落回知识库。
// `wf` 是已下线的「智能体编排」（2026-08-01 删除），老书签一并落到 tapflow。
// 注意这里是历史字面量，改名脚本不该再动它
const LEGACY_TABS: Record<string, TabKey> = {
  tapnowflow: 'tapflow', tapnow: 'tapflow', wf: 'tapflow',
  // 原独立菜单「模型配置/资源包/功能配置」并入模型管理（页内左栏二级菜单）
  models: 'modelmgmt', respkg: 'modelmgmt', modelfeatures: 'modelmgmt' }
// 旧独立页 key → 模型管理内的子页（重定向时保住落点；功能配置已并入模型配置）
const LEGACY_SUB: Record<string, string> = {
  models: 'models', respkg: 'respkg', modelfeatures: 'models' }

/**
 * 系统管理容器：知识库（统一文件夹树：画风库/文风库/角色库/音色库/提示词块/知识+自定义）
 * / 技能（数字员工能力配置，不属于知识库）/ 模型配置 / 资源包剩余 / 生成日志 / 学习资料。
 */
export function AdminView() {
  const navigate = useNavigate()
  const params = useParams()
  // 未知 tab（旧链接/手输）兜底到知识库，不做重定向，避免多压一条历史
  const legacy = params.tab ? LEGACY_TABS[params.tab] : undefined
  const tab: TabKey = TAB_KEYS.includes(params.tab as TabKey) ? params.tab as TabKey : legacy ?? 'kb'
  // 旧 key 换成新 URL：replace 不压历史，后退键仍回到上一个页面
  const legacySub = params.tab ? LEGACY_SUB[params.tab] : undefined
  useEffect(() => {
    if (legacy) navigate(`/admin/${legacy}${legacySub ? `/${legacySub}` : ''}`, { replace: true })
  }, [legacy, legacySub, navigate])

  return (
    <Shell rail="admin" onHome={() => navigate('/')} onAdmin={() => navigate(-1)}>
      <SubNav
        title={<div className="subnav-title"><Icon name="gear" /> 系统管理</div>}
        items={[
          { key: 'kb', icon: <Icon name="book" />, label: '知识库' },
          { key: 'chars', icon: <Icon name="user" />, label: '角色库' },
          { key: 'voice', icon: <Icon name="mic" />, label: '音色库' },
          { key: 'agents', icon: <Icon name="users" />, label: '数字员工' },
          { key: 'skill', icon: <Icon name="tools" />, label: 'Skills' },
          { key: 'tools', icon: <Icon name="console" />, label: '工具' },
          { key: 'caps', icon: <Icon name="puzzle" />, label: '能力' },
          { key: 'tapflow', icon: <Icon name="layers" />, label: 'tapflow' },
          { key: 'assettypes', icon: <Icon name="palette" />, label: '资产类型' },
          { key: 'tags', icon: <Icon name="tag" />, label: '标签' },
          { key: 'modelmgmt', icon: <Icon name="puzzle" />, label: '模型管理' },
          { key: 'genlogs', icon: <Icon name="clipboard" />, label: '生成日志' },
          { key: 'test', icon: <Icon name="flask" />, label: '测试' },
          { key: 'learning', icon: <Icon name="text" />, label: '学习资料' },
          { key: 'sysconfig', icon: <Icon name="monitor" />, label: '系统配置' },
        ]}
        active={tab} onSelect={k => navigate(`/admin/${k}`)} />
      <div className="board-main">
        {tab === 'kb' || tab === 'chars' || tab === 'voice' ? (
          <div className="card-body scroll">
            {tab === 'kb' && <KnowledgeBase />}
            {tab === 'chars' && <CharacterLibrary />}
            {tab === 'voice' && <VoiceAdmin />}
          </div>
        ) : (
          <div className="card-body adm-fill">
            {tab === 'tags' && <TagManager />}
            {tab === 'agents' && <AgentsAdmin />}
            {tab === 'skill' && <SkillsAdmin />}
            {tab === 'tools' && <ToolsAdmin />}
            {tab === 'caps' && <CapabilityCatalog />}
            {tab === 'tapflow' && <TapflowPage />}
            {tab === 'assettypes' && <AssetTypesAdmin />}
            {tab === 'modelmgmt' && <ModelManagement sub={params.sub} />}
            {tab === 'genlogs' && <GenLogPanel />}
            {tab === 'test' && <TestAdmin />}
            {tab === 'learning' && <LearningMaterials />}
            {tab === 'sysconfig' && <SystemConfig />}
          </div>
        )}
      </div>
    </Shell>
  )
}
