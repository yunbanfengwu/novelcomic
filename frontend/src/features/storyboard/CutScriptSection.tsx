import type { ReactNode } from 'react'
import type { Shot } from '../../api'
import { Icon } from '../../components/Icon'
import { assignDialogue } from '../../lib/shotDialogue'

/** 分镜脚本区（纯展示）：故事概述 + 逐 cut 三列表（时间轴｜镜头语言｜内容）+ 兜底台词 + footer。
 * 台词按后端装配同一规则落到各切（lib/shotDialogue），标题栏右侧是「重做镜头设计」。
 * footer=区末尾插槽（现放本镜参考区）；站位/移动已归到「场景站位光影锚定」块。 */
export function CutScriptSection({ shot, busy, onRedesign, footer }: {
  shot: Shot
  busy: boolean
  onRedesign: () => void
  footer?: ReactNode
}) {
  const cuts = shot.meta.cuts ?? []
  const dialogue = assignDialogue(shot.meta.dialogue, cuts)
  let cutStart = 0
  return (
    <section className="inspector-section">
      {/* 标题行带本镜时长（原详情头的独立标签行已撤，参数就近落到对应卡片）。
          「承接上一镜」不在此重复——首切的「切入方式」标签已表达（承接上镜/起幅） */}
      <div className="inspector-section-title"><Icon name="workflow" /> 分镜脚本
        <span className="tag" title="本镜时长">{shot.meta.duration_s}s</span>
        <button type="button" className="small ghost vt-redesign-btn" disabled={busy}
          onClick={onRedesign}
          title="重新设计景别、正反打、反应镜、切内运镜与硬切时间轴，再装配提示词并质检">
          {busy ? <Icon name="spinner" spin /> : <Icon name="refresh" />} 重做镜头设计
        </button>
      </div>
      {/* 本镜故事概述（拆镜产物 summary）：脚本区顶部只出现一次，各生成卡不再重复 */}
      {shot.summary && <p className="cut-script-summary">{shot.summary}</p>}
      <div className="cut-script-list">
        {cuts.length ? cuts.map((cut, index) => {
          const start = cutStart
          const end = start + (cut.seconds ?? 0)
          cutStart = end
          return (
            <div className="cut-script-row" key={`${index}-${start}`}>
              <div className="cut-script-time">
                <b>Cut {index + 1}</b>
                <span>{start}–{end}秒</span>
              </div>
              {/* 中列＝镜头语言：景别 / 运镜 / 切入方式。切入方式是切与切之间的接法——
                  首切承上（本镜首帧接上一镜尾帧则为「承接」，否则「起幅」），其余切一律硬切
                  （装配时间轴写作「硬切至{景别}」，见 services/storyboard.py 的 _timeline_segments） */}
              <div className="cut-script-lens">
                {cut.scale && <span className="cut-tag">{cut.scale}</span>}
                <span className="cut-tag">{cut.camera_move || '固定'}</span>
                <span className="cut-tag cut-tag-join" title="切入方式">
                  {index ? '硬切' : shot.meta.link_prev ? '承接上镜' : '起幅'}
                </span>
              </div>
              <div className="cut-script-body">
                {/* 主体 + 动作同一行："修理区全景：岚音手中的工具在风帆翼上飞舞" */}
                {(cut.subject || cut.action) && (
                  <div className="cut-script-act">
                    {cut.subject && <b>{cut.subject}{cut.action ? '：' : ''}</b>}
                    {cut.action}
                  </div>
                )}
                {/* 本切台词：整镜 dialogue 按后端同一规则落位（说话人↔切主体），逐切显示 */}
                {dialogue.perCut[index]?.map((line, i) => (
                  <div className="cut-line" key={`${line.speaker}-${i}`}>
                    {line.speaker && <b className="cut-line-who">{line.speaker}：</b>}
                    {line.text}
                  </div>
                ))}
              </div>
            </div>
          )
        }) : (
          <div className="inspector-empty">暂无分段脚本，当前按单个连续镜头处理。</div>
        )}
      </div>
      {/* 落不到具体切的台词（说话人对不上任何切主体）。
          站位/镜内移动已移到「场景站位光影锚定」块右侧文字——空间信息集中在场景卡看 */}
      {dialogue.rest.length > 0 && (
        <div className="cut-script-notes">
          <div className="dim" title="说话人未匹配到任一切的主体；装配提示词时后端会为这些台词新开一切">
            <Icon name="chat" /> {cuts.length ? '未落到切：' : '台词：'}
            {dialogue.rest.map(l => `${l.speaker ? l.speaker + '：' : ''}${l.text}`).join(' / ')}
          </div>
        </div>
      )}
      {/* 末尾：本镜参考区（要素/音频/手选 + ＋添加）——本镜要产出的是视频，参考池就跟着脚本看 */}
      {footer}
    </section>
  )
}
