-- ═══════════ 99 · 智能体规划落库（P3 · 2026-09-17）═══════════
--
-- 规划此前只活在 agent_runtime 单次运行的 steps 里：进程一断，计划和进度全没了，
-- 既不能恢复也不能重试。本迁移把「计划」变成一等实体：
--   agent_plans      = 一个目标（goal）+ 状态机
--   agent_plan_steps = 有序步骤（seq），每步独立状态机，失败可单步重试
--
-- 设计约束：
-- · 计划是"读取存量数据的产物"，不是脚本：每步只存指令（title/detail/tool_hints），
--   执行产物进 result，不把全量上下文抄进来；
-- · 步骤状态机禁止跳跃（pending→running→done/failed；failed→running 仅经 retry），
--   状态流转校验放 services/planner.py 纯函数里，DB 层 CHECK 只兜非法字面量；
-- · 幂等：全部 IF NOT EXISTS，重复应用无副作用。

CREATE TABLE IF NOT EXISTS agent_plans (
    id          BIGSERIAL PRIMARY KEY,
    project_id  BIGINT REFERENCES content_projects(id) ON DELETE CASCADE,
    goal        TEXT NOT NULL,                      -- 这次要达成什么（模型据此生成步骤）
    status      TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'running', 'done', 'failed', 'aborted')),
    current_seq INT NOT NULL DEFAULT 0,             -- 推进到的最大 seq（0=未开始）
    created_by  TEXT REFERENCES users(id),
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb, -- 生成参数等（flexible）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_plans_project_idx
    ON agent_plans (project_id, id DESC);

CREATE TABLE IF NOT EXISTS agent_plan_steps (
    id          BIGSERIAL PRIMARY KEY,
    plan_id     BIGINT NOT NULL REFERENCES agent_plans(id) ON DELETE CASCADE,
    seq         INT  NOT NULL CHECK (seq > 0),      -- 从 1 起的执行顺序
    title       TEXT NOT NULL,                      -- 这步做什么（一句话）
    detail      TEXT,                               -- 展开后的执行指令（喂给 charter）
    tool_hints  TEXT[] NOT NULL DEFAULT '{}',       -- 建议工具名（提示用，不构成授权）
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'done', 'failed', 'skipped')),
    result      JSONB,                              -- 执行产物（output 的 JSON 摘录）
    error       TEXT,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    UNIQUE (plan_id, seq)
);
CREATE INDEX IF NOT EXISTS agent_plan_steps_plan_idx
    ON agent_plan_steps (plan_id, seq);

COMMENT ON TABLE  agent_plans      IS '智能体规划：goal→步骤序列，落库后可恢复/重试/审计';
COMMENT ON COLUMN agent_plans.status IS 'draft=已生成未跑 / running / done / failed / aborted=人工终止';
COMMENT ON TABLE  agent_plan_steps IS '规划步骤：单步独立状态机，失败单步重试，不牵连整计划';
