// 「上次看到第几集」的会话级记忆：按项目 id 存于 sessionStorage
// （随标签页存活，关闭/新开窗口即清空；默认回到第一集）——不落库、不跨窗口。

const KEY = 'novelcomic:lastSeq'
type Store = Record<string, number> // pid -> seq

function read(): Store {
  try { return JSON.parse(sessionStorage.getItem(KEY) || '{}') } catch { return {} }
}

/** 取该项目上次停留的集号（本会话内）；无记录返回 undefined */
export function getLastSeq(pid: number): number | undefined {
  return read()[pid]
}

/** 记下该项目当前停留的集号（本会话内） */
export function setLastSeq(pid: number, seq: number): void {
  const s = read()
  s[pid] = seq
  try { sessionStorage.setItem(KEY, JSON.stringify(s)) } catch { /* 隐私模式等写失败：忽略 */ }
}
