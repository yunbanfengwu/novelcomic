import { Icon } from '../../../components/Icon'
import { GUIDE_STEPS } from '../../../lib/guideSteps'
import type { GuideStepMeta } from '../../../lib/guideSteps'

/** 引导弹框左列：步骤清单（当前高亮、已过标 ✓、全程可点跳转——各步皆暂存无先后依赖）。纯 props→JSX。 */
export function GuideRail({ active, onJump, steps = GUIDE_STEPS, title = '新建作品', foot = '每一步都可跳过，最后一步统一创建；之后在项目里随时补充。' }: {
  active: number
  onJump: (i: number) => void
  steps?: GuideStepMeta[]
  title?: string
  foot?: string
}) {
  return (
    <div className="guide-rail">
      <div className="guide-rail-brand"><span className="guide-rail-logo"><Icon name="wand" /></span> {title}</div>
      <ol className="guide-rail-steps">
        {steps.map((s, i) => {
          const state = i === active ? 'active' : i < active ? 'done' : 'todo'
          const clickable = i !== active
          return (
            <li key={s.key} className={`guide-step ${state}${clickable ? ' clickable' : ''}`}
              onClick={() => clickable && onJump(i)}>
              <span className="guide-step-dot">
                {state === 'done' ? <Icon name="check" /> : <Icon name={s.icon} />}
              </span>
              <span className="guide-step-label">
                <b>{s.label}</b>
                <em>第 {i + 1} 步 / 共 {steps.length} 步</em>
              </span>
            </li>
          )
        })}
      </ol>
      <div className="guide-rail-foot dim">{foot}</div>
    </div>
  )
}
