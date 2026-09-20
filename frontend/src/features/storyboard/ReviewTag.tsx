import type { PromptReview } from '../../api'
import { Icon } from '../../components/Icon'

/** 九维质检结果标签：合格 / 请注意(gold，后端字段仍叫「有保留」) / 不合格，悬停看问题清单。
 * plain=只上色不套胶囊（用于放进 tab 组等已有底色的容器）。 */
export function ReviewTag({ r, plain }: { r?: PromptReview; plain?: boolean }) {
  if (!r) return null
  const tone = r.合格 ? (r.有保留 ? 'gold' : 'accent') : 'bad'
  const inner = (
    <>
      {r.合格 ? (r.有保留 ? <><Icon name="warn" />请注意</> : <Icon name="check" />) : <Icon name="cross" />}
      {typeof r.得分 === 'number' ? ` ${r.得分}` : ''}
    </>
  )
  const title = (r.问题 || []).join('\n') || '无问题'
  if (plain) return <span className={'review-plain ' + tone} title={title}>{inner}</span>
  return <span className={'tag' + (tone === 'bad' ? '' : ' ' + tone)} title={title}>{inner}</span>
}
