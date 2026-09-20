import { useNavigate } from 'react-router-dom'
import { SubNav } from '../../components/SubNav'
import { Icon } from '../../components/Icon'
import { ModelAdmin } from './ModelAdmin'
import { VendorAdmin } from './VendorAdmin'
import { ResourcePackages } from './ResourcePackages'

const SUB_KEYS = ['models', 'vendors', 'respkg'] as const
type SubKey = typeof SUB_KEYS[number]

/** 模型管理：页面分左右两栏——左栏是 模型配置/模型厂商/资源包 二级菜单
 *  （位于系统管理主菜单与内容之间），右栏是选中的子页。子页即 URL 的 :sub 段。
 *  功能配置已并入模型配置（按类型/按功能双视图）。 */
export function ModelManagement({ sub }: { sub?: string }) {
  const navigate = useNavigate()
  const cur: SubKey = SUB_KEYS.includes(sub as SubKey) ? sub as SubKey : 'models'
  return (
    <div className="mm-split">
      <SubNav
        title={<div className="subnav-title"><Icon name="puzzle" /> 模型管理</div>}
        items={[
          { key: 'models', icon: <Icon name="robot" />, label: '模型配置' },
          { key: 'vendors', icon: <Icon name="users" />, label: '模型厂商' },
          { key: 'respkg', icon: <Icon name="blocks" />, label: '资源包' },
        ]}
        active={cur} onSelect={k => navigate(`/admin/modelmgmt/${k}`)} />
      <div className="mm-content">
        {cur === 'models' && <ModelAdmin />}
        {cur === 'vendors' && <VendorAdmin />}
        {cur === 'respkg' && <ResourcePackages />}
      </div>
    </div>
  )
}
