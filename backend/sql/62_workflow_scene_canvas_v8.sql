-- 画布 v8：节点标题带出**本次运行的对象名**（2026-08-01）。
--
-- v7 的标题是死字符串「场景介绍」「场景设定图」——同一张画布跑哪个场景都长一个样，
-- 截图/日志/多标签页并排看时根本分不清是谁。对象名其实早就在画布本地（开始节点的入参），
-- 缺的只是把它接上去，所以做成模板：ui.title 里写 {{input.xxx}}，前端按当前入参替换
-- （见 lib/tapflowGraphAdapter.resolveTitle）。没选场景时占位连同分隔符一起抹掉，
-- 标题退回「场景介绍」，不会留个半截的「场景介绍 · 」。
--
-- 只动 ui.title：ui 是画布提示，后端解释器不读它，执行语义与 v7 完全一致。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目 + 场景 → 要素入库 → 场景介绍(引用最小集,缺才跑) → 设定图(装配+质检+出图) → 回写。',
  8, 'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目"},
    "chapter_id":{"type":"int","required":false,"desc":"章"},
    "scene_name":{"type":"string","required":true,"desc":"场景"}}'::jsonb,
  '{"sheet_url":{"type":"string"},"element_id":{"type":"int"}}'::jsonb,
  $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":40,"y":220},
       "config":{"ui":{"tap":"start","title":"开始"}}},

      {"id":"ensure","type":"action","position":{"x":380,"y":220},
       "config":{"name":"element.upsert",
                 "args":{"project_id":"{{input.project_id}}","kind":"scene",
                         "name":"{{input.scene_name}}"},
                 "preview":{"name":"element.find",
                            "args":{"project_id":"{{input.project_id}}","kind":"scene",
                                    "name":"{{input.scene_name}}"}},
                 "ui":{"tap":"link","title":"关联·场景要素","hide_in_run":true}}},

      {"id":"brief","type":"subflow","position":{"x":720,"y":200},
       "config":{"slug":"scene-brief","version":1,
                 "inputs":{"project_id":"{{input.project_id}}",
                           "element_id":"{{ensure.id}}",
                           "scene_name":"{{input.scene_name}}"},
                 "skip_if":{"sql":"SELECT nullif(btrim(coalesce(brief,'')),'') FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有介绍,跳过(缺才跑)"},
                 "ui":{"tap":"text","title":"场景介绍 · {{input.scene_name}}",
                       "show":"text","w":360,"h":300}}},

      {"id":"gen","type":"gen","position":{"x":1120,"y":180},
       "config":{"modality":"image",
                 "assemble":{"name":"element.layers",
                             "args":{"project_id":"{{input.project_id}}",
                                     "element_id":"{{ensure.id}}"}},
                 "step":"gen_element_sheet",
                 "payload":{"element_id":"{{ensure.id}}"},
                 "qc":{"on":true,"skill":"场景设定图质检","stage":"prompt",
                       "threshold":80,"retry":1},
                 "skip_if":{"sql":"SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有设定图,跳过(选中节点→重新生成 可强制重出)"},
                 "ui":{"tap":"gen","title":"场景设定图 · {{input.scene_name}}","w":460,"h":273,
                       "model":"系统出图模型"}}},

      {"id":"end","type":"end","position":{"x":1560,"y":210},
       "config":{"outputs":{"sheet_url":"{{gen.url}}","element_id":"{{ensure.id}}"},
                 "ui":{"tap":"next","title":"next · 回写与通知",
                       "next":{"writes":["要素 · 设定图 meta.sheet_url"],
                               "attach":true,"notify":["任务中心"]}}}}
    ],
    "edges": [
      {"from":"start","to":"ensure"},
      {"from":"ensure","to":"brief"},
      {"from":"brief","to":"gen"},
      {"from":"gen","to":"end"}
    ]
  }$g$::jsonb,
  920, '{canvas,scene}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;
