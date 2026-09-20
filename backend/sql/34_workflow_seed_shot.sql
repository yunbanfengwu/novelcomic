-- 单镜出图工作流（2026-07-29）：验 subflow 嵌套 + loop 循环这两个还没跑过的机制。
--
-- 这是用户最初描述的形状：「单镜出图依赖获取本镜所有角色，判断角色是否已生成、
-- 场景是否已生成，未生成则生成」。
--
-- 图的读法：
--   取本镜出场要素 → 循环每个要素 → 每轮调 element-sheet 子工作流（缺才跑）
-- element-sheet 自身带 skip_if，所以已有设定图的要素在子工作流里就被跳过，
-- 循环体不必再判一次——「缺才跑」的语义只在一处定义，不散落。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph)
VALUES (
  'shot-prepare-elements', '单镜要素准备',
  '取本镜出场的全部角色/场景，逐个确保设定图已生成（缺才跑）。单镜出图的前置。',
  1, 'published',
  '{"project_id":{"type":"int","required":true},
    "shot_id":{"type":"int","required":true}}'::jsonb,
  '{"total":{"type":"int"},"missing":{"type":"int"}}'::jsonb,
  $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":0,"y":140}},

      {"id":"elements","type":"action","position":{"x":220,"y":140},
       "config":{"name":"shot.elements","args":{"shot_id":"{{input.shot_id}}"}}},

      {"id":"each","type":"loop","position":{"x":460,"y":140},
       "config":{"source":"{{elements.items}}","body":["ensure_sheet"]}},

      {"id":"ensure_sheet","type":"subflow","position":{"x":460,"y":300},
       "config":{"slug":"element-sheet","version":1,
                 "inputs":{"project_id":"{{input.project_id}}",
                           "element_id":"{{__item__.id}}",
                           "variant_id":null}}},

      {"id":"end","type":"end","position":{"x":760,"y":140},
       "config":{"outputs":{"total":"{{elements.count}}",
                            "iterations":"{{each.count}}"}}}
    ],
    "edges": [
      {"from":"start","to":"elements"},
      {"from":"elements","to":"each"},
      {"from":"each","to":"end"}
    ]
  }$g$::jsonb
)
ON CONFLICT (slug, version) DO UPDATE SET
  name=excluded.name, description=excluded.description, status=excluded.status,
  input_schema=excluded.input_schema, output_schema=excluded.output_schema,
  graph=excluded.graph, updated_at=now();
