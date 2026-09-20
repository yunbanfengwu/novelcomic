import { useEffect } from 'react'

const SHORTCUTS: Array<[string, string]> = [
  ['滚轮', '平移画布'],
  ['Ctrl / ⌘ + 滚轮', '缩放画布（以指针为中心）'],
  ['空格 + 拖拽 / 中键拖拽', '平移画布'],
  ['拖拽空白处', '框选节点'],
  ['Shift + 拖拽空白处', '框选并加入已选'],
  ['Shift / ⌘ + 点击节点', '加选 / 取消该节点'],
  ['拖拽节点', '移动节点（多选时整组一起移）'],
  ['点击节点', '编排=属性面板 / 运行=生成输入条'],
  ['拖拽节点圆点到另一节点', '连线到该节点'],
  ['拖拽节点圆点到空白处', '扩展并连线新节点'],
  ['点击连线', '选中（编排态）'],
  ['选中连线后 Delete', '删除连线'],
  ['选中节点后 Delete', '删除节点（可多个，连线一并删）'],
  ['Ctrl / ⌘ + Z', '撤销增删（关掉画布即失效）'],
  ['Ctrl / ⌘ + Shift + Z', '重做（Ctrl + Y 同义）'],
  ['选中文本节点后滚轮', '滚动节点正文'],
  ['点击空白处', '取消选中'],
]

/** 快捷键说明浮窗：由左下角控制条的「帮助」开合，点画布任意处关闭。 */
export function TapflowHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const close = (e: PointerEvent) => {
      if (!(e.target as Element | null)?.closest?.('.tap-help-pop')) onClose()
    }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [onClose])

  return (
    <div className="tap-help-pop" onPointerDown={e => e.stopPropagation()}>
      <div className="tap-help-title">快捷键</div>
      {SHORTCUTS.map(([keys, desc]) => (
        <div key={keys} className="tap-help-row">
          <kbd>{keys}</kbd>
          <span>{desc}</span>
        </div>
      ))}
    </div>
  )
}
