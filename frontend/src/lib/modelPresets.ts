/** 模型配置页的厂商常量与候选模型清单（纯数据，无 JSX）。
 *
 * 候选模型有两个来源：① 这里的静态预设（免费/常用、不一定出现在资源包里）；
 * ② 系统管理→资源包里的真实余量行（后端派生 real_model_name，见 resource_map.py）。
 */

import type { IconName } from '../components/Icon'

/** 用途（purpose）→ 图标与中文名。与后端 resource_map._PROFILE / _PURPOSE_MODALITIES 同源。 */
export const PURPOSE_META: Record<string, { icon: IconName; label: string }> = {
  text: { icon: 'text', label: '文本 LLM' },
  embedding: { icon: 'blocks', label: '向量模型' },
  image: { icon: 'image', label: '图片生成' },
  video: { icon: 'video', label: '视频生成' },
  tts: { icon: 'speaker', label: '语音 TTS' },
  review: { icon: 'flask', label: '质检评审' },
  math: { icon: 'ruler', label: '数学模型' },
  code: { icon: 'console', label: '代码模型' },
  rerank: { icon: 'layers', label: '重排模型' },
  ocr: { icon: 'clipboard', label: 'OCR 识别' },
  translate: { icon: 'web', label: '翻译模型' },
  other: { icon: 'puzzle', label: '其它模型' },
}

/** 生成链路会真正取用的用途（后端 get_active 只查这几个）。 */
export const PURPOSES = ['text', 'image', 'video', 'tts', 'embedding'] as const

/** 专用挂档：接口形同 chat 但能力对不上生成链路，登记额度/手工调用用，
 *  **任何生成步骤都不会取到**。数学模型被选成「文本 LLM」是 2026-08-01 事故根因，
 *  故必须与上面那组在 UI 上分栏隔开，不能混在一个下拉里。 */
export const SPECIAL_PURPOSES = ['math', 'code', 'rerank', 'ocr', 'translate', 'other'] as const

export const SPECIAL_HINT = '专用模型：仅登记额度与手工调用，不参与任何生成链路'

/** 接口类型（provider）：只有 ark 在后端有专属分支，其余一律走 OpenAI 兼容口。 */
export const PROVIDERS = [
  { value: 'ark', label: '火山引擎 ARK' },
  { value: 'dashscope', label: '阿里云百炼（兼容模式）' },
  { value: 'minimax', label: 'MiniMax（原生图像接口）' },
  { value: 'grsai', label: 'GRSAI' },
  { value: 'openai_compat', label: 'OpenAI 兼容' },
] as const

/** provider → 默认 Base URL；实际优先用该厂商 Key 预设自带的 base_url（工作空间专属域名） */
export const PROVIDER_BASE: Record<string, string> = {
  ark: 'https://ark.cn-beijing.volces.com/api/v3',
  dashscope: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  minimax: 'https://api.minimaxi.com/v1',
  grsai: 'https://grsai.dakka.com.cn/v1',
  openai_compat: 'https://api.siliconflow.cn/v1',
}

/** 资源包厂商 → 插入模型管理时用的接口类型（与后端 resource_map.profile_target 同源） */
export const VENDOR_PROVIDER: Record<string, string> = { volc: 'ark', bailian: 'dashscope' }

export interface ModelPreset { name: string; model: string; provider: string; purpose: string }

/** 模型编辑弹框的空表单与编辑态类型（ModelAdmin 与 ModelEditorModal 共用） */
export const EMPTY_MODEL = {
  purpose: 'image', provider: 'ark', name: '',
  base_url: 'https://ark.cn-beijing.volces.com/api/v3',
  api_key: '', key_ref: '', model_name: '',
  max_refs: null as number | null, extra: {} as Record<string, unknown>,
}
export type ModelEditing = typeof EMPTY_MODEL & { id?: number }

/** 编辑弹框「候选模型」下拉的条目（静态预设 + 资源包行合并后） */
export interface ModelSuggestion { label: string; name: string; model: string; provider: string }

/** 静态候选：硅基流动向量 + 阿里百炼常用模型。
 * 百炼文本/向量走 OpenAI 兼容模式；生图与生视频都走 DashScope 原生异步任务
 * （后端 dashscope.py 已适配两者，兼容模式下这两条路径实测都是 404）。 */
export const MODEL_PRESETS: ModelPreset[] = [
  { name: 'MiniMax image-01', model: 'image-01', provider: 'minimax', purpose: 'image' },
  { name: '硅基流动 bge-m3（免费）', model: 'BAAI/bge-m3', provider: 'openai_compat', purpose: 'embedding' },
  { name: '硅基流动 bge-m3 Pro', model: 'Pro/BAAI/bge-m3', provider: 'openai_compat', purpose: 'embedding' },
  { name: '硅基流动 Qwen3 Embedding 0.6B', model: 'Qwen/Qwen3-Embedding-0.6B', provider: 'openai_compat', purpose: 'embedding' },
  { name: '硅基流动 Qwen3 Embedding 4B', model: 'Qwen/Qwen3-Embedding-4B', provider: 'openai_compat', purpose: 'embedding' },
  { name: '硅基流动 Qwen3 Embedding 8B', model: 'Qwen/Qwen3-Embedding-8B', provider: 'openai_compat', purpose: 'embedding' },
  { name: '百炼 qwen-plus', model: 'qwen-plus', provider: 'dashscope', purpose: 'text' },
  { name: '百炼 qwen-turbo', model: 'qwen-turbo', provider: 'dashscope', purpose: 'text' },
  { name: '百炼 qwen-max', model: 'qwen-max', provider: 'dashscope', purpose: 'text' },
  { name: '百炼 qwen-long（长文本）', model: 'qwen-long', provider: 'dashscope', purpose: 'text' },
  { name: '百炼 qwen-vl-plus（读图）', model: 'qwen-vl-plus', provider: 'dashscope', purpose: 'text' },
  { name: '百炼 qwen-vl-max（读图）', model: 'qwen-vl-max', provider: 'dashscope', purpose: 'text' },
  { name: '百炼 text-embedding-v4', model: 'text-embedding-v4', provider: 'dashscope', purpose: 'embedding' },
  { name: '百炼 text-embedding-v3', model: 'text-embedding-v3', provider: 'dashscope', purpose: 'embedding' },
  // 百炼「视觉模型」里的生图档（已实测 qwen-image 走原生异步任务可出图）
  { name: '百炼 qwen-image（文生图）', model: 'qwen-image', provider: 'dashscope', purpose: 'image' },
  { name: '百炼 qwen-image-edit-plus（图像编辑）', model: 'qwen-image-edit-plus', provider: 'dashscope', purpose: 'image' },
  { name: '百炼 wan2.6-image', model: 'wan2.6-image', provider: 'dashscope', purpose: 'image' },
  { name: '百炼 wanx-v1', model: 'wanx-v1', provider: 'dashscope', purpose: 'image' },
  { name: '百炼 wanx-sketch-to-image-lite（线稿上色）', model: 'wanx-sketch-to-image-lite', provider: 'dashscope', purpose: 'image' },
  // 百炼「视觉模型」里的生视频档（i2v 需先出首帧，t2v 纯文本即可）
  { name: '百炼 wan2.7-i2v（图生视频）', model: 'wan2.7-i2v', provider: 'dashscope', purpose: 'video' },
  { name: '百炼 wan2.7-videoedit（视频编辑）', model: 'wan2.7-videoedit', provider: 'dashscope', purpose: 'video' },
  { name: '百炼 happyhorse-1.1-i2v（图生视频）', model: 'happyhorse-1.1-i2v', provider: 'dashscope', purpose: 'video' },
  // ── 专用模型：登记在各自类型下，从此不会再出现在「文本 LLM」的候选里 ──
  { name: '百炼 qwen-math-turbo（解数学题）', model: 'qwen-math-turbo', provider: 'dashscope', purpose: 'math' },
  { name: '百炼 qwen-math-plus（解数学题）', model: 'qwen-math-plus', provider: 'dashscope', purpose: 'math' },
  { name: '百炼 qwen3-coder-plus（写代码）', model: 'qwen3-coder-plus', provider: 'dashscope', purpose: 'code' },
  { name: '百炼 qwen3-coder-flash（写代码）', model: 'qwen3-coder-flash', provider: 'dashscope', purpose: 'code' },
  { name: '百炼 gte-rerank-v2（检索重排）', model: 'gte-rerank-v2', provider: 'dashscope', purpose: 'rerank' },
  { name: '百炼 qwen-vl-ocr（图文识别）', model: 'qwen-vl-ocr', provider: 'dashscope', purpose: 'ocr' },
  { name: '百炼 qwen-mt-turbo（机器翻译）', model: 'qwen-mt-turbo', provider: 'dashscope', purpose: 'translate' },
  { name: '百炼 qwen-mt-plus（机器翻译）', model: 'qwen-mt-plus', provider: 'dashscope', purpose: 'translate' },
]

/** 没有通用测试口的用途 → 原因文案（空串=可测）。与后端 run_model_test 的分支对齐，
 *  模型配置弹框与资源包行内测试共用这一份，别在组件里各写一遍。 */
export const noTestReason = (purpose: string) => ({
  video: '视频测试会创建计费长任务，请保存后前往视频生成工作台验证。',
  rerank: '重排模型没有通用测试口，请到厂商控制台验证。',
  ocr: 'OCR 模型需要上传图片，没有通用测试口，请到厂商控制台验证。',
}[purpose] || '')

export const testPlaceholder = (purpose: string) => ({
  text: '例如：用一句话介绍你自己',
  embedding: '例如：古风悬疑短剧中的雨夜追逐',
  image: '例如：电影感的雨夜霓虹街道，广角镜头',
  tts: '例如：欢迎使用模型测试功能。',
  math: '例如：求 1 到 100 所有偶数之和',
  code: '例如：写一个判断回文串的 Python 函数',
  translate: '例如：把「雨夜霓虹街道」翻译成英文',
}[purpose] || '输入测试内容')
