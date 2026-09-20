// 提示词版本历史：按 (项目, 镜头, 类型) 存快照，供版本回退用。
// 优先 IndexedDB（容量大、跨刷新持久）；不可用（隐私模式/旧环境）时回落 sessionStorage。
// 所有写入都吞掉异常——历史落盘失败不该阻断出图/出视频。

// 首帧/视频/尾帧 + 要素设定图(element) + 封面(cover) + 独立参考图(ref) + 先导预告片(trailer)：各宿主的历史归类维度
export type PromptTarget = 'image' | 'video' | 'last' | 'element' | 'cover' | 'ref' | 'asset_video' | 'trailer'

export interface PromptVersion {
  ts: number                                  // 快照时间戳（Date.now）
  seq?: number | string                       // 镜头序号（shot_no，人读；手动插入镜为小数号；要素/封面无此维度）
  target: PromptTarget                        // 类型：首帧/视频/尾帧/要素/封面
  reason: 'generate' | 'ai-edit' | 'save' | 'regen'   // 触发场景（决定标签）
  prompt: string
}

const DB_NAME = 'novelcomic-prompt-history'   // 专用库名，避免与其它 novelcomic 库版本冲突
const STORE = 'versions'
const CAP = 30                                // 每 key 最多保留的版本数（超出丢最旧）

/** 稳定 key：同一镜头同一类型的历史归为一条记录（内含版本数组，新→旧）。 */
export function historyKey(pid: number, shotId: number, target: PromptTarget) {
  return `${pid}:${shotId}:${target}`
}

// 打开专用库；若库已存在却缺 STORE（历史遗留/异常），自动升版号补建，自愈不永久回落。
let dbP: Promise<IDBDatabase | null> | null = null
function openDB(): Promise<IDBDatabase | null> {
  if (dbP) return dbP
  dbP = new Promise(resolve => {
    try {
      if (typeof indexedDB === 'undefined') { resolve(null); return }
      const probe = indexedDB.open(DB_NAME)     // 不带版本：先探明当前版本
      probe.onerror = () => resolve(null)
      probe.onsuccess = () => {
        const db = probe.result
        if (db.objectStoreNames.contains(STORE)) { resolve(db); return }
        // 缺 STORE：升一个版本触发 onupgradeneeded 补建
        const nextV = db.version + 1
        db.close()
        const up = indexedDB.open(DB_NAME, nextV)
        up.onupgradeneeded = () => {
          const udb = up.result
          if (!udb.objectStoreNames.contains(STORE)) udb.createObjectStore(STORE)
        }
        up.onsuccess = () => resolve(up.result)
        up.onerror = () => resolve(null)
      }
    } catch { resolve(null) }
  })
  return dbP
}

// ── sessionStorage 回落 ──────────────────────────
const ssKey = (key: string) => `ph:${key}`
function ssGet(key: string): PromptVersion[] {
  try { const raw = sessionStorage.getItem(ssKey(key)); return raw ? JSON.parse(raw) : [] }
  catch { return [] }
}
function ssSet(key: string, list: PromptVersion[]) {
  try { sessionStorage.setItem(ssKey(key), JSON.stringify(list)) } catch { /* 配额满/隐私模式：忽略 */ }
}

/** 读取某镜某类型的全部版本（新→旧）。 */
export async function listPromptVersions(key: string): Promise<PromptVersion[]> {
  const db = await openDB()
  if (!db) return ssGet(key)
  return new Promise(resolve => {
    try {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(key)
      req.onsuccess = () => resolve((req.result as PromptVersion[] | undefined) ?? [])
      req.onerror = () => resolve(ssGet(key))
    } catch { resolve(ssGet(key)) }
  })
}

/** 追加一个版本到栈顶；与栈顶内容完全相同则跳过，空内容不入栈。永不抛错。 */
export async function pushPromptVersion(key: string, v: PromptVersion): Promise<void> {
  const prompt = (v.prompt ?? '').trim()
  if (!prompt) return
  const prev = await listPromptVersions(key)
  if (prev[0]?.prompt.trim() === prompt) return   // 去重：连续相同内容只留一条
  const next = [{ ...v, prompt }, ...prev].slice(0, CAP)
  const db = await openDB()
  if (!db) { ssSet(key, next); return }
  await new Promise<void>(resolve => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(next, key)
      tx.oncomplete = () => resolve()
      tx.onerror = () => { ssSet(key, next); resolve() }
    } catch { ssSet(key, next); resolve() }
  })
}
