import { Modal } from '../../components/Modal'
import { Icon } from '../../components/Icon'
import { ModelTestOutput } from './ModelTestOutput'
import type { ModelTestResult, ProviderKeyPreset } from '../../api'
import {
  PROVIDERS, PURPOSES, PURPOSE_META, SPECIAL_HINT, SPECIAL_PURPOSES,
  noTestReason, testPlaceholder,
} from '../../lib/modelPresets'
import type { ModelEditing, ModelSuggestion } from '../../lib/modelPresets'

const isSpecial = (p: string) => (SPECIAL_PURPOSES as readonly string[]).includes(p)

/** 模型新增/编辑弹框（纯展示：状态与请求全在 ModelAdmin，弹框只回调）。 */
export function ModelEditorModal({ editing, keys, suggestions, saving, testing, error,
  testPrompt, testResult, onChange, onPurposeChange, onProviderChange, onApplySuggestion,
  onTestPrompt, testRefs, onTestRefs, onTest, onSave, onClose }: {
  editing: ModelEditing | null
  keys: ProviderKeyPreset[]
  suggestions: ModelSuggestion[]
  saving: boolean; testing: boolean; error: string
  testPrompt: string; testResult: ModelTestResult | null
  /** 图像编辑族测试必需：底图 URL（逗号/换行分隔，最多 3 张） */
  testRefs?: string; onTestRefs?: (v: string) => void
  onChange: (next: ModelEditing) => void
  onPurposeChange: (purpose: string) => void
  onProviderChange: (provider: string) => void
  onApplySuggestion: (model: string) => void
  onTestPrompt: (v: string) => void
  onTest: () => void; onSave: () => void; onClose: () => void
}) {
  const noTest = editing ? noTestReason(editing.purpose) : ''
  return (
    <Modal open={!!editing} onClose={() => !saving && !testing && onClose()}
      closeOnBackdrop={!saving && !testing} wide
      title={editing?.id ? `编辑模型 #${editing.id}` : '新增模型'}>
      {editing && <div className="model-editor">
        <div className="model-form-grid">
          <label><span>模型类型</span>
            <select value={editing.purpose} onChange={e => onPurposeChange(e.target.value)}>
              <optgroup label="生成链路">
                {PURPOSES.map(p => <option key={p} value={p}>{PURPOSE_META[p].label}</option>)}
              </optgroup>
              <optgroup label="专用挂档（不参与生成）">
                {SPECIAL_PURPOSES.map(p =>
                  <option key={p} value={p}>{PURPOSE_META[p].label}</option>)}
              </optgroup>
            </select>
            {isSpecial(editing.purpose) && <small className="dim">{SPECIAL_HINT}</small>}
          </label>
          <label><span>接口类型</span>
            <select value={editing.provider} onChange={e => onProviderChange(e.target.value)}>
              {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
          <label><span>显示名称</span>
            <input placeholder="例如：硅基流动 bge-m3" value={editing.name}
              onChange={e => onChange({ ...editing, name: e.target.value })} />
          </label>
          <label><span>候选模型</span>
            <select value="" onChange={e => onApplySuggestion(e.target.value)}>
              <option value="">选择预设（百炼/硅基流动）或资源包中的模型…</option>
              {suggestions.map((s, i) =>
                <option key={`${s.model}-${i}`} value={s.model}>{s.label} · {s.model}</option>)}
            </select>
          </label>
        </div>
        <label><span>Base URL</span>
          <input value={editing.base_url} onChange={e => onChange({ ...editing, base_url: e.target.value })} />
        </label>
        <label><span>模型 ID</span>
          <input value={editing.model_name} placeholder="提供商使用的准确模型 ID"
            onChange={e => onChange({ ...editing, model_name: e.target.value })} />
        </label>
        <div className="model-form-grid">
          <label><span>API Key 来源</span>
            <select value={editing.key_ref}
              onChange={e => onChange({ ...editing, key_ref: e.target.value, api_key: '' })}>
              <option value="">手动输入 Key</option>
              {keys.map(k =>
                <option key={k.ref} value={k.ref}>{k.label}（{k.masked}）</option>)}
            </select>
          </label>
          {!editing.key_ref && <label><span>API Key</span>
            <input type="password" placeholder={editing.id ? '留空=沿用原 Key' : '输入 API Key'}
              value={editing.api_key} onChange={e => onChange({ ...editing, api_key: e.target.value })} />
          </label>}
          {(editing.purpose === 'image' || editing.purpose === 'video') && <label><span>参考图上限</span>
            <input type="number" min={0} placeholder="留空=提供商默认"
              value={editing.max_refs ?? ''}
              onChange={e => onChange({ ...editing, max_refs: e.target.value ? Number(e.target.value) : null })} />
          </label>}
        </div>

        <section className="model-test">
          <div className="model-test-head">
            <div><b>连接与输出测试</b><div className="dim">使用上方当前配置真实调用，不会自动保存。</div></div>
            <button className="small" disabled={testing || !!noTest} onClick={onTest}>
              <Icon name={testing ? 'spinner' : 'flask'} spin={testing} /> {testing ? '测试中…' : '开始测试'}
            </button>
          </div>
          {noTest
            ? <div className="dim">{noTest}</div>
            : <textarea rows={3} value={testPrompt} placeholder={testPlaceholder(editing.purpose)}
                onChange={e => onTestPrompt(e.target.value)} />}
          {/* 图像编辑族必须带底图（qwen-image-edit 等 1~3 张）；其余模态不显示此输入 */}
          {editing.purpose === 'image' && !noTest && (
            <textarea rows={2} value={testRefs ?? ''}
              placeholder="参考图 URL（图像编辑类模型必填底图，如 qwen-image-edit；多张用逗号分隔，最多 3 张）"
              onChange={e => onTestRefs?.(e.target.value)} />
          )}
          {testResult && <ModelTestOutput result={testResult} />}
        </section>

        {error && <div className="model-error">{error}</div>}
        <div className="modal-actions btns">
          <button className="ghost" disabled={saving || testing} onClick={onClose}>取消</button>
          <button disabled={saving || testing} onClick={onSave}>
            <Icon name={saving ? 'spinner' : 'save'} spin={saving} /> {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>}
    </Modal>
  )
}
