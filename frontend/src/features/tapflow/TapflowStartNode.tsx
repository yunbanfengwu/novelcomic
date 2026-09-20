import { TAP_NO_VOLUME, TAP_OVERALL_KEY, type TapNode } from '../../lib/tapflowData'
import { TapflowProjectCard } from './TapflowProjectCard'

/**
 * 开始节点的卡内正文。**两态同一套骨架**——都是项目设定卡（画风示意图 / 比例 /
 * 真人虚拟 / 主线 / 文风），右列排入参，编排时看到的就是运行时的样子，位置不跳：
 *
 * - **编排态**＝项目无关的模板：设定卡整卡走占位态（请选择项目 / 请选择画风 /
 *   选择比例 / 请输入整体设定），右列列入参声明（参数名 + 类型），没有值；
 * - **运行态**＝带上下文：设定卡填真项目，右列是各入参的实际值。
 */
export function TapflowStartNode({ node, mode }: {
  node: TapNode
  mode: 'edit' | 'run'
}) {
  const params = node.params ?? []
  // 项目那一项由设定卡自己表达（卡头就是项目名），参数表里不再重复列一遍。
  // 入参排进设定卡的右列（真人/虚拟下面）——它们和画风示意图是并排的两栏，
  // 摆到卡底下会在示意图左下留一大块空白
  // 「整体设定」不进右列的参数表：没选项目时它占卡片底部整幅（那本来是故事线/文风的位置）
  const rest = params.filter(p => p.ctx !== 'project_id' && p.k !== TAP_OVERALL_KEY)
  const overall = params.find(p => p.k === TAP_OVERALL_KEY)?.v
  return (
    <div className="tap-start-body">
      <TapflowProjectCard
        // 编排是项目无关模板：即便节点上挂着上次运行留下的项目，编排态也只给占位骨架
        info={mode === 'run' ? node.project : null}
        overall={mode === 'run' ? overall : undefined}
        aside={!params.length
          ? mode === 'edit' && <div className="tap-param-empty">尚未声明入参</div>
          : !!rest.length && (
            <div className="tap-param-group">
              {rest.map(p => (
                <div key={p.k}
                  className={'tap-param-row' + (mode === 'edit' ? ' decl' : '')
                    + (p.type === 'ctx' ? ' ctx' : '')}>
                  {(mode === 'edit' || p.type !== 'ctx') && (
                    <span className="k">{p.label || p.k}{p.required && <i>*</i>}</span>
                  )}
                  {mode === 'edit' ? (
                    <span className="t">
                      {p.type === 'ctx' ? '上下文' : p.type === 'int' ? '数字' : '文本'}
                    </span>
                  ) : (
                    <span className={'v' + (p.v ? '' : ' empty')}>
                      {p.v || (p.ctx === 'volume_id' ? TAP_NO_VOLUME
                        : p.type === 'ctx' ? `请选择${p.label || p.k}` : '运行时填写')}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )} />
    </div>
  )
}
