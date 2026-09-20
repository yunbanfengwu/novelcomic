import type { Capability, ToolParam } from '../../api'

function ParamTable({ title, rows }: { title: string; rows: Record<string, ToolParam> }) {
  const entries = Object.entries(rows || {})
  return (
    <div className="cap-params">
      <label>{title}</label>
      {!entries.length ? <div className="cap-none">无声明</div> : (
        <table>
          <tbody>
            {entries.map(([key, p]) => (
              <tr key={key}>
                <th>{key}{p.required && <b>*</b>}</th>
                <td><code>{p.type || 'string'}</code></td>
                <td>{p.desc || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** 单条能力的合同：入参 / 出参 / 副作用。这就是规划节点判断「该不该用它」的全部依据。 */
export function CapabilityDetail({ cap }: { cap: Capability }) {
  return (
    <div className="cap-detail">
      <div className="cap-detail-head">
        <h3>{cap.title}
          <span className={`cap-kind ${cap.kind}`}>{cap.kind === 'flow' ? '流程' : '工具'}</span>
          {cap.writes && <span className="cap-kind write">有副作用</span>}
          {cap.cardinality === 'many' && <span className="cap-kind many">多产物</span>}
        </h3>
        <code>{cap.id}{cap.version ? ` v${cap.version}` : ''}</code>
      </div>
      {cap.superseded_by && (
        <div className="cap-warn">已被 <code>{cap.superseded_by}</code> 取代，调用会自动转发</div>
      )}
      <p className={cap.description ? 'cap-desc' : 'cap-desc thin'}>
        {cap.description || '没写描述——模型选能力只看这段文字，务必补上「什么情况下用它」。'}
      </p>
      <ParamTable title="入参" rows={cap.inputs} />
      <ParamTable title="产出" rows={cap.outputs} />
      {cap.kind === 'flow' && (
        <div className="cap-cost">
          花钱节点 {cap.costly_nodes ?? 0} 个（出图 / 出视频 / 入队执行体）
        </div>
      )}
    </div>
  )
}
