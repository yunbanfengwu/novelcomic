-- 第一个工作流：生成角色/场景设定图（2026-07-29）。幂等，启动时自动应用。
--
-- 这是最小验证单元：一个 action（装配 payload）+ 一个 task（包 gen_element_sheet）。
-- 用它验三件事——解释器能不能跑、skip_if「缺才跑」是否生效、运行记录是否可回放。
--
-- 注意：角色和场景共用同一个工作流。二者在 content_elements 里只是 kind 不同，
-- 出图走的都是 gen_element_sheet，没有必要拆成两个图。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph)
VALUES (
  'element-sheet', '生成要素设定图', '角色三视图/场景概念图。缺才跑——已有设定图直接跳过。',
  1, 'published',
  '{"project_id":{"type":"int","required":true},
    "element_id":{"type":"int","required":true},
    "variant_id":{"type":"string","required":false}}'::jsonb,
  '{"sheet_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":0,"y":120}},

      {"id":"prepare","type":"action","position":{"x":220,"y":120},
       "config":{"name":"element_sheet.prepare",
                 "args":{"project_id":"{{input.project_id}}",
                         "element_id":"{{input.element_id}}",
                         "variant_id":"{{input.variant_id}}"}}},

      {"id":"gen","type":"task","position":{"x":460,"y":120},
       "config":{"kind":"gen_element_sheet","priority":10,
                 "payload":{"prompt":"{{prepare.prompt}}",
                            "element_id":"{{prepare.element_id}}",
                            "variant_id":"{{prepare.variant_id}}",
                            "reference_images":"{{prepare.reference_images}}",
                            "hair_prompt":"{{prepare.hair_prompt}}"},
                 "skip_if":{"sql":"SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
                            "args":["{{input.element_id}}"],
                            "reason":"本要素已有设定图，跳过（想重出请用 force）"}}},

      {"id":"check","type":"action","position":{"x":700,"y":120},
       "config":{"name":"element.sheet_exists",
                 "args":{"element_id":"{{input.element_id}}"}}},

      {"id":"end","type":"end","position":{"x":940,"y":120},
       "config":{"outputs":{"sheet_url":"{{check.sheet_url}}",
                            "exists":"{{check.exists}}"}}}
    ],
    "edges": [
      {"from":"start","to":"prepare"},
      {"from":"prepare","to":"gen"},
      {"from":"gen","to":"check"},
      {"from":"check","to":"end"}
    ]
  }$g$::jsonb
)
ON CONFLICT (slug, version) DO UPDATE SET
  name=excluded.name, description=excluded.description, status=excluded.status,
  input_schema=excluded.input_schema, output_schema=excluded.output_schema,
  graph=excluded.graph, updated_at=now();
