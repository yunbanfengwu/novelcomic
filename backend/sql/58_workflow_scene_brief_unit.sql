-- 场景介绍抽成**独立最小集**(2026-08-01)。
--
-- 原来它是单场景画布里的一个 llm 节点。抽出来的理由与「element-sheet 是最小集」一样:
-- 别的流程也要用（角色卡、分镜、批量补场景设定），内联在某张画布里就只有那张画布能用。
-- 画布那边改成 subflow 引用它——节点形态、缺才跑、回写语义全不变。
--
-- 「缺才跑」放在**两层**都判：最小集自己判（被别处调用时也省）、画布的 subflow 节点也判
-- （省掉一次子运行的建行开销）。判据同源，都是 element.brief 非空。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-brief', '场景介绍',
  '按场景名与项目设定写一段场景详细介绍并回写要素 brief。缺才跑——要素已有介绍直接取用。',
  1, 'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目"},
    "element_id":{"type":"int","required":true,"desc":"场景要素 id"},
    "scene_name":{"type":"string","required":false,"desc":"场景名（日志与提示词用）"}}'::jsonb,
  '{"text":{"type":"string"}}'::jsonb,
  $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":40,"y":120},
       "config":{"ui":{"tap":"start","title":"开始"}}},

      {"id":"write","type":"llm","position":{"x":360,"y":120},
       "config":{"charter":"你是世界观设定师。根据场景名与项目设定,写一段场景详细介绍:空间格局、材质与光照、时段与氛围、可供表演的关键道具。只写场景,不写人物。150 字以内,直接给正文,不要标题和解释。",
                 "task":"项目 {{input.project_id}} 的场景「{{input.scene_name}}」。请写它的场景介绍。",
                 "tools":["project.info"],
                 "skip_if":{"sql":"SELECT nullif(btrim(coalesce(brief,'')),'') FROM content_elements WHERE id=$1",
                            "args":["{{input.element_id}}"],
                            "reason":"该场景已有介绍,跳过(缺才跑)"},
                 "write":{"name":"element.set_brief",
                          "args":{"element_id":"{{input.element_id}}","brief":"{{write.text}}"}},
                 "ui":{"tap":"text","title":"场景介绍","show":"text","w":360,"h":300}}},

      {"id":"end","type":"end","position":{"x":760,"y":120},
       "config":{"outputs":{"text":"{{write.text}}"},"ui":{"hide":true}}}
    ],
    "edges": [{"from":"start","to":"write"},{"from":"write","to":"end"}]
  }$g$::jsonb,
  910, '{unit,scene}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;

-- 画布 v7：场景介绍节点改为引用上面那个最小集。
-- 节点在画布上仍是一张「场景介绍」文本卡（ui.tap=text / show=text），
-- 用户看不出它从内联变成了引用——这正是抽最小集不该有的副作用。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目 + 场景 → 要素入库 → 场景介绍(引用最小集,缺才跑) → 设定图(装配+质检+出图) → 回写。',
  7, 'published',
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
                 "ui":{"tap":"text","title":"场景介绍","show":"text","w":360,"h":300}}},

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
                 "ui":{"tap":"gen","title":"场景设定图","w":460,"h":273,
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
