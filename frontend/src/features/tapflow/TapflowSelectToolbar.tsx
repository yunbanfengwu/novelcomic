import { Icon } from '../../components/Icon'

/**
 * 多选（框选）后浮在选区上方的工具条。
 * 「新建节点」= 把选中的这些节点全部连到一个新节点上——它们就是新节点的参考元素。
 * 「打组」只是画布上的视觉圈选，不进图数据、不参与运行；选中恰好等于某个组时切成「解组」。
 * 改图的几个动作只在编排态给：运行态的图是这次运行的现场。
 */
export function TapflowSelectToolbar({
  count, grouped, onGroup, onFolder, onLoop, onNewNode, onDuplicate, onRemove, onClear,
}: {
  count: number
  /** 当前选中恰好是一个已有的组 → 按钮变「解组」 */
  grouped?: boolean
  /** 不给 = 该动作在当前形态下不可用 */
  onGroup?: () => void
  /** 将多选节点折叠成一个仅存在于当前画布的文件夹节点 */
  onFolder?: () => void
  /** 将多选节点变成一个真实 loop.body（编排态提供） */
  onLoop?: () => void
  onNewNode?: () => void
  onDuplicate?: () => void
  onRemove?: () => void
  onClear: () => void
}) {
  return (
    <div className="tap-node-toolbar tap-select-bar" onPointerDown={e => e.stopPropagation()}>
      <span className="tap-select-count">已选 {count} 个节点</span>
      {onGroup && (
        <button type="button" className="tap-select-act" onClick={onGroup}>
          <Icon name={grouped ? 'ungroup' : 'layers'} /> {grouped ? '解组' : '打组'}
        </button>
      )}
      {onFolder && (
        <button type="button" className="tap-select-act" onClick={onFolder}>
          <Icon name="folderplus" /> 归入文件夹
        </button>
      )}
      {onLoop && (
        <button type="button" className="tap-select-act" onClick={onLoop}>
          <Icon name="loop" /> 设为循环
        </button>
      )}
      {onNewNode && (
        <button type="button" className="tap-select-act" onClick={onNewNode}>
          <Icon name="plus" /> 新建节点
        </button>
      )}
      <span className="tap-select-sep" />
      {onDuplicate && (
        <button type="button" className="tap-tool" title="复制副本" onClick={onDuplicate}>
          <Icon name="clipboard" />
        </button>
      )}
      {onRemove && (
        <button type="button" className="tap-tool danger" title="删除" onClick={onRemove}>
          <Icon name="trash" />
        </button>
      )}
      <button type="button" className="tap-tool" title="取消选择" onClick={onClear}>
        <Icon name="cross" />
      </button>
    </div>
  )
}
