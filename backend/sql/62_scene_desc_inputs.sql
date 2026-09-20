-- 「单场景设定描述」独立可跑：入参只留 项目 + 场景名，要素 id 由流程自己解析（2026-08-01）。
--
-- 初版把 element_id 做成必填入参，单独打开这张流程时运行面板给出的是一个**要手填的
-- 数字框**——用户根本无从知道 id 是多少（截图反馈）。项目/场景名有 ctx 下拉，id 没有。
--
-- 改法与「单场景设定图」画布里的 ensure 节点同一套：图里自带一个 element.upsert
-- （查找或创建，按 project_id+kind+name 幂等），拿到 id 再往下走。这样：
--   · 单独跑 → 选项目、选场景名即可；
--   · 被画布引用 → 画布也只传 project_id + scene_name，两边用同一条解析规则，
--     不会出现"外层按名字找的是 A、内层按 id 写的是 B"。
--
-- 幂等：靠 `input_schema ? 'element_id'` 作闸——修过一次之后条件不再成立。

UPDATE workflows SET
  input_schema = '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
                   "scene_name":{"type":"string","required":true,"desc":"场景","seq":1}}'::jsonb,
  graph = $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":40,"y":120},
       "config":{"ui":{"tap":"start","title":"开始","xy":true}}},

      {"id":"find","type":"action","position":{"x":380,"y":120},
       "config":{"name":"element.upsert",
                 "args":{"project_id":"{{input.project_id}}","kind":"scene",
                         "name":"{{input.scene_name}}"},
                 "preview":{"name":"element.find",
                            "args":{"project_id":"{{input.project_id}}","kind":"scene",
                                    "name":"{{input.scene_name}}"}},
                 "ui":{"tap":"link","title":"关联·场景要素","hide_in_run":true,"xy":true}}},

      {"id":"write","type":"llm","position":{"x":760,"y":120},
       "config":{
         "charter":"你是场景概念设定师。根据场景名与项目设定，写出这个地点的**画面描述**，供后续出图使用。\n严格要求：\n1. 只写画面可见之物——空间格局与体量、建筑结构与材质、地面与陈设、光照方向与时段、天气与色彩氛围。\n2. **不写剧情**：谁在这里做过什么、案件线索、人物关系、情节作用，一概不写。\n3. **场景名必须是描述的主体**，开头点明它是什么地方；不要被项目梗概里的其它地点带偏。\n4. 不写抽象形容词（温婉、古朴、文艺这类），要把它们落成具体的材质、光影与色彩。\n5. 只写场景，不写人物与生物。150 字以内，直接给正文，不要标题和解释。",
         "task":"项目 {{input.project_id}} 的场景「{{input.scene_name}}」。请写它的画面描述。",
         "tools":["project.info"],
         "skip_if":{"sql":"SELECT nullif(btrim(coalesce(brief,'')),'') FROM content_elements WHERE id=$1",
                    "args":["{{find.id}}"],
                    "reason":"该场景已有描述,跳过(缺才跑)；要重写请单独点这个节点"},
         "write":{"name":"element.set_brief",
                  "args":{"element_id":"{{find.id}}","brief":"{{write.text}}"}},
         "ui":{"tap":"text","title":"场景画面描述","show":"text","w":420,"h":300,"xy":true}}},

      {"id":"end","type":"end","position":{"x":1240,"y":120},
       "config":{"outputs":{"text":"{{write.text}}","element_id":"{{find.id}}"},
                 "ui":{"hide":true}}}
    ],
    "edges": [
      {"from":"start","to":"find"},
      {"from":"find","to":"write"},
      {"from":"write","to":"end"}
    ]
  }$g$::jsonb,
  updated_at = now()
WHERE slug = 'scene-desc' AND input_schema ? 'element_id';


-- 画布那边的引用也跟着只传 项目 + 场景名（要素解析交给被引用方，一处规则）。
UPDATE workflows SET graph = jsonb_set(
    graph, '{nodes}',
    (SELECT jsonb_agg(
        CASE WHEN n->>'id' = 'brief'
             THEN jsonb_set(n, '{config,inputs}',
                    '{"project_id":"{{input.project_id}}","scene_name":"{{input.scene_name}}"}'::jsonb)
             ELSE n END)
     FROM jsonb_array_elements(graph->'nodes') n)
  ), updated_at = now()
WHERE slug = 'scene-sheet-canvas'
  AND graph->'nodes' @> '[{"id":"brief","config":{"slug":"scene-desc"}}]'::jsonb
  AND graph::text LIKE '%element_id%{{ensure.id}}%';
