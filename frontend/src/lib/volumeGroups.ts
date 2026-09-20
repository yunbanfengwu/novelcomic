import type { Chapter, Volume, VolumeOverrides, Project } from '../api'

/** 一卷及其章节（按卷序排列） */
export interface VolumeGroupData { volume: Volume; chapters: Chapter[] }

/**
 * 按卷把章节分组（卷按 seq 排列，卷内章节按 seq）。
 * 无卷（隐式卷1）时返回空数组——调用方据此走「平铺」渲染，不显示卷头。
 * 归属不到任何现存卷的散章（历史/异常）兜底并入第一卷，避免漏显。
 */
export function groupChaptersByVolume(volumes: Volume[], chapters: Chapter[]): VolumeGroupData[] {
  if (volumes.length === 0) return []
  const ordered = [...volumes].sort((a, b) => a.seq - b.seq)
  const ids = new Set(ordered.map(v => v.id))
  const byVol = new Map<number, Chapter[]>(ordered.map(v => [v.id, []]))
  const firstId = ordered[0].id
  for (const c of chapters) {
    const key = c.parent_id != null && ids.has(c.parent_id) ? c.parent_id : firstId
    byVol.get(key)!.push(c)
  }
  return ordered.map(v => ({ volume: v, chapters: byVol.get(v.id)!.sort((a, b) => a.seq - b.seq) }))
}

/** 卷某项设置的生效值：卷有覆盖则用覆盖，否则继承项目（用于回显「继承项目：xxx」）。 */
export function effectiveSetting(
  field: keyof VolumeOverrides, overrides: VolumeOverrides, project: Project,
): string {
  const ov = overrides[field]
  if (field === 'aspect_ratio') return (ov as string) || project.config.aspect_ratio || '16:9'
  if (field === 'art_style') return (ov as string) || project.art_style || ''
  if (field === 'writing_style') return (ov as string) || project.writing_style || ''
  return ''
}
