import { Icon, type IconName } from '../../components/Icon'

/** 总览辅助区的「一块总览」：标题行（图标 + 标题 + 计数 + 右侧画布入口）+ 3 列图块网格。
 * 图块与前置条件区同口径——有图=缩略图，无图=同尺寸虚线占位（点击进对应画布去出图）。 */
export interface OverviewTile {
  key: string
  url?: string | null
  icon: IconName        // 无图时的占位图标
  label: string         // 图块下方主标题（第N张 / 场景N）
  note?: string         // 副行：覆盖镜号 / 空间说明 / 待生成
  hint: string          // title 提示（≤5 字）
  onClick?: () => void
}

export function OverviewTileGrid({ title, icon, count, actionLabel, onAction, busy, tiles, empty }: {
  title: string
  icon: IconName
  count?: string
  actionLabel?: string
  onAction?: () => void
  busy?: boolean
  tiles: OverviewTile[]
  empty: string         // 无条目时的说明文字
}) {
  return (
    <div className="aux-block">
      <div className="aux-title ov-title">
        <Icon name={icon} /> {title}
        {count && <span className="tag">{count}</span>}
        {onAction && actionLabel && (
          <button type="button" className="small ghost pre-canvas-btn" onClick={onAction}
            title={actionLabel}>
            {busy ? <Icon name="spinner" spin /> : <Icon name="workflow" />} {actionLabel}
          </button>
        )}
      </div>
      {tiles.length ? (
        <div className="ov-grid">
          {tiles.map(t => (
            <button type="button" key={t.key} className={`ov-tile${t.url ? ' ready' : ''}`}
              disabled={!t.onClick} onClick={t.onClick} title={t.hint}>
              {t.url ? <img src={t.url} alt={t.label} loading="lazy" /> : <Icon name={t.icon} />}
              <b>{t.label}</b>
              {t.note && <span>{t.note}</span>}
            </button>
          ))}
        </div>
      ) : <div className="dim ov-empty">{empty}</div>}
    </div>
  )
}
