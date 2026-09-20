import type { Project } from '../../api'
import { Icon } from '../../components/Icon'
import { KIND_META } from '../../lib/kinds'

/** 核心要素·空态（尚无要素时的引导，纯展示件）：
 * ① 要素类型判定任务在途 → 判定中提示；
 * ② 类型已判定（config.element_kinds）→ 展示分组胶囊 + AI 生成要素按钮；
 * ③ 类型缺失且无在途（判定失败/老项目）→ 重新判定 + 直接生成两条路。 */
export function ElementsEmpty({ p, kindsBusy, generating, onGenerate, onRetryKinds }: {
  p: Project
  kindsBusy: boolean
  generating: boolean
  onGenerate: () => void
  onRetryKinds: () => void
}) {
  const kinds = p.config.element_kinds ?? []

  // 生成已开始但首个要素尚未落库（LLM 出第一条前的等待窗口）：给明确进度，避免「点了没反应」错觉
  if (generating) {
    return (
      <div className="section-empty">
        <div style={{ fontSize: 40 }}><Icon name="puzzle" /></div>
        <div className="dim"><Icon name="spinner" spin /> AI 正在生成素材设定，稍候会逐个出现…</div>
      </div>
    )
  }

  if (!kinds.length && kindsBusy) {
    return (
      <div className="section-empty">
        <div style={{ fontSize: 40 }}><Icon name="puzzle" /></div>
        <div className="dim"><Icon name="spinner" spin /> AI 正在按剧情判定本作需要的要素类型…</div>
      </div>
    )
  }

  if (kinds.length) {
    return (
      <div className="section-empty">
        <div style={{ fontSize: 40 }}><Icon name="puzzle" /></div>
        <div>已按剧情建立要素分组</div>
        <div className="elem-kind-chips">
          {kinds.map(k => (
            <span className="tag" key={k.code}>
              <Icon name={KIND_META[k.code]?.icon ?? 'puzzle'} /> {k.label}
            </span>
          ))}
        </div>
        <button className="empty-hint-btn guide-glow" onClick={onGenerate}>
          <Icon name="sparkles" /> AI 生成素材设定
        </button>
      </div>
    )
  }

  return (
    <div className="section-empty">
      <div style={{ fontSize: 40 }}><Icon name="puzzle" /></div>
      <div>尚无素材设定</div>
      <div className="btns">
        <button className="empty-hint-btn" onClick={onRetryKinds}>
          <Icon name="refresh" /> 判定要素类型
        </button>
        <button className="empty-hint-btn guide-glow" onClick={onGenerate}>
          <Icon name="sparkles" /> AI 生成素材设定
        </button>
      </div>
    </div>
  )
}
