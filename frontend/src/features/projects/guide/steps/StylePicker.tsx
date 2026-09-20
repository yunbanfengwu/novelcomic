import type { StyleOption } from '../../../../api'
import { Icon } from '../../../../components/Icon'
import { openLightbox } from '../../../../lib/lightbox'

/**
 * 画风/文风选择卡片墙（知识库画风库/文风库数据）：画风带缩略图，文风纯文字卡；
 * 末尾常驻「自定义」卡切换回自由输入+AI 评估。
 */
export function StylePicker({ kind, options, selectedName, customActive, onPick, onCustom }: {
  kind: 'writing' | 'art'
  options: StyleOption[]
  selectedName: string | null
  customActive: boolean
  onPick: (o: StyleOption) => void
  onCustom: () => void
}) {
  return (
    <div className="style-cards">
      {options.map(o => (
        <button key={o.id} type="button"
          className={`style-card${selectedName === o.name ? ' active' : ''}`}
          onClick={() => onPick(o)}>
          {kind === 'art' && (
            o.thumbnail_url ? (
              <span className="style-card-thumb-box">
                <img className="style-card-thumb" src={o.thumbnail_url} alt={o.title} />
                {/* 右下角放大：查看大图，不触发选中（阻止冒泡到卡片选择） */}
                <span className="style-card-zoom" title="查看大图"
                  onClick={e => { e.stopPropagation(); openLightbox(o.thumbnail_url!, o.title) }}>
                  <Icon name="search" />
                </span>
              </span>
            ) : (
              <div className="style-card-thumb style-card-thumb-empty"><Icon name="palette" /></div>
            )
          )}
          <div className="style-card-body">
            <b>{o.title}</b>
            <span className="dim">{o.content}</span>
            {!!o.tags?.length && (
              <span className="style-card-tags">
                {o.tags.map(t => <span key={t} className="tag">{t}</span>)}
              </span>
            )}
          </div>
          {selectedName === o.name && <span className="style-card-check"><Icon name="check" /></span>}
        </button>
      ))}
      <button type="button" className={`style-card style-card-custom${customActive ? ' active' : ''}`}
        onClick={onCustom}>
        {kind === 'art' && <div className="style-card-thumb style-card-thumb-empty"><Icon name="wand" /></div>}
        <div className="style-card-body">
          <b>自定义</b>
          <span className="dim">{kind === 'writing' ? '自由描述文风，可让 AI 评估' : '自由描述画风，可让 AI 评估'}</span>
        </div>
        {customActive && <span className="style-card-check"><Icon name="check" /></span>}
      </button>
    </div>
  )
}
