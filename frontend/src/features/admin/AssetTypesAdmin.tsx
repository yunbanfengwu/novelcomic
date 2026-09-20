import { useEffect, useState } from 'react'
import { api, type AssetTypeInfo } from '../../api'
import { Icon } from '../../components/Icon'

const TYPES = [
  ['project.character', '项目角色', 'content_elements · character', '查询 / 设定图 / 参考图'],
  ['project.scene', '项目场景', 'content_elements · scene', '查询 / 变体设定图 / 参考图'],
  ['project.prop', '项目道具', 'content_elements · prop', '查询 / 设定图 / 参考图'],
  ['project.shot', '项目分镜', 'content_nodes · shot', '查询 / 分镜脚本 / 连续性'],
  ['project.keyframe', '项目关键帧', 'project.shot 上的媒体产物', '生成 / 关联 / 溯源'],
  ['common.image', '通用图片', 'content_attachments', '上传 / 生成 / 引用'],
  ['common.video', '通用视频', 'content_attachments', '上传 / 生成 / 引用'],
  ['demo.color', '颜色资产（演示）', '前端假数据', '读取 / 核心要素 / 生成色板'],
] as const

/** 仅展示内置 registry 的前端概念模型；尚未接入后端。 */
export function AssetTypesAdmin() {
  const [types, setTypes] = useState<AssetTypeInfo[] | null>(null)
  useEffect(() => { api.assetTypes().then(setTypes).catch(() => setTypes([])) }, [])
  const rows = types === null ? TYPES.map(([code, name, storage, abilities]) => ({ code, name, storage, abilities, mediaKind: 'data', tags: [] as string[] }))
    : types.map(item => ({ code: item.code, name: item.name, storage: item.storage,
      abilities: item.operations.join(' / ') + (item.async_default ? ' / 异步' : ''),
      mediaKind: item.media_kind, tags: item.tags }))
  return (
    <div className="adm-panel">
      <header className="adm-head">
        <h2><Icon name="palette" /> 资产类型</h2>
        <span className="dim">内置注册表 · 只读演示</span>
      </header>
      <div className="adm-scroll asset-types-demo">
        <div className="asset-types-note">
          类型由后端受控注册；这里展示未来 Tapflow 可使用的身份、存储映射和能力，不提供编辑入口。
        </div>
        <div className="asset-types-grid">
          {rows.map(({ code, name, storage, abilities, mediaKind, tags }) => (
            <article className="asset-type-card" key={code}>
              <div className="asset-type-top"><Icon name={code === 'demo.color' ? 'palette' : 'cube'} /><b>{name}</b><span>内置</span></div>
              <code>{code}</code>
              <div className="asset-type-tags"><span className="asset-media-kind">{mediaKind}</span>{tags.map(tag => <span key={tag}>{tag}</span>)}</div>
              <div><small>存储映射</small><p>{storage}</p></div>
              <div><small>可用能力</small><p>{abilities}</p></div>
            </article>
          ))}
        </div>
        <section className="asset-types-flow">
          <b>运行时规则</b>
          <div>资产类型 + 资产实例 + 操作 → 自动解析查询器、默认工作流、异步策略与产物关联。</div>
          <div className="asset-types-example"><code>demo.color + 北境主色 + generate_palette</code><span>→</span><code>颜色资产卡 / color.palette</code></div>
        </section>
      </div>
    </div>
  )
}
