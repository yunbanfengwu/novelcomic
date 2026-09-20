import { useState } from 'react'
import { Icon } from '../../components/Icon'
import { LEARNING_MATERIALS } from '../../lib/learningMaterials'
import { CaseLibrary } from './CaseLibrary'

/** 学习资料：左侧列表选择、右侧预览。案例库（动态数据）置顶，其余为静态资料 iframe 内嵌 */
export function LearningMaterials() {
  const [active, setActive] = useState('cases')
  const current = LEARNING_MATERIALS.find(m => m.key === active)

  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="text" /> 学习资料</h2>
      </div>
      <div className="lm-body">
        <div className="lm-list">
          <button className={`lm-item${active === 'cases' ? ' active' : ''}`}
            onClick={() => setActive('cases')}>
            <div className="lm-item-title"><Icon name="clapper" /> 案例库</div>
            <div className="lm-item-desc">优秀生成案例：标题 + 生成结果 + 提示词 + 参考素材，可上传维护</div>
          </button>
          {LEARNING_MATERIALS.map(m => (
            <button key={m.key} className={`lm-item${m.key === active ? ' active' : ''}`}
              onClick={() => setActive(m.key)}>
              <div className="lm-item-title">{m.title}</div>
              <div className="lm-item-desc">{m.desc}</div>
            </button>
          ))}
        </div>
        <div className="lm-preview">
          {active === 'cases'
            ? <div className="lm-cases"><CaseLibrary /></div>
            : current
              ? <iframe key={current.key} src={current.src} title={current.title} />
              : <div className="dim lm-empty">请选择左侧资料</div>}
        </div>
      </div>
    </div>
  )
}
