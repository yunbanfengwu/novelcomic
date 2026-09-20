import type { ArkCharacter, Element } from '../api'

/** 作品角色 → 火山角色库 的共享纯逻辑（名匹配 + 提交体构造），供单角色按钮与批量条复用。 */

/** 角色名归一：去两端空白 + 去括注（"沉默老船长（黑衣人）" → "沉默老船长"）。 */
export const bare = (s: string) => (s || '').trim().split(/[（(]/)[0].trim()

/** 两角色名是否同一身份：精确 / 去括注精确。 */
export const sameChar = (a: string, b: string) =>
  a.trim() === b.trim() || (!!bare(a) && bare(a) === bare(b))

/** 有设定图的角色要素才可提交（火山 CreateAsset 只收公网图 URL）。 */
export const canSubmitToArk = (el: Element) => el.kind === 'character' && !!el.meta.sheet_url

/** 由角色要素构造角色库提交体：设定图作形象图，profile 派生 gender/age，外貌提示词作描述。
 * group_name 取去括注的基名——同一角色的多套图（"沉默老船长（黑衣人）"/"沉默老船长"）自动归同一分组。 */
export function arkBodyFromElement(pid: number, el: Element): Partial<ArkCharacter> {
  const p = el.meta.profile
  return {
    name: el.name, category: 'work', group_name: bare(el.name), source_project_id: pid,
    image_url: el.meta.sheet_url, description: el.meta.外貌提示词 || '',
    gender: p?.性别 || 'neutral', age: p?.年龄段 || 'adult',
  }
}
