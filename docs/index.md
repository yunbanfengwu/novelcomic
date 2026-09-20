# 文档索引

> 全项目文档入口。**新增文档同时改这里**。规范：每篇文档标题行带（状态 · 日期）；项目基本信息见根目录 [README.md](../README.md)。

## research — 开源调研（2026-07-08 完成）

- [tech-selection-summary.md](research/tech-selection-summary.md) —— **开源选型组合总览（调研定稿 2026-07-08）**：汇合四份分项调研的总装配图——自建薄平台(mneme 同构六表+四层抽象)为脑子 + ComfyUI 媒体引擎为肌肉 + PG 一库三用；明确不采用清单(Dify/MaxKB/AutoGen…含 License 理由)；五条跨调研工程共识(prompt=编译产物/先画后动/确定性骨架/一库三用/风格偏好可落地)；下一步=架构细化+公共知识入库+两大风险实测(动漫脸唇形/LoRA 基线)
- [novel-writing-survey.md](research/novel-writing-survey.md) —— **AI 小说写作开源调研（2026-07-08）**：AI_NovelGenerator 5.6k(中文蓝本·向量长记忆+伏笔跟踪)/oh-story-claudecode 3.8k(数字员工形态最契合·skill+agent+hooks+去AI味)/ainovel-cli 1.3k(长篇一致性工程最成熟·多层摘要+四维检索+断点恢复)/NovelForge 991(Schema约束+知识注入,AGPL 只借思路)/LongWriter·RecurrentGPT(方法论)；结论=写作员工=AgentWrite 式生成技能+一致性知识召回+项目偏好注入
- [comic-drama-pipeline-survey.md](research/comic-drama-pipeline-survey.md) —— **AI 漫剧生成流水线开源调研（2026-07-08）**：七环节选型——分镜(LLM+导演技能)/一致性(LoRA 主力+InstantID 12k/PuLID/StoryDiffusion 6.4k 补丁,先画后动)/出图编排(ComfyUI 120k=技能包枢纽)/I2V(Wan2.2 16.6k+FLF2V 首尾帧)/配音(CosyVoice 22k)/唇形(LatentSync,⚠️动漫脸须先实测)/合成(FFmpeg+FCPXML 空白差异化)；同类平台 Jellyfish 5.1k(Apache 唯一可复用)/Toonflow 11.2k/LumenX(阿里 MIT)；与 mneme 先行视频调研互证
- [agent-platform-survey.md](research/agent-platform-survey.md) —— **智能体平台/数字员工框架开源调研（2026-07-08）**：编排框架(CrewAI 55k 角色范式/Agno 41k 四层映射最全/LangGraph 36.8k/⚠️AutoGen 维护模式勿选)、LLM 平台横评(Dify 148k 多租户+去Logo 受限/AnythingLLM 62.9k Workspace 隔离最纯/MaxKB GPLv3 传染…无一 8 项全中→自建)、记忆偏好(mem0 60.4k=项目级偏好最原生 user×app×agent 作用域/Letta 共享记忆块)、技能标准(anthropics/skills 159k=SKILL.md 事实标准须兼容)
- [fullstack-scaffold-survey.md](research/fullstack-scaffold-survey.md) —— **全栈技术选型调研（2026-07-08）**：full-stack-fastapi-template 44.1k(MIT 主脚手架)+pgvector 22.1k(不引独立向量库)+procrastinate(PG 原生队列,长任务零新中间件)+FastAPI 0.135 内置 SSE+shadcn/ui 118k+hey-api/openapi-ts(端到端类型安全)；核心=**PostgreSQL 一库三用**(业务+向量+队列),升级路径不推倒重来

## plan — 平台补强计划

- [platform-hardening-2026-09-17.md](plan/platform-hardening-2026-09-17.md) —— **平台补强计划：知识库/技能/规划/计量/团队（✅ P1-P5 全部完成 2026-09-17）**：结论=留自研不并入开源平台；P1 知识库文档摄取+混合检索(pgvector+trgm+ILIKE 三级融合,agent 的 kb.search 升级)、P2 技能试运行+tool_calls 用量聚合、P3 规划落库 agent_plans/agent_plan_steps(断点恢复/步骤重试)、P4 llm_usage token 计量(对外计费走 New API/LiteLLM 网关部署层)、P5 teams+项目分享+assert_project_access ACL 地基；全部零新 pip 依赖(pdf/docx 可选依赖 try-import)；三个引用已删 agent_unit 的坏测试文件记录在案不修

## modules — 平台补强新增模块（2026-09-17，全部零新 pip 依赖）

- **知识库文档摄取+混合检索（P1）**：`app/services/kb_ingest.py`（解析 txt/md/docx/html/json/csv，pdf 可选依赖；标题感知分块带链式重叠；source_hash 幂等重建；pgvector+trgm+ILIKE 三级融合、中文分词兜底）+ `app/api/kb_doc.py`（/api/kb/doc/ingest|upload|search|{hash}）+ `sql/98_kb_doc_ingest.sql`；agent 工具 `kb.search` 已同步升级为同款混合检索
- **技能试运行+用量（P2）**：`app/api/skill_run.py`（POST /api/skills/{slug}/dry-run 沙箱跑 tool-calling 循环；GET /api/skills/{slug}/usage 从 tool_calls 审计聚合被谁/哪里/调了多少次）
- **规划落库（P3）**：`app/services/planner.py`（LLM 拆步容错解析→agent_plans/agent_plan_steps 落库；advance/retry_step/崩溃恢复 running 归位；状态机纯函数禁止跳跃）+ `app/api/plans.py` + `sql/99_agent_plans.sql`
- **token 计量（P4）**：`app/services/llm_usage.py`（采集点收敛 llm._post 咽喉，fire-and-forget 写 llm_usage，绝不阻断生成；流式暂不采）+ `app/api/usage.py`（/api/usage/summary 按 日×模型 对账）+ `sql/100_llm_usage.sql`；对外计费仍建议部署层挂 New API/LiteLLM 网关
- **团队与分享（P5）**：`app/services/teams.py`（teams/team_members/team_projects；decide_access 纯函数：owner 直通、成员可读、任一分享可写才可写；assert_project_access 供后续 API 复用）+ `app/api/teams.py` + `sql/101_teams.sql`
- **开发期用户切换（2026-09-17）**：不接注册/登录（避免挡 AI 流水线）——首页悬浮区「用户切换」下拉（components/UserSwitcher，点选即换 X-User-Id 身份并刷新）；`sql/102_dev_users.sql` 内置张三/李四测试账号；`api/projects.py` 归属闭环=列表/回收站按 owner 过滤（admin 全见）、创建归属当前用户、详情/删除/恢复/清空 owner-or-admin 校验（非 owner 一律 404 不暴露存在性）。接真登录时只需把 api.ts 的身份头换成 Bearer + users.py 换会话解析，业务代码不动
- 测试：`tests/test_kb_ingest.py`(13) / `test_skill_run.py`(4) / `test_planner.py`(15) / `test_llm_usage.py`(6) / `test_teams.py`(9)，全量 204 绿（--ignore 三个引用已删 agent_unit 的坏文件）

## runbook — 运行手册

- [start.md](runbook/start.md) —— **启动与验证（已实测跑通 2026-07-08）**：后端 8765(FastAPI+任务队列worker)+前端 5173；八步用户旅程全实测（贴草稿建项目→文风画风评估→目录带故事线→要素+出现索引→偏好→写章节回写三件→无正文直接拆分镜+三套专业提示词→黑白故事板带运镜箭头→异步视频）；**二批**=要素设定图(角色身份版三视图/表情/动作/色板)+系统管理(知识库/技能CRUD)+分镜角色侧栏；**三批**=cocc-work 知识迁移(74条:14画风+24动作+文风)+OSS转存(taskox桶,存量8产物已迁,防第三方CDN失效)；**四批**=**模型管理**(model_profiles 注册表+系统管理🤖模型配置tab可切换,key掩码,ARK key 从 cocc-work 库静默导入)——当前 active=Qwen2.5-72B/火山Seedream 4.0(实测出图)/**火山Seedance 1.5 Pro(实测真I2V:故事板首帧→mp4→OSS)**

## samples — 金标准样例

- [storyboard-golden-sample.md](samples/storyboard-golden-sample.md) —— **分镜金标准样例《深澜纪·衔光》（定稿 2026-07-09）**：原创样章（海洋星球少女与深海巨鳐缔结共鸣，情绪曲线=恐惧→搏斗→连接→飞翔）+ 12 镜全字段专业分镜（含复用块占位演示 prompt=编译产物）；用途=拆镜质量评审对照物 + 装配器/校验 Gate 测试样本

## arch — 架构与设计

- [generation-flow-guards.md](arch/generation-flow-guards.md) —— **统一生成管线：前置→执行→next 守卫架构（已落地 2026-07-11）**：所有生成功能同构三段式（Vue 路由守卫模式），flow.py 自建薄框架（Step 注册表/幂等入队/优先级/重试上限默认1次+终态错误不重试/链深防环）+ steps.py 七个 Step；业务状态 meta.gen.<产线> 只由框架写（刷新可恢复）；预检缓存双重有效性（指纹+TTL：质检72h/音频24h/设定图外貌指纹）；启动 reconcile+周期 stalled 对账根治热重载杀在途；按钮合并=提示词生成含质检；拆分镜异步化且 next 自动串每镜提示词任务
- [audio-precheck-av-loop.md](arch/audio-precheck-av-loop.md) —— **音色标注·音频预检·音画闭环（已落地实测 2026-07-11）**：①角色卡生成期标注 voice_profile（vocal_mode/language，拟人动物=speech 真动物=call 自创语言=hybrid，三处写后者覆盖，存量一键补标注）；②视频生成前音频预检=确定性 gate（未捏音色/silent 有台词=error）+best-effort 补小样（TTS 欠费降级不阻塞）+LLM 四维评审，落 shot.meta.audio_precheck，**永不阻断生成**；③图像+音频→视频闭环：预检产出 audio_refs→media 按 model id 拼 reference_audio（仅 Seedance 2.0、有对白才传、必须伴随图、≤3段≤14s、拒收剔除重试）；已实测镜 197 两段参考音频+设定图→成片带音轨
- [voice-timbre-design.md](arch/voice-timbre-design.md) —— **音色库与配音链路设计（MVP 已落地 2026-07-10）**：音色库=听觉版设定图，已 seed 41 条(26人声+10生物+旁白/AI)；MVP=SiliconFlow CosyVoice2 TTS档+预置绑定+试听API+前端音色库tab；**捏音色技能已上线**(单角色指令/无指令自主设计 + 批量选角，库契合复用否则新建项目级条目，绑定落 character.meta.voice)；双阶段=预制选角→克隆定妆；**韵律两层模型已落码**(基线=音色params.speed三档=平时说话,调制=生成时逐句按分镜mood关键词映射语速倍率+语气指令,钳制0.7-1.4,零token)；数据模型零新表；调用链=建库→选角→生产(cue逐条TTS→时长回写三统一)；**合规红线=不可克隆名人声音,用风格标签+授权音色**
- [subtitle-design.md](arch/subtitle-design.md) —— **视频字幕设计（调研定稿 2026-07-10·未改码）**：字幕=分镜数据的编译产物（对白+cuts秒区间已结构化，永不手工打轴）；三层挂钩=shot.meta.subtitles(镜内相对时间)→镜级VTT(独立文件随分镜同生死)→章级VTT/SRT(按时长累加偏移对齐全集时间轴)；选型=Web播放WebVTT/成片SRT软内挂/发布层可选ASS烧录；二期配音TTS实测时长回写对齐
- [short-drama-painpoints.md](arch/short-drama-painpoints.md) —— **短剧视频生成全链路痛点清单（定稿 2026-07-09）**：25 个痛点五组（一致性/镜头运动/叙事分镜/音频/生产工程）带实现状态——✅已实现12（三重锁一致性/慢漂移对抗/ASL节奏/镜头组/Gate省抽卡…）⚠️部分6（多角色同框/表情天花板/运镜服从性…）📋待办7（跨镜轴线/唇形/竖屏/合成层…）；附行业数据来源与优先级建议
- [storyboard-to-video-keypoints.md](arch/storyboard-to-video-keypoints.md) —— **拆分镜到真实视频关键点清单（定稿 2026-07-09）**：用户逐轮纠正沉淀的 12 条关键点（病灶→决策→落点）——颗粒度效果化转译/AI视频三硬约束/技能四层装配/知识块按镜召回/分镜级要素关联/彩色首帧双轨/**同场快切=镜头组cuts**/剪辑节奏ASL 3-4s/**AI慢漂移显式对抗**/校验Gate闭环/max_tokens工程教训/一致性三重锁；附四轮真实迭代收敛轨迹
- [storyboard-prompt-spec.md](arch/storyboard-prompt-spec.md) —— **分镜故事板提示词规范（定稿 2026-07-09）**：颗粒度决策（拉片叙事层全保留+技术层效果化转译：光圈→浅景深/灯具→画面光效/焦段感保留）；AI 视频三硬约束（一镜一相机动作一主体动作/2-8s 时长曲线即情绪/首帧+运动增量两段式）；分镜 meta 新增 angle/lens_feel/lighting/palette/mood/action 六字段；零 token 校验 Gate G1-G8；来源=狄金斯《1917》《BR2049》公开实拆
- [data-model-and-knowledge-layering.md](arch/data-model-and-knowledge-layering.md) —— **数据模型与知识分层 + 两条核心原则（需求定稿 2026-07-08·未改码）**：**原则1=1000章不断不飘**：故事线落成四路数据（①基本信息②目录表逐章「故事发展简介流水账」+卷级摘要双粒度③核心要素状态随章更新④**要素×出现章节索引**），每章生成前确定性检索管线（大纲定位→查要素上次出现→取相关章流水账→取要素状态卡→装配→生成→**回写三件**：本章流水账/要素状态/出现索引，写后回写与写前检索同等重要）；**原则2=专业**：镜头语言/肢体动作/运镜/画风=知识库结构化专业提示词块，按本镜内容动态召回装配（prompt=编译产物）。六大核心表同构 mneme content_*+task_queue；扩展表(会话/消息/项目记忆=项目级偏好/项目资料)；待拍板=DDL/出现索引落法(荐独立关联表)/卷摘要刷新策略/写后确定性预检
