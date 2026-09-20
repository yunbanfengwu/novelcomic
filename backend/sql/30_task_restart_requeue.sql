-- 重启中断自动重排（2026-07-28）：worker 重启会杀掉当时全部在途任务，
-- 原先一律判 failed 且不重排——线上一次发版就静默打断所有在跑的出图/出视频，
-- 用户只能自己去任务队列逐个点重试。改为自动重排，但必须有独立计数兜底：
-- 若某任务本身会把进程带崩，无限自动重排就是无限重启循环。
-- 与 attempt 分开计数——attempt 是业务重试（质检不合格/可重试错误），
-- 被重启打断不是业务失败，不该消耗业务重试次数。幂等，启动时自动应用。
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS restart_requeues INT NOT NULL DEFAULT 0;
COMMENT ON COLUMN task_queue.restart_requeues IS '因 worker 重启被中断后自动重排的次数；达到 flow.MAX_RESTART_REQUEUES 仍被中断则判 failed，留给人工重试';
