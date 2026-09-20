import type { Element } from '../../api'
import { openLightbox } from '../../lib/lightbox'
import { Icon } from '../../components/Icon'
import { LightboxInfo } from '../../components/LightboxInfo'

/** 本章角色设定带（Character Design & Casting） */
export function CastBar({ cast }: { cast: Element[] }) {
  return (
    <div className="card cast-bar">
      <h2><Icon name="users" /> 本章角色设定（Character Design &amp; Casting）</h2>
      <div className="cast-strip">
        {cast.map(c => (
          <div key={c.id} className="cast-card">
            {c.meta.sheet_url
              ? <img src={c.meta.sheet_url} alt={c.name} className="zoomable"
                  title="点击放大" onClick={() => openLightbox(c.meta.sheet_url!, c.name, <LightboxInfo sections={[
                    { label: '简介', text: c.brief },
                    { label: '外貌提示词', text: c.meta.外貌提示词 },
                  ]} />)} />
              : <div className="cast-empty">未生成设定图</div>}
            <b>{c.name}</b>
            <div className="dim">{c.brief?.slice(0, 40)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
