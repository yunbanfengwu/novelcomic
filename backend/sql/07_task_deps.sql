-- 依赖 DAG（2026-07-13，docs/arch/generation-flow-guards.md 增补）：
-- 任务可声明前置依赖（拉式，目标导向）——缺什么就递归派发生产者子任务，
-- 子任务完成回调（callFun）逐级向上通知父任务（deps_remaining 计数归零 → 父转 pending）。
-- 幂等，启动时自动应用。

-- 父任务等待中的未完成前置数：>0 且 status='waiting_deps' 时不被 worker 领取；
-- 子任务 done 时对所有父任务 -1，归零转 pending（poller 周期对账兜底崩溃窗口）
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS deps_remaining INT NOT NULL DEFAULT 0;
COMMENT ON COLUMN task_queue.deps_remaining IS '等待中的前置任务数（依赖 DAG）：子任务完成逐个 -1，归零由 waiting_deps 转 pending';

-- 依赖边（多父 DAG，不是单父树）：同一个 gen_prompts 子任务可同时被
-- gen_video 与 gen_keyframe 依赖（幂等去重会把重复入队合并为同一任务）
CREATE TABLE IF NOT EXISTS task_deps (
    parent_task_id BIGINT NOT NULL REFERENCES task_queue(id) ON DELETE CASCADE,
    child_task_id  BIGINT NOT NULL REFERENCES task_queue(id) ON DELETE CASCADE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_task_id, child_task_id)
);
CREATE INDEX IF NOT EXISTS task_deps_child_idx ON task_deps (child_task_id);
COMMENT ON TABLE task_deps IS '任务依赖边：parent 等 child 完成（拉式依赖解析在 flow.enqueue_with_deps，一次事务原子成树）';
