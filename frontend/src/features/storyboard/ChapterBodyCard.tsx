import type { Chapter } from '../../api'
import { Icon } from '../../components/Icon'
import { useChapterBody } from '../../lib/useChapterBody'

/** 总览辅助区 ·「本章正文」：本集尚未拆镜时顶替关联要素/场景锚定两块，
 * 让辅助区直接可读拆镜所依据的原文。正文自带滚动，长章不把辅助区撑成一条长滚动。 */
export function ChapterBodyCard({ pid, chapter }: { pid: number; chapter: Chapter }) {
  const { body, loading } = useChapterBody(pid, chapter.id)
  return (
    <div className="aux-block">
      <div className="aux-title ov-title">
        <Icon name="text" /> 第{chapter.seq}章 正文
        {!!body && <span className="tag">{body.length} 字</span>}
      </div>
      {chapter.summary && <p className="cb-summary">{chapter.summary}</p>}
      {loading
        ? <div className="dim ov-empty">正文加载中…</div>
        : body
          ? <div className="cb-text">{body}</div>
          : <div className="dim ov-empty">本章尚无正文，先到「剧集 · 正文」生成后再拆镜</div>}
    </div>
  )
}
