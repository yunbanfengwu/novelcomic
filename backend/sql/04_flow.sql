-- 统一生成管线（2026-07-11，docs/arch/generation-flow-guards.md）
-- task_queue 增列：重试计数 / 链追踪 / 优先级。幂等，启动时自动应用。

ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS attempt      INT    NOT NULL DEFAULT 0;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS root_task_id BIGINT;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS priority     INT    NOT NULL DEFAULT 0;

COMMENT ON COLUMN task_queue.attempt      IS '已重试次数：next 判不合格或可重试错误时 +1 重排；超过 Step.max_retries 落 failed——绝不无限循环';
COMMENT ON COLUMN task_queue.root_task_id IS '链式任务的根任务（如拆分镜 next 串出的每镜提示词任务）；配合 payload.chain_depth 防环';
COMMENT ON COLUMN task_queue.priority     IS '取任务顺序 priority DESC, created_at：单镜手点=10 > 拆镜=5 > 整章批量=0';

-- 取任务路径：pending 按优先级；旧 status 索引保留（poller 按 status 扫）
CREATE INDEX IF NOT EXISTS task_queue_pick_idx ON task_queue (status, priority DESC, created_at);
