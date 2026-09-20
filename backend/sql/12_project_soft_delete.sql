-- 项目软删除（回收站）：deleted_at 非空=在回收站；列表默认过滤，可恢复或彻底删除。
-- 幂等：ADD COLUMN IF NOT EXISTS + 部分索引 IF NOT EXISTS。
ALTER TABLE content_projects ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
COMMENT ON COLUMN content_projects.deleted_at IS '软删除时间：非空=在回收站（列表默认排除）；恢复置空；彻底删除走物理 DELETE 级联';
-- 部分索引：正常列表只扫未删项目
CREATE INDEX IF NOT EXISTS content_projects_alive_idx ON content_projects (id DESC) WHERE deleted_at IS NULL;
