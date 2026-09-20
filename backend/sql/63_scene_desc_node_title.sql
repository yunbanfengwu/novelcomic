-- 画布上「场景设定描述」节点补回**对象名**（2026-08-01）。
--
-- 61_scene_desc_flow 把 brief 节点改引用 scene-desc 时，顺手把标题写成了死字符串
-- 「场景设定描述」——同一行的设定图节点是「场景设定图 · 初入的山林」，描述节点却只有
-- 类型名，并排看就像它跟本次运行的对象没关系（截图反馈）。标题模板见 v8 的说明：
-- ui.title 里的 {{input.scene_name}} 由前端按当前入参替换（lib/tapflowGraphAdapter.resolveTitle），
-- 没选场景时占位连同分隔符一起抹掉，退回「场景设定描述」，不会留半截。
--
-- 顺带把 config.slug 一并盖成 scene-desc：全新库上文件按名字顺序执行，
-- 62_workflow_scene_canvas_v8 的 INSERT 排在 61 的 UPDATE **之后**，v8 这行不会被 61 改到，
-- brief 会停在旧的 scene-brief 引用上。这里补一刀，两种库收敛到同一状态。
--
-- inputs 同理跟着 62_scene_desc_inputs 收敛：只传 项目 + 场景名，要素 id 由被引用方解析
-- （scene-desc 的 input_schema 已经不收 element_id 了，传过去也是白传）。
--
-- 只动 config 的 slug / inputs / ui.title，位置尺寸与边全不变。
-- 幂等：三者都已是目标值时条件不成立。
UPDATE workflows SET graph = jsonb_set(
    graph, '{nodes}',
    (SELECT jsonb_agg(
        CASE WHEN n->>'id' = 'brief'
             THEN jsonb_set(
                    jsonb_set(
                      jsonb_set(n, '{config,slug}', '"scene-desc"'::jsonb),
                      '{config,inputs}',
                      '{"project_id":"{{input.project_id}}","scene_name":"{{input.scene_name}}"}'::jsonb),
                    '{config,ui,title}', '"场景设定描述 · {{input.scene_name}}"'::jsonb)
             ELSE n END)
     FROM jsonb_array_elements(graph->'nodes') n)
  ), updated_at = now()
WHERE slug = 'scene-sheet-canvas'
  AND graph->'nodes' @> '[{"id":"brief"}]'::jsonb
  AND NOT (graph->'nodes' @> '[{"id":"brief","config":{
             "slug":"scene-desc",
             "inputs":{"project_id":"{{input.project_id}}","scene_name":"{{input.scene_name}}"},
             "ui":{"title":"场景设定描述 · {{input.scene_name}}"}}}]'::jsonb);
