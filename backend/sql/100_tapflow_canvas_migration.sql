-- ═══════════════════════════════════════════════════════════════════════════
-- 画布收编（2026-09-18）：旧 InfiniteMediaCanvas 九处使用点全部迁移到 tapflow。
-- 本文件只**新增**模板（ON CONFLICT DO NOTHING，幂等），不动任何已发布模板；
-- 旧画布的专属数据（sop 画布/批量首帧板/画布回收站）不再被任何入口读写。
--
-- 新增 8 张模板与旧入口的对应关系：
--   asset-image-canvas        ← AddElementModal 生成图片 tab / 素材库 genFromRef
--   asset-video-canvas        ← AddElementModal 生成视频 tab
--   project-trailer-canvas    ← TrailerCard 先导预告片
--   scene-group-canvas        ← sceneGroups 两阶段画布（空场景→站位图）
--   shot-video-canvas         ← ShotSopCanvas(video)：关键帧子流程缺才跑 → gen_video
--   shot-lastframe-canvas     ← ShotSopCanvas(last)
--   storyboard-grid-canvas    ← StoryboardGridCanvas 宫格故事板
--   batch-keyframe-canvas     ← BatchKeyframeCanvas 批量首帧（loop 逐场景组）
-- 分镜首帧沿用既有 shot-keyframe-canvas（shotEditor image 入口直接打开）。
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1) 素材库图片画布 ──────────────────────────────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'asset-image-canvas','素材图片·画布',
  '自由图片生成：提示词/上游文本 → gen_canvas_image → 落项目附件（素材库可见），可带参考图。',
  1,'published',
  '{"project_id":{"type":"int","desc":"项目","seq":0},
    "ref_url":{"type":"string","desc":"参考图地址（素材库入口带入，可空）","seq":1},
    "prompt":{"type":"string","desc":"入口预填的需求句（可空）","seq":2}}'::jsonb,
  '{"image_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"开始"}}},
      {"id":"gen","type":"gen","position":{"x":520,"y":200},
       "config":{"modality":"image","step":"gen_canvas_image",
                 "instruction":"按需求生成一张图：{{input.prompt}}；带参考图时严格遵循其构图与内容。",
                 "payload":{"reference_images":[{"name":"参考图","kind":"upload","url":"{{input.ref_url}}"}]},
                 "ui":{"tap":"gen","title":"生成图片","w":460,"h":273,"model":"当前图片模型"}}},
      {"id":"end","type":"end","position":{"x":1060,"y":230},
       "config":{"outputs":{"image_url":"{{gen.url}}"},
                 "ui":{"tap":"next","title":"保存到素材库",
                       "next":{"attach":true,"notify":["任务中心"],"writes":["content_attachments"]}}}}
    ],
    "edges":[{"from":"start","to":"gen"},{"from":"gen","to":"end"}]
  }$g$::jsonb,
  905,'{canvas,图片,素材库}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 2) 素材库视频画布 ──────────────────────────────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'asset-video-canvas','素材视频·画布',
  '自由视频生成：提示词/上游首尾帧 → gen_canvas_video → 落项目附件（素材库可见）。',
  1,'published',
  '{"project_id":{"type":"int","desc":"项目","seq":0},
    "ref_url":{"type":"string","desc":"首帧参考图地址（可空）","seq":1},
    "prompt":{"type":"string","desc":"入口预填的需求句（可空）","seq":2}}'::jsonb,
  '{"video_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"开始"}}},
      {"id":"gen","type":"gen","position":{"x":520,"y":200},
       "config":{"modality":"video","step":"gen_canvas_video",
                 "instruction":"按需求生成一段视频：{{input.prompt}}；上游图片作为首帧参考。",
                 "payload":{"reference_images":[{"name":"首帧参考","kind":"upload","url":"{{input.ref_url}}"}]},
                 "ui":{"tap":"gen","title":"生成视频","w":460,"h":273,"model":"当前视频模型"}}},
      {"id":"end","type":"end","position":{"x":1060,"y":230},
       "config":{"outputs":{"video_url":"{{gen.url}}"},
                 "ui":{"tap":"next","title":"保存到素材库",
                       "next":{"attach":true,"notify":["任务中心"],"writes":["content_attachments"]}}}}
    ],
    "edges":[{"from":"start","to":"gen"},{"from":"gen","to":"end"}]
  }$g$::jsonb,
  906,'{canvas,视频,素材库}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 3) 项目预告片画布 ──────────────────────────────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'project-trailer-canvas','先导预告片·画布',
  '15s 硬切蒙太奇预告片（Seedance）：提示词为空时自动按项目配置蒸馏，生成条/对话改写优先 → 回写项目预告片字段。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0}}'::jsonb,
  '{"trailer_url":{"type":"string"},"prompt":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"开始"}}},
      {"id":"gen","type":"gen","position":{"x":520,"y":200},
       "config":{"modality":"video","step":"gen_trailer",
                 "instruction":"生成 15 秒先导预告片；角色设定图作参考图保持一致。提示词为空时按项目配置自动蒸馏。",
                 "ui":{"tap":"gen","title":"生成预告片","w":460,"h":273,"model":"当前视频模型"}}},
      {"id":"end","type":"end","position":{"x":1060,"y":230},
       "config":{"outputs":{"trailer_url":"{{gen.url}}","prompt":"{{gen.prompt}}"},
                 "ui":{"tap":"next","title":"保存预告片",
                       "next":{"attach":true,"notify":["任务中心"],
                               "writes":["content_projects.config.trailer_url"]}}}}
    ],
    "edges":[{"from":"start","to":"gen"},{"from":"gen","to":"end"}]
  }$g$::jsonb,
  915,'{canvas,预告片}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 4) 场景组两阶段画布（空场景基准图 → 角色站位图） ────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'scene-group-canvas','场景组·两阶段画布',
  '场景组画布：先出无人空场景基准图（空间真值），再以其为首参考生成角色站位图。缺前段自动补跑。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "chapter_id":{"type":"int","required":true,"desc":"章（集）","seq":1},
    "seg":{"type":"int","required":true,"desc":"场景组号","seq":2}}'::jsonb,
  '{"empty_url":{"type":"string"},"sheet_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"场景组"}}},
      {"id":"gen_empty","type":"gen","position":{"x":440,"y":120},
       "config":{"modality":"image","step":"gen_scene_empty","node_id":"{{input.chapter_id}}",
                 "payload":{"seg":"{{input.seg}}"},
                 "instruction":"生成本场景组的无人空场景基准图：锁死空间几何与光影，画面中没有任何人物。",
                 "ui":{"tap":"gen","title":"① 空场景基准图","w":460,"h":273,"model":"当前图片模型"}}},
      {"id":"gen_sheet","type":"gen","position":{"x":980,"y":240},
       "config":{"modality":"image","step":"gen_scene_sheet","node_id":"{{input.chapter_id}}",
                 "payload":{"seg":"{{input.seg}}"},
                 "instruction":"在空场景基准图上生成角色站位图：空间、机位与光线照搬基准图，只新增角色。",
                 "ui":{"tap":"gen","title":"② 角色站位图","w":460,"h":273,"model":"当前图片模型"}}},
      {"id":"end","type":"end","position":{"x":1500,"y":260},
       "config":{"outputs":{"empty_url":"{{gen_empty.url}}","sheet_url":"{{gen_sheet.url}}"},
                 "ui":{"tap":"next","title":"保存场景组",
                       "next":{"attach":true,"notify":["任务中心"],
                               "writes":["content_nodes.meta.scene_blocking"]}}}}
    ],
    "edges":[{"from":"start","to":"gen_empty"},
             {"from":"gen_empty","to":"gen_sheet"},
             {"from":"gen_sheet","to":"end"}]
  }$g$::jsonb,
  925,'{canvas,scene}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 5) 分镜视频画布（关键帧缺才跑 → gen_video） ────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'shot-video-canvas','分镜视频·画布',
  '镜头视频：首帧子流程（缺才跑，已有即跳过）→ gen_video 生成成品视频 → 回写 video_url。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "shot_id":{"type":"int","required":true,"desc":"分镜","seq":1}}'::jsonb,
  '{"video_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"开始"}}},
      {"id":"ensure_keyframe","type":"subflow","position":{"x":420,"y":140},
       "config":{"slug":"shot-keyframe-canvas",
                 "inputs":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                 "ui":{"tap":"gen","title":"首帧（缺才跑）","w":460,"h":273}}},
      {"id":"gen","type":"gen","position":{"x":960,"y":220},
       "config":{"modality":"video","step":"gen_video","node_id":"{{input.shot_id}}",
                 "instruction":"以首帧为 I2V 锚点生成分镜视频；提示词用该镜已装填的视频提示词。",
                 "skip_if":{"sql":"SELECT meta->>'video_url' FROM content_nodes WHERE id=$1",
                            "args":["{{input.shot_id}}"],
                            "reason":"该分镜已有视频，跳过（生成条发送可强制重出）"},
                 "ui":{"tap":"gen","title":"生成分镜视频","w":460,"h":273,"model":"当前视频模型"}}},
      {"id":"end","type":"end","position":{"x":1480,"y":250},
       "config":{"outputs":{"video_url":"{{gen.url}}"},
                 "ui":{"tap":"next","title":"保存并提供",
                       "next":{"attach":true,"notify":["任务中心"],
                               "writes":["content_attachments","content_nodes.meta.video_url"]}}}}
    ],
    "edges":[{"from":"start","to":"ensure_keyframe"},
             {"from":"ensure_keyframe","to":"gen"},
             {"from":"gen","to":"end"}]
  }$g$::jsonb,
  935,'{canvas,shot,video}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 5b) 分镜尾帧画布 ──────────────────────────────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'shot-lastframe-canvas','分镜尾帧·画布',
  '尾帧定格画面：与首帧同路径生图（设定图参考+引用句），产物回写 meta.last_frame_url。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "shot_id":{"type":"int","required":true,"desc":"分镜","seq":1}}'::jsonb,
  '{"last_frame_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"开始"}}},
      {"id":"context","type":"action","position":{"x":420,"y":200},
       "config":{"name":"shot.keyframe.context",
                 "args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                 "ui":{"tap":"text","title":"分镜数据与统一参考资产","show":"summary","w":420,"h":320}}},
      {"id":"gen","type":"gen","position":{"x":920,"y":200},
       "config":{"modality":"image","node_id":"{{input.shot_id}}",
                 "step":"gen_last_keyframe",
                 "instruction":"生成该镜的尾帧定格画面：与首帧同画风同角色，收束本镜动作。",
                 "skip_if":{"sql":"SELECT meta->>'last_frame_url' FROM content_nodes WHERE id=$1",
                            "args":["{{input.shot_id}}"],
                            "reason":"该分镜已有尾帧，跳过（生成条发送可强制重出）"},
                 "ui":{"tap":"gen","title":"生成尾帧","w":460,"h":273,"model":"当前图片模型"}}},
      {"id":"end","type":"end","position":{"x":1440,"y":230},
       "config":{"outputs":{"last_frame_url":"{{gen.url}}"},
                 "ui":{"tap":"next","title":"保存尾帧",
                       "next":{"attach":true,"notify":["任务中心"],
                               "writes":["content_attachments","content_nodes.meta.last_frame_url"]}}}}
    ],
    "edges":[{"from":"start","to":"context"},{"from":"context","to":"gen"},{"from":"gen","to":"end"}]
  }$g$::jsonb,
  936,'{canvas,shot,lastframe}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 6) 宫格故事板画布 ──────────────────────────────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'storyboard-grid-canvas','分镜故事板·画布',
  '章级分镜总览宫格（3:2，每格一镜）：board=N 只重出第 N 张，缺省出全部；每镜回写 storyboard_ref。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "chapter_id":{"type":"int","required":true,"desc":"章（集）","seq":1},
    "board":{"type":"int","desc":"只重出第 N 张（可空=全部）","seq":2}}'::jsonb,
  '{"grid_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"章"}}},
      {"id":"gen","type":"gen","position":{"x":520,"y":200},
       "config":{"modality":"image","step":"gen_overview_grid","node_id":"{{input.chapter_id}}",
                 "instruction":"生成本章分镜总览宫格故事板：每格一镜，画面之间共享造型与空间逻辑。",
                 "payload":{"board":"{{input.board}}"},
                 "ui":{"tap":"gen","title":"生成宫格故事板","w":460,"h":273,"model":"当前图片模型"}}},
      {"id":"end","type":"end","position":{"x":1060,"y":230},
       "config":{"outputs":{"grid_url":"{{gen.url}}"},
                 "ui":{"tap":"next","title":"保存宫格",
                       "next":{"attach":true,"notify":["任务中心"],
                               "writes":["content_nodes.meta.storyboard_ref"]}}}}
    ],
    "edges":[{"from":"start","to":"gen"},{"from":"gen","to":"end"}]
  }$g$::jsonb,
  945,'{canvas,storyboard}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;

-- ── 7) 批量首帧画布（loop 逐场景组） ───────────────────────────────────────
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'batch-keyframe-canvas','批量首帧·画布',
  '整集分镜按场景切组批量出首帧：计划节点列出各批次（同场景合同一批，≤6镜），loop 逐批 gen_keyframes_group。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "chapter_id":{"type":"int","required":true,"desc":"章（集）","seq":1},
    "seg":{"type":"int","desc":"只装该场景组（可空=全部）","seq":2},
    "note":{"type":"string","desc":"整组一致性约束（全局要求）","seq":3}}'::jsonb,
  '{"results":{"type":"array"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":240},
       "config":{"ui":{"tap":"start","title":"章"}}},
      {"id":"plan","type":"action","position":{"x":420,"y":200},
       "config":{"name":"scene.batch_plan",
                 "args":{"project_id":"{{input.project_id}}","chapter_id":"{{input.chapter_id}}"},
                 "ui":{"tap":"tool","title":"场景分组计划","w":420,"h":300}}},
      {"id":"batch_loop","type":"loop","position":{"x":900,"y":200},
       "config":{"source":"{{plan.batches}}","body":["gen_group"],"concurrency":2,
                 "ui":{"tap":"loop","title":"逐场景组出图","show_loop_body":true}}},
      {"id":"gen_group","type":"gen","position":{"x":1360,"y":220},
       "config":{"modality":"image","step":"gen_keyframes_group","node_id":"{{input.chapter_id}}",
                 "instruction":"按该场景组的设定图参考池批量生成组内各镜首帧：组内同一场景、同一批角色必须完全一致。",
                 "payload":{"shot_ids":"{{__item__.shot_ids}}",
                            "refs":"{{__item__.refs}}",
                            "note":"{{input.note}}"},
                 "ui":{"tap":"gen","title":"生成组图","w":460,"h":273,"model":"当前图片模型"}}},
      {"id":"end","type":"end","position":{"x":1840,"y":250},
       "config":{"outputs":{"results":"{{batch_loop.results}}"},
                 "ui":{"tap":"next","title":"批次汇总",
                       "next":{"attach":true,"notify":["任务中心"],"writes":["content_attachments"]}}}}
    ],
    "edges":[{"from":"start","to":"plan"},
             {"from":"plan","to":"batch_loop"},
             {"from":"batch_loop","to":"gen_group","mapping":"each"},
             {"from":"gen_group","to":"end","mapping":"collect"}]
  }$g$::jsonb,
  955,'{canvas,batch,keyframe}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;
