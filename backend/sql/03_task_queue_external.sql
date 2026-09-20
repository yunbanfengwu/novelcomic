-- 任务队列异步外部任务支持（2026-07-08）
-- 火山 ARK 图/视频均为异步任务：提交后 worker 立即释放，poller 轮询收割。
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS external_task_id TEXT;
COMMENT ON COLUMN task_queue.external_task_id IS '外部服务商任务 id（ARK contents/generations/tasks）；status=waiting_external 时由 poller 轮询';
