import type { Element, ElementVariant } from '../api'

/** 要素形态（身份/阶段/变身）前端工具，与后端 element_variants.py 同构。
 * 惰性兼容：无 variants 的要素合成单一「默认」形态，展示层无需分叉。 */

export function hasVariants(el: Element): boolean {
  const vs = el.meta.variants
  return Array.isArray(vs) && vs.length > 0
}

export function variantsOf(el: Element): ElementVariant[] {
  const vs = el.meta.variants
  if (Array.isArray(vs) && vs.length) return vs
  return [{
    id: 'default', tag: '', desc: el.meta.sheet_desc ?? '',
    外貌提示词: el.meta.外貌提示词, sheet_url: el.meta.sheet_url,
    profile: el.meta.profile,
  }]
}

/** 当前展示/编辑的形态：优先选中 id；否则首个有图的；再否则第一条。 */
export function activeVariant(el: Element, id?: string): ElementVariant {
  const vs = variantsOf(el)
  return (id ? vs.find(v => v.id === id) : undefined) ?? vs.find(v => v.sheet_url) ?? vs[0]
}

/** 设定图显示名：优先短标签→描述首几字→按序号「图N」（不再要求命名形态）。 */
export function variantLabel(v: ElementVariant, index?: number): string {
  const s = (v.tag || '').trim() || (v.desc || '').trim().slice(0, 8)
  return s || (index != null ? `图${index + 1}` : '默认')
}

/** 该图是否「沿用上一张」（默认开；仅显式 false 才关）。 */
export function inheritEnabled(v: ElementVariant): boolean {
  return v.inherit_ref !== false
}
