import type { ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import { Seg } from '../../components/Seg'
import type { TapProjectInfo } from '../../lib/tapflowData'

/**
 * 开始节点里的项目设定卡：本次运行落在哪个项目设定下。
 *
 * 两态同一套骨架，只换内容——未选项目时是占位（请选择项目 / 请选择画风 / 选择比例），
 * 选了就填真数据。骨架不变，选前选后位置不跳。
 *
 * **只读**：这些是项目的属性不是画布的，改要去项目页。比例与画风还会直接影响出图
 * （后端按项目比例算尺寸、按 art_style 召回画风块进 anchor 段），在这里只作交代。
 */
export function TapflowProjectCard({ info, aside, overall }: {
  info?: TapProjectInfo | null
  /** 右列插槽：流程入参排在真人/虚拟下面。入参不是项目属性，所以是插槽不是本件的字段 */
  aside?: ReactNode
  /** 未选项目时底部那条「整体设定」入参的当前值（没有项目做底，整体设定由人给） */
  overall?: string
}) {
  return (
    <div className={'tap-project-card' + (info ? '' : ' empty')}>
      <div className="tap-pc-title">{info ? info.title : '请选择项目'}</div>

      <div className="tap-pc-main">
        {/* 画风示意图：一眼看出项目长什么样，比一段画风文字管用。右下角叠画幅比例 */}
        {/* 有图就只放图——画风文字是给没图时兜底的，不跟图并排占位。
            不做 title 提示：前端规则里 tooltip 只概括功能且 ≤5 字，
            一整段画风描述属于「细节」，该放正文而不是塞进 tooltip。 */}
        <div className="tap-pc-art">
          {info?.styleImage
            ? <img src={info.styleImage} alt="" draggable={false} />
            : info?.artStyle
              ? <span className="tap-pc-art-text">{info.artStyle}</span>
              : <span className="tap-pc-art-empty">请选择画风</span>}
          <span className="tap-pc-aspect">{info ? info.aspect : '选择比例'}</span>
        </div>

        <div className="tap-pc-side">
          {/* 全局按钮组（components/Seg，与详情页「剧集/视频」同一套）。
              只读回显：角色类型是项目属性，改要去项目页，所以 onSelect 空实现 */}
          <Seg
            active={info?.characterMode}
            items={[
              { key: 'real', label: <><Icon name="user" /> 真人</>, title: '项目设定' },
              { key: 'virtual', label: <><Icon name="wand" /> 虚拟</>, title: '项目设定' },
            ]}
            onSelect={() => undefined} />
          {aside}
        </div>
      </div>

      {/* 底部整幅：选了项目就是项目的故事线与文风（只读，改去项目页）；
          没选项目就落到「整体设定」这个入参上——没有项目做底，整体设定得由人给。
          这里只展示值，填值在右侧运行面板（与章/场景等入参一致，不在画布上直接编辑）。 */}
      {info ? (
        <>
          {info.storyline && <p className="tap-pc-line">{info.storyline}</p>}
          {info.writingStyle && (
            <p className="tap-pc-line dim"><b>文风：</b>{info.writingStyle}</p>
          )}
        </>
      ) : (
        <div className={'tap-pc-overall' + (overall ? '' : ' empty')}>
          {overall || '请输入整体设定'}
        </div>
      )}
    </div>
  )
}
