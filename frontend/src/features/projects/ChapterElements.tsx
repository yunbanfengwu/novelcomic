import type { Element } from '../../api'
import { KIND_META } from '../../lib/kinds'
import { openLightbox } from '../../lib/lightbox'
import { Icon } from '../../components/Icon'
import { LightboxInfo } from '../../components/LightboxInfo'

/** 本章关联要素：平铺展示与本章相关、且需要设定图的核心要素（角色/场景/设定…）；有图可点击放大，无图显示占位。 */
export function ChapterElements({ elements }: { elements: Element[] }) {
  return (
    <div className="card chapter-elements">
      <h2><Icon name="clip" /> 本章关联要素</h2>
      <div className="ce-strip">
        {elements.map(el => {
          const sheet = el.meta.sheet_url
          const icon = KIND_META[el.kind]?.icon ?? 'puzzle'
          return (
            <div key={el.id} className="ce-card">
              <div className="ce-card-left">
                {sheet
                  ? <img src={sheet} alt={el.name} className="zoomable" title="点击放大"
                      onClick={() => openLightbox(sheet, el.name, <LightboxInfo sections={[
                        { label: '简介', text: el.brief },
                        { label: '外貌提示词', text: el.meta.外貌提示词 },
                      ]} />)} />
                  : <div className="ce-noimg"><Icon name={icon} /></div>}
              </div>
              <div className="ce-card-right">
                <b>{el.name}</b>
                <div className="dim">{el.brief?.slice(0, 40)}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
