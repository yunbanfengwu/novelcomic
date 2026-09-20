-- 单场景设定图画布 v4(2026-08-01):出图提示词回到图片节点的生成条里。
--
-- v3 把「提示词装配」画成一张文本卡,画布上就成了「一大段提示词占半屏」。
-- tapflow 的语义是:**图片的提示词属于图片**——选中图片炸开,下方生成条里是
-- 参考图缩略图 + 提示词 + 模型/参数,不该另占一张卡。所以 v4:
--   ui.hide=true   → 画布(编排/运行都)不画这个节点,连线自动桥接 info→gen;
--   ui.feeds="gen" → 但它照常执行,产物 prompt / reference_images 喂进 gen 的生成条。
-- 场景信息节点保持可见——那是「这个场景是什么」,不是出图参数。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目信息 + 画风 + 场景说明 → 场景要素入库 → 场景信息 → 提示词装配 → 设定图 → 质检 → 回写。缺才跑;force=["gen"] 强制重出。',
  4, 'published',
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
                 "ui":{"hide":true,"feeds":"gen","title":"提示词装配"}}},

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
