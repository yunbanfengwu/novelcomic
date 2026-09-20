-- 下线「智能体编排」（2026-08-01 用户定稿；2026-08-07 改黑名单，见下）。
--
-- 背景：`workflows` 表上曾经并存两套解释器——
--   ② agent_unit.run_unit：把整张图的节点 config 扁平合并成一份「最小集」再跑；
--   ③ services/workflow.py：按 edges 拓扑排序、按 node.type 分派的 DAG 解释器。
-- ② 连同它的管理页（admin「智能体编排」）整体删除。② 的编排是当时在管理页里手工建的
-- （种子里只有 UPDATE 没有 INSERT），所以只有线上库里有；这条迁移负责把它们清掉。
--
-- ⚠ 2026-08-07 从白名单改成**黑名单**：本文件每次启动都跑（init_pool 幂等执行 sql/*.sql），
-- 白名单写死 4 个 slug，导致序号在 60 之后种的每一张画布（61/67/80/91/95…）每次启动都被
-- 先 DELETE 再由各自种子重新 INSERT——行是回来了，但 BIGSERIAL id 换了新的，
-- workflow_runs / workflow_node_runs 被外键 CASCADE 连带清空（实测：连续两次 init_pool，
-- agent-plan-demo 的 id 4498→4514，运行历史全丢；线上每次发版重启同样丢）。
-- 要删的旧编排本来就是**有穷且写死**的（42/43 号种子里 UPDATE 过的那批），按名点杀：
-- 天然幂等（删过就删不到了），永远不会误伤任何后来新增的画布。
DELETE FROM workflows WHERE slug = ANY(ARRAY[
    -- 项目级
    'a.project-info', 'a.project-outline', 'a.element-kinds', 'c.project-bootstrap',
    -- 要素级
    'a.character-sheet', 'a.scene-sheet',
    -- 章级
    'a.chapter-breakdown', 'a.chapter-expand', 'a.chapter-blocking',
    'a.scene-empty', 'a.scene-blocking', 'a.chapter-stills', 'a.chapter-grid',
    'c.chapter-to-storyboard', 'c.episode-elements', 'c.episode-scenes',
    -- 镜级
    'a.shot-storyboard', 'a.shot-prompt', 'a.shot-keyframe', 'a.shot-lastframe',
    'a.shot-video', 'c.episode-keyframes', 'c.episode-video', 'ep-batch-keyframe',
    -- 旁支与取数
    'a.voice-sample',
    'q.project-info', 'q.element', 'q.chapter-shots', 'q.scene-groups', 'q.shot-elements'
]);

-- 试运行记录表：随 services/agent_runs.py 一并下线，没有任何读写方了。
-- 建表语句原在 37_agent_runs.sql，已删除；这里把存量表也收走，免得新老库结构不一致。
DROP TABLE IF EXISTS agent_runs;
