import type { ReactNode } from 'react'
import type { ModelProfile } from '../../api'

/** 模型行：按类型/按功能两个视图共用同一套显示，动作按钮由视图各自传入。 */
export function ModelRow({ m, seq, isDefault, actions }: {
  m: Pick<ModelProfile, 'name' | 'provider' | 'model_name'> &
    Partial<Pick<ModelProfile, 'base_url' | 'api_key_masked' | 'max_refs' | 'is_active'>>
  seq?: number; isDefault?: boolean; actions?: ReactNode
}) {
  const detail = [
    m.model_name, m.base_url,
    m.api_key_masked !== undefined ? `key: ${m.api_key_masked || '（未配置）'}` : '',
  ].filter(Boolean).join(' ｜ ')
  return (
    <div className="kb-row">
      <div>
        {seq != null && <span className="fma-seq">{seq}</span>} <b>{m.name}</b>
        {m.is_active && <span className="tag gold">✓ 当前使用</span>}
        {isDefault && <span className="tag gold">默认</span>}
        <span className="tag">{m.provider}</span>
        {m.max_refs ? <span className="tag">参考图≤{m.max_refs}</span> : null}
        <div className="dim">{detail}</div>
      </div>
      {actions && <div className="btns">{actions}</div>}
    </div>
  )
}
