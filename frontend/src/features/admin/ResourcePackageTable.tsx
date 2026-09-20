import type { ResourcePackage } from '../../api'

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(0))
/** 总量/余量都为 0 = 额度未登记（手动加的模型行），不等于「已用完」，不标红 */
const unknown = (r: ResourcePackage) => r.total <= 0 && r.remaining <= 0

/** 资源包表格（展示件）：一行 = 一个资源包/免费额度；余量为 0 的整行标红。 */
export function ResourcePackageTable({ rows, busy, onToModel, onTest, onDelete }: {
  rows: ResourcePackage[]
  busy: string | null
  onToModel: (r: ResourcePackage, activate: boolean) => void
  onTest: (r: ResourcePackage) => void
  onDelete: (r: ResourcePackage) => void
}) {
  return (
    <table className="rp-table">
      <thead>
        <tr>
          <th>厂商</th><th>模态</th><th>产品</th><th>配置名称</th><th>真实模型名</th><th>实例ID</th>
          <th>规格</th><th>总量</th><th>余量</th><th>购买时间</th><th>生效时间</th>
          <th>失效时间</th><th>服务主体</th><th className="rp-ops">操作</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.instance_id} className={r.remaining <= 0 && !unknown(r) ? 'rp-empty' : ''}>
            <td><span className={`tag v-${r.vendor}`}>{r.vendor_label}</span></td>
            <td><span className={`tag m-${r.modality}`}>{r.modality_label}</span></td>
            <td className="dim">{r.product}</td>
            <td><b>{r.config_name}</b></td>
            <td><code>{r.real_model_name}</code></td>
            <td className="dim rp-id">{r.instance_id}</td>
            <td className="dim">{r.spec} {r.spec_unit}</td>
            <td className="dim">{unknown(r) ? '—' : fmt(r.total)}</td>
            <td className={unknown(r) ? 'dim' : 'rp-remain'}>{unknown(r) ? '额度未登记' : fmt(r.remaining)}</td>
            <td className="dim">{r.purchased_at}</td>
            <td className="dim">{r.effective_at}</td>
            <td className="dim">{r.expires_at}</td>
            <td className="dim">{r.provider_entity}</td>
            <td className="rp-ops">
              <div className="btns">
                <button className="small ghost" title="用内置 Key 试" onClick={() => onTest(r)}>测试</button>
                <button className="small" disabled={busy === r.instance_id}
                  onClick={() => onToModel(r, false)}>插入模型管理</button>
                <button className="small ghost" disabled={busy === r.instance_id}
                  onClick={() => onToModel(r, true)}>设为默认</button>
                <button className="small ghost" onClick={() => onDelete(r)}>删除</button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
