/** 年龄档位 → 滑块缺省数字（未设 age_years 时按档位取中值展示） */
export const AGE_CLASS_DEFAULT: Record<string, number> = {
  child: 6, young: 14, adult: 26, middle: 45, elder: 68, none: 26,
}

export function defaultAgeYears(meta: Record<string, unknown>): number {
  const y = meta.age_years
  if (typeof y === 'number' && y >= 1) return y
  return AGE_CLASS_DEFAULT[String(meta.age || '')] ?? 26
}
