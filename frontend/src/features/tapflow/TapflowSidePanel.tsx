import { Icon } from '../../components/Icon'
import type { ReactNode } from 'react'

/** 右侧合并面板：属性 + 执行 两个 tab（原属性面板与运行面板各占一个停靠位，
 * 现在合并为一个面板，编排态与运行态、studio 与 production 通用）。
 * - 「属性」= 节点编排配置（TapflowInspectorBody）
 * - 「执行」= 运行参数 + 执行卡（TapflowRunBody，原「日志」tab 已删除——
 *   运行日志改由对话面板的「对话」tab 以运行折叠卡承载）
 * tab 自动切换沿用原交互语义：点节点「属性」icon 切属性，「运行管理」切执行。 */
export function TapflowSidePanel({ tab, onTab, inspector, run, onClose, canProps = true }: {
  tab: 'props' | 'run'
  onTab: (t: 'props' | 'run') => void
  /** 属性 tab 内容（含未选中节点的空态） */
  inspector: ReactNode
  /** 执行 tab 内容 */
  run: ReactNode
  onClose: () => void
  /** 属性 tab 可不可进（生产态且未选中「自己加的节点」时不可——外层此时
   *  不渲染属性视图，若让 onTab('props') 过去，面板会被渲染条件整个卸掉：
   *  表现为「点属性整个面板消失」，实测踩过。禁用并提示即可。 */
  canProps?: boolean
}) {
  return (
    <aside className="tap-inspector tap-side-panel">
      <header className="tap-insp-head">
        <span className="tap-seg-mini">
          <button type="button" className={tab === 'props' ? 'on' : ''}
            disabled={!canProps} title={canProps ? undefined : '选中自己添加的节点后可配置'}
            onClick={() => { if (canProps) onTab('props') }}>属性</button>
          <button type="button" className={tab === 'run' ? 'on' : ''}
            onClick={() => onTab('run')}>执行</button>
        </span>
        <button type="button" className="tap-tool" title="收起" onClick={onClose}>
          <Icon name="collapse" />
        </button>
      </header>
      {tab === 'props' ? inspector : run}
    </aside>
  )
}
