-- 分镜回收站（软删除）：content_nodes.deleted_at 非空=在回收站。
-- 用途①手动「删除本镜」不再物理删行；②重拆镜时上一版整集分镜整体移入回收站。
-- 关键：镜行不删 → content_attachments(node_id ON DELETE CASCADE) 不级联清理 → 视频/首帧资料完整保留。
-- 依产品要求：暂不做恢复，仅支持查看与彻底删除。

ALTER TABLE content_nodes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
COMMENT ON COLUMN content_nodes.deleted_at IS
  '分镜软删除时间：非空=在回收站（分镜列表/素材默认排除，可彻底删除、暂不恢复）；重拆镜时旧整集分镜整体置入。同一次删除的所有镜共享同一 now() 值→天然批次键';

-- 存活分镜（工作台/素材视图走此路）：按章 + seq
CREATE INDEX IF NOT EXISTS content_nodes_shot_alive_idx
  ON content_nodes (parent_id, seq) WHERE kind = 'shot' AND deleted_at IS NULL;
-- 回收站视图：按项目 + 删除时间倒序（跨项目列表 + 项目筛选）
CREATE INDEX IF NOT EXISTS content_nodes_shot_trash_idx
  ON content_nodes (project_id, deleted_at DESC) WHERE kind = 'shot' AND deleted_at IS NOT NULL;
