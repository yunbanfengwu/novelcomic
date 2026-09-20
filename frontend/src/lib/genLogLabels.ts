// ═══════════ 生成日志展示口径：状态/类型中文 + 时间格式（GenLogItem 与 GenLogPanel 共用）═══════════

export const GENLOG_STATUS_CN: Record<string, string> = {
  accepted: '已受理·生成中', rejected: '提交被拒', done: '成功', failed: '生成失败', submitted: '已提交',
}

export const GENLOG_KIND_CN: Record<string, string> = {
  gen_video: '视频', gen_keyframe: '首帧', gen_last_keyframe: '尾帧', gen_element_sheet: '设定图',
  gen_overview_grid: '宫格', gen_cover: '封面', gen_kb_thumb: '风格库', gen_scene_empty: '空场景图', gen_scene_sheet: '站位图',
  gen_ref: '参考图', gen_asset_video: '素材视频',
}

export const fmtLogTime = (s?: string | null) =>
  s ? new Date(s).toLocaleString('zh-CN', { hour12: false }) : ''
