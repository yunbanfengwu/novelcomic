-- 单场景设定图画布 v3(2026-07-31):场景信息独立成节点。
--
-- v2 把「场景是什么」和「提示词怎么装」挤在一个节点里,画布上看不出取数与装配是两件事。
-- v3 拆开(与 tapflow 演示画布同形——先有信息节点,再有装配节点):
--   开始 → 关联·场景要素(link,运行态隐藏) → 场景信息(取数,直出场景文本)
--        → 提示词装配(真实装配结果) → 场景设定图(gen) → 质检 → next
--
-- 场景信息走 element.get(只读,writes=false),预检时真执行——参数一填画布上就有内容,
-- 不用等运行。它输出的 summary 只是取数排版,不掺提示词工程(那是 element_sheet 的活)。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目信息 + 画风 + 场景说明 → 场景要素入库 → 场景信息 → 提示词装配 → 设定图 → 质检 → 回写。缺才跑;force=["gen"] 强制重出。',
  3, 'published',
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

      {"id":"info","type":"action","position":{"x":700,"y":120},
       "config":{"name":"element.get",
                 "args":{"project_id":"{{input.project_id}}",
                         "element_id":"{{ensure.id}}"},
                 "ui":{"tap":"text","title":"场景信息","show":"summary","w":340,"h":260}}},

      {"id":"prompt","type":"action","position":{"x":1060,"y":120},
       "config":{"name":"element_sheet.prepare",
                 "args":{"project_id":"{{input.project_id}}",
                         "element_id":"{{ensure.id}}"},
                 "ui":{"tap":"text","title":"提示词装配","show":"prompt","w":360,"h":300}}},

      {"id":"gen","type":"subflow","position":{"x":1460,"y":160},
       "config":{"slug":"element-sheet","version":1,
                 "inputs":{"project_id":"{{input.project_id}}",
                           "element_id":"{{ensure.id}}"},
                 "skip_if":{"sql":"SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有设定图,跳过(force=[\"gen\"] 强制重出)"},
                 "ui":{"tap":"gen","title":"场景设定图","w":460,"h":273}}},

      {"id":"check","type":"action","position":{"x":1860,"y":210},
       "config":{"name":"element.sheet_exists",
                 "args":{"element_id":"{{ensure.id}}"},
                 "ui":{"tap":"qc","title":"质检·设定图"}}},

      {"id":"end","type":"end","position":{"x":2100,"y":190},
       "config":{"outputs":{"sheet_url":"{{check.sheet_url}}",
                            "element_id":"{{ensure.id}}"},
                 "ui":{"tap":"next","title":"next · 回写与通知",
                       "next":{"writes":["要素 · 设定图 meta.sheet_url"],
                               "attach":true,"notify":["任务中心"]}}}}
    ],
    "edges": [
      {"from":"start","to":"ensure"},
      {"from":"ensure","to":"info"},
      {"from":"info","to":"prompt"},
      {"from":"prompt","to":"gen"},
      {"from":"gen","to":"check"},
      {"from":"check","to":"end"}
    ]
  }$g$::jsonb,
  920, '{canvas,scene}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;
