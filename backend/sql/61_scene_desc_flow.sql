-- 「单场景设定描述」：文本类工作流，产出**画面描述**并回写要素 brief（2026-08-01）。
--
-- 由来：出图那条链原先直接吃 content_elements.brief，而 brief 里装的是章节拆解写的
-- **剧情**文字（「可疑年轻人徘徊的地方，老刑警在这里发现了…」）——一个字都不描述
-- 这地方长什么样。模型手里只剩世界观里的「江南小镇」，于是给「废弃仓库」画出了
-- 水乡河道（实测 run 84 之前）。所以场景描述本身该是一条独立、可编辑、可重跑的
-- 工作流，而不是藏在别人的前置里。
--
-- 产物仍落 **brief**（不另开字段）：brief 本就是要素的设定描述，只是内容被写错了；
-- 另开一列会让"场景是什么样"分裂成两处真相。
--
-- 重跑语义（用户 2026-08-01 定稿）：
--   · 被别的流程引用   → 缺才跑（brief 已有就不跑）；
--   · 单独点这个节点   → 强制重跑（引擎 force 命中 subflow 节点时整张子图重跑，
--                        见 workflow.FORCE_ALL；生成条里的指令经同一通配键传进来）。
--
-- tags 含 canvas → 出现在 tapflow 列表里，可单独打开、编辑、试跑。

INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-desc', '单场景设定描述',
  '按场景名与项目设定写出可直接用于出图的画面描述（空间格局/建筑与材质/光照与时段/色彩氛围），回写要素 brief。缺才跑；单独点节点可强制重写。',
  1, 'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "element_id":{"type":"int","required":true,"desc":"场景要素 id","seq":1},
    "scene_name":{"type":"string","required":false,"desc":"场景名","seq":2}}'::jsonb,
  '{"text":{"type":"string"}}'::jsonb,
  $g${
    "nodes": [
      {"id":"start","type":"start","position":{"x":40,"y":120},
       "config":{"ui":{"tap":"start","title":"开始","xy":true}}},

      {"id":"write","type":"llm","position":{"x":420,"y":120},
       "config":{
         "charter":"你是场景概念设定师。根据场景名与项目设定，写出这个地点的**画面描述**，供后续出图使用。\n严格要求：\n1. 只写画面可见之物——空间格局与体量、建筑结构与材质、地面与陈设、光照方向与时段、天气与色彩氛围。\n2. **不写剧情**：谁在这里做过什么、案件线索、人物关系、情节作用，一概不写。\n3. **场景名必须是描述的主体**，开头点明它是什么地方；不要被项目梗概里的其它地点带偏。\n4. 不写抽象形容词（温婉、古朴、文艺这类），要把它们落成具体的材质、光影与色彩。\n5. 只写场景，不写人物与生物。150 字以内，直接给正文，不要标题和解释。",
         "task":"项目 {{input.project_id}} 的场景「{{input.scene_name}}」。请写它的画面描述。",
         "tools":["project.info"],
         "skip_if":{"sql":"SELECT nullif(btrim(coalesce(brief,'')),'') FROM content_elements WHERE id=$1",
                    "args":["{{input.element_id}}"],
                    "reason":"该场景已有描述,跳过(缺才跑)；要重写请单独点这个节点"},
         "write":{"name":"element.set_brief",
                  "args":{"element_id":"{{input.element_id}}","brief":"{{write.text}}"}},
         "ui":{"tap":"text","title":"场景画面描述","show":"text","w":420,"h":300,"xy":true}}},

      {"id":"end","type":"end","position":{"x":900,"y":120},
       "config":{"outputs":{"text":"{{write.text}}"},"ui":{"hide":true}}}
    ],
    "edges": [
      {"from":"start","to":"write"},
      {"from":"write","to":"end"}
    ]
  }$g$::jsonb,
  910, '{canvas,scene,text}'::text[]
)
ON CONFLICT (slug, version) DO NOTHING;


-- 画布上那个「场景介绍」节点改引用它：subflow 换 slug，标题与判据同步。
-- 只动 config 里这几个键，其余（位置/尺寸/边）原样不动。
UPDATE workflows SET graph = jsonb_set(
    graph,
    '{nodes}',
    (SELECT jsonb_agg(
        CASE WHEN n->>'id' = 'brief'
             THEN jsonb_set(
                    jsonb_set(n, '{config,slug}', '"scene-desc"'::jsonb),
                    '{config,ui,title}', '"场景设定描述"'::jsonb)
             ELSE n END)
     FROM jsonb_array_elements(graph->'nodes') n)
  ), updated_at = now()
WHERE slug = 'scene-sheet-canvas'
  AND graph->'nodes' @> '[{"id":"brief"}]'::jsonb
  AND NOT (graph::text LIKE '%scene-desc%');
