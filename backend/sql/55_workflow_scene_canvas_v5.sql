-- 单场景设定图画布 v5(2026-08-01):生成节点换成**通用 gen 节点**,提示词三层装配。
--
-- v4 的 gen 是 subflow(element-sheet) 黑盒:画布上看不到装配、生成条里改了提示词也送不进去
-- (prepare 会按实体重装配一遍把手改冲掉)。v5 换成引擎新增的 type=gen:
--
--   user   = element.layers 的叙事段 ⊕ 上游文本节点产物 ⊕ 生成条里的用户指令
--   anchor = element.layers 的结构段(版式+画风锚+质量词+偏好) —— 画布改不了,质量护栏
--   refs   = element.layers 的实体参考图 + 上游图片节点产物(去重,≤4,超出如实记日志)
--
-- 装配器 element.layers 是零副作用纯取数(装配本体仍是 element_sheet 那一份,已逐字节对拍),
-- 所以运行预检就能算出真实提示词——参数一填,生成条里就是即将提交的那一份。
-- 出图本体仍入队既有 gen_element_sheet Step:落库(附件 + meta.sheet_url + 外貌指纹)一字未改。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目 + 场景说明 → 场景要素入库 → 场景信息 → 设定图(三层装配,生成条可改指令) → 质检 → 回写。缺才跑;force=["gen"] 强制重出。',
  5, 'published',
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

      {"id":"gen","type":"gen","position":{"x":1100,"y":160},
       "config":{"modality":"image",
                 "assemble":{"name":"element.layers",
                             "args":{"project_id":"{{input.project_id}}",
                                     "element_id":"{{ensure.id}}"}},
                 "instruction":"",
                 "step":"gen_element_sheet",
                 "payload":{"element_id":"{{ensure.id}}"},
                 "skip_if":{"sql":"SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有设定图,跳过(force=[\"gen\"] 强制重出)"},
                 "ui":{"tap":"gen","title":"场景设定图","w":460,"h":273,
                       "model":"系统出图模型","editable":true}}},

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
      {"from":"ensure","to":"info"},
      {"from":"info","to":"gen"},
      {"from":"gen","to":"check"},
      {"from":"check","to":"end"}
    ]
  }$g$::jsonb,
  920, '{canvas,scene}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;
