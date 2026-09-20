import { useEffect, useState } from 'react'
import { api } from '../api'

/** 章节正文（只读）：按 项目/章节 拉取正文文本；切章自动重取并丢弃过期响应。 */
export function useChapterBody(pid: number, chapterId: number) {
  const [body, setBody] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let on = true
    setLoading(true); setBody('')
    api.getBody(pid, chapterId)
      .then(r => { if (on) setBody(r.content || '') })
      .catch(() => { if (on) setBody('') })
      .finally(() => { if (on) setLoading(false) })
    return () => { on = false }
  }, [pid, chapterId])
  return { body, loading }
}
