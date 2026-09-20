import type { SceneGroup } from '../../api'
import { stageBrief } from '../../lib/sceneSheet'
import { OverviewTileGrid, type OverviewTile } from './OverviewTileGrid'

/** 总览辅助区 ·「场景锚定总览」：本集每个场景组的场景空间站位图（本组各镜光影/空间以它为准）。
 * 与镜级前置条件区「场景站位光影锚定」同一份数据（useSceneGroups），点图块进该组的场景图画布。 */
export function SceneAnchorBlock({ groups, onOpenSheet }: {
  groups: SceneGroup[]
  onOpenSheet: (g: SceneGroup) => void
}) {
  const done = groups.filter(g => g.sheet_url).length
  const tiles: OverviewTile[] = groups.map((g): OverviewTile => {
    const nos = g.shot_nos ?? []
    return {
      key: `seg-${g.seg}`,
      url: g.sheet_url || g.empty_url,
      icon: 'scene',
      label: `场景${g.seg} · ${g.scene || '未命名'}`,
      note: [
        nos.length ? `镜${nos[0]}–${nos[nos.length - 1]}` : '未分配镜头',
        stageBrief(g),
      ].filter(Boolean).join(' · '),
      hint: g.sheet_url ? '进场景画布' : '去生成场景图',
      onClick: () => onOpenSheet(g),
    }
  })
  return (
    <OverviewTileGrid title="场景锚定总览" icon="scene"
      count={groups.length ? `${done}/${groups.length}组` : undefined}
      tiles={tiles} empty="本集未做场景空间规划" />
  )
}
