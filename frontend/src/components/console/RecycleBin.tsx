import { useState } from 'react'
import { ProjectTrash } from './ProjectTrash'
import { ShotTrash } from './ShotTrash'

type Kind = 'project' | 'shot'

/**
 * 回收站容器：顶部「项目 / 分镜」分段切换，内部再各自筛选。
 * - 项目：软删除的整项目，可恢复 / 彻底删除。
 * - 分镜：跨项目的软删除分镜（删除本镜 / 重拆镜移入），按项目筛选，仅彻底删除（暂不恢复）。
 *   （旧无限画布节点的「画布节点」回收站随画布收编一并移除——tapflow 实例走画布内自身的删除）
 * onChanged：项目回收站恢复/彻底删除后回调，供首页刷新项目列表。
 */
export function RecycleBin({ onChanged }: { onChanged?: () => void }) {
  const [kind, setKind] = useState<Kind>('project')
  return (
    <div className="recycle-bin">
      <div className="seg recycle-seg">
        <button type="button" className={`seg-btn${kind === 'project' ? ' active' : ''}`}
          onClick={() => setKind('project')}>项目</button>
        <button type="button" className={`seg-btn${kind === 'shot' ? ' active' : ''}`}
          onClick={() => setKind('shot')}>分镜</button>
      </div>
      {kind === 'project' ? <ProjectTrash onChanged={onChanged} /> : <ShotTrash />}
    </div>
  )
}
