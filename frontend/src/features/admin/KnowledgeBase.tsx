import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { KbFolder } from '../../api'
import { KbFolderGrid } from './KbFolderGrid'
import { KbFolderView } from './KbFolderView'

/**
 * 统一知识库：kb_entries 一张表，文件夹是组织层。
 * 首页=文件夹卡片墙；点击进入文件夹（上 header 下内容）：
 * 角色库/音色库/画风库为直接卡片流，其余为左侧分类菜单+右侧内容。
 * 技能不属于知识库（数字员工能力配置，独立 tab）。
 */
export function KnowledgeBase() {
  const [folders, setFolders] = useState<KbFolder[]>([])
  const [openId, setOpenId] = useState<number | null>(null)

  const reload = useCallback(async () => {
    const fs = await api.listKbFolders()
    setFolders(fs)
    setOpenId(id => (id == null || fs.some(f => f.id === id)) ? id : null)
  }, [])
  useEffect(() => { reload() }, [reload])

  const open = folders.find(f => f.id === openId)
  return open
    ? <KbFolderView folder={open} onBack={() => setOpenId(null)} onChanged={reload} />
    : <KbFolderGrid folders={folders} onOpen={setOpenId} onChanged={reload} />
}
