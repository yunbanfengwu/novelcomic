-- 生成审计日志（用户 2026-07-12；2026-07-14 扩展到图片）：每次视频/图片生成的
-- 真实提交入参与最终结果，供排查与复盘（"之前效果好现在不行"的对照依据）。
-- source=来源标记（project_10_2_21_video / project_10_2_21_image / kb_style_35），
-- 前缀筛 source 即可看某分镜或某风格库条目的全部生成记录。
-- 关联模型：一单 task（task_queue.id）可有多行提交（降级级联 attempt_no 1/2/3），
-- 每行记提交瞬间的完整 request；收割/失败时按 task_id 回写 result 与终态——
-- 入参与异步结果通过 task_id + external_task_id 双键闭环。
CREATE TABLE IF NOT EXISTS gen_logs (
  id               BIGSERIAL PRIMARY KEY,
  project_id       BIGINT,
  chapter_id       BIGINT,        -- 剧集（章节点 id）
  chapter_title    TEXT,          -- 冗余落库：章删了日志还能读
  node_id          BIGINT,        -- 镜节点 id
  shot_no          INT,
  task_id          BIGINT,        -- task_queue.id（关联键）
  kind             TEXT NOT NULL DEFAULT 'gen_video',
  attempt_no       INT NOT NULL DEFAULT 1,   -- 本单第几次提交（降级级联序号）
  provider         TEXT,          -- ark / grsai
  model            TEXT,
  modality         TEXT,          -- 模态摘要：text[721字]+reference_image×4+reference_audio×1
  request          JSONB,         -- 完整提交入参：content 数组全文 + duration/ratio
  external_task_id TEXT,
  status           TEXT NOT NULL DEFAULT 'submitted',  -- accepted/rejected/done/failed
  error            TEXT,
  result           JSONB,         -- 收割结果：video_url（OSS 转存后）等
  created_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz
);
CREATE INDEX IF NOT EXISTS idx_gen_logs_task ON gen_logs (task_id);
CREATE INDEX IF NOT EXISTS idx_gen_logs_node ON gen_logs (node_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gen_logs_proj ON gen_logs (project_id, created_at DESC);

-- 来源标记（2026-07-14）：project_{项目}_{章seq}_{镜号}_{video|image} / kb_style_{条目id}
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS source TEXT;
CREATE INDEX IF NOT EXISTS idx_gen_logs_source ON gen_logs (source, created_at DESC);
-- 存量视频日志回填 source（幂等：只补 NULL 行；章节点已删的记 x 占位）
UPDATE gen_logs g SET source = 'project_' || g.project_id || '_'
    || COALESCE((SELECT c.seq::text FROM content_nodes c WHERE c.id = g.chapter_id), 'x')
    || '_' || COALESCE(g.shot_no::text, 'x') || '_video'
WHERE g.source IS NULL AND g.kind = 'gen_video' AND g.project_id IS NOT NULL;
