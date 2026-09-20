// 选择器的一条候选：value 是**引擎认的值**，label 是给人看的名字。
// 单独放一个文件，是因为 tapflowData（纯类型+常量）与 useTapflowCatalog（要 api）
// 都要用它，放任何一边都会让另一边多背一个依赖。

export interface TapOption {
  value: string
  label: string
  /** 次要说明（条目数 / 工具描述），浮窗里灰字显示 */
  note?: string
  /** 分组（生图 / 生视频 / 拆镜…）：按节点模态筛候选用 */
  group?: string
}

/** 候选可以只给字符串（value===label），也可以给完整对象 */
export type TapOptionLike = string | TapOption

export function normOption(o: TapOptionLike): TapOption {
  return typeof o === 'string' ? { value: o, label: o } : o
}

/** value → label。目录还没加载完时回落成 value 本身，不显示空白。 */
export function optionLabel(options: TapOptionLike[], value: string): string {
  return options.map(normOption).find(o => o.value === value)?.label ?? value
}
