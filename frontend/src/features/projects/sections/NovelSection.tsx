import { Icon } from '../../../components/Icon'

/** 小说分区：成书视角的连续小说文本（可为空，功能开发中） */
export function NovelSection() {
  return (
    <div className="section-scroll">
      <div className="empty-hint"><Icon name="book" /> 小说功能开发中 —— 这里将展示成书视角的连续小说文本（区别于分集视频脚本）</div>
    </div>
  )
}
