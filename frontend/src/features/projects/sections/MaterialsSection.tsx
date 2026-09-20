import { Icon } from '../../../components/Icon'

/** 资料面板（总览子栏）：项目级知识库/参考资料（功能开发中）。滚动由外层总览面板负责。 */
export function MaterialsSection() {
  return (
    <div className="empty-hint"><Icon name="clip" /> 暂无资料 —— 项目级知识库开发中</div>
  )
}
