const J = { 'Content-Type': 'application/json' }

// 当前用户（系统还没有登录）：所有请求带 X-User-Id，后端 app/users.py 认这个头。
// 接入真登录后这里换成会话即可，业务代码不用动。
let currentUserId = localStorage.getItem('nc_user_id') || 'sys_dev'
export const getCurrentUserId = () => currentUserId
export function setCurrentUserId(id: string) {
  currentUserId = id
  localStorage.setItem('nc_user_id', id)
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    ...init,
    headers: { ...(init?.headers as Record<string, string> | undefined), 'X-User-Id': currentUserId },
  })
  if (!r.ok) {
    const raw = await r.text()
    let msg = raw
    // FastAPI 错误统一 {"detail": "..."}——弹窗只展示人话，不展示原始 JSON
    try {
      const j = JSON.parse(raw)
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      // 非 JSON（网关 504/502 的 HTML 错误页等）：不把整页 HTML 当错误信息弹出
      msg = r.status === 504 ? '请求超时（服务仍可能在后台完成，请稍后刷新查看）' : `服务异常（HTTP ${r.status}），请稍后重试`
    }
    throw new Error(msg || `HTTP ${r.status}`)
  }
  return r.json()
}

/** 流式文本请求（POST）：逐段回调累计文本；后端以「【生成失败】」标记行透传流中错误。
 * body：可选 JSON 入参（如正文生成的目标时长）——不传则发空 POST，与旧行为一致。 */
async function reqStream(url: string, onDelta: (acc: string) => void, errLabel: string,
                         body?: unknown): Promise<string> {
  const r = await fetch(url, body === undefined
    ? { method: 'POST' }
    : { method: 'POST', headers: J, body: JSON.stringify(body) })
  if (!r.ok || !r.body) throw new Error(`${errLabel}（HTTP ${r.status}）`)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let acc = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    acc += dec.decode(value, { stream: true })
    onDelta(acc)
  }
  if (acc.includes('【生成失败】')) throw new Error(acc.slice(acc.indexOf('【生成失败】')))
  return acc
}

/** NDJSON 流请求（POST）：后端每落库一条推一行 JSON，逐行回调（前端实时逐条显示）；
 * 行内 {"error"} 即抛错——中途已产出条目已落库并回调过，保留不回滚 */
async function reqNdjson(url: string, body: unknown, onLine: (obj: Record<string, unknown>) => void): Promise<void> {
  const r = await fetch(url, { method: 'POST', headers: J, body: JSON.stringify(body) })
  if (!r.ok || !r.body) {
    let msg = `服务异常（HTTP ${r.status}），请稍后重试`
    try { const j = JSON.parse(await r.text()); if (j.detail) msg = String(j.detail) } catch { /* 保持默认文案 */ }
    throw new Error(msg)
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (value) buf += dec.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 1)
      if (!line) continue
      const obj = JSON.parse(line) as Record<string, unknown>
      if (obj.error) throw new Error(String(obj.error))
      onLine(obj)
    }
    if (done) break
  }
}

export interface Project {
  id: number; title: string; synopsis: string; writing_style: string
  project_type?: string
  art_style: string; storyline?: string; outline_md?: string; status: string
  config: {
    genre?: string; suggested_chapters?: number; aspect_ratio?: '16:9' | '9:16'; cover_url?: string
    /** 项目用途标签（来自标签分组，视频类型等）。 */
    tags?: string[]; project_type?: string
    // 年代/世界观锚（用户手填）：角色/场景档案补全据此定妆造，留空则 AI 依梗概推断
    era?: string
    // 封面生成落库：编辑后的提示词 + 手选参考图池（含停用项）+ 停用名单（公共图片生成弹框）
    cover_prompt?: string
    cover_prompt_user?: string; cover_prompt_anchor?: string  // 双字段（编辑框分隔线展示）
    cover_refs?: { name: string; kind: string; url: string }[]
    cover_ref_off?: string[]
    // 先导预告片（15s 硬切蒙太奇，封面下方卡片）：成片 + 提示词 + 参考图池/停用名单（同封面形态）
    trailer_url?: string
    trailer_prompt?: string
    trailer_refs?: { name: string; kind: string; url: string }[]
    trailer_ref_off?: string[]
    // AI 按剧情判定的要素分组类型（gen_element_kinds 任务写入；缺失=尚未判定）
    element_kinds?: { code: string; label: string }[]
    // 生成真人角色卡（项目级三态覆盖）：enable=允许照片级真人；disable=强制虚拟角色；follow/缺失=跟随系统配置
    realistic_character?: 'enable' | 'disable' | 'follow'
    // 每个项目必须明确选择：真人项目使用系统备案身份；虚拟形象项目按普通角色卡生成。
    character_mode?: 'real' | 'virtual'
    // 项目开发期大纲质检：允许合理扩展，同时记录接受、拒绝与修订理由
    outline_content_review?: {
      content_stage?: string
      decision_summary?: string
      issues?: string[]
      accepted_additions?: { name?: string; reason?: string }[]
      rejected_additions?: { name?: string; reason?: string }[]
      setting_assessments?: {
        name?: string
        origin?: string
        verdict?: '保留' | '修订' | '删除'
        reason?: string
      }[]
      integrity_issues?: string[]
      policy_issues?: string[]
      semantic_review?: {
        passed?: boolean
        unresolved_issues?: string[]
        reasonable_settings?: { name?: string; reason?: string }[]
        settings_requiring_revision?: { name?: string; reason?: string }[]
        summary?: string
      }
    }
  }
  employees?: { code: string; name: string; role: string; charter: string }[]
}

export interface ProjectVisualAsset {
  id: number
  project_id: number
  asset_role: 'project_environment_style_anchor' | 'project_character_ensemble_style_anchor' | 'project_cover_poster'
  version: number
  prompt: string
  attachment_id: number
  url: string
  status: 'generated' | 'approved' | 'rejected'
  meta: {
    reference_urls?: string[]
    poster_plan?: {
      layout_id: string
      reference_layout: string
      selection_reason: string
      prompt: string
    }
  }
  created_at: string
}
/** 回收站条目：软删除的项目（deleted_at 非空），config 供封面展示 */
export interface TrashProject {
  id: number; title: string; synopsis?: string
  config: Project['config']; deleted_at: string; created_at: string
}
/** 分镜回收站：有回收分镜的项目（筛选下拉） */
export interface ShotTrashProject { project_id: number; title: string; cnt: number; last_deleted: string }
/** 回收分镜条目：软删除的分镜（手动删除 / 重拆镜移入），带项目/章节标注 + 缩略图字段 */
export interface RecycledShot {
  id: number; project_id: number; project_title: string
  chapter_id: number | null; chapter_seq: number | null; chapter_title: string | null
  seq: number; shot_no?: string | number | null; summary?: string | null; duration_s?: number | null
  video_url?: string | null; video_cover_url?: string | null
  keyframe_url?: string | null; last_frame_url?: string | null; deleted_at: string
}
export interface Chapter { id: number; seq: number; title: string; summary: string; status: string; parent_id?: number | null }
export type EpisodeFlashMode =
  | 'flash20'
  | 'sampled_story'
  | 'timeline_supercut'
  | 'adaptive_groups'
  | 'adaptive_duration'
  | 'slate_marked'
export interface EpisodeFlashRef {
  element_id?: number; name: string; kind: string; url: string; binding?: 'identity'
}
export interface EpisodeFlashBeat {
  no: number; stage?: string; scene?: string; shot_size?: string
  picture: string; characters?: string[]; evidence?: string
  source_start_s?: number; source_end_s?: number
  output_start_s?: number; output_end_s?: number
  group_no?: number; group_beat_no?: number
}
export interface EpisodeFlashGroup {
  no: number; title?: string; beat_count?: number; shot_count?: number
  duration_s?: number; prompt?: string; beats?: EpisodeFlashBeat[]
  source_start_s?: number; source_end_s?: number
  output_start_s?: number; output_end_s?: number
  continuity_in?: string; continuity_out?: string
  attachment_id?: number; video_url?: string; group_video_url?: string
}
export interface EpisodeFlashMarker {
  shot_no: number; time_s: number; frame: number
}
export interface EpisodeFlashSplitRun {
  run_id?: string; manifest_attachment_id?: number
  method?: string; visual_slate_detection?: boolean
  master_attachment_id?: number; shot_count?: number; boundary_frames?: number[]
  source_frame_count?: number; total_content_frames?: number; excluded_slate_frames?: number
  status?: string; created_at?: string; finished_at?: string; preserved?: boolean
}
export interface EpisodeFlashExtractedFrame {
  attachment_id: number; url: string; beat_no: number; at_s: number
}
export interface PreviewStoryEvent {
  id: string; seq: number; beat_no: number
  stage?: string; scene?: string; shot_size?: string
  picture: string; evidence?: string; characters?: string[]
  story_start_s: number; story_end_s: number
}
export interface PreviewCandidateFrame {
  attachment_id: number; url: string; at_s: number; role?: string
}
export interface PreviewTimelineSegment {
  id: string; seq: number; script_event_ids: string[]; beat_nos: number[]
  preview_start_s: number; preview_end_s: number
  picture: string; evidence?: string; stage?: string; scene?: string; shot_size?: string
  characters?: string[]; candidate_frames: PreviewCandidateFrame[]
  selected_frame_attachment_id?: number | null; selected_frame_url?: string | null
  confidence?: number; locked?: boolean; converted_shot_id?: number | null
}
export interface PreviewScriptBand {
  event_id: string; start_s: number; end_s: number
}
export interface EpisodePreviewTimeline {
  attachment_id: number; timeline_id: string; version: number
  source_attachment_id: number; batch_id: string; mode: EpisodeFlashMode
  duration_s: number; source_minutes: number
  events: PreviewStoryEvent[]; script_bands?: PreviewScriptBand[]
  segments: PreviewTimelineSegment[]
  status: 'draft' | 'converted'; created_at: string
}
export interface EpisodeFlashFrameExtractRun {
  id?: string; run_id?: string; source_attachment_id?: number
  frame_count?: number; status?: string; created_at?: string; finished_at?: string
  preserved?: boolean
}
export interface EpisodeFlashFrameExtractResponse {
  frames: EpisodeFlashExtractedFrame[]
  run: EpisodeFlashFrameExtractRun
  idempotent: boolean
}
export interface EpisodeFlashDraft {
  id: string; created_at: string; status: 'draft'; prompt: string
  beats: EpisodeFlashBeat[]; refs: EpisodeFlashRef[]
  duration_s: number; shot_count: number; mode?: EpisodeFlashMode; source_minutes?: number
  groups?: EpisodeFlashGroup[]
  resolution?: '480p' | '720p' | '1080p' | null
}
export interface EpisodeFlashBatch {
  id: string; attachment_id: number; video_url: string; created_at: string
  status: 'awaiting_review' | 'extracting' | 'sampled' | 'done' | 'failed' | 'invalid'
  valid: boolean; note?: string | null; frames: number; visible_frames: number
  draft_id?: string | null; prompt?: string; beats?: EpisodeFlashBeat[]
  refs?: EpisodeFlashRef[]; mode?: EpisodeFlashMode; source_minutes?: number
  duration_s?: number; shot_count?: number; groups?: EpisodeFlashGroup[]
  markers?: EpisodeFlashMarker[]
  raw_attachment_id?: number | null; raw_video_url?: string | null
  split_runs?: EpisodeFlashSplitRun[]
  split_method?: string; visual_slate_detection?: boolean
  total_extracted_frames?: number
  extracted_frames?: EpisodeFlashExtractedFrame[]
  frame_extract_runs?: EpisodeFlashFrameExtractRun[]
  timeline?: EpisodePreviewTimeline | null
  timeline_version_count?: number
  resolution?: '480p' | '720p' | '1080p' | null
}
export interface EpisodeFlashStatus {
  batches: EpisodeFlashBatch[]; latest?: EpisodeFlashBatch | null
  draft?: EpisodeFlashDraft | null; drafts?: EpisodeFlashDraft[]
}
/** 卷覆盖项：仅存被覆盖字段，缺省=继承项目 */
export interface VolumeOverrides {
  art_style?: string; writing_style?: string
  aspect_ratio?: '16:9' | '9:16'; element_kinds?: { code: string; label: string }[]
}
/** 卷（分卷分组）：旗下章节按 parent_id 归属；overrides 覆盖项目的画风/文风/比例/要素类型 */
export interface Volume { id: number; seq: number; title: string; chapter_count: number; overrides: VolumeOverrides }
/** 项目资料（已落库）：文本=source 'input'；上传文件=source 'upload' 引用附件，url 指向 OSS */
export interface Material {
  id: number; title: string; source: 'input' | 'upload'
  url?: string | null; chars: number; created_at: string; stored?: boolean
}
/** 引导式新建·暂存资料（未落库）：文本带 content；文件已直传 OSS 拿到 url，随最后一步创建一并落库 */
export interface StagedMaterial {
  title: string; source: 'input' | 'upload'
  content?: string; url?: string | null; size?: number; content_type?: string | null
  /** 文件在服务器临时目录中的引用及解析结果（创建前即可用于预览）。 */
  staging_path?: string | null; extractor?: string | null
  extracted_chars?: number; chunk_count?: number; core_excerpt?: string | null
}
/** 角色结构化档案（后置补全）：批量抽取不产外貌，改由此按项目年代背景逐个生成 */
export interface CharacterProfile {
  年龄段?: string; 性别?: string; 身份称谓?: string; 身份?: string; 时代服饰?: string; 体貌?: string
  招牌动作?: string; 招牌眼神?: string
}
/** 场景轻量特征（织入设定图出图）：人群密度/时段/氛围 */
export interface SceneProfile { 人群密度?: string; 时段?: string; 氛围?: string }
/** 要素设定图（一要素多张图）：每张带一句可选描述(desc，供弱匹配自动选图/人工可覆盖)与
 * inherit_ref（默认 true：生成时沿用上一张为参考锚住相貌/风格；关掉=整容/变身/换景）。
 * tag 退为可选短标签。主/默认图的 sheet_url/外貌提示词 同时镜像回 meta 顶层，老读点无需分叉。 */
export interface ElementVariant {
  id: string; tag?: string; desc?: string; inherit_ref?: boolean
  外貌提示词?: string; sheet_url?: string | null; sheet_fingerprint?: string
  sheet_prompt?: string; sheet_prompt_user?: string; sheet_prompt_anchor?: string
  profile?: CharacterProfile & SceneProfile
}
export interface Element {
  id: number; kind: string; name: string; brief: string
  state: Record<string, unknown>
  meta: {
    外貌提示词?: string; sheet_url?: string; sheet_prompt?: string; sheet_desc?: string
    // 设定图锚定段（版式+画风+质量词，双字段下段）：改过则 anchor_edited 冻结、装配不再刷新
    sheet_prompt_user?: string; sheet_prompt_anchor?: string; sheet_prompt_anchor_edited?: boolean
    profile?: CharacterProfile & SceneProfile
    variants?: ElementVariant[]
    voice?: VoiceBinding
    needs_image?: boolean; needs_voice?: boolean
    // 设定图手选参考图池 + 停用名单（公共图片生成弹框：生成时喂给出图模型）
    extra_refs?: { name: string; kind: string; url: string }[]
    sheet_ref_off?: string[]
    identity_character_id?: number | null
    identity_character_name?: string
    identity_image_url?: string
    hair_sheet_url?: string
  } & Record<string, unknown>
  appears_in: number[]
}
export interface VoiceBinding { kb_voice_id: number; name: string; provider?: string; voice_type?: string }
export interface VoiceSpec {
  name?: string; description?: string; tags?: string[]
  params?: { pitch?: string; speed?: string; energy?: string }
}
export interface ModelProfile {
  id: number; purpose: string; provider: string; name: string
  base_url: string; api_key_masked: string; model_name: string
  max_refs: number | null  // 参考图/附件数量上限；null=用 provider 默认，生成时超出自动截断
  extra: Record<string, unknown>; is_active: boolean
}
/** 模型能力档案（归一化后，/api/models/capabilities）：画布/生成条自适应的唯一数据源 */
export interface ModelCapabilities {
  id: number; name: string; provider: string; model_name: string
  is_active: boolean; max_refs: number | null
  capabilities: {
    transport?: string
    refs: { max: number; kind: string }
    aspects?: string[] | null
    sizes?: string[] | null
  }
}
/** 模型厂商（模型管理→模型厂商）：登记厂商凭据，登记后出现在模型配置「API Key 来源」下拉 */
export interface ModelVendor {
  id: number; label: string; provider: string; base_url: string; api_key_masked: string
}
/** 功能配置（模型管理内）：功能 code 后端写死，每个功能挂一组有序模型（第一个=默认） */
export interface FeatureModelRef {
  id: number; name: string; provider: string; model_name: string; purpose: string
}
export interface FeatureModelConfig {
  code: string; label: string; purpose: string; hint: string; models: FeatureModelRef[]
}
export type ModelTestResult =
  | { kind: 'text'; text: string }
  | { kind: 'vector'; vector: number[]; dimensions: number; endpoint?: string
      storage_compatible?: boolean; storage_dimensions?: number }
  | { kind: 'image'; url: string }
  | { kind: 'audio'; url: string }
export interface SkillPackage {
  id: number; slug: string; name: string; description: string; version: string
  source_url?: string | null; license?: string | null; skill_md: string
  manifest: { format?: string; files?: string[]; legacy?: boolean } & Record<string, unknown>
  status: 'installed' | 'disabled' | 'invalid'; agent_count: number; file_count: number
}
export interface AgentTemplate {
  id: number; code: string; name: string; role: string; description: string
  charter: string; model?: string | null; config: Record<string, unknown>; enabled: boolean
  skills: { id: number; slug: string; name: string }[]
}
export interface ExpertTeam {
  id: number; code: string; name: string; description: string; enabled: boolean
  members: { id: number; code: string; name: string; role_in_team: string; seq: number }[]
}

export interface TestRunSummary {
  test_run_id: string
  project_id?: number | null
  title?: string | null
  started_at: string
  finished_at?: string | null
  step_count: number
  passed: number
  failed: number
  running: number
}

export interface TestLog {
  id: number
  project_id?: number | null
  task_id?: number | null
  kind: string
  source?: string | null
  status: string
  test_run_id: string
  test_item?: string | null
  employee_codes: string[]
  skill_slugs: string[]
  knowledge_refs: string[]
  sop_code?: string | null
  planner_snapshot: Record<string, unknown>
  request: Record<string, unknown>
  result: Record<string, unknown>
  provider?: string | null
  model?: string | null
  error?: string | null
  duration_ms?: number | null
  created_at: string
  finished_at?: string | null
}
/** 可选厂商 key 预设：模型配置下拉用，只带掩码 + ref（明文不下发） */
export interface ProviderKeyPreset {
  ref: string; label: string; provider: string; base_url: string; masked: string
}
/** 资源包厂商：火山方舟 / 阿里百炼（免费额度 + Token Plan） */
export type ResourceVendor = 'volc' | 'bailian'
/** 资源包剩余：一行 = 一个模型类资源包/免费额度（后端补 vendor + modality + 真实模型名） */
export interface ResourcePackage {
  instance_id: string; product: string; config_name: string
  spec: string; spec_unit: string; total: number; remaining: number
  status: string; purchased_at: string; effective_at: string; expires_at: string
  provider_entity: string
  vendor: ResourceVendor; vendor_label: string
  modality: 'text' | 'image' | 'video' | 'audio' | 'embedding' | '3d' | 'other'
  modality_label: string; real_model_name: string
}
/** 情绪试听小样：喜怒哀乐+平，各一条按角色定制的台词 + 音频 */
export interface VoiceSample { emotion: string; text: string; url: string; duration_s?: number }
export interface KbEntry {
  id: number; scope: string; kind: string; category: string | null
  name: string; title?: string | null; description: string; content: string
  tags: string[]
  meta: { positive?: string; negative?: string; samples?: VoiceSample[]
    sample_audio_url?: string; attachments?: { title?: string; url: string }[]
  } & Record<string, unknown>
  thumbnail_url?: string | null; folder_id?: number | null
  weight?: number  // 搜索召回与页面展示排序权重，越大越靠前
  enabled: boolean
}
/** 知识库文件夹：system=按 (kind,category) 规则的虚拟视图（角色库/音色库/画风库…）；自定义=folder_id 归属 */
export interface KbFolder {
  id: number; name: string; title: string; kind: string | null; category: string | null
  system: boolean; seq: number; count: number
}
/** 引导式新建·画风/文风选择卡片（画风带缩略图）；tags=选中后「自带」继承的标签 code */
export interface StyleOption {
  id: number; name: string; title: string; description: string
  content: string; positive?: string; thumbnail_url: string | null; tags?: string[]
}
/** 标签：名称 + 全局唯一 code + 缩略图；kb_entries.tags 存其 code */
export interface Tag {
  id: number; group_id: number; code: string; name: string
  thumbnail_url?: string | null; seq: number
}
/** 标签分组：system=内置受保护（视频类型/风格类型），不可删除 */
export interface TagGroup {
  id: number; code: string; title: string; seq: number; system: boolean; tags: Tag[]
}
/** 案例库分组（如「游戏制作 · 场景设计」） */
export interface CaseGroup { id: number; title: string; seq: number; count: number }
/** 案例参考素材：带标签的图/视频/音频（视频可带封面） */
export interface CaseRef { kind: 'image' | 'video' | 'audio'; label: string; url: string; cover?: string }
/** 案例条目：标题 + 生成结果 + 提示词 + 参考素材；source=project 为项目镜头发布 */
export interface CaseEntry {
  id: number; group_id: number | null; title: string; prompt: string; note: string
  result_kind: 'video' | 'image'; result_url: string; result_cover: string
  refs: CaseRef[]; source: 'manual' | 'project'
  project_id?: number | null; shot_id?: number | null; seq: number
}
/** 独立角色库条目：形象图 + 名称/描述，单向注册火山素材库拿 asset_id（与知识库分离） */
export interface ArkCharacter {
  id: number; name: string; category: string
  group_name: string   // 角色分组（folder）：同分组=同一逻辑角色的多套图；空=未分组独立角色
  owner_user: string; source_work: string; source_project_id: number | null
  description: string
  gender: string; age: string; tags: string[]
  image_url: string
  ark_project: string; ark_group_id: string; ark_asset_id: string
  ark_status: 'pending' | 'processing' | 'active' | 'failed'; ark_error: string
  seq: number
}
export interface Shot {
  id: number; seq: number; title: string; summary: string; status: string
  meta: {
    shot_no?: number | string; scene?: string; scene_element?: string; scale?: string; angle?: string
    camera_move?: string; camera_path?: string; duration_s?: number; dialogue?: string; sfx?: string
    lens_feel?: string; lighting?: string; palette?: string; mood?: string; action?: string
    /** 视频生成单元内的剪辑镜头；每项是两次硬切之间的连续画面。 */
    cuts?: { seconds?: number; scale?: string; camera_move?: string; subject?: string; action?: string }[]
    storyboard_script_ready?: boolean; storyboard_script_at?: string
    motion_hint?: string; characters?: string[]; element_ids?: number[]; reference_urls?: string[]
    reference_images?: { name: string; kind: string; url: string }[]
    image_prompt?: string; video_prompt?: string
    // 提示词双字段（2026-07-17）：user=叙事段（手编不被覆盖）/ anchor=结构句段（装配自动刷新，
    // 改过冻结）；{key} 恒为编译全文（提交/质检用）。编辑框两段用分隔线合并展示
    image_prompt_user?: string; image_prompt_anchor?: string
    image_prompt_user_edited?: boolean; image_prompt_anchor_edited?: boolean
    video_prompt_user?: string; video_prompt_anchor?: string
    video_prompt_user_edited?: boolean; video_prompt_anchor_edited?: boolean
    last_image_prompt_user?: string; last_image_prompt_anchor?: string
    // 尾帧定格（可选）：提示词为手动/AI 内容，自动装配永不触碰；出图写 last_frame_url
    last_image_prompt?: string; last_image_prompt_edited?: boolean; last_frame_url?: string
    // 手编标记：弹框「保存」后为 true——自动装配与质检重构不再覆盖；显式重生成提示词时清除
    image_prompt_edited?: boolean; video_prompt_edited?: boolean
    keyframe_url?: string; video_url?: string
    video_cover_url?: string  // 视频封面（生成时自动抽首帧）：作 <video poster> 与缩略图
    // 首/尾帧来源：gen=生图产线；prev_video/next_video=一键抽相邻镜视频首/尾帧；
    // extracted=视频抽帧弹窗按时间点手抽（本镜/邻镜/上传视频拖轴定位）；
    // next_keyframe=接缝帧（下一镜首帧自动回填为本镜尾帧，link_prev 连贯镜对共用一张图）
    keyframe_source?: 'gen' | 'prev_video' | 'extracted' | 'episode_flash_extract'
    last_frame_source?: 'gen' | 'next_video' | 'next_keyframe' | 'extracted'
    experimental?: boolean; episode_flash_batch?: string; episode_flash_at?: number
    // 镜间衔接（拆镜 LLM 标记 + 代码校验）：true=本镜与上一镜连贯相接（接缝帧共用的依据）
    link_prev?: boolean
    // 场景组（空间锚定 2026-07-16）：scene 连续段组号 + 本镜站位链（空间/开场站位/镜内移动）
    scene_seg?: number
    // 场景连续性状态（continuity_records 落库时回写）：scene_contract_id 是组图批次键的一半
    //（同 scene_seg 但不同合同的镜不得同批出图）；status=blocked 或整个字段缺失时，
    // 后端生成门禁 assert_shot_generation_ready 会直接拦住出图
    continuity?: {
      scene_contract_id?: number | null; shot_state_id?: number; version?: number
      status?: 'approved' | 'blocked'
      errors?: { code?: string; message?: string; field?: string }[]
    }
    blocking?: { space?: string; chars?: Record<string, string>; moves?: string; seg?: number }
    // 本镜所需/被剔除要素清单（装配产物）：参考区按此渲染，无图要素=占位可点击去生成
    required_refs?: RequiredRef[]
    excluded_refs?: (RequiredRef & { reason?: string })[]
    // 音频预检产物（视频生成的声线参考）：视频卡展示为"音频·{speaker}"参考胶囊。
    // speakers=全部说话人明细（含未捏音色/无小样者，供卡片「点击试听 / 未生成则捏音色生成」）；
    // audio_refs=最终入音画闭环的可用小样（仅 speech/hybrid + 有样本）。
    audio_precheck?: {
      audio_refs?: { speaker: string; url: string }[]
      speakers?: {
        speaker: string; element_id?: number | null; kb_voice_id?: number | null
        voice_name?: string | null; vocal_mode?: string | null
        sample_audio_url?: string | null
      }[]
    }
    // 本镜在宫格故事板中的位置（第几张第几格 + 整图 URL）——「按本张出图」时的构图参考引用
    storyboard_ref?: { board: number; panel: number; url?: string }
    // 参考图按目标独立关联：停用名单（要素名/"故事板"/"首帧"/"尾帧"），首帧/视频/尾帧各自管理
    ref_off?: { image?: string[]; video?: string[]; last?: string[] }
    // 前置条件·分镜图默认关联本镜首帧（无首帧取尾帧）；用户解除关联后置 true，
    // 该块改为空占位关键帧——可在分镜图画布里单独出一张本镜关键帧
    board_link_off?: boolean
    // 用户手选的镜级额外参考（资产面板挑的项目图片资产：首帧/故事板/封面等）
    extra_refs?: { name: string; kind: string; url: string }[]
    prompt_review?: PromptReview; prompt_review_image?: PromptReview
    gen?: Record<string, GenState>  // 各产线业务状态（prompts/keyframe/video…），由后端管线统一写
  }
}
/** 本镜所需要素（装配产物 meta.required_refs 单项）：targets 标记用于首帧(image)/视频(video) */
export interface RequiredRef {
  name: string; kind: string; element_id?: number; url?: string | null; targets?: string[]
}
/** 场景组（章 meta.scene_blocking.groups 单项）：空间布局/角色站位/两视角场景参考图提示词与成图 */
export type SceneImageRef = { name: string; kind: string; url?: string }
export type SceneImageVersion = { url: string; superseded_by_task?: number }
/** 场景组的两阶段锚定产物（2026-07-28）：
 * empty_* = 无人空场景基准图，钉死几何与光，也是组内各镜的下游空间参考；
 * sheet_* = 角色站位图，以基准图为参考图生成，只往里加人。 */
/** 工作流引擎（系统管理→tapflow）。 */
export interface WorkflowSummary {
  id: number; slug: string; name: string; description: string
  version: number; status: string; updated_at: string
  /** 排序（需求优先级，小者在前；0=未分配排最后），列表已按它返回 */
  seq: number
  /** 标签（多值）：阶段/类别/产物三维混用，第一个兼当列表页分组名 */
  tags: string[]
  /** 画布实例：fork 自哪张模板（模板本身为 null） */
  origin_slug?: string | null
  /** 画布实例绑定的业务对象（element/project + 主键）。非空即「某个对象的专属画布」。
   * 与 owner_id（用户所有权，谁建的这张图）无关，刻意不同名 */
  subject_kind?: string | null
  subject_id?: number | null
  /** 支持智能调用：被别的画布引用时，这张卡能炸开输入提示词，由大模型规划
   * 子流程里哪几个节点重生成、哪几个复用（后端 workflows.smart_call） */
  smart_call?: boolean
  /** end 节点声明的产物存储目标（如 ["project_cover"]）：业务页据此把「生成封面」
   * 这类按钮直接指向这张画布，画布跑完产物自动落库（2026-09-17） */
  bindings?: string[]
}
/** 画布实例绑定的业务对象：某个场景要素/项目等，它有一份自己的画布 */
export interface WorkflowSubject {
  kind: string; id: number
  /** 显示名，只用于 fork 时给实例起名 */
  name?: string
  /** One business object can have multiple independent product slots, e.g. element sheet variants. */
  canvasRole?: string
}
export interface WorkflowDetail extends WorkflowSummary {
  input_schema: Record<string, unknown>; output_schema: Record<string, unknown>
  graph: { nodes: WorkflowNode[]; edges: { from: string; to: string; mapping?: 'auto' | 'each' | 'collect' }[] }
  /** Derived backend contract: one final product or an aggregate of child products. */
  output_cardinality?: 'one' | 'many'
  subflow_contracts?: Record<string, {
    version: number; name?: string
    output_cardinality: 'one' | 'many'; is_multi_child: boolean
    /** 该子流程是否支持智能调用（引用卡能否炸开生成条） */
    smart_call?: boolean
  }>
  /** 当前图中 action/tool 节点引用的系统工具合同，来源与系统管理工具页完全相同。 */
  tool_contracts?: Record<string, ToolSpec>
}
export interface WorkflowNode {
  id: string; type: string
  config?: Record<string, unknown>; position?: { x: number; y: number }
}
export interface WorkflowRun {
  id: number; slug: string; name: string; version: number
  status: string; depth: number; created_at: string; finished_at?: string; error?: string
}

/** 公共对话面板（components/chat）的会话契约，与后端 app/api/chat.py 对应 */
export interface ChatConversationMsg {
  id: number; role: 'user' | 'assistant'; content: string
  meta: Record<string, unknown>; created_at: string
}
export interface ChatConversation { id: number; title: string; messages: ChatConversationMsg[] }
/** 会话列表项（三条杠弹层）：preview=首条用户消息摘要 */
export interface ChatConversationItem {
  id: number; title: string; archived: boolean
  updated_at: string | null; preview: string
}
export interface ChatReply extends ChatConversationMsg {
  /** 模型输出里解析出的画布动作（如 focus_node），无则 null */
  action: Record<string, unknown> | null
  actions?: Record<string, unknown>[]
  /** 模型给出的后续问题建议（SUGGEST 协议行，快捷问题数据源） */
  suggestions: string[]
}
/** 流式规划回复的 SSE 事件（POST /chat/conversations/{cid}/reply/stream）。
 * step=思考时间线一格；delta=正文增量；action=画布动作（边流边执行）；
 * suggestions=后续问题；done=落库后的完整回复；error=模型层错误。 */
export interface ChatStreamEvent {
  event: 'step' | 'phase' | 'delta' | 'action' | 'suggestions' | 'done' | 'error'
  phase?: string
  state?: 'run' | 'running' | 'done' | 'err'
  title?: string
  detail?: string
  text?: string
  action?: Record<string, unknown>
  items?: string[]
  message?: ChatConversationMsg & { action?: Record<string, unknown> | null }
  partial_message?: ChatConversationMsg
  actions?: Record<string, unknown>[]
  suggestions?: string[]
}
export interface WorkflowNodeRun {
  node_key: string; iteration: number; status: string
  task_id?: number; subrun_id?: number; skip_reason?: string; error?: string
  outputs: Record<string, unknown>
  inputs?: Record<string, unknown>
}
/** run 本体(画布轮询的终态判据) */
export interface WorkflowRunDetail {
  id: number; slug: string; name: string; version: number; status: string
  inputs: Record<string, unknown>; outputs: Record<string, unknown> | null
  error?: string; created_at: string; finished_at?: string
}
/** 上次运行（画布回填用）：inputs=开始节点填的那份，run_options=「怎么跑」。
 * 没跑过时接口返回 null。
 * inputs/run_options 声明成 unknown 是照实说：asyncpg 的 jsonb 出来是字符串，
 * 取用前一律过 lib/tapflowGraphAdapter 的 jsonbObj 解包。 */
export interface WorkflowLastRun {
  id: number; status: string; created_at: string
  project_id?: number | null; node_id?: number | null
  inputs: unknown
  run_options: unknown
}
/** run_options 解包后的形态（见 sql/59_workflow_run_options.sql）：
 * range/force_all 给画布回填；force/stop_after/node_overrides 给运行记录追溯 */
export interface WorkflowRunOptions {
  force?: string[]; stop_after?: string | null; force_all?: boolean
  range?: { from: string | null; to: string | null } | null
  node_overrides?: Record<string, unknown>
}
export interface UnifiedReference {
  id: number; project_id: number; subject_kind: string; subject_id: number; purpose: string
  source_kind: 'element' | 'attachment' | 'canvas_node' | 'url'; source_id?: number | null
  source_canvas_slug?: string | null; source_node_key?: string | null
  role: string; enabled: boolean; seq: number; name: string; kind: string; url?: string | null
  snapshot: Record<string, unknown>
}
/** preview 单节点结果:action 有 outputs;task/subflow 只探 skip_if(exists+探到的值) */
export interface WorkflowPreviewNode {
  outputs?: Record<string, unknown>
  exists?: boolean; value?: unknown; reason?: string
  skipped_write?: boolean; error?: string
  /** Recursive, read-only preview keyed by nodes from the referenced child graph. */
  child_preview?: Record<string, WorkflowPreviewNode>
}

/** 智能体编排（系统管理→智能体）：最小单元是「技能 + 知识 + 工具」。 */
export interface AgentSkill { slug: string; name: string; description: string; version: string }
export interface AgentKbFolder {
  id: number; name: string; title: string; kind?: string; category?: string
  system: boolean; entry_count: number
}
export interface AgentTool {
  name: string; title?: string; description?: string; group: string; writes: boolean
  params?: Record<string, { type?: string; required?: boolean; desc?: string }>
  outputs?: Record<string, ToolParam>
}
/** 质检技能：kb 里 kind='skill'/agent_code='reviewer' 的**条目名**，
 * 与 skill_packages 不是一回事（引擎按名字取规则正文，见 storyboard._reviewer_system） */
export interface AgentQcSkill { name: string; description: string }
/** 生成步骤（执行体）：gen 节点 config.step 的合法取值，来源是后端 flow.STEPS 注册表 */
export interface AgentStepSpec { kind: string; group: string; note: string; manual: boolean }
export interface AgentAssets {
  skills: AgentSkill[]; folders: AgentKbFolder[]; tools: AgentTool[]
  qc_skills?: AgentQcSkill[]; steps?: AgentStepSpec[]
}
export interface CtxNode { id: number; parent_id?: number; kind: string; seq: number; title: string }
export interface CtxElement { id: number; kind: string; name: string; has_sheet: boolean }

export interface SceneGroup {
  seg: number; scene: string; shot_nos?: (number | string)[]
  space?: string; anchors?: Record<string, string>
  empty_desc?: string; sheet_desc?: string
  empty_prompt?: string; empty_url?: string | null
  empty_prompt_user?: string; empty_prompt_anchor?: string
  empty_refs?: SceneImageRef[]; empty_versions?: SceneImageVersion[]
  sheet_prompt?: string; sheet_url?: string | null
  sheet_prompt_user?: string; sheet_prompt_anchor?: string  // 双字段（编辑框分隔线展示）
  sheet_refs?: SceneImageRef[]; sheet_versions?: SceneImageVersion[]
}
/** 业务状态槽 meta.gen.<产线>：刷新页面后可从数据恢复在途/失败状态 */
export interface GenState {
  state: 'waiting_deps' | 'pending' | 'running' | 'done' | 'failed' | 'canceled'
  task_id?: number; error?: string; at?: string
}
export interface ProductionCanvasNode {
  id: string; label: string; kind: 'text' | 'image' | 'video' | 'quality'
  status: 'empty' | 'optional' | 'waiting_deps' | 'pending' | 'running' | 'done' | 'failed' | 'canceled'
  fixed: boolean; content?: string; url?: string | null; error?: string | null
  rerunnable?: boolean; refs?: { name: string; kind: string; url?: string | null }[]
}
/** 画布技能节点执行结果 */
export interface CanvasSkillResult {
  skill: { slug: string; name: string }
  text: string
  data: Record<string, unknown>
  notes: string[]
}
/** 画布 Agent 规划：reply=给用户的说明，actions=待执行的画布操作 */
export interface CanvasAgentAction {
  type: 'set_prompt' | 'run_skill' | 'add_node' | 'connect' | 'toggle_ref' | 'run_stage' | 'generate'
  params: Record<string, unknown>
  reason?: string
}
export interface CanvasAgentPlan { reply: string; actions: CanvasAgentAction[] }
export interface ShotProductionCanvas {
  shot_id: number; title: string; sop_code: string; sop_version: number
  nodes: ProductionCanvasNode[]
  edges: { source: string; target: string; type: 'dep' | 'chain' | 'soft' }[]
}
/** 一集分镜总览黑白宫格故事板中的一张（3:2，rows×cols，覆盖 shot_nos 各镜与 scenes 场景） */
export interface OverviewBoard {
  no: number; url: string; rows: number; cols: number
  shot_nos: (number | string)[]; scenes?: string[]; prompt?: string
}
/** 分镜图（宫格故事板）画布的运行实例：按当前分板重装配的逐张提示词 + 参考设定图 + 已出图 URL */
export interface StoryboardBoard {
  no: number; rows: number; cols: number
  shot_ids: number[]; shot_nos: (number | string)[]; scenes: string[]
  prompt: string
  element_refs: { name: string; kind: string; url: string }[]
  url?: string | null
}
export interface StoryboardGridCanvasData {
  chapter: { id: number; seq: number; title: string }
  focus_board: number | null
  gen?: GenState
  boards: StoryboardBoard[]
}
export interface PromptReview {
  合格?: boolean; 得分?: number; 重构?: boolean; 有保留?: boolean
  问题?: string[]; 修改建议?: string[]; 复审问题?: string[]
}
export interface Task {
  id: number; node_id: number; kind: string; status: string
  error?: string; result?: { url?: string }
}
/** 任务摘要（依赖 DAG 口径）：/tasks 列表与 SSE 事件流共用——含依赖边与节点标注 */
export interface TaskInfo {
  id: number; project_id: number; node_id: number | null; kind: string
  status: 'waiting_deps' | 'pending' | 'running' | 'waiting_external' | 'done' | 'failed' | 'canceled'
  progress: number; error: string | null; attempt: number; priority: number
  deps_remaining: number; root_task_id: number | null
  created_at: string | null; started_at: string | null; finished_at: string | null
  element_id: number | null; node_kind: string | null; node_title: string | null
  shot_no: number | string | null  // 手动插入镜为小数点分号（如 '8.5'）
  parents: number[]  // 依赖边：本任务是这些父任务的前置（多父 DAG）
}
/** 依赖解析入队结果：planned=本次新建的整棵任务树（含自动派发的前置子任务） */
export interface EnqueueResult {
  task_id: number; deduped?: boolean
  planned?: { task_id: number; kind: string; node_id: number | null; deps: number }[]
}
/** 项目图片资产（公共图片生成弹框·添加参考面板）：要素设定图带 element_id（可作镜级关联，可能无图） */
export interface ProjectAsset {
  group: string; kind: string; name: string
  url?: string | null; element_id?: number; variant_id?: string
}
/** 生成/素材库条目：项目内全部产物（图/视频/音频）+ 封面。id 为附件 id（封面/找回项为 null）；
 * recovered=true 表示来自 gen_logs 找回的历史结果（附件已随重拆丢失，仅日志留存） */
export interface AssetItem {
  id: number | null; group: string; media: 'image' | 'video' | 'audio'
  kind: string; name: string; url: string; recovered?: boolean
  cover_url?: string  // 视频封面（首帧）：列表缩略/poster 用
}
export interface WorkflowArtifactSource {
  target_kind: 'element' | 'content_node'; target_id: number; role: string; url?: string
  workflow_id: number; workflow_run_id: number; workflow_node_run_id: number
  node_key: string; iteration: number; operation?: string; slug: string; version: number; origin_slug?: string
}
export interface AssetTypeInfo {
  code: string; name: string; media_kind: 'text' | 'image' | 'video' | 'audio' | 'data' | 'math' | 'vector'
  tags: string[]
  subject_kind: 'element' | 'content_node' | 'attachment' | 'none'
  storage: string; operations: string[]; async_default: boolean
  allows_variant: boolean; allows_version: boolean
  target_ref_kind: 'element' | 'content_node' | 'attachment' | 'none' | null
  target_content_kind: string | null
  context_bindings: [string, string][]
  target_scope_levels: { key: string; label: string; required: boolean }[]
}
export interface AssetTargetOption {
  ref: string; name: string; kind: string
  scopes: Record<string, { value: string; name: string }>
}
export interface AssetTargetResponse {
  asset_type: AssetTypeInfo
  levels: { key: string; label: string; required: boolean }[]
  targets: AssetTargetOption[]
}
export interface SmartInputSelection {
  project_id?: number
  asset_type?: string
  volume_id?: number
  chapter_id?: number
  shot_id?: number
  material_kind?: string
  material_ref?: string
}
export interface AssetInstance {
  id: number; project_id: number; asset_type: string | null
  subject_kind: string | null; subject_id: number | null; variant: string | null
  version: number; attachment_id: number | null; url: string | null; created_at: string
}
export interface Memory { id: number; agent_code: string | null; kind: string; content: string }
/** 生成审计日志：每次真实提交一行（含完整入参）；视频异步结果按 task_id 回写同行，
 * 图片同步一行到位。source=来源标记（project_10_2_21_video / kb_style_35），前缀可筛 */
export interface GenLog {
  id: number; project_id?: number; chapter_id?: number; chapter_title?: string
  node_id?: number; shot_no?: number; task_id?: number; kind: string; source?: string
  attempt_no: number
  provider?: string; model?: string; modality?: string
  request?: {
    content?: { type: string; role?: string; text?: string
      image_url?: { url: string }; audio_url?: { url: string } }[]
    duration?: number; ratio?: string; prompt?: string
    size?: string; image?: string[]  // 图片生成入参（Seedream：prompt + 参考图 URL 列表）
  }
  external_task_id?: string; status: string; error?: string
  result?: { video_url?: string; image_url?: string; provider?: string }
  created_at: string; finished_at?: string
  task_status?: string; task_error?: string
  // 火山备案素材解析：asset://<id> → 真实形象图地址+角色名（后端读时补，显示备案角色真图用）
  assets?: Record<string, { url: string; name: string }>
  employee_codes?: string[]
  skill_slugs?: string[]
  knowledge_refs?: string[]
  sop_code?: string
  planner_snapshot?: Record<string, unknown>
  duration_ms?: number
}

export interface GenLogPage {
  items: GenLog[]
  total: number
  page: number
  page_size: number
}

export const api = {
  listProjects: () => req<Project[]>('/api/projects'),
  // 引导式新建终点：草稿 + 各步暂存值（空字段由 AI 按草稿初拟）+ 暂存资料，一次创建
  createProject: (body: {
    draft: string; title?: string; synopsis?: string; storyline?: string
    writing_style?: string; art_style?: string; aspect_ratio?: '16:9' | '9:16'
    character_mode?: 'real' | 'virtual'
    project_type?: string
    tags?: string[]
    materials?: StagedMaterial[]
  }) =>
    req<Project>('/api/projects', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  // 文件直传：仅转存 OSS 返回 URL，不落库（项目未建时用）
  uploadFile: (file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return req<{ url: string | null; name: string; size: number; content_type?: string | null; stored: boolean
      staging_path?: string | null; extractor?: string | null; extracted_chars?: number; chunk_count?: number; core_excerpt?: string | null }>(
      '/api/projects/uploads', { method: 'POST', body: fd })
  },
  analyzeMaterial: (projectId: number, materialId: number, force = false) =>
    req<{ material_id: number; cached: boolean; analysis: Record<string, unknown> }>(
      `/api/projects/${projectId}/materials/${materialId}/analyze`, {
        method: 'POST', headers: J, body: JSON.stringify({ force }),
      }),
  // 软删除项目（移入回收站，可恢复）
  deleteProject: (id: number) => req<{ ok: boolean }>(`/api/projects/${id}`, { method: 'DELETE' }),
  // 回收站：列出已软删除的项目
  listTrash: () => req<TrashProject[]>('/api/projects/trash'),
  // 从回收站恢复项目
  restoreProject: (id: number) => req<{ ok: boolean }>(`/api/projects/${id}/restore`, { method: 'POST' }),
  // 彻底删除项目（物理删除，级联清全部关联，不可恢复）
  purgeProject: (id: number) => req<{ ok: boolean }>(`/api/projects/${id}/purge`, { method: 'DELETE' }),
  // 分镜回收站（跨项目）：有回收分镜的项目清单（筛选下拉用）
  shotTrashProjects: () => req<ShotTrashProject[]>('/api/shot-trash/projects'),
  // 分镜回收站列表（可选按项目筛选）
  listShotTrash: (projectId?: number) =>
    req<RecycledShot[]>(`/api/shot-trash${projectId ? `?project_id=${projectId}` : ''}`),
  // 彻底删除单个回收分镜（物理删，不可恢复）
  purgeShot: (shotId: number) => req<{ ok: boolean }>(`/api/shot-trash/${shotId}`, { method: 'DELETE' }),
  // 批量彻底删除回收分镜（整集/整批）
  purgeShotBatch: (shotIds: number[]) =>
    req<{ ok: boolean; deleted: number }>('/api/shot-trash/purge-batch',
      { method: 'POST', headers: J, body: JSON.stringify({ shot_ids: shotIds }) }),
  getProject: (id: number) => req<Project>(`/api/projects/${id}`),
  // 更新基本信息（书名/梗概/文风/画风/主线）——引导式新建各步保存；outline_md=大纲手动改稿
  updateProject: (id: number, patch: Partial<Pick<Project, 'title' | 'synopsis' | 'writing_style' | 'art_style' | 'storyline' | 'outline_md' | 'project_type'>>) =>
    req<Project>(`/api/projects/${id}`, { method: 'PATCH', headers: J, body: JSON.stringify(patch) }),
  // 基本信息步·星标一键生成书名/梗概/主线（草稿态，项目未建，返回文本不落库）
  draftInfo: (draft: string) =>
    req<{ title: string; synopsis: string; storyline: string }>('/api/projects/draft-info', {
      method: 'POST', headers: J, body: JSON.stringify({ draft }),
    }),
  // AI 评估文风/画风（草稿态，项目未建）：上下文全由前端暂存值提供，返回建议文本不落库
  restyle: (body: {
    target: 'writing' | 'art'; instruction?: string
    draft?: string; title?: string; synopsis?: string; current?: string
  }) =>
    req<{ suggestion: string }>('/api/projects/restyle', {
      method: 'POST', headers: J, body: JSON.stringify(body),
    }),
  // 项目资料
  listMaterials: (id: number) => req<Material[]>(`/api/projects/${id}/materials`),
  addMaterialText: (id: number, content: string, title?: string) =>
    req<Material>(`/api/projects/${id}/materials`, {
      method: 'POST', headers: J, body: JSON.stringify({ content, title: title || '' }),
    }),
  uploadMaterial: (id: number, file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return req<Material>(`/api/projects/${id}/materials/upload`, { method: 'POST', body: fd })
  },
  deleteMaterial: (id: number, materialId: number) =>
    req<{ ok: boolean }>(`/api/projects/${id}/materials/${materialId}`, { method: 'DELETE' }),
  // 补拟基本信息+大纲（后台任务链 gen_project_info→gen_outline_md，服务端幂等去重）
  ensureProjectInfo: (id: number) =>
    req<{ task_id: number; deduped: boolean }>(`/api/projects/${id}/gen-info`, { method: 'POST' }),
  // AI 按剧情判定要素分组类型（后台任务，写 config.element_kinds，服务端幂等去重）
  genElementKinds: (id: number) =>
    req<{ task_id: number; deduped: boolean }>(`/api/projects/${id}/element-kinds`, { method: 'POST' }),
  // 重新生成长篇架构大纲（Markdown 全文）
  regenerateOutlineMd: (id: number) =>
    req<{ outline_md: string }>(`/api/projects/${id}/outline-md`, { method: 'POST' }),
  // 后台重新生成并质检长篇架构大纲；旧稿在任务成功前保留
  regenerateOutlineMdTask: (id: number) =>
    req<{ task_id: number; deduped: boolean }>(`/api/projects/${id}/outline-md/task`, { method: 'POST' }),
  // 流式重新生成架构大纲：逐段回调 onDelta（边生成边显示），后端流完自动清洗落库
  streamOutlineMd: (id: number, onDelta: (acc: string) => void) =>
    reqStream(`/api/projects/${id}/outline-md/stream`, onDelta, '大纲生成失败'),
  // 流式生成章节正文：逐段回调（累计文本含末尾 <STATE> 回写块，展示时截断），后端流完自动落库+回写。
  // targetMinutes（6-10）：目标成片时长，后端据此下发字数硬约束并在流尾追加【验收未通过】。
  // 不传=不加时长约束——线上实测那样只写 346 字，拆出来 8 镜共 42 秒，故 UI 默认给 6。
  streamWriteChapter: (id: number, nodeId: number, onDelta: (acc: string) => void,
                       targetMinutes?: number) =>
    reqStream(`/api/projects/${id}/chapters/${nodeId}/write/stream`, onDelta, '正文生成失败',
      targetMinutes ? { target_minutes: targetMinutes } : undefined),
  // 生成项目封面（简介+画风提示词，按画幅比例出图；prompt 传空=后端自动拼）；refs=手选参考图喂给出图模型
  generateCover: (id: number, prompt?: string, refs?: { name: string; kind: string; url: string }[]) =>
    req<{ cover_url: string; prompt: string }>(`/api/projects/${id}/cover`, {
      method: 'POST', headers: J,
      body: JSON.stringify({ prompt: prompt || null, refs: refs ?? null }),
    }),
  projectVisualAssets: (id: number) =>
    req<ProjectVisualAsset[]>(`/api/projects/${id}/visual-assets`),
  generateProjectVisualAsset: (
    id: number,
    role: ProjectVisualAsset['asset_role'],
    prompt?: string,
    refs?: { name: string; kind: string; url: string }[],
  ) => req<ProjectVisualAsset>(`/api/projects/${id}/visual-assets/${role}`, {
    method: 'POST', headers: J,
    body: JSON.stringify({ prompt: prompt || null, refs: refs ?? null }),
  }),
  // AI 按要求改写封面提示词（同步返回新提示词，不落库——回填编辑框由用户确认生成）；instruction 空=按简介+画风重写
  aiEditCoverPrompt: (id: number, instruction: string, prompt?: string) =>
    req<{ prompt: string }>(`/api/projects/${id}/cover/prompt/ai-edit`,
      { method: 'POST', headers: J, body: JSON.stringify({ instruction, prompt: prompt || null }) }),
  // 蒸馏封面「海报级关键视觉」：LLM 据梗概/主线/主角提炼剧情专属画面 + 画风 positive；不落库，回填编辑框
  coverKeyVisual: (id: number) =>
    req<{ prompt: string; key_visual: string }>(`/api/projects/${id}/cover/key-visual`,
      { method: 'POST', headers: J }),
  // 先导预告片提示词：无 instruction=蒸馏全剧 5 节点硬切蒙太奇（附默认主角设定图参考）；有=按要求 AI 改写。不落库
  trailerPrompt: (id: number, instruction?: string, prompt?: string) =>
    req<{ prompt: string; refs: { name: string; kind: string; url: string }[] | null }>(
      `/api/projects/${id}/trailer/prompt`,
      { method: 'POST', headers: J, body: JSON.stringify({ instruction: instruction || null, prompt: prompt || null }) }),
  // 生成先导预告片（15s，同步等待数分钟）：落 config.trailer_url + 素材库附件 + gen_logs
  generateTrailer: (id: number, prompt: string, refs?: { name: string; kind: string; url: string }[]) =>
    req<{ trailer_url: string; prompt: string }>(`/api/projects/${id}/trailer`,
      { method: 'POST', headers: J, body: JSON.stringify({ prompt, refs: refs ?? null }) }),
  updateConfig: (id: number, config: Record<string, unknown>) =>
    req<{ config: Record<string, unknown> }>(`/api/projects/${id}/config`, {
      method: 'PATCH', headers: J, body: JSON.stringify({ config }),
    }),
  buildOutline: (id: number, count: number) =>
    req<Chapter[]>(`/api/projects/${id}/outline`, { method: 'POST', headers: J, body: JSON.stringify({ count }) }),
  // 新增（续写）章节：按续写要求紧接目录末尾生成 1..N 章（章数由后端按要求判断）
  appendChapters: (id: number, requirement: string) =>
    req<Chapter[]>(`/api/projects/${id}/outline/append`,
      { method: 'POST', headers: J, body: JSON.stringify({ requirement }) }),
  // 流式新增章节：后端 MD 逐章生成、解析一章落库一章并逐行推送（onChapter 实时回调），返回全部新增章节
  appendChaptersStream: async (id: number, requirement: string, onChapter: (c: Chapter) => void): Promise<Chapter[]> => {
    const out: Chapter[] = []
    await reqNdjson(`/api/projects/${id}/outline/append/stream`, { requirement }, o => {
      if (o.chapter) { const c = o.chapter as Chapter; out.push(c); onChapter(c) }
    })
    return out
  },
  getOutline: (id: number) => req<Chapter[]>(`/api/projects/${id}/outline`),
  deleteChapter: (id: number, nodeId: number) =>
    req<{ ok: boolean; id: number; seq: number }>(
      `/api/projects/${id}/chapters/${nodeId}`, { method: 'DELETE' }),
  // ── 卷（分卷分组）──
  getVolumes: (id: number) => req<Volume[]>(`/api/projects/${id}/volumes`),
  createVolume: (id: number, title?: string) =>
    req<Volume>(`/api/projects/${id}/volumes`, { method: 'POST', headers: J, body: JSON.stringify({ title }) }),
  // 改卷：标题 + 覆盖项；覆盖项传空串/空数组=清除该覆盖（回到继承项目）
  updateVolume: (id: number, volumeId: number, patch: { title?: string } & VolumeOverrides) =>
    req<Volume>(`/api/projects/${id}/volumes/${volumeId}`, { method: 'PATCH', headers: J, body: JSON.stringify(patch) }),
  deleteVolume: (id: number, volumeId: number) =>
    req<{ ok: boolean; moved_chapters: number; into_volume: number }>(
      `/api/projects/${id}/volumes/${volumeId}`, { method: 'DELETE' }),
  moveChapter: (id: number, nodeId: number, volumeId: number) =>
    req<{ ok: boolean }>(`/api/projects/${id}/chapters/${nodeId}/move`,
      { method: 'POST', headers: J, body: JSON.stringify({ volume_id: volumeId }) }),
  buildElements: (id: number) => req<Element[]>(`/api/projects/${id}/elements`, { method: 'POST' }),
  getElements: (id: number) => req<Element[]>(`/api/projects/${id}/elements`),
  // 手动新增单个核心要素（保留接口，当前 UI 未用）
  addElement: (id: number, body: { kind: string; name: string; brief?: string }) =>
    req<Element>(`/api/projects/${id}/elements/add`, { method: 'POST', headers: J, body: JSON.stringify(body) }),
  // 按要求 AI 新增核心要素：生成一个还是多个由后端模型按要求判断；留空=依目录重建全部
  addElementsAI: (id: number, requirement: string) =>
    req<Element[]>(`/api/projects/${id}/elements/add_ai`,
      { method: 'POST', headers: J, body: JSON.stringify({ requirement }) }),
  // 流式生成核心要素：后端 MD 逐个生成、解析一个落库一个并逐行推送（实时回调刷新）；
  // 无目录时自动先流式建目录（章节走 onChapter）。返回产出的要素条数
  addElementsAIStream: async (id: number, requirement: string, on: {
    onElement?: (e: { id: number; kind: string; name: string; brief: string }) => void
    onChapter?: (c: Chapter) => void
  }): Promise<number> => {
    let n = 0
    await reqNdjson(`/api/projects/${id}/elements/add_ai/stream`, { requirement }, o => {
      if (o.element) { n++; on.onElement?.(o.element as { id: number; kind: string; name: string; brief: string }) }
      if (o.chapter) on.onChapter?.(o.chapter as Chapter)
    })
    return n
  },
  addMemory: (id: number, content: string, agent_code?: string) =>
    req<Memory>(`/api/projects/${id}/memories`, { method: 'POST', headers: J, body: JSON.stringify({ content, agent_code }) }),
  listMemories: (id: number) => req<Memory[]>(`/api/projects/${id}/memories`),
  writeChapter: (pid: number, nid: number, body?: {
    target_minutes?: number; creative_brief?: string
    required_terms?: string[]; forbidden_terms?: string[]
  }) =>
    req<{ word_count: number }>(`/api/projects/${pid}/chapters/${nid}/write`, {
      method: 'POST', headers: J, body: JSON.stringify(body || {}),
    }),
  getBody: (pid: number, nid: number) => req<{ content: string }>(`/api/projects/${pid}/chapters/${nid}/body`),
  // 手动保存正文（人工编辑，不触发 AI 回写）
  saveBody: (pid: number, nid: number, content: string) =>
    req<{ content: string; word_count: number }>(`/api/projects/${pid}/chapters/${nid}/body`, {
      method: 'PUT', headers: J, body: JSON.stringify({ content }),
    }),
  // 拆分镜：异步任务（拆完后端自动为每镜串出"提示词生成+质检"任务）
  breakdown: (pid: number, nid: number) =>
    req<{ task_id: number }>(`/api/projects/${pid}/chapters/${nid}/storyboard`, { method: 'POST' }),
  // 章级超级加速实验：先落库带切换数/分组/动态时长的提示词草稿，再据此生成母带；不改正式分镜。
  episodeFlashPrompt: (pid: number, nid: number, body: {
    mode: EpisodeFlashMode; source_minutes: number
  }) =>
    req<EpisodeFlashDraft>(
      `/api/projects/${pid}/chapters/${nid}/episode-flash/prompt`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  getEpisodeFlash: (pid: number, nid: number) =>
    req<EpisodeFlashStatus>(`/api/projects/${pid}/chapters/${nid}/episode-flash`),
  generateEpisodeFlashMaster: (pid: number, nid: number, body: { draft_id: string }) =>
    req<{ video_url: string; prompt: string; beats: EpisodeFlashBeat[]; refs: EpisodeFlashRef[] }>(
    `/api/projects/${pid}/chapters/${nid}/episode-flash/master`,
    { method: 'POST', headers: J, body: JSON.stringify(body) }),
  splitEpisodeFlashPreset: (pid: number, nid: number, attachmentId: number) =>
    req<{ shots: Shot[]; split: EpisodeFlashSplitRun }>(
      `/api/projects/${pid}/chapters/${nid}/episode-flash/${attachmentId}/split-preset`,
      { method: 'POST' }),
  // 任意实验母带按自身剧情节拍抽关键帧；只新增独立图片附件，不创建或修改正式分镜。
  extractEpisodeFlashFrames: (pid: number, nid: number, attachmentId: number) =>
    req<EpisodeFlashFrameExtractResponse>(
      `/api/projects/${pid}/chapters/${nid}/episode-flash/${attachmentId}/extract-frames`,
      { method: 'POST' }),
  createEpisodePreviewTimeline: (pid: number, nid: number, attachmentId: number) =>
    req<{ timeline: EpisodePreviewTimeline; idempotent: boolean }>(
      `/api/projects/${pid}/chapters/${nid}/episode-flash/${attachmentId}/timeline`,
      { method: 'POST' }),
  saveEpisodePreviewTimeline: (pid: number, nid: number, attachmentId: number, body: {
    base_attachment_id: number
    segments: Pick<PreviewTimelineSegment, 'id' | 'script_event_ids' | 'preview_start_s'
      | 'preview_end_s' | 'selected_frame_attachment_id' | 'locked'>[]
    script_bands?: PreviewScriptBand[]
  }) =>
    req<{ timeline: EpisodePreviewTimeline; preserved: boolean }>(
      `/api/projects/${pid}/chapters/${nid}/episode-flash/${attachmentId}/timeline/versions`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  convertEpisodePreviewTimeline: (pid: number, nid: number, attachmentId: number) =>
    req<{ shots: Shot[]; timeline: EpisodePreviewTimeline; idempotent: boolean; preserved?: boolean }>(
      `/api/projects/${pid}/chapters/${nid}/episode-flash/${attachmentId}/timeline/convert`,
      { method: 'POST' }),
  listShots: (pid: number, nid: number) => req<Shot[]>(`/api/projects/${pid}/chapters/${nid}/shots`),
  // 场景组（空间锚定）：分组/站位链/单幅场景参考图——分镜板分节展示与场景图人工确认生成
  // ── 工作流引擎（2026-07-29 新增）──
  listWorkflows: () => req<WorkflowSummary[]>(`/api/workflows`),
  getWorkflow: (slug: string, version?: number) =>
    req<WorkflowDetail>(`/api/workflows/${slug}` + (version ? `?version=${version}` : '')),
  /** 专业能力「智能添加」：按节点提示词从已有技能/知识库/工具里挑（有就选、没有别硬选），
   * 返回的 value 就是引擎认的 slug / folder_id / 工具名，直接并进 bind */
  smartCapabilities: (body: { charter: string; skills?: string[]; kb?: string[]; tools?: string[] }) =>
    req<{ ok: boolean; skills: string[]; kb: string[]; tools: string[]; reason: string }>(
      `/api/workflows/smart-capabilities`, { method: 'POST', headers: J, body: JSON.stringify(body) }),
  runWorkflow: (slug: string, body: { project_id?: number; node_id?: number; version?: number; inputs: Record<string, unknown> }) =>
    req<{ ok: boolean; outputs: Record<string, unknown> }>(`/api/workflows/${slug}/run`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  /** 画布模式:立返 run_id 后台跑,前端轮询 workflowRun/workflowRunNodes 点亮节点;
   * force=节点 id 列表,命中的生成节点跳过「缺才跑」强制重出 */
  runWorkflowAsync: (slug: string, body: { project_id?: number; node_id?: number
    version?: number; inputs: Record<string, unknown>; force?: string[]
    /** 节点级覆盖 {节点id:{prompt|text|instruction}}：
     * prompt=手编的最终提示词，整段覆盖装配；text=手编的文本产出，模型不跑直接落库；
     * instruction=只追加一段指令 */
    node_overrides?: Record<string, {
      prompt?: string; text?: string; instruction?: string
      /** 手选的上游参考节点 id：只用这几个，不再无差别收全部入边 */
      ref_nodes?: string[] }>
    /** 跑到这个节点为止（画布的「结束节点」）。没有对应的「从哪开始」：
     * 整图永远从头走，起点之前靠「缺才跑」只查不生成，开始节点用 force 表达 */
    stop_after?: string
    /** 下面两个引擎不读，只为「下次打开画布回填」落库：
     * force 是 range 折算后的结果，折算不可逆（range.from 可能是非花钱节点） */
    force_all?: boolean
    run_range?: { from: string | null; to: string | null }
    /** Frontend intent: a manual node action versus a workflow run. */
    run_mode?: 'all' | 'single'; run_node?: string }) =>
    req<{ ok: boolean; run_id: number }>(`/api/workflows/${slug}/run`,
      { method: 'POST', headers: J, body: JSON.stringify({ ...body, mode: 'async' }) }),
  /** 运行预检(零副作用):画布运行态打开时回显已有产物/预填内容 */
  previewWorkflow: (slug: string, body: { version?: number; inputs: Record<string, unknown> }) =>
    req<{ ok: boolean; nodes: Record<string, WorkflowPreviewNode> }>(`/api/workflows/${slug}/preview`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  workflowRun: (runId: number) => req<WorkflowRunDetail>(`/api/workflows/runs/${runId}`),
  /** 这条编排最近一次运行的入参与执行选项（画布打开时回填）。没跑过返回 null */
  workflowLastRun: (slug: string) =>
    req<WorkflowLastRun | null>(`/api/workflows/${slug}/runs/last`),
  /** 每个节点各自最近一次产物；用于恢复分支画布，不能只看最后一轮运行 */
  workflowLatestNodes: (slug: string, version?: number) =>
    req<WorkflowNodeRun[]>(`/api/workflows/${slug}/nodes/latest`
      + (version === undefined ? '' : `?version=${version}`)),
  listUnifiedReferences: (pid: number, subjectKind: string, subjectId: number, purpose = 'image') =>
    req<UnifiedReference[]>(`/api/projects/${pid}/references?subject_kind=${encodeURIComponent(subjectKind)}`
      + `&subject_id=${subjectId}&purpose=${encodeURIComponent(purpose)}`),
  addUnifiedReference: (pid: number, body: {
    subject_kind: string; subject_id: number; purpose?: string
    source_kind: UnifiedReference['source_kind']; source_id?: number
    canvas_slug?: string; node_key?: string; role?: string
    snapshot?: Record<string, unknown>
  }) => req<UnifiedReference>(`/api/projects/${pid}/references`,
    { method: 'POST', headers: J, body: JSON.stringify(body) }),
  deleteUnifiedReference: (pid: number, referenceId: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/references/${referenceId}`, { method: 'DELETE' }),
  /** 保存图。draft_from_published=true 时，目标版本若已发布则**另存草稿版本**，
   * 不原地覆盖——已发布的图可能正被别的流程按 slug+version 引用 */
  saveWorkflow: (body: { slug: string; name: string; description?: string
    input_schema?: Record<string, unknown>; output_schema?: Record<string, unknown>
    graph: unknown; seq?: number; tags?: string[]; draft_from_published?: boolean }) =>
    req<{ id: number; slug: string; version: number; status: string }>(`/api/workflows`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  /** 质检未通过后的「重新生成」：把**生成条里的当前全文** + 质检原因 + 关联要素
   * 交给模型重写；给了 skill 就顺带复判一次。刻意不走自动重试那条路——
   * 那条依赖质检技能自己返回「重构提示词」，判据一严就轮轮 0 分 */
  qcRewrite: (body: { prompt: string; issues?: string[]; element_id?: number
    project_id?: number; extra?: string; skill?: string; threshold?: number }) =>
    req<{ ok: boolean; prompt: string
      qc: { passed?: boolean; score?: number; rounds?: number; issues?: string[]; user?: string } }>(
      `/api/workflows/qc/rewrite`, { method: 'POST', headers: J, body: JSON.stringify(body) }),
  /** 这个业务对象有没有自己的画布（生产态改过结构就会有）。没有返回 null，不是错误 */
  getWorkflowInstance: (slug: string, subject: WorkflowSubject) =>
    req<WorkflowDetail | null>(
      `/api/workflows/${slug}/instance?subject_kind=${encodeURIComponent(subject.kind)}`
      + `&subject_id=${subject.id}` + `&canvas_role=${encodeURIComponent(subject.canvasRole ?? '')}`),
  /** 从模板 fork 出该对象的专属画布（已存在直接返回，幂等）。
   * 生产态画布第一次做结构改动时调用——此后编辑都落进这份副本，模板保持干净 */
  /** 连线即挂载（2026-09-18）：把挂载点当前指向的那张图**立即落库**，不等一次运行。
   * 与运行收尾同一条 apply_mount_binding：project_cover 写 config.cover_url，
   * 资产类型码写 workflow_artifacts。连的常常是现有的图，不值得为存图跑一遍模型 */
  storeMount: (slug: string, body: { project_id?: number; target: string
    subject?: { kind: string; id: number }; url: string; prompt?: string; variant?: string }) =>
    req<{ stored: string; url?: string; version?: number; unchanged?: boolean; reason?: string }>(
      `/api/workflows/${encodeURIComponent(slug)}/mount-store`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  forkWorkflowInstance: (slug: string, subject: WorkflowSubject) =>
    req<WorkflowDetail>(`/api/workflows/${slug}/instance`, {
      method: 'POST', headers: J,
      body: JSON.stringify({ subject_kind: subject.kind, subject_id: subject.id,
                             subject_name: subject.name ?? '', canvas_role: subject.canvasRole ?? '' }),
    }),
  publishWorkflow: (slug: string, version: number) =>
    req<{ ok: boolean; slug: string; version: number }>(
      `/api/workflows/${slug}/publish?version=${version}`, { method: 'POST' }),
  /** 只改标签（列表页标色用）：不动图/版本，按 slug 全版本生效 */
  setWorkflowTags: (slug: string, tags: string[]) =>
    req<{ ok: boolean; slug: string; tags: string[] }>(`/api/workflows/${slug}/tags`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ tags }) }),
  /** 标记「支持智能调用」：被别的画布引用时能否炸开生成条、由大模型规划子图重跑范围。
   * 与标签同理按 slug 全版本生效——这是流程的能力声明，不是某一版的图内容 */
  setWorkflowSmartCall: (slug: string, smartCall: boolean) =>
    req<{ ok: boolean; slug: string; smart_call: boolean }>(
      `/api/workflows/${encodeURIComponent(slug)}/smart-call`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ smart_call: smartCall }) }),
  /** 只规划不执行：这句提示词会让子流程里的哪几个节点重生成（画布点生成前的预览）。
   * 真跑时引擎会用同一个规划器再算一次，两边同一份结论 */
  workflowSmartPlan: (slug: string, body: {
    version?: number; project_id?: number; inputs?: Record<string, unknown>; prompt: string
  }) => req<{
    ok: boolean; force: string[]; overrides: Record<string, { instruction?: string }>
    nodes: { id: string; title: string; type: string; exists: boolean | null }[]
    reason: string; degraded?: string
  }>(`/api/workflows/${encodeURIComponent(slug)}/smart-plan`,
     { method: 'POST', headers: J, body: JSON.stringify(body) }),
  /** 整轮运行的上下文轨迹：逐节点入参/出参，按真实执行序（回看 + AI 规划同一份） */
  workflowRunContext: (runId: number) => req<{
    id: number; status: string; inputs: Record<string, unknown>
    outputs: Record<string, unknown>
    context: { node: string; type: string; title: string; iteration: number
               inputs?: unknown; outputs?: unknown }[]
  }>(`/api/workflows/runs/${runId}/context`),
  workflowRuns: (projectId?: number) =>
    req<WorkflowRun[]>(`/api/workflows/runs/recent` + (projectId ? `?project_id=${projectId}` : '')),
  workflowRunNodes: (runId: number) => req<WorkflowNodeRun[]>(`/api/workflows/runs/${runId}/nodes`),

  /** 公共对话面板（components/chat）：会话按 scope 隔离，消息后端持久化。 */
  chatLatest: (scopeKind: string, scopeKey: string) =>
    req<ChatConversation | null>(
      `/api/chat/conversations/latest?scope_kind=${encodeURIComponent(scopeKind)}&scope_key=${encodeURIComponent(scopeKey)}`),
  /** fresh=true 时归档当前活跃会话并新建（弹层里的「新对话」） */
  chatNew: (scopeKind: string, scopeKey: string, fresh = false, legacyScopeKeys: string[] = []) =>
    req<ChatConversation>('/api/chat/conversations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope_kind: scopeKind, scope_key: scopeKey, fresh,
        legacy_scope_keys: legacyScopeKeys }),
    }),
  /** 会话列表（活跃+归档，倒序）：三条杠弹层用 */
  chatList: (scopeKind: string, scopeKey: string) =>
    req<ChatConversationItem[]>(
      `/api/chat/conversations/list?scope_kind=${encodeURIComponent(scopeKind)}&scope_key=${encodeURIComponent(scopeKey)}`),
  /** 切到指定历史会话（该会话转活跃，原活跃归档） */
  chatSwitch: (conversationId: number, scopeKind: string, scopeKey: string) =>
    req<ChatConversation>(`/api/chat/conversations/${conversationId}/switch`
      + `?scope_kind=${encodeURIComponent(scopeKind)}&scope_key=${encodeURIComponent(scopeKey)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    }),
  chatAppend: (conversationId: number, role: 'user' | 'assistant', content: string,
    meta: Record<string, unknown> = {}) =>
    req<ChatConversationMsg>(`/api/chat/conversations/${conversationId}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, content, meta }),
    }),
  /** 让后端读会话历史（+画布上下文）调 LLM；回复落库后连同动作指令一起返回 */
  chatReply: (conversationId: number, context?: string) =>
    req<ChatReply>(`/api/chat/conversations/${conversationId}/reply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ context }),
    }),
  /** 流式规划回复（SSE）：规划步骤→逐字正文→画布动作，边流边回调。
 * 返回最后一个 done 事件（含落库后的完整回复）；中途断流扌出已收到的部分。 */
  chatReplyStream: async (
    conversationId: number, context: string | undefined,
    onEvent: (ev: ChatStreamEvent) => void | Promise<void>,
    signal?: AbortSignal,
  ): Promise<ChatStreamEvent | null> => {
    const r = await fetch(`/api/chat/conversations/${conversationId}/reply/stream`, {
      method: 'POST', headers: J, body: JSON.stringify({ context }), signal,
    })
    if (!r.ok || !r.body) {
      const raw = await r.text().catch(() => '')
      let msg = raw
      try { const j = JSON.parse(raw); if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* 非 JSON */ }
      throw new Error(msg || `HTTP ${r.status}`)
    }
    const reader = r.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    let last: ChatStreamEvent | null = null
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data:')) continue
          try {
            const ev = JSON.parse(line.slice(5).trim()) as ChatStreamEvent
            last = ev
            await onEvent(ev)
          } catch { /* 半包/非 JSON 忽略 */ }
        }
      }
    }
    return last
  },
  /** 属性面板的候选目录（技能/知识库文件夹/工具）：**唯一目录源**，前端不留假数组 */
  agentAssets: () => req<AgentAssets>('/api/agents/assets'),
  assetTypes: () => req<AssetTypeInfo[]>('/api/assets/types'),
  assetTargets: (type: string, projectId: number) =>
    req<AssetTargetResponse>(
      `/api/assets/types/${encodeURIComponent(type)}/targets?project_id=${projectId}`),
  resolveSmartInputs: (slug: string, version: number | undefined, selection: SmartInputSelection) =>
    req<{ inputs: Record<string, string>; labels: Record<string, string> }>(
      `/api/workflows/${encodeURIComponent(slug)}/smart-inputs/resolve`, {
        method: 'POST', headers: J,
        body: JSON.stringify({ ...selection, version }),
      }),
  assets: (projectId: number, type?: string, subjectKind?: string, subjectId?: number) => {
    const q = new URLSearchParams({ project_id: String(projectId) })
    if (type) q.set('asset_type', type)
    if (subjectKind) q.set('subject_kind', subjectKind)
    if (subjectId) q.set('subject_id', String(subjectId))
    return req<AssetInstance[]>(`/api/assets?${q}`)
  },
  agentProjects: () => req<{ projects: { id: number; title: string }[] }>('/api/agents/context'),
  agentCtxNodes: (projectId: number) =>
    req<{ nodes: CtxNode[]; elements: CtxElement[] }>(
      `/api/agents/context?project_id=${projectId}`),
  sceneGroups: (pid: number, nid: number) =>
    req<{ groups: SceneGroup[]; at?: string }>(`/api/projects/${pid}/chapters/${nid}/scene-groups`),
  runSceneBlocking: (pid: number, nid: number, force = false) =>
    req<{ task_id: number }>(
      `/api/projects/${pid}/chapters/${nid}/scene-blocking${force ? '?force=true' : ''}`,
      { method: 'POST' }),
  // stage: 'empty'=空场景基准图 / 'sheet'=角色站位图（两阶段各有自己的提示词与成图）
  saveSceneSheetPrompt: (pid: number, nid: number, seg: number, prompt: string,
                         stage: 'empty' | 'sheet' = 'sheet') =>
    req<{ ok: boolean }>(`/api/projects/${pid}/chapters/${nid}/scene-groups/${seg}`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ sheet_prompt: prompt, stage }) }),
  genSceneSheet: (pid: number, nid: number, seg: number, prompt?: string,
                  stage: 'empty' | 'sheet' = 'sheet') =>
    req<{ task_id: number }>(
      `/api/projects/${pid}/chapters/${nid}/scene-groups/${seg}/${stage}`,
      { method: 'POST', headers: J, body: JSON.stringify({ prompt: prompt ?? null }) }),
  // 在两镜之间插入空白镜（时间轴悬停「+」）：afterShotId=null 插到最前；返回新镜（含生成的小数镜号）
  insertShot: (pid: number, nid: number, afterShotId: number | null) =>
    req<Shot>(`/api/projects/${pid}/chapters/${nid}/shots/insert`,
      { method: 'POST', headers: J, body: JSON.stringify({ after_shot_id: afterShotId }) }),
  // 删除单镜：只删该行，其它镜 seq/镜号不动（被删镜号永久保留、不复用）
  deleteShot: (pid: number, sid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/${sid}`, { method: 'DELETE' }),
  // 章级总览宫格故事板（一集多张）：仅手动生成（拆镜后不再自动串出）；GET 读张列表+生成状态。
  // 分镜图画布提交 { board, prompt } → 只重出该张、用画布里确认过的提示词；缺省=整章重出
  genOverviewGrid: (pid: number, nid: number, body?: { board?: number; prompt?: string }) =>
    req<{ task_id: number }>(`/api/projects/${pid}/chapters/${nid}/storyboard-grid`,
      { method: 'POST', headers: J, body: JSON.stringify(body ?? {}) }),
  // 分镜图画布运行实例：按当前分板重装配逐张提示词/参考设定图，合并已出图；shotId 给定则回聚焦张
  storyboardGridCanvas: (pid: number, nid: number, shotId?: number) =>
    req<StoryboardGridCanvasData>(`/api/projects/${pid}/chapters/${nid}/storyboard-grid/canvas`
      + (shotId != null ? `?shot_id=${shotId}` : '')),
  getStoryboardOverview: (pid: number, nid: number) =>
    req<{ overview: { boards: OverviewBoard[]; at?: string } | null; gen?: GenState }>(
      `/api/projects/${pid}/chapters/${nid}/storyboard-overview`),
  // 按某张故事板批量生成其覆盖各镜的首帧（整张作构图参考+固定格位引用句；跳过已有首帧）
  batchKeyframesByBoard: (pid: number, nid: number, board: number, force = false) =>
    req<{ queued: number; tasks: { shot_id: number; task_id: number }[] }>(
      `/api/projects/${pid}/chapters/${nid}/storyboard-grid/${board}/keyframes${force ? '?force=true' : ''}`,
      { method: 'POST' }),
  // 首帧生成（依赖 DAG）：缺提示词自动派发 gen_prompts 前置子任务（planned 含整棵树）
  genKeyframe: (pid: number, sid: number) =>
    req<EnqueueResult>(`/api/projects/${pid}/shots/${sid}/keyframe`, { method: 'POST' }),
  // 尾帧定格生成（可选）：无自动装配链，缺提示词后端 400（先手写或 AI 生成）
  genLastKeyframe: (pid: number, sid: number, prompt?: string) =>
    req<EnqueueResult>(`/api/projects/${pid}/shots/${sid}/last-keyframe`, {
      method: 'POST', headers: J, body: JSON.stringify(prompt ? { prompt } : {}),
    }),
  // AI 生成尾帧定格提示词（同步返回并落库）：以本章分镜脚本+本镜首帧/视频提示词为依据
  genLastFramePrompt: (pid: number, sid: number) =>
    req<{ prompt: string }>(`/api/projects/${pid}/shots/${sid}/last-prompt/ai`, { method: 'POST' }),
  // 从相邻镜视频抽帧（同步，秒级）：first=上一镜视频尾帧→本镜首帧；last=下一镜视频首帧→本镜尾帧
  extractNeighborFrame: (pid: number, sid: number, target: 'first' | 'last') =>
    req<{ url: string }>(`/api/projects/${pid}/shots/${sid}/frame-from-neighbor`,
      { method: 'POST', headers: J, body: JSON.stringify({ target }) }),
  // 视频抽帧弹窗：按时间点从已有视频(URL)或临时上传件(file)抽一帧作本镜首/尾帧（同步落库）
  extractFrameFromVideo: (pid: number, sid: number,
    body: { target: 'first' | 'last'; atSec: number; videoUrl?: string; file?: File }) => {
    const fd = new FormData()
    fd.append('target', body.target)
    fd.append('at_sec', String(body.atSec))
    if (body.file) fd.append('file', body.file)
    else if (body.videoUrl) fd.append('video_url', body.videoUrl)
    return req<{ url: string }>(`/api/projects/${pid}/shots/${sid}/frame-from-video`,
      { method: 'POST', body: fd })
  },
  batchKeyframes: (pid: number, nid: number, force = false) =>
    req<{ queued: number; tasks: { shot_id: number; task_id: number }[] }>(
      `/api/projects/${pid}/chapters/${nid}/keyframes${force ? '?force=true' : ''}`, { method: 'POST' }),
  // 整页首帧·组图（Seedream 组图一次出 N 张，组内角色/场景/画风一致）：章级单任务，
  // refs=弹框勾选的要素参考，note=组图全局要求；缺提示词的镜自动带出 gen_prompts 子任务
  genKeyframesGroup: (pid: number, nid: number,
    body: { shot_ids: number[]; refs: { name: string; kind: string; url: string }[]; note: string }) =>
    req<EnqueueResult>(`/api/projects/${pid}/chapters/${nid}/keyframes/group`,
      { method: 'POST', headers: J, body: JSON.stringify(body) }),
  // 提示词生成（含质检）：装配三套提示词→九维评审→不合格自动重构→复审，异步任务；
  // only=image/video 只重生成并质检一侧（首帧/视频提示词单独重生成）
  genPrompts: (pid: number, sid: number, only?: 'image' | 'video', redesignCuts = false) =>
    req<{ task_id: number }>(`/api/projects/${pid}/shots/${sid}/prompts`,
      { method: 'POST', headers: J, body: JSON.stringify({ only: only ?? null, redesign_cuts: redesignCuts }) }),
  // 画布技能节点：按 SKILL.md 执行一次，返回结构化结果
  runCanvasSkill: (pid: number, slug: string, body: { instruction?: string; context?: unknown }) =>
    req<CanvasSkillResult>(`/api/projects/${pid}/canvas/skills/${encodeURIComponent(slug)}/run`, {
      method: 'POST', headers: J, body: JSON.stringify(body),
    }),
  // 画布 Agent：读画布状态 + 指令 → 返回可执行操作序列
  canvasAgent: (pid: number, body: { instruction: string; canvas: unknown }) =>
    req<CanvasAgentPlan>(`/api/projects/${pid}/canvas/agent`, {
      method: 'POST', headers: J, body: JSON.stringify(body),
    }),
  shotProductionCanvas: (pid: number, sid: number) =>
    req<ShotProductionCanvas>(`/api/projects/${pid}/shots/${sid}/production-canvas`),
  runProductionCanvasNode: (pid: number, sid: number, nodeId: string,
    scope: 'self' | 'with_dependencies' = 'with_dependencies') =>
    req<EnqueueResult | Record<string, unknown>>(
      `/api/projects/${pid}/shots/${sid}/production-canvas/nodes/${encodeURIComponent(nodeId)}/run`,
      { method: 'POST', headers: J, body: JSON.stringify({ scope }) }),
  // 参考图按目标独立关联：传入停用名单（要素名/"故事板"/"首帧"/"尾帧"）；
  // board_link_off=解除「分镜图关联首/尾帧」（前置条件区那块改为空占位关键帧）
  updateShotRefs: (pid: number, sid: number,
    body: { image_off?: string[]; video_off?: string[]; last_off?: string[]
      board_link_off?: boolean }) =>
    req<{ ref_off: { image?: string[]; video?: string[]; last?: string[] } }>(
      `/api/projects/${pid}/shots/${sid}/refs`,
      { method: 'PATCH', headers: J, body: JSON.stringify(body) }),
  // 手动增删本镜关联要素（改绑定后后端自动重装配提示词）
  updateShotElements: (pid: number, sid: number, body: { add?: number; remove?: number }) =>
    req<{ element_ids: number[]; characters: string[] }>(`/api/projects/${pid}/shots/${sid}/elements`,
      { method: 'PATCH', headers: J, body: JSON.stringify(body) }),
  // 视频生成（依赖 DAG）：缺视频提示词/首帧自动逐级向上派发前置子任务，全部完成后自动生成
  genVideo: (pid: number, sid: number, prompt?: string) =>
    req<EnqueueResult>(`/api/projects/${pid}/shots/${sid}/video`, {
      method: 'POST', headers: J, body: JSON.stringify(prompt ? { prompt } : {}),
    }),
  // 音频预检（对白×音色）：确定性 gate + best-effort 补小样 + LLM 评审，落 meta.audio_precheck。
  // 捏音色后重跑它即可把新小样刷进本镜的"音频·{speaker}"参考卡（同步返回，永不阻断视频生成）。
  audioPrecheck: (pid: number, sid: number) =>
    req<{ speakers?: unknown[]; audio_refs?: unknown[] }>(
      `/api/projects/${pid}/shots/${sid}/audio-precheck`, { method: 'POST' }),
  // 保存手编提示词（落 edited 标记：自动装配/质检重构不再覆盖；显式重生成提示词时清除）
  saveShotPrompt: (pid: number, sid: number, target: 'image' | 'video' | 'last', prompt: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/${sid}/prompt`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ target, prompt }) }),
  // 保存手编分镜脚本正文（视频详情弹框顶部「分镜脚本」框）：更新 summary，作装配/AI 改写的事实边界
  saveShotSummary: (pid: number, sid: number, summary: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/${sid}/summary`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ summary }) }),
  // AI 按要求修改提示词（同步返回新提示词，不落库——回填编辑框由用户确认保存）
  aiEditShotPrompt: (pid: number, sid: number, target: 'image' | 'video' | 'last', instruction: string, prompt?: string) =>
    req<{ prompt: string }>(`/api/projects/${pid}/shots/${sid}/prompt/ai-edit`,
      { method: 'POST', headers: J, body: JSON.stringify({ target, instruction, prompt: prompt || null }) }),
  taskStatus: (pid: number, tid: number) => req<Task>(`/api/projects/${pid}/tasks/${tid}`),
  // 任务摘要列表（在途全量+最近已结束，含依赖边）——任务队列面板/刷新恢复用
  listTasks: (pid: number) => req<TaskInfo[]>(`/api/projects/${pid}/tasks`),
  cancelTask: (pid: number, tid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/tasks/${tid}/cancel`, { method: 'POST' }),
  retryTask: (pid: number, tid: number) =>
    req<EnqueueResult>(`/api/projects/${pid}/tasks/${tid}/retry`, { method: 'POST' }),
  // SSE 事件流地址（EventSource 直连，非 fetch）：任务状态变更/流式拆镜逐镜产出
  taskEventsUrl: (pid: number) => `/api/projects/${pid}/events`,
  genElementSheet: (pid: number, eid: number, variantId?: string) =>
    req<{ task_id: number }>(`/api/projects/${pid}/elements/${eid}/sheet`
      + (variantId ? `?variant_id=${encodeURIComponent(variantId)}` : ''), { method: 'POST' }),
  // 手动编辑要素基本信息（名称/描述，对所有类型通用；角色外貌提示词另走 saveElementPrompt）
  updateElement: (pid: number, eid: number, patch: { name?: string; brief?: string }) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/elements/${eid}`,
      { method: 'PATCH', headers: J, body: JSON.stringify(patch) }),
  // 手动编辑要素「出现章节」：按章节 seq 列表重建出现索引（element_appearances）
  updateElementAppears: (pid: number, eid: number, seqs: number[]) =>
    req<{ appears_in: number[] }>(`/api/projects/${pid}/elements/${eid}/appears`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ seqs }) }),
  // 保存要素生图提示词（公共图片生成弹框的存储回调）：角色=外貌提示词，其余=brief；多形态可指定 variantId
  saveElementPrompt: (pid: number, eid: number, prompt: string, variantId?: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/elements/${eid}/prompt`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ prompt, variant_id: variantId || null }) }),
  // 后置补全角色结构化档案（年龄/性别/身份/时代服饰/体貌）+ 派生英文外貌提示词并落库（治"古装现代脸"）
  genElementProfile: (pid: number, eid: number, hints?: string) =>
    req<{ profile: CharacterProfile; 外貌提示词: string }>(
      `/api/projects/${pid}/elements/${eid}/profile/gen`,
      { method: 'POST', headers: J, body: JSON.stringify({ hints: hints || null }) }),
  // 保存用户手改的结构化档案（角色档案 / 场景特征）
  saveElementProfile: (pid: number, eid: number, profile: Record<string, string>) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/elements/${eid}/profile`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ profile }) }),
  bindCharacterIdentity: (pid: number, eid: number, arkCharacterId: number | null) =>
    req<{ identity_character_id: number | null; identity_character_name: string; identity_image_url: string }>(
      `/api/projects/${pid}/elements/${eid}/identity`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ ark_character_id: arkCharacterId }) }),
  // 增删要素设定图手选参考图（资产面板挑的项目图片资产）；生成设定图时并入参考池喂给出图模型
  updateElementExtraRefs: (pid: number, eid: number,
    change: { add?: { name: string; kind: string; url: string }; remove?: string }) =>
    req<{ extra_refs: { name: string; kind: string; url: string }[] }>(
      `/api/projects/${pid}/elements/${eid}/extra-refs`,
      { method: 'PATCH', headers: J, body: JSON.stringify(change) }),
  // 要素设定图参考图启停：停用名单（存 meta.sheet_ref_off，生成时不上传其图）
  updateElementRefs: (pid: number, eid: number, off: string[]) =>
    req<{ sheet_ref_off: string[] }>(`/api/projects/${pid}/elements/${eid}/refs`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ off }) }),
  // AI 按要求改写要素生图提示词（同步返回，不落库——回填编辑框由用户确认保存）；instruction 空=按设定重写
  aiEditElementPrompt: (pid: number, eid: number, instruction: string, prompt?: string, variantId?: string) =>
    req<{ prompt: string }>(`/api/projects/${pid}/elements/${eid}/prompt/ai-edit`,
      { method: 'POST', headers: J,
        body: JSON.stringify({ instruction, prompt: prompt || null, variant_id: variantId || null }) }),
  // 直接把一张图应用为该要素设定图（跳过生成）：写 sheet_url + 落附件表；多形态可指定 variantId
  applyElementImage: (pid: number, eid: number, url: string, variantId?: string) =>
    req<{ sheet_url: string }>(`/api/projects/${pid}/elements/${eid}/apply-image`,
      { method: 'POST', headers: J, body: JSON.stringify({ url, variant_id: variantId || null }) }),
  // 保存要素的设定图清单（改描述 / 沿用开关 / 删除 / 排序）；≤1 张时后端折叠回单图
  saveElementVariants: (pid: number, eid: number,
    variants: { id?: string; tag?: string; desc?: string; inherit_ref?: boolean }[]) =>
    req<{ variants: ElementVariant[] }>(`/api/projects/${pid}/elements/${eid}/variants`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ variants }) }),
  // 加一张空设定图（外貌/档案沿用主图），返回新图 id，供前端立即打开出图弹框生成
  addElementVariant: (pid: number, eid: number) =>
    req<{ id: string; variants: ElementVariant[] }>(
      `/api/projects/${pid}/elements/${eid}/variants/add`, { method: 'POST', headers: J }),
  // 直接把一张图应用为本镜首帧/尾帧（跳过生成）
  applyShotFrame: (pid: number, sid: number, target: 'image' | 'last', url: string) =>
    req<Record<string, string>>(`/api/projects/${pid}/shots/${sid}/apply-frame`,
      { method: 'POST', headers: J, body: JSON.stringify({ target, url }) }),
  // 项目图片资产清单（添加参考面板）：要素设定图/故事板/首帧/封面
  listProjectAssets: (pid: number) => req<ProjectAsset[]>(`/api/projects/${pid}/assets`),
  // 上传一张参考图 → OSS + 附件表（meta.type=ref），返回 {name,url} 作参考图用
  uploadAsset: (pid: number, file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return req<{ id: number; name: string; kind: string; url: string }>(
      `/api/projects/${pid}/assets/upload`, { method: 'POST', body: fd })
  },
  // 从视频抽一帧存为项目参考图（素材面板「从视频中抽」）：ffmpeg 秒级抽帧→附件表(meta.type=ref)
  extractAssetFrameFromVideo: (pid: number, body: { atSec: number; videoUrl?: string; file?: File }) => {
    const fd = new FormData()
    fd.append('at_sec', String(body.atSec))
    if (body.file) fd.append('file', body.file)
    else if (body.videoUrl) fd.append('video_url', body.videoUrl)
    return req<{ id: number; name: string; kind: string; url: string }>(
      `/api/projects/${pid}/assets/frame-from-video`, { method: 'POST', body: fd })
  },
  // 给没有封面的视频补封面（素材库 hover「生成封面」）：后端抽首帧转存 OSS 并回写，返回封面 URL
  genVideoCover: (pid: number, body: { attachmentId?: number | null; videoUrl: string }) =>
    req<{ cover_url: string }>(`/api/projects/${pid}/assets/video-cover`,
      { method: 'POST', headers: J, body: JSON.stringify({ attachment_id: body.attachmentId ?? null, video_url: body.videoUrl }) }),
  // 生成一张独立参考图或一段素材视频：出图/出片存附件表 + 落 gen_logs；refs=子弹框挑的参考。
  // opts 两开关（新增素材弹框）：useProject=参考项目总体设定，useKb=采用系统知识构建；全关=纯享模式
  generateAsset: (pid: number, prompt: string, refs?: { name: string; kind: string; url: string }[],
    opts?: { media?: 'image' | 'video'; useProject?: boolean; useKb?: boolean }) =>
    req<{ id: number; name: string; kind: string; url: string }>(
      `/api/projects/${pid}/assets/generate`,
      { method: 'POST', headers: J, body: JSON.stringify({ prompt, refs: refs ?? null,
        media: opts?.media ?? 'image', use_project: opts?.useProject ?? false, use_kb: opts?.useKb ?? false }) }),
  // AI 写/改素材生成提示词（同步返回，不落库）；instruction 空=新写一版；
  // opts.media=video 按视频口径起草，useProject=false（纯享模式）不带项目题材上下文
  aiPromptAsset: (pid: number, instruction: string, prompt?: string,
    opts?: { media?: 'image' | 'video'; useProject?: boolean }) =>
    req<{ prompt: string }>(`/api/projects/${pid}/assets/ai-prompt`,
      { method: 'POST', headers: J, body: JSON.stringify({ instruction, prompt: prompt || null,
        media: opts?.media ?? 'image', use_project: opts?.useProject ?? true }) }),
  // 资产库：项目内全部生成/上传产物（图/视频/音频）+ 封面，分组供浏览/用作参考/设为封面
  assetLibrary: (pid: number) => req<AssetItem[]>(`/api/projects/${pid}/asset-library`),
  workflowArtifactSource: (attachmentId: number) => req<WorkflowArtifactSource | null>(`/api/workflows/artifacts/${attachmentId}/source`),
  // 增删镜级手选额外参考（资产面板挑的非要素图片资产）；要素类走 updateShotElements，启停走 updateShotRefs
  updateShotExtraRefs: (pid: number, sid: number,
    change: { add?: { name: string; kind: string; url: string }; remove?: string }) =>
    req<{ extra_refs: { name: string; kind: string; url: string }[] }>(
      `/api/projects/${pid}/shots/${sid}/extra-refs`,
      { method: 'PATCH', headers: J, body: JSON.stringify(change) }),
  // 捏音色：为角色设计并绑定专属音色（instruction 可空=按性格自主设计）
  designVoice: (pid: number, eid: number, instruction?: string) =>
    req<{ binding: VoiceBinding; spec: VoiceSpec; reused: boolean }>(
      `/api/projects/${pid}/elements/${eid}/voice`, {
        method: 'POST', headers: J, body: JSON.stringify({ instruction: instruction || null }),
      }),
  castVoices: (pid: number) =>
    req<{ cast: ({ element: string; error?: string } & Partial<VoiceBinding>)[] }>(
      `/api/projects/${pid}/voices/cast`, { method: 'POST' }),
  // 音色库
  listVoices: () => req<KbEntry[]>('/api/admin/voices'),
  getVoice: (id: number) => req<KbEntry>(`/api/admin/voices/${id}`),
  bindVoicePresets: () => req<{ bound: number }>('/api/admin/voices/bind-presets', { method: 'POST' }),
  genVoiceSamples: () => req<{ task_id: number }>('/api/admin/voices/samples', { method: 'POST' }),
  // 生成试听样本并保存到 meta.sample_audio_url（覆盖）；试听=直接播已存 URL
  genVoiceSample: (id: number, text?: string) =>
    req<{ url: string }>(`/api/admin/voices/${id}/sample`, {
      method: 'POST', headers: J, body: JSON.stringify(text ? { text } : {}),
    }),
  // 生成 5 情绪试听小样（喜怒哀乐+平，按角色定制），存 meta.samples
  genVoiceEmotionSamples: (id: number) =>
    req<{ samples: VoiceSample[]; mode: string }>(`/api/admin/voices/${id}/emotion-samples`, { method: 'POST' }),
  // 音色年龄滑块：存数字年龄并按人物特征库重推档位+换年龄标签
  setVoiceAge: (id: number, ageYears: number) =>
    req<{ ok: boolean; age: string; tags: string[] }>(`/api/admin/voices/${id}/age`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ age_years: ageYears }) }),
  // 角色年龄滑块：存 meta.age_years（捏音色/外貌补档的最优先年龄依据）
  setElementAge: (pid: number, eid: number, ageYears: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/elements/${eid}/age`,
      { method: 'PATCH', headers: J, body: JSON.stringify({ age_years: ageYears }) }),
  // 系统管理
  listKb: (params?: { kind?: string; category?: string; folder_id?: number }) => {
    const q = new URLSearchParams(params as unknown as Record<string, string>).toString()
    return req<KbEntry[]>(`/api/admin/kb${q ? '?' + q : ''}`)
  },
  // 知识库文件夹（系统文件夹=角色库/音色库/画风库/文风库等虚拟视图；自定义可增删改名）
  listKbFolders: () => req<KbFolder[]>('/api/admin/kb-folders'),
  createKbFolder: (body: { name: string; title: string; kind?: string }) =>
    req<KbFolder>('/api/admin/kb-folders', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  renameKbFolder: (id: number, title: string) =>
    req<KbFolder>(`/api/admin/kb-folders/${id}`, { method: 'PUT', headers: J, body: JSON.stringify({ title }) }),
  deleteKbFolder: (id: number) => req<{ ok: boolean }>(`/api/admin/kb-folders/${id}`, { method: 'DELETE' }),
  // 条目缩略图：提示词生图→OSS 转存→回写 thumbnail_url（留空 prompt=按条目正向词+示例场景）
  genKbThumbnail: (id: number, prompt?: string) =>
    req<{ thumbnail_url: string }>(`/api/admin/kb/${id}/thumbnail`, {
      method: 'POST', headers: J, body: JSON.stringify({ prompt: prompt || null }),
    }),
  // 标签词表：分组（视频类型/风格类型为内置受保护）+ 标签（名称/code/缩略图）
  listTagGroups: () => req<TagGroup[]>('/api/admin/tag-groups'),
  createTagGroup: (body: { code: string; title: string; seq?: number }) =>
    req<TagGroup>('/api/admin/tag-groups', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateTagGroup: (id: number, body: { title: string; seq?: number }) =>
    req<TagGroup>(`/api/admin/tag-groups/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  deleteTagGroup: (id: number) => req<{ ok: boolean }>(`/api/admin/tag-groups/${id}`, { method: 'DELETE' }),
  createTag: (body: { group_id: number; code: string; name: string; thumbnail_url?: string; seq?: number }) =>
    req<Tag>('/api/admin/tags', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateTag: (id: number, body: { name: string; thumbnail_url?: string; seq?: number }) =>
    req<Tag>(`/api/admin/tags/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  deleteTag: (id: number) => req<{ ok: boolean }>(`/api/admin/tags/${id}`, { method: 'DELETE' }),
  // 引导式新建：画风/文风选择库
  styleLibrary: (target: 'art' | 'writing') =>
    req<StyleOption[]>(`/api/style-library?target=${target}`),
  createKb: (body: Partial<KbEntry>) =>
    req<KbEntry>('/api/admin/kb', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateKb: (id: number, body: Partial<KbEntry>) =>
    req<KbEntry>(`/api/admin/kb/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  deleteKb: (id: number) => req<{ ok: boolean }>(`/api/admin/kb/${id}`, { method: 'DELETE' }),
  // 只改排序权重（画风/音色/角色等库内卡片通用；越大越靠前）
  setKbWeight: (id: number, weight: number) =>
    req<{ id: number; weight: number }>(`/api/admin/kb/${id}/weight`,
      { method: 'PUT', headers: J, body: JSON.stringify({ weight }) }),
  // 生成审计日志（系统管理）：入参与异步结果按 task_id 关联
  listGenLogs: (params?: { project_id?: number; node_id?: number; status?: string
    media?: 'video' | 'image'; source?: string; task_id?: number; page?: number; page_size?: number }) => {
    const q = new URLSearchParams(
      Object.fromEntries(Object.entries(params ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))
    ).toString()
    return req<GenLogPage>(`/api/admin/gen-logs${q ? '?' + q : ''}`)
  },
  // 模型配置
  listModels: () => req<ModelProfile[]>('/api/admin/models'),
  /** 模型能力档案（2026-09-17）：画布/生成条按 active 档自适应（公开只读，无密钥）。
   * refs.max 控参考图槽位、aspects 控比例选项、profile.name 供模型名展示。 */
  getModelCapabilities: (purpose: 'image' | 'video' | 'text' = 'image') =>
    req<{ purpose: string; active: ModelCapabilities | null; profiles: (ModelCapabilities & { extra?: unknown })[] }>(
      `/api/models/capabilities?purpose=${purpose}`),
  listProviderKeys: () => req<ProviderKeyPreset[]>('/api/admin/provider-keys'),
  createModel: (body: Record<string, unknown>) =>
    req<ModelProfile>('/api/admin/models', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateModel: (id: number, body: Record<string, unknown>) =>
    req<ModelProfile>(`/api/admin/models/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  testModel: (body: Record<string, unknown>) =>
    req<ModelTestResult>('/api/admin/models/test', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  activateModel: (id: number) =>
    req<{ ok: boolean }>(`/api/admin/models/${id}/activate`, { method: 'POST' }),
  deleteModel: (id: number) => req<{ ok: boolean }>(`/api/admin/models/${id}`, { method: 'DELETE' }),
  // 模型厂商：登记厂商凭据（key 只回掩码；编辑留空=沿用原 key）
  listVendors: () => req<ModelVendor[]>('/api/admin/vendors'),
  createVendor: (body: { label: string; provider: string; base_url: string; api_key: string }) =>
    req<ModelVendor>('/api/admin/vendors', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateVendor: (id: number, body: { label: string; provider: string; base_url: string; api_key: string }) =>
    req<ModelVendor>(`/api/admin/vendors/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  deleteVendor: (id: number) =>
    req<{ ok: boolean }>(`/api/admin/vendors/${id}`, { method: 'DELETE' }),
  // 功能配置：功能清单后端写死，这里只读列表 + 整表替换某功能的模型顺序（第一个=默认）
  listModelFeatures: () => req<FeatureModelConfig[]>('/api/admin/model-features'),
  saveModelFeature: (code: string, model_profile_ids: number[]) =>
    req<{ ok: boolean }>(`/api/admin/model-features/${code}`, {
      method: 'PUT', headers: J, body: JSON.stringify({ model_profile_ids }),
    }),
  skillPackages: () => req<SkillPackage[]>('/api/admin/skill-packages'),
  installSkillPackage: (source_url: string) =>
    req<SkillPackage>('/api/admin/skill-packages/install', {
      method: 'POST', headers: J, body: JSON.stringify({ source_url }),
    }),
  agentTemplates: () => req<AgentTemplate[]>('/api/admin/agent-templates'),
  createAgentTemplate: (body: Omit<AgentTemplate, 'id' | 'skills'> & { skill_ids: number[] }) =>
    req<AgentTemplate>('/api/admin/agent-templates', {
      method: 'POST', headers: J, body: JSON.stringify(body),
    }),
  updateAgentTemplate: (id: number, body: Omit<AgentTemplate, 'id' | 'skills'> & { skill_ids: number[] }) =>
    req<AgentTemplate>(`/api/admin/agent-templates/${id}`, {
      method: 'PUT', headers: J, body: JSON.stringify(body),
    }),
  expertTeams: () => req<ExpertTeam[]>('/api/admin/expert-teams'),
  testRuns: () => req<TestRunSummary[]>('/api/admin/test-runs'),
  testRun: (runId: string) => req<TestLog[]>(`/api/admin/test-runs/${runId}`),
  createTestRun: (body: { title: string; project_id?: number; summary?: string }) =>
    req<TestLog>('/api/admin/test-runs', {
      method: 'POST', headers: J, body: JSON.stringify(body),
    }),
  createTestStep: (runId: string, body: {
    project_id?: number; test_item: string; status?: string
    employee_codes?: string[]; skill_slugs?: string[]; knowledge_refs?: string[]
    sop_code?: string; planner_snapshot?: Record<string, unknown>
    request?: Record<string, unknown>; result?: Record<string, unknown>
    error?: string; task_id?: number; provider?: string; model?: string; duration_ms?: number
  }) => req<TestLog>(`/api/admin/test-runs/${runId}/steps`, {
    method: 'POST', headers: J, body: JSON.stringify(body),
  }),
  updateTestStep: (stepId: number, body: Partial<Omit<TestLog,
    'id' | 'kind' | 'source' | 'test_run_id' | 'test_item' | 'created_at' | 'finished_at'>>) =>
    req<TestLog>(`/api/admin/test-steps/${stepId}`, {
      method: 'PATCH', headers: J, body: JSON.stringify(body),
    }),
  finishTestRun: (runId: string) =>
    req<TestLog>(`/api/admin/test-runs/${runId}/finish`, { method: 'POST' }),
  // 资源包剩余
  listResourcePackages: (p?: {
    search?: string; modality?: string; vendor?: ResourceVendor; only_remaining?: boolean
  }) => {
    const q = new URLSearchParams()
    if (p?.search) q.set('search', p.search)
    if (p?.modality) q.set('modality', p.modality)
    if (p?.vendor) q.set('vendor', p.vendor)
    if (p?.only_remaining === false) q.set('only_remaining', 'false')
    const s = q.toString()
    return req<ResourcePackage[]>(`/api/admin/resource-packages${s ? '?' + s : ''}`)
  },
  /** 重传某厂商控制台导出的 CSV：只替换该厂商的行，另一家不受影响 */
  importResourcePackages: (file: File, vendor: ResourceVendor = 'volc') => {
    const fd = new FormData(); fd.append('file', file); fd.append('vendor', vendor)
    return req<{ count: number }>('/api/admin/resource-packages/import', { method: 'POST', body: fd })
  },
  /** 手动登记一条资源包/免费额度（百炼控制台无 CSV 导出时用） */
  createResourcePackage: (body: {
    vendor: ResourceVendor; config_name: string; total?: number; remaining?: number
    spec_unit?: string; expires_at?: string; status?: string; product?: string
  }) => req<ResourcePackage>('/api/admin/resource-packages', {
    method: 'POST', headers: J, body: JSON.stringify(body),
  }),
  /** 用系统内置的厂商 Key 直接试这个资源包里的模型（不必先插入模型管理） */
  testResourcePackage: (instanceId: string, prompt: string) =>
    req<ModelTestResult>(`/api/admin/resource-packages/${encodeURIComponent(instanceId)}/test`, {
      method: 'POST', headers: J, body: JSON.stringify({ prompt }),
    }),
  deleteResourcePackage: (instanceId: string) =>
    req<{ ok: boolean }>(`/api/admin/resource-packages/${encodeURIComponent(instanceId)}`, { method: 'DELETE' }),
  // 案例库（浏览型生成案例，与知识库分离，不参与召回）
  listCaseGroups: () => req<CaseGroup[]>('/api/case-library/groups'),
  createCaseGroup: (title: string) =>
    req<CaseGroup>('/api/case-library/groups', { method: 'POST', headers: J, body: JSON.stringify({ title }) }),
  updateCaseGroup: (id: number, body: { title: string; seq?: number }) =>
    req<CaseGroup>(`/api/case-library/groups/${id}`, { method: 'PUT', headers: J, body: JSON.stringify({ seq: 0, ...body }) }),
  deleteCaseGroup: (id: number) =>
    req<{ ok: boolean }>(`/api/case-library/groups/${id}`, { method: 'DELETE' }),
  listCaseEntries: (groupId?: number) =>
    req<CaseEntry[]>(`/api/case-library/entries${groupId != null ? `?group_id=${groupId}` : ''}`),
  createCaseEntry: (body: Partial<CaseEntry>) =>
    req<CaseEntry>('/api/case-library/entries', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateCaseEntry: (id: number, body: Partial<CaseEntry>) =>
    req<CaseEntry>(`/api/case-library/entries/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  deleteCaseEntry: (id: number) =>
    req<{ ok: boolean }>(`/api/case-library/entries/${id}`, { method: 'DELETE' }),
  uploadCaseAsset: (file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return req<{ url: string; name: string; size: number }>('/api/case-library/upload', { method: 'POST', body: fd })
  },
  // 独立角色库（形象图单向注册火山素材库，与知识库分离）
  listArkCharacters: (sourceProjectId?: number) =>
    req<ArkCharacter[]>(`/api/character-library/characters${sourceProjectId != null ? `?source_project_id=${sourceProjectId}` : ''}`),
  getArkCharacter: (id: number) => req<ArkCharacter>(`/api/character-library/characters/${id}`),
  createArkCharacter: (body: Partial<ArkCharacter>) =>
    req<ArkCharacter>('/api/character-library/characters', { method: 'POST', headers: J, body: JSON.stringify(body) }),
  updateArkCharacter: (id: number, body: Partial<ArkCharacter>) =>
    req<ArkCharacter>(`/api/character-library/characters/${id}`, { method: 'PUT', headers: J, body: JSON.stringify(body) }),
  deleteArkCharacter: (id: number) =>
    req<{ ok: boolean }>(`/api/character-library/characters/${id}`, { method: 'DELETE' }),
  registerArkCharacter: (id: number) =>
    req<{ ok: boolean }>(`/api/character-library/characters/${id}/register`, { method: 'POST' }),
  unregisterArkCharacter: (id: number) =>
    req<{ ok: boolean }>(`/api/character-library/characters/${id}/unregister`, { method: 'POST' }),
  // 分组：批量把某分类下 old 分组的全部条目改名为 new（new 为空=解散该组）；不动火山备案
  renameArkGroup: (category: string, oldName: string, newName: string) =>
    req<{ ok: boolean; updated: number }>('/api/character-library/rename-group',
      { method: 'POST', headers: J, body: JSON.stringify({ category, old_name: oldName, new_name: newName }) }),
  uploadCharacterImage: (file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return req<{ url: string; name: string; size: number }>('/api/character-library/upload', { method: 'POST', body: fd })
  },
  generateCharacterImage: (prompt: string, size?: string) =>
    req<{ url: string }>('/api/character-library/generate-image', { method: 'POST', headers: J, body: JSON.stringify({ prompt, ...(size ? { size } : {}) }) }),
  resourcePackageToModel: (instanceId: string, activate: boolean) =>
    req<{ id: number; purpose: string; name: string; model_name: string; activated: boolean; reused: boolean }>(
      `/api/admin/resource-packages/${encodeURIComponent(instanceId)}/to-model`,
      { method: 'POST', headers: J, body: JSON.stringify({ activate }) }),
  // 系统配置：首页背景（多组轮播，前端当前只取第一组）
  getHomeBg: () => req<{ groups: HomeBgGroup[] }>('/api/app-config/home-bg'),
  setHomeBg: (groups: HomeBgGroup[]) =>
    req<{ groups: HomeBgGroup[] }>('/api/app-config/home-bg', { method: 'PUT', headers: J, body: JSON.stringify({ groups }) }),
  // 系统配置：生成配置（生成真人角色卡 / 允许项目直传火山等开关）；PUT 只发变动字段，后端按字段合并
  getGenConfig: () => req<GenConfig>('/api/app-config/gen-config'),
  setGenConfig: (cfg: Partial<GenConfig>) =>
    req<GenConfig>('/api/app-config/gen-config', { method: 'PUT', headers: J, body: JSON.stringify(cfg) }),
  // 工具（系统管理 → 工具）：查询走只读 SQL，增删改走命名动作；将来技能也从这里取清单
  listTools: () => req<{ me: SysUser; tools: ToolSpec[] }>('/api/tools'),
  invokeTool: (name: string, args: Record<string, unknown>, projectId?: number) =>
    req<{ ok: boolean; tool: string; result: unknown }>(`/api/tools/${encodeURIComponent(name)}/invoke`,
      { method: 'POST', headers: J, body: JSON.stringify({ args, project_id: projectId ?? null }) }),
  listToolCalls: (tool?: string) =>
    req<ToolCall[]>(`/api/tools/calls${tool ? `?tool=${encodeURIComponent(tool)}` : ''}`),
  listUsers: () => req<SysUser[]>('/api/users'),
  /** 能力目录：工具与 tapflow 抹平成同一种条目。与规划节点看到的是同一份。 */
  listCapabilities: () =>
    req<{ capabilities: Capability[] }>('/api/agents/capabilities'),
}

export interface SysUser { id: string; name: string; role: 'dev' | 'admin'; enabled: boolean }
export interface ToolParam {
  type: string; required?: boolean; desc?: string
  items?: { type?: string; properties?: Record<string, ToolParam> }
}
export interface ToolSpec {
  name: string
  title: string
  description: string
  group: string
  writes: boolean
  params: Record<string, ToolParam>
  outputs: Record<string, ToolParam>
}
/**
 * 一条能力：工具与 tapflow 共用这一种形状（后端 services/capabilities）。
 * `id` 的 `tool:` / `flow:` 前缀只表示当前实现载体，语义不看前缀——能力从工具迁成
 * 流程时，用它的编排不需要改。
 */
export interface Capability {
  id: string
  kind: 'tool' | 'flow'
  title: string
  description: string
  group: string
  writes: boolean
  cardinality: 'one' | 'many'
  inputs: Record<string, ToolParam>
  outputs: Record<string, ToolParam>
  version?: number
  costly_nodes?: number
  superseded_by?: string
}
export interface ToolCall {
  id: number; tool: string; caller: string; source: string; project_id: number | null
  args: string; ok: boolean; row_count: number | null; error: string | null
  duration_ms: number | null; created_at: string
}
/** db.query 的返回体（其余工具返回自定义结构，前端按 JSON 原样展示）。 */
export interface ToolQueryResult {
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  truncated: boolean
}

export interface HomeBgGroup { image: string; video: string }
export interface GenConfig {
  realistic_character: boolean
  // 允许项目角色面板直接上传到火山虚拟角色库；false=隐藏项目侧直传入口，统一到角色库管理
  allow_project_ark_upload: boolean
}
