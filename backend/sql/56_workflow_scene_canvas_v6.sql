-- 单场景设定图画布 v6(2026-08-01):对齐前端定稿的四节点形态。
--
--   开始(只定位:项目/章可空,场景必填)
--    → 关联·场景要素(action element.upsert,运行态隐藏)
--    → 场景介绍(llm,缺才跑;写出来的介绍回写 element.brief)
--    → 场景设定图(gen,三层装配 + 质检 + 出图三合一)
--    → next · 回写与通知(end)
--
-- 与 v5 的差别:
--   1. 开始节点去掉「场景说明」「参考图」两个入参——说明是**产物**不是入参(由场景介绍
--      节点生成);参考图有正当来源(要素已有的 extra_refs、上游连进来的图片节点),不该手填。
--   2. 新增 llm 类型的「场景介绍」节点,缺才跑(要素已有 brief 就跳过,直接用已有那份)。
--   3. gen 节点带质检配置:判法来自技能(kb 里的 reviewer 条目),阈值/时机/重试是本条产线
--      的策略。stage=prompt 出图前判,不合格带问题清单重装配再判,用尽次数则停链**不出图**。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'scene-sheet-canvas', '单场景设定图',
  '项目 + 场景 → 要素入库 → 场景介绍(缺才跑) → 设定图(装配+质检+出图) → 回写。force=["gen"] 强制重出。',
  6, 'published',
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

      {"id":"brief","type":"llm","position":{"x":720,"y":200},
       "config":{"charter":"你是世界观设定师。根据场景名与项目设定,写一段场景详细介绍:空间格局、材质与光照、时段与氛围、可供表演的关键道具。只写场景,不写人物。150 字以内,直接给正文,不要标题和解释。",
                 "task":"项目 {{input.project_id}} 的场景「{{input.scene_name}}」。请写它的场景介绍。",
                 "tools":["project.info"],
                 "skip_if":{"sql":"SELECT nullif(btrim(coalesce(brief,'')),'') FROM content_elements WHERE id=$1",
                            "args":["{{ensure.id}}"],
                            "reason":"该场景已有介绍,跳过(缺才跑)"},
                 "write":{"name":"element.set_brief",
                          "args":{"element_id":"{{ensure.id}}","brief":"{{brief.text}}"}},
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
                            "reason":"该场景已有设定图,跳过(force=[\"gen\"] 强制重出)"},
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

-- 质检技能:判法放 kb（项目级可覆盖全局），输出结构由 _REVIEW_JSON_TAIL 代码强制。
-- 不同工作流的质检规则不一样,所以判法必须可换——这条是「场景设定图」这条产线用的。
--
-- ⚠️ 幂等靠 WHERE NOT EXISTS，不能用 ON CONFLICT DO NOTHING：kb_entries 上没有任何唯一
-- 约束（只有 pkey 和普通索引），ON CONFLICT 永远不触发，本文件每次启动都会新插一条。
-- 实测本地开发库累积到 128 条同名「场景设定图质检」、连带 127 个 legacy-skill-* 包
-- （skill_packages 按 kb id 一对一派生），生产每部署一次 +1。去重见 64_dedupe_qc_scene_skill。
-- 判重键与 knowledge_seed._seed_skills 保持一致：scope + kind + agent_code + name。
INSERT INTO kb_entries(kind, agent_code, name, content, enabled, scope)
SELECT 'skill', 'reviewer', '场景设定图质检',
$q$你是场景设定图提示词质检员。判定这段提示词能不能出一张合格的**场景概念图**。
六个维度：
1 主体是地点：空间格局/建筑结构/地貌是画面主体，不是某个人或生物的特写
2 无人无生物：不得出现主要人物、具名角色、可识别人物、主要兽类、坐骑、怪兽；
  也不得用剪影、影子、倒影、雕像、壁画变相表现它们（远景不可辨的路人群像可以）
3 双景别版式：同时交代大远景全貌与中景细部
4 材质与光照：写出关键材质（金属/木/玻璃/岩石…）与光源、时段、天气
5 世界观贴合：与项目画风、年代、地域设定不冲突
6 可执行性：具体可画，没有「氛围感拉满/高级感」这类无法落笔的抽象词
得分 0-100。任一硬性维度（2 无人无生物）不满足即判不合格。$q$,
       true, 'global'
WHERE NOT EXISTS (
  SELECT 1 FROM kb_entries
   WHERE scope='global' AND kind='skill' AND agent_code='reviewer'
     AND name='场景设定图质检');
