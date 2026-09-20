-- 单场景设定图画布 v2(2026-07-31):对齐 tapflow 演示画布的完整节点形状。
-- v1 只有 开始→关联→生成→质检,画布上太素;v2 补两个节点:
--   · prompt(action element_sheet.prepare,ui.tap=text「提示词装配」):把真实装配的
--     提示词摆上画布——与 element-sheet 子流程内部的 prepare 同一份唯一实现,
--     纯 DB+字符串装配零模型成本,重复执行幂等;
--   · end 不再隐藏,ui.tap=next「回写与通知」:回写本体仍在 ElementSheetStep.next
--     (附件+meta.sheet_url,单一实现),ui.next 只是把落点如实标出来。
-- 与 51 同理 ON CONFLICT DO NOTHING:画布保存可回写坐标,重启不冲。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目信息 + 画风 + 场景说明 → 场景要素入库 → 提示词装配 → 设定图 → 质检 → 回写。缺才跑;force=["gen"] 强制重出。',
  2, 'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目"},
    "scene_name":{"type":"string","required":true,"desc":"场景"},
    "scene_brief":{"type":"string","required":false,"desc":"场景说明"},
    "ref_url":{"type":"string","required":false,"desc":"参考图 url(可选)"}}'::jsonb,
  '{"sheet_url":{"type":"string"},"element_id":{"type":"int"}}'::jsonb,
  $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":40,"y":200},
       "config":{"ui":{"tap":"start","title":"开始"}}},

      {"id":"ensure","type":"action","position":{"x":360,"y":200},
       "config":{"name":"element.upsert",
                 "args":{"project_id":"{{input.project_id}}","kind":"scene",
                         "name":"{{input.scene_name}}","brief":"{{input.scene_brief}}",
                         "ref_url":"{{input.ref_url}}"},
                 "preview":{"name":"element.find",
                            "args":{"project_id":"{{input.project_id}}","kind":"scene",
                                    "name":"{{input.scene_name}}"}},
                 "ui":{"tap":"link","title":"关联·场景要素","hide_in_run":true}}},

      {"id":"prompt","type":"action","position":{"x":700,"y":120},
       "config":{"name":"element_sheet.prepare",
                 "args":{"project_id":"{{input.project_id}}",
                         "element_id":"{{ensure.id}}"},
                 "ui":{"tap":"text","title":"提示词装配","w":360,"h":300}}},

      {"id":"gen","type":"subflow","position":{"x":1100,"y":160},
       "config":{"slug":"element-sheet","version":1,
                 "inputs":{"project_id":"{{input.project_id}}",
                           "element_id":"{{ensure.id}}"},
                 "skip_if":{"sql":"SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有设定图,跳过(force=[\"gen\"] 强制重出)"},
                 "ui":{"tap":"gen","title":"场景设定图","w":460,"h":273}}},

      {"id":"check","type":"action","position":{"x":1500,"y":210},
       "config":{"name":"element.sheet_exists",
                 "args":{"element_id":"{{ensure.id}}"},
                 "ui":{"tap":"qc","title":"质检·设定图"}}},

      {"id":"end","type":"end","position":{"x":1740,"y":190},
       "config":{"outputs":{"sheet_url":"{{check.sheet_url}}",
                            "element_id":"{{ensure.id}}"},
                 "ui":{"tap":"next","title":"next · 回写与通知",
                       "next":{"writes":["要素 · 设定图 meta.sheet_url"],
                               "attach":true,"notify":["任务中心"]}}}}
    ],
    "edges": [
      {"from":"start","to":"ensure"},
      {"from":"ensure","to":"prompt"},
      {"from":"prompt","to":"gen"},
      {"from":"gen","to":"check"},
      {"from":"check","to":"end"}
    ]
  }$g$::jsonb,
  920, '{canvas,scene}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;
