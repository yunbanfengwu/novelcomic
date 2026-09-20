import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { Element } from '../../api'
import { Icon } from '../../components/Icon'
import { arkBodyFromElement, canSubmitToArk, sameChar } from '../../lib/arkChar'

/** 批量提交本项目「已出设定图、未入库」的角色到火山虚拟人像库（真实照片感画风才需要，避开 Seedance
 * "疑似真人"拒收）。逐个 createArkCharacter（后端建条即自动注册），进度回显；无待提交角色时不出现。 */
export function ArkBatchSubmitBar({ pid, elements }: { pid: number; elements: Element[] }) {
  const [inLib, setInLib] = useState<string[]>([])          // 已入库角色名
  const [prog, setProg] = useState<{ i: number; n: number } | null>(null)

  const refresh = useCallback(async () => {
    try { setInLib((await api.listArkCharacters(pid)).map(r => r.name)) }
    catch { /* 静默：入库状态非关键路径 */ }
  }, [pid])
  useEffect(() => { refresh() }, [refresh])

  const todo = elements.filter(
    el => canSubmitToArk(el) && !inLib.some(nm => sameChar(nm, el.name)))
  if (!todo.length && !prog) return null

  const run = async () => {
    setProg({ i: 0, n: todo.length })
    for (let i = 0; i < todo.length; i++) {
      try { await api.createArkCharacter(arkBodyFromElement(pid, todo[i])) }
      catch (e) { alert(String((e as Error).message || e)) }
      setProg({ i: i + 1, n: todo.length })
    }
    await refresh()
    setProg(null)
  }

  return (
    <div className="profile-batch-bar">
      {prog
        ? <span className="dim"><Icon name="spinner" spin /> 提交火山角色库 {prog.i}/{prog.n}…</span>
        : <button className="small" onClick={run}
            title="把本项目已出设定图、尚未入库的角色批量提交到火山虚拟人像库（真实照片感画风才需要；提交后自动注册）">
            <Icon name="upload" /> 提交角色到火山库（{todo.length}）
          </button>}
    </div>
  )
}
