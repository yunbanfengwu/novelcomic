-- 运行选项落库（2026-08-01）：画布「上次怎么跑的」要能回填，不用每次重选。
--
-- 入参（项目/卷章镜/场景名…）本来就存在 workflow_runs.inputs 里，缺的只是
-- 「怎么跑」那几样——它们此前只活在 HTTP 请求体里，运行一结束就没了。
--
-- 不另起「上次参数」表：那会变成第二份真相（哪次算上次、失败的算不算、谁清理），
-- 而它本质只是 workflow_runs 按 workflow_id 取 MAX(id) 的派生值。加一列即可。
--
-- 一列装下整份提交而不是拆四列：force/stop_after/node_overrides 是给运行记录
-- 解释「那次为什么跳过、为什么用了手编提示词」的，range/force_all 是给画布回填的，
-- 同属「这一次的执行选项」，拆列只会让以后每加一个开关就动一次 schema。

ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS run_options JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN workflow_runs.run_options IS
  '本次运行的执行选项，前端提交原样：'
  '{force:[节点id], stop_after:节点id, force_all:bool, range:{from,to}, node_overrides:{}}。'
  'range/force_all 供画布回填「上次怎么跑的」；force/stop_after/node_overrides 供运行记录追溯';
