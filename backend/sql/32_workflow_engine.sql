-- 工作流引擎（2026-07-29）：把流程从代码里搬到数据里。
--
-- 背景：现有流程写死在 steps.py 的 missing_deps/chains_to 里，调整流程必须改代码发版。
-- 本表让流程变成可编辑的数据（节点/边存 JSONB），由一个新的 Step（kind='workflow'）解释执行。
--
-- 与现有 task_queue 的关系：工作流不是第二套运行时——每个节点最终仍然入队成普通任务，
-- 重启自动重排、依赖解析、SSE 进度推送全部复用。故新旧流程天然共存：
-- 没迁走的任务照走 steps.py，迁走的走 kind='workflow'，不需要停机切换。
--
-- 设计参照 ComfyUI 的执行模型（PR #2666）：拓扑排序 + 运行时节点展开（循环靠展开成子图实现），
-- 以及扣子/Dify 的子工作流（工作流可被别的工作流当节点调用，故需要 开始/结束 声明签名）。

CREATE TABLE IF NOT EXISTS workflows (
    id            BIGSERIAL PRIMARY KEY,
    slug          TEXT NOT NULL,                 -- 稳定标识（子工作流按 slug+version 引用）
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    version       INT  NOT NULL DEFAULT 1,       -- 引用方固定到已发布版本，不跟随 latest
    status        TEXT NOT NULL DEFAULT 'draft', -- draft | published | archived
    -- 开始/结束节点声明的签名：没有它工作流无法被嵌套调用
    input_schema  JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- 图本体：nodes=[{id,type,config,position}] edges=[{from,to,from_port,to_port}]
    graph         JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 同一 slug 的同一版本只能有一条；发布后改动应新起版本
CREATE UNIQUE INDEX IF NOT EXISTS workflows_slug_version_idx ON workflows (slug, version);
CREATE INDEX IF NOT EXISTS workflows_status_idx ON workflows (status) WHERE status = 'published';

COMMENT ON COLUMN workflows.graph IS
  'nodes/edges 图定义。node.type ∈ start|end|task|subflow|loop|branch；'
  'task 节点 config.kind 指向 steps.py 里已注册的 Step（粗粒度包装，第一版不拆 steps.py）；'
  'subflow 节点 config.{slug,version} 引用另一个工作流；'
  'loop 节点 config.{source,body} 运行时展开成 N 份子图（ComfyUI 尾递归展开的做法）';

-- 一次运行。parent_run_id 支持子工作流嵌套；depth 用于递归保护（保存时查环，运行时限深）
CREATE TABLE IF NOT EXISTS workflow_runs (
    id            BIGSERIAL PRIMARY KEY,
    workflow_id   BIGINT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    project_id    BIGINT REFERENCES content_projects(id) ON DELETE CASCADE,
    node_id       BIGINT REFERENCES content_nodes(id) ON DELETE SET NULL,  -- 章/镜上下文
    parent_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE CASCADE,
    depth         INT  NOT NULL DEFAULT 0,
    task_id       BIGINT,                        -- 驱动本次运行的 task_queue 行
    status        TEXT NOT NULL DEFAULT 'running', -- running | done | failed | canceled
    inputs        JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS workflow_runs_wf_idx     ON workflow_runs (workflow_id, created_at DESC);
CREATE INDEX IF NOT EXISTS workflow_runs_parent_idx ON workflow_runs (parent_run_id);
CREATE INDEX IF NOT EXISTS workflow_runs_project_idx ON workflow_runs (project_id, created_at DESC);

-- 节点级运行记录：画布上回放"哪个节点跑了、拿到什么、错在哪"
CREATE TABLE IF NOT EXISTS workflow_node_runs (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    node_key     TEXT   NOT NULL,                -- graph.nodes[].id
    iteration    INT    NOT NULL DEFAULT 0,      -- 循环展开的第几份（非循环恒为 0）
    status       TEXT   NOT NULL DEFAULT 'pending', -- pending|running|done|failed|skipped
    task_id      BIGINT,                         -- task 节点派发出的 task_queue 行
    subrun_id    BIGINT REFERENCES workflow_runs(id) ON DELETE SET NULL,  -- subflow 节点的子运行
    inputs       JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs      JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- skipped 的原因：子工作流当前置条件时"产物已在就不重跑"，要能解释为什么跳过
    skip_reason  TEXT,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_node_runs_key_idx
    ON workflow_node_runs (run_id, node_key, iteration);
CREATE INDEX IF NOT EXISTS workflow_node_runs_run_idx ON workflow_node_runs (run_id);

COMMENT ON COLUMN workflow_node_runs.skip_reason IS
  '跳过原因。subflow 当前置条件时默认语义是「缺才跑」——产物已在就跳过，'
  '否则每次批量都会把已有产物重新生成一遍覆盖掉（2026-07-28 批量首帧就踩过这个坑）';
