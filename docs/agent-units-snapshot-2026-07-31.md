# 智能体编排 config 快照（2026-07-31，本地库导出）

> 由 `backend/scripts/dump_agent_units.py` 从 `workflows` 表导出（每 slug 取最新版本），
> 用途：让只存在数据库里的 charter/task 在仓库里可 review、可 diff。
> **这不是自动执行的 seed**——不会在启动时回写，画布上的手编不受影响。
> 重新导出：`backend/.venv/Scripts/python.exe backend/scripts/dump_agent_units.py`。

## a.project-info v1（补齐项目基本信息，draft，seq=10）

- **charter**：你是项目筹备编辑，负责把项目的基本盘（题材/风格/受众）补齐。
- **task**：补齐项目基本信息。
- **folder_ids**：`[6]`
- **tools**：`["project.info"]`
- **step**：gen_project_info
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}]`

## a.project-outline v1（生成长篇大纲，draft，seq=20）

- **charter**：你是长篇小说的结构编辑，负责生成整部作品的卷章目录。
- **task**：生成长篇大纲。
- **skills**：`["legacy-skill-97"]`
- **folder_ids**：`[2]`
- **tools**：`["project.info"]`
- **ref_flows**：`["a.project-info"]`
- **dep_mode**：serial
- **step**：gen_outline_md
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}]`

## a.element-kinds v1（判定要素类型，draft，seq=30）

- **charter**：你是设定集管理员，负责判定每个要素属于角色/场景/道具/势力/设定。
- **task**：判定要素类型。
- **tools**：`["project.info", "db.query"]`
- **args**：`{"sql": "SELECT id,kind,name,brief FROM content_elements WHERE project_id=$1 ORDER BY kind,id", "args": ["{{ctx.project_id}}"], "limit": 200}`
- **ref_flows**：`["a.project-info"]`
- **dep_mode**：serial
- **step**：gen_element_kinds
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}]`

## c.project-bootstrap v1（项目视觉定妆，draft，seq=40）

- **task**：完成项目筹备。
- **ref_flows**：`["a.project-info", "a.project-outline", "a.element-kinds"]`
- **dep_mode**：serial
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}]`

## a.character-sheet v1（单角色设定图，draft，seq=50）

- **charter**：你是角色视觉设计师，为角色产出全身设定图的生图提示词。
- **task**：
  ```
  先用 element.get 取当前角色（element_id={{ctx.element_id}}）的姓名、简介与外貌设定，再用 project.info 取项目画风，然后装配这个角色的设定图提示词（三视图/表情/色板）。只输出提示词正文，不要解释。
  ```
- **skills**：`["legacy-skill-146", "legacy-skill-222"]`
- **folder_ids**：`[5, 2054, 2470]`
- **tools**：`["element.get", "project.info"]`
- **tool_names**：`["element.get", "project.info", "db.query"]`
- **step**：gen_element_sheet
- **only_missing**：yes
- **writes**：content_elements.meta.sheet_url
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "element_id", "key": "element_id", "type": "ctx", "label": "要素（角色/场景）", "required": true}]`

## a.scene-sheet v1（单场景概念图，draft，seq=60）

- **charter**：你是场景概念设计师，为场景产出环境设定图的生图提示词。
- **task**：为当前场景装配概念图提示词。
- **skills**：`["legacy-skill-223", "legacy-skill-221"]`
- **folder_ids**：`[5, 2054, 2471, 2469]`
- **tools**：`["element.get", "project.info"]`
- **step**：gen_element_sheet
- **only_missing**：yes
- **writes**：content_elements.meta.sheet_url
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "element_id", "key": "element_id", "type": "ctx", "label": "要素（角色/场景）", "required": true}]`

## a.chapter-breakdown v1（粗拆分镜骨架，draft，seq=70）

- **charter**：你是分镜导演，第一轮先拆出本章的分镜骨架。
- **task**：对本章执行 粗拆分镜骨架。
- **skills**：`["legacy-skill-195", "legacy-skill-194"]`
- **folder_ids**：`[2, 5]`
- **tools**：`["project.info"]`
- **step**：breakdown_chapter
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.chapter-expand v1（展开详细分镜，draft，seq=80）

- **charter**：你是分镜导演，第二轮把骨架展开成带镜头语言的详细分镜。
- **task**：对本章执行 展开详细分镜。
- **skills**：`["legacy-skill-196"]`
- **folder_ids**：`[5]`
- **ref_flows**：`["a.chapter-breakdown"]`
- **dep_mode**：serial
- **step**：expand_shot_details
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.chapter-blocking v1（场景归组与空间规划，draft，seq=90）

- **charter**：你是美术指导，做本章的场景归组与空间规划。
- **task**：对本章执行 场景归组与空间规划。
- **skills**：`["legacy-skill-214"]`
- **folder_ids**：`[2469]`
- **ref_flows**：`["a.chapter-expand"]`
- **dep_mode**：serial
- **step**：scene_blocking
- **only_missing**：yes
- **writes**：content_nodes.meta.scene_blocking
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.scene-empty v1（单场景空场景基准图，draft，seq=100）

- **charter**：你是布景师，产出无人的空场景基准图——下游站位图和镜头的空间真值。
- **task**：为当前场景组装配无人空场景基准图提示词，钉死几何与光。
- **skills**：`["scene-light-blocking-anchor", "legacy-skill-214"]`
- **folder_ids**：`[5, 2469]`
- **ref_flows**：`["a.chapter-blocking"]`
- **dep_mode**：serial
- **step**：gen_scene_empty
- **batch**：ctx.scene_groups_empty
- **only_missing**：yes
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.scene-blocking v1（单场景角色站位图，draft，seq=110）

- **charter**：你是走位导演，在空场景基准图之上摆角色站位。
- **task**：在空场景基准图上装配角色站位图提示词，只往里加人。
- **skills**：`["scene-light-blocking-anchor"]`
- **folder_ids**：`[5, 2469]`
- **ref_flows**：`["a.scene-empty"]`
- **dep_mode**：serial
- **step**：gen_scene_sheet
- **batch**：ctx.scene_groups_sheet
- **only_missing**：yes
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.chapter-stills v1（整集选定格，draft，seq=120）

- **charter**：你是剪辑指导，从整集分镜里选定关键格。
- **task**：对本章执行 整集选定格。
- **skills**：`["legacy-skill-96"]`
- **ref_flows**：`["a.chapter-expand"]`
- **dep_mode**：serial
- **step**：gen_stills
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.chapter-grid v1（分镜总览宫格，draft，seq=130）

- **charter**：你是出版编辑，把整集分镜排成总览宫格。
- **task**：对本章执行 分镜总览宫格。
- **ref_flows**：`["a.chapter-expand"]`
- **dep_mode**：serial
- **step**：gen_overview_grid
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## c.chapter-to-storyboard v1（章节到分镜，draft，seq=140）

- **task**：把本章正文拆成可拍摄的分镜序列。
- **ref_flows**：`["a.chapter-breakdown", "a.chapter-expand", "a.chapter-blocking", "a.chapter-stills"]`
- **dep_mode**：serial
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## c.episode-elements v1（本集要素备齐，draft，seq=150）

- **task**：确保本集出场的角色与场景都有设定图。
- **tools**：`["shot.elements"]`
- **ref_flows**：`["q.shot-elements", "a.character-sheet"]`
- **ref_each**：`["a.character-sheet"]`
- **batch**：ctx.characters
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## c.episode-scenes v1（本集场景锚定，draft，seq=160）

- **task**：为本集每个场景组出锚定图。
- **ref_flows**：`["q.scene-groups", "a.scene-empty", "a.scene-blocking"]`
- **ref_each**：`["a.scene-empty", "a.scene-blocking"]`
- **dep_mode**：serial
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.shot-storyboard v1（单镜镜头语言，draft，seq=170）

- **charter**：你是分镜师，把本镜拆成镜头语言完整的 cuts 序列。
- **task**：为当前镜头生成镜内时间轴、景别、主体动作、运镜与硬切。
- **skills**：`["legacy-skill-196", "legacy-skill-194"]`
- **folder_ids**：`[5]`
- **tools**：`["shot.elements"]`
- **step**：gen_shot_storyboard
- **only_missing**：yes
- **writes**：content_nodes.meta.cuts
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## a.shot-prompt v1（单镜提示词装配，draft，seq=180）

- **charter**：你是本项目的分镜画师，为当前镜头装配首帧生图提示词。
- **task**：为当前镜头装配首帧图/视频/纯文本三套提示词。
- **skills**：`["legacy-skill-98", "legacy-skill-182"]`
- **folder_ids**：`[5, 2054]`
- **tools**：`["shot.elements"]`
- **ref_flows**：`["a.shot-storyboard"]`
- **dep_mode**：serial
- **step**：gen_prompts
- **only_missing**：yes
- **writes**：content_nodes.meta.image_prompt
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## g.shot-elements v1（守卫·取本镜出场要素，draft，seq=183）

- **charter**：守卫：取本镜出场要素。先查已关联要素是否齐全，缺则由模型按正文判定并补建入库，后续环节直接取用。
- **tools**：`["shot.ensure_elements"]`
- **args**：`{"shot_id": "{{ctx.node_id}}", "project_id": "{{ctx.project_id}}"}`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## g.shot-sheets v1（守卫·补要素设定图，draft，seq=184）

- **charter**：守卫：补要素设定图。设定图是身份/画风锚点，缺图或外貌已改必须先补，否则下游每张图一致地画错。会真实出图（花钱），指纹命中即跳过。
- **tools**：`["shot.ensure_sheets"]`
- **args**：`{"shot_id": "{{ctx.node_id}}", "project_id": "{{ctx.project_id}}"}`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## g.shot-blocking v1（守卫·场景站位兜底，draft，seq=185）

- **charter**：守卫：场景站位兜底。本镜场景组缺站位链就先做空间规划，保证出图时空间/光线/站位有真值可引。
- **tools**：`["shot.ensure_blocking"]`
- **args**：`{"shot_id": "{{ctx.node_id}}", "project_id": "{{ctx.project_id}}"}`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## g.shot-reassemble v1（守卫·重装配提示词，draft，seq=186）

- **charter**：守卫：重装配提示词与参考图。设定图 URL 固化在镜 meta 里，重出过设定图后必须重装配才指得到最新图；手编提示词由装配内部尊重。
- **tools**：`["shot.reassemble_prompts"]`
- **args**：`{"shot_id": "{{ctx.node_id}}", "project_id": "{{ctx.project_id}}"}`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## g.shot-image-qc v1（守卫·首帧提示词质检，draft，seq=187）

- **charter**：守卫：首帧提示词质检。十维评审，不合格自动重构后复审；出图环节不再重跑质检，以本守卫结果为准。
- **tools**：`["shot.review_image_prompt"]`
- **args**：`{"shot_id": "{{ctx.node_id}}", "project_id": "{{ctx.project_id}}"}`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## a.shot-keyframe v1（单镜首帧，draft，seq=190）

- **charter**：你是出图执行者，确保首帧引用了正确的角色/场景设定图。
- **skills**：`["legacy-skill-182"]`
- **ref_flows**：`["g.shot-elements", "g.shot-sheets", "g.shot-blocking", "a.shot-prompt", "g.shot-reassemble", "g.shot-image-qc"]`
- **dep_mode**：serial
- **step**：gen_keyframe_v2
- **only_missing**：yes
- **writes**：content_nodes.meta.keyframe_url
- **attach**：no
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## a.shot-lastframe v1（单镜尾帧，draft，seq=200）

- **charter**：你是尾帧设计师，基于首帧推演本镜结束时刻的画面。
- **task**：为当前镜头出尾帧定格画面。
- **skills**：`["legacy-skill-182", "subject-aware-scene-transitions"]`
- **folder_ids**：`[5]`
- **ref_flows**：`["a.shot-keyframe"]`
- **dep_mode**：serial
- **step**：gen_last_keyframe
- **only_missing**：yes
- **writes**：content_nodes.meta.last_frame_url
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## a.shot-video v1（单镜视频，draft，seq=210）

- **charter**：你是运镜师，为首尾帧之间的运动装配视频提示词。
- **task**：为当前镜头出视频。
- **skills**：`["legacy-skill-181", "subject-aware-scene-transitions"]`
- **folder_ids**：`[5, 2054]`
- **ref_flows**：`["a.shot-keyframe", "a.shot-lastframe"]`
- **dep_mode**：serial
- **step**：gen_video
- **only_missing**：yes
- **writes**：content_nodes.meta.video_url
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "镜（单镜）", "required": true}]`

## c.episode-keyframes v1（本集批量首帧，draft，seq=220）

- **task**：为本集所有镜头出首帧。
- **ref_flows**：`["c.episode-elements", "c.episode-scenes", "a.shot-prompt", "a.shot-keyframe"]`
- **ref_each**：`["a.shot-prompt", "a.shot-keyframe"]`
- **step**：gen_keyframe
- **batch**：ctx.shots
- **only_missing**：yes
- **writes**：content_nodes.meta.keyframe_url
- **notify**：`["frontend.refresh"]`
- **then_flows**：`["c.episode-video"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## c.episode-video v1（本集批量视频，draft，seq=230）

- **task**：为本集所有镜头出视频。
- **ref_flows**：`["c.episode-keyframes", "a.shot-lastframe", "a.shot-video"]`
- **ref_each**：`["a.shot-lastframe", "a.shot-video"]`
- **step**：gen_video
- **batch**：ctx.shots
- **only_missing**：yes
- **writes**：content_nodes.meta.video_url
- **notify**：`["frontend.refresh"]`
- **inputs**：`[{"ctx": "project_id", "key": "project_id", "type": "ctx", "label": "项目", "required": true}, {"ctx": "node_id", "key": "node_id", "type": "ctx", "label": "章（本章）", "required": true}]`

## a.voice-sample v1（单音色试听，draft，seq=240）

- **charter**：你是配音导演，为音色库生成试听样本。
- **task**：为当前音色生成试听样本。
- **folder_ids**：`[4]`
- **step**：gen_voice_samples
- **only_missing**：yes
- **writes**：kb_entries.meta.sample_audio_url
- **attach**：yes
- **notify**：`["frontend.refresh"]`
- **on_fail**：skip

## q.project-info v1（查项目基本信息，draft，seq=250）

- **tools**：`["project.info"]`
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`

## q.element v1（查单个要素，draft，seq=260）

- **tools**：`["element.get", "element.sheet_exists"]`
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`

## q.chapter-shots v1（查本章所有镜头，draft，seq=270）

- **tools**：`["db.query"]`
- **args**：`{"sql": "SELECT id, coalesce(meta->>'shot_no', seq::text) AS shot_no, summary, (meta->>'keyframe_url') IS NOT NULL AS has_keyframe, (meta->>'video_url') IS NOT NULL AS has_video FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL ORDER BY seq", "args": ["{{ctx.node_id}}"], "limit": 50}`
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`

## q.scene-groups v1（查本章场景归组，draft，seq=280）

- **tools**：`["db.query"]`
- **args**：`{"sql": "SELECT DISTINCT meta->>'scene' AS scene, count(*) AS shots FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL GROUP BY 1 ORDER BY 2 DESC", "args": ["{{ctx.node_id}}"], "limit": 50}`
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`

## q.shot-elements v1（查本镜关联角色场景，draft，seq=290）

- **tools**：`["shot.elements"]`
- **only_missing**：yes
- **notify**：`["frontend.refresh"]`

## 工作流引擎 DAG 图（非 unit，仅列名）

- ep-batch-keyframe v1（某一集·批量首帧，draft）
- element-sheet v1（生成要素设定图，published）
- shot-prepare-elements v1（单镜要素准备，published）
