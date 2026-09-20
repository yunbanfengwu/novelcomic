-- 第一张 tapflow 画布工作流：单场景设定图（2026-07-31）。幂等，启动时自动应用。
--
-- 「组合集引入最小集」的样板：本图不含任何生成逻辑，生成由 subflow 引用原子工作流
-- element-sheet（33 号 seed）完成；ensure 是画布的「关联」节点（把画布文本落成项目
-- 场景要素——资产自动入库的归属一步），附件入库仍由 ElementSheetStep.next 自动完成。
--
-- node.config.ui 是画布展示层（解释器不读）：tap=start/link/gen/qc 决定 tapflow 节点
-- 样式；hide_in_run=true 的节点运行态不渲染但照常执行。
--
-- ⚠️ 与 33 刻意不同：ON CONFLICT DO NOTHING——画布保存会把用户拖动的坐标写回本行
-- graph，若用 DO UPDATE 每次重启都会把它们冲回种子布局。要改种子内容请升 version。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目信息 + 画风 + 场景说明 → 场景要素入库 → 设定图。缺才跑；force=["gen"] 强制重出。',
  1, 'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目"},
    "scene_name":{"type":"string","required":true,"desc":"场景名"},
    "scene_brief":{"type":"string","required":false,"desc":"场景说明"},
    "ref_url":{"type":"string","required":false,"desc":"参考图 url（可选）"}}'::jsonb,
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

      {"id":"gen","type":"subflow","position":{"x":700,"y":160},
       "config":{"slug":"element-sheet","version":1,
                 "inputs":{"project_id":"{{input.project_id}}",
                           "element_id":"{{ensure.id}}"},
                 "skip_if":{"sql":"SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有设定图，跳过（force=[\"gen\"] 强制重出）"},
                 "ui":{"tap":"gen","title":"场景设定图","w":460,"h":273}}},

      {"id":"check","type":"action","position":{"x":1200,"y":210},
       "config":{"name":"element.sheet_exists",
                 "args":{"element_id":"{{ensure.id}}"},
                 "ui":{"tap":"qc","title":"质检·设定图"}}},

      {"id":"end","type":"end","position":{"x":1440,"y":210},
       "config":{"outputs":{"sheet_url":"{{check.sheet_url}}",
                            "element_id":"{{ensure.id}}"},
                 "ui":{"hide":true}}}
    ],
    "edges": [
      {"from":"start","to":"ensure"},
      {"from":"ensure","to":"gen"},
      {"from":"gen","to":"check"},
      {"from":"check","to":"end"}
    ]
  }$g$::jsonb,
  920, '{canvas,scene}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;
