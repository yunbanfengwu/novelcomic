import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Chapter } from '../../api'
import { useParentWidth } from '../../lib/useParentWidth'
import './ChapterPager.css'

/** 每个页码格占宽：44px 方块 + 6px 间隙 */
const SLOT_W = 50
/** 固定件占宽：‹ › 两钮 + 「共 N 集」标签（估宽，含间隙），页码预算须先扣掉 */
const FIXED_W = 2 * SLOT_W + 110

/** 窗口化页码：容纳数够则全显；不够只显以当前为中心的连续窗口，靠边时平移补足 */
function pageWindow(current: number, total: number, count: number): number[] {
  if (count <= 0) return []
  const range = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => a + i)
  if (total <= count) return range(1, total)
  let start = current - Math.floor((count - 1) / 2)
  let end = start + count - 1
  if (start < 1) { end += 1 - start; start = 1 }
  if (end > total) { start -= end - total; end = total }
  return range(Math.max(1, start), end)
}

/** 跳集分页：‹ 45 … 55 › [共 XX 集]。页码数按所在容器宽度 70% 折算（最少 0 个，窄屏只剩 ‹ › + 全部）；点「共 XX 集」唤起浮窗显示全部集。 */
export function ChapterPager({ id, chapters, current }: { id: number; chapters: Chapter[]; current: number }) {
  const navigate = useNavigate()
  const [showAll, setShowAll] = useState(false)
  const { ref, width } = useParentWidth()
  const slots = Math.max(0, Math.floor((width * 0.7 - FIXED_W) / SLOT_W))
  const total = chapters.length
  const curPos = Math.max(1, chapters.findIndex(c => c.seq === current) + 1 || 1)

  const go = (pos: number) => {
    const seq = chapters[pos - 1]?.seq
    if (seq != null) { navigate(`/project/${id}/video/${seq}`); setShowAll(false) }
  }

  if (!total) return null
  return (
    <div className="pager" ref={ref}>
      <button className="pager-btn" disabled={curPos <= 1} onClick={() => go(curPos - 1)} title="上一集">‹</button>
      {pageWindow(curPos, total, slots).map(p =>
        <button key={p} className={`pager-btn${p === curPos ? ' active' : ''}`} onClick={() => go(p)}>{p}</button>
      )}
      <button className="pager-btn" disabled={curPos >= total} onClick={() => go(curPos + 1)} title="下一集">›</button>
      <div className="pager-total-wrap">
        <button className="pager-total" onClick={() => setShowAll(v => !v)} title="全部集">共 {total} 集<span className="pager-total-caret">»</span></button>
        {showAll && (
          <>
            <div className="pager-all-backdrop" onClick={() => setShowAll(false)} />
            <div className="pager-all" role="dialog" aria-label="全部集">
              <div className="pager-all-grid">
                {chapters.map((_, i) =>
                  <button key={i} className={`pager-btn${i + 1 === curPos ? ' active' : ''}`} onClick={() => go(i + 1)}>{i + 1}</button>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
