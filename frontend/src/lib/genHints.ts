// 公共图片生成弹框各宿主的固定文案（提示词标签/占位/确认/按钮 title）——纯常量，零 JSX。
// 首帧/尾帧/视频（镜头）、要素设定图、封面各一套；抽出来让容器文件保持精简。
import type { IconName } from '../components/Icon'

export interface GenHints {
  promptHint: string
  placeholder: string
  refsHint?: string
  aiEditTitle?: string
  regenConfirm?: string
  regenTitle?: string
  busyHint?: string
  generateTitle?: string
}

/** 镜头（首帧/视频/尾帧）文案：last=尾帧定格（无自动装配链，AI 走同步端点按分镜脚本写定格提示词）。 */
export function shotHints(target: 'image' | 'video' | 'last'): GenHints {
  const isLast = target === 'last'
  const cn = { image: '首帧', video: '视频', last: '尾帧' }[target]
  return {
    refsHint: '参考素材',
    promptHint: isLast
      ? '尾帧定格提示词（可选：留空则本镜不带尾帧；可直接编辑，AI 修改：在原文下方另起一行写修改要求）'
      : '提示词（可直接编辑，保存后自动装配不再覆盖；要 AI 修改：在原文下方另起一行写修改要求，点右下按钮）',
    placeholder: isLast
      ? '尾帧为可选——需要精确控制本镜结尾画面时才用。点右下「AI 生成」按本章分镜脚本写「本镜结束瞬间」的定格画面，也可直接手写。\n已有内容后：在原文下方另起一行写修改要求，再点该按钮即为 AI 修改。'
      : '尚未生成提示词——点右下「AI 生成」按本章分镜脚本装配（含质检），也可直接手写。\n已有内容后：在原文下方另起一行写修改要求（如：把场景改到夜晚集市、加一段人群反应），再点该按钮即为 AI 修改。',
    aiEditTitle: 'AI 按下方追加的修改要求改写原提示词（以本章分镜脚本为事实依据，后台改写、改完自动落库并刷新，可直接关闭本弹框）',
    regenConfirm: isLast
      ? '将按本章分镜脚本 AI 生成尾帧定格提示词，覆盖当前内容。继续？'
      : '将按本章分镜脚本重新装配并质检本侧提示词（异步任务），覆盖当前内容。继续？',
    regenTitle: isLast
      ? '按本章分镜脚本 AI 生成「本镜结束瞬间」的定格提示词（完成后卡片自动刷新）；也可用 Ctrl+Enter 触发'
      : '按本章分镜脚本生成本侧提示词（装配+质检，异步任务，完成后卡片自动刷新）；也可用 Ctrl+Enter 触发',
    busyHint: '本镜有生成任务在途——完成后卡片自动刷新',
    generateTitle: `有改动先保存，再触发${cn}生成（异步任务）`,
  }
}

/** 要素设定图文案：角色=外貌提示词（身份锚点），场景等=描述（brief）。 */
export function elementHints(isChar: boolean): GenHints {
  return {
    refsHint: '参考素材',
    promptHint: isChar
      ? '外貌提示词（角色身份锚点；保存后按其装配三视图设定图，改动后相关镜会自动重生成设定图）'
      : '场景描述（保存后按其装配场景设定图提示词）',
    placeholder: isChar
      ? '英文外貌描述，用于生图（如 short black hair, bright eyes…）\n已有内容后：在原文下方另起一行写修改要求，点右下「AI 修改」。'
      : '一句话场景描述\n已有内容后：在原文下方另起一行写修改要求，点右下「AI 修改」。',
    aiEditTitle: 'AI 按下方追加的修改要求改写原提示词（以要素设定为事实依据，同步返回回填编辑框，确认后再保存）',
    regenConfirm: '将按要素设定 AI 重写提示词，覆盖当前内容。继续？',
    regenTitle: 'AI 按要素设定重写一版提示词（回填编辑框，需再保存/生成才生效）；也可用 Ctrl+Enter 触发',
    busyHint: '设定图生成任务在途——完成后自动刷新',
    generateTitle: '有改动先保存提示词，再触发设定图生成（异步任务）',
  }
}

/** 封面文案：提示词=简介+画风（可编辑后生成，参考图+提示词都落库）。 */
export const coverHints: GenHints = {
  refsHint: '参考素材',
  promptHint: '封面提示词（小说简介 + 所选画风，可编辑后生成；参考图与提示词都会保存）',
  placeholder: '封面画面描述。\n已有内容后：在原文下方另起一行写修改要求，点右下「AI 修改」。',
  aiEditTitle: 'AI 按下方追加的修改要求改写封面提示词（以简介+画风为事实依据，同步返回回填编辑框）',
  regenConfirm: '将按简介与画风 AI 重写封面提示词，覆盖当前内容。继续？',
  regenTitle: 'AI 按简介与画风重写一版封面提示词（回填编辑框，需再点生成才出图）；也可用 Ctrl+Enter 触发',
  generateTitle: '按上方提示词生成封面（同步出图，需等待片刻）',
}

/** 先导预告片文案：15s 硬切蒙太奇（5 镜×3s，开端→结局），提示词由 AI 蒸馏全剧节点后可编辑。 */
export const trailerHints: GenHints = {
  refsHint: '参考素材（角色设定图锚定主角外貌；可增删/停用）',
  promptHint: '预告片提示词（AI 蒸馏全剧 5 个关键节点：开端→结局硬切蒙太奇，可编辑后生成）',
  placeholder: '预告片画面描述（5 镜、每镜 3 秒、镜间硬切）。\n已有内容后：在原文下方另起一行写修改要求，点右下「AI 修改」。',
  aiEditTitle: 'AI 按下方追加的修改要求改写预告片提示词（保持 5 镜硬切结构，同步回填编辑框）',
  regenConfirm: '将按全剧剧情重新蒸馏预告片提示词，覆盖当前内容。继续？',
  regenTitle: 'AI 重新蒸馏全剧 5 个关键节点写一版预告片提示词（回填编辑框，需再点生成）；也可用 Ctrl+Enter 触发',
  generateTitle: '按上方提示词生成 15 秒先导预告片（同步等待，约需数分钟）',
}

/** 生成弹框图标：角色/场景/封面/首帧/视频 */
export const GEN_ICON: Record<string, IconName> = {
  character: 'person', scene: 'scene', cover: 'palette', image: 'palette', video: 'video', last: 'palette',
}
