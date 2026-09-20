import { useState } from 'react'
import { api } from '../../api'
import type { ModelTestResult, ResourcePackage } from '../../api'
import { Icon } from '../../components/Icon'
import { Modal } from '../../components/Modal'
import { ModelTestOutput } from './ModelTestOutput'
import { noTestReason, testPlaceholder } from '../../lib/modelPresets'

/** 资源包行内测试：用系统内置的厂商 Key 直接调这个模型，不必先插入模型管理。
 * purpose/凭据由后端按厂商+模态派生（与「插入模型管理」同源），回显复用模型配置那份。 */
export function ResourcePackageTest({ pkg, onClose }: {
  pkg: ResourcePackage | null
  onClose: () => void
}) {
  const [prompt, setPrompt] = useState('')
  const [result, setResult] = useState<ModelTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState('')

  const close = () => { if (testing) return; setPrompt(''); setResult(null); setError(''); onClose() }
  const run = async () => {
    if (!pkg || !prompt.trim()) { setError('请输入测试内容'); return }
    setTesting(true); setResult(null); setError('')
    try { setResult(await api.testResourcePackage(pkg.instance_id, prompt.trim())) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setTesting(false) }
  }

  const purpose = pkg?.modality === 'audio' ? 'tts' : (pkg?.modality || 'text')
  const noTest = noTestReason(purpose)
  return (
    <Modal open={!!pkg} onClose={close} closeOnBackdrop={!testing} wide
      title={`测试模型 · ${pkg?.config_name || ''}`}>
      {pkg && <div className="model-editor">
        <div className="dim">
          {pkg.vendor_label} ｜ 模型 ID <code>{pkg.real_model_name}</code> ｜ {pkg.modality_label}
          ｜ 使用系统内置的{pkg.vendor_label} Key，真实调用会消耗该资源包余量。
        </div>
        <section className="model-test">
          <div className="model-test-head">
            <div><b>连接与输出测试</b><div className="dim">不改动模型管理里的任何配置。</div></div>
            <button className="small" disabled={testing || !!noTest} onClick={run}>
              <Icon name={testing ? 'spinner' : 'flask'} spin={testing} /> {testing ? '测试中…' : '开始测试'}
            </button>
          </div>
          {noTest
            ? <div className="dim">{noTest}</div>
            : <textarea rows={3} value={prompt} placeholder={testPlaceholder(purpose)}
                onChange={e => setPrompt(e.target.value)} />}
          {result && <ModelTestOutput result={result} />}
        </section>
        {error && <div className="model-error">{error}</div>}
        <div className="modal-actions btns">
          <button className="ghost" disabled={testing} onClick={close}>关闭</button>
        </div>
      </div>}
    </Modal>
  )
}
