# 开源选型组合总览：小说 + 漫剧智能生成平台（调研定稿 · 2026-07-08）

> 汇合四份分项调研（[写作](novel-writing-survey.md) / [漫剧](comic-drama-pipeline-survey.md) / [智能体平台](agent-platform-survey.md) / [全栈](fullstack-scaffold-survey.md)），回答「不同技术栈怎么组合」。技术栈已定 Python(FastAPI) + React + PostgreSQL；底座路线已定**自建为主**（参考 `D:\mneme\banckend` 已验证的数据模型与平台范式）。

## TL;DR

- **一句话组合**：自建薄平台（mneme 同构六表 + 技能/知识/员工/偏好四层抽象）为"脑子"，**ComfyUI 为核心的媒体引擎**做"肌肉"（独立部署、经工具接缝异步接入），写作能力用 LLM + 移植开源项目的一致性工程，全程 PostgreSQL 一库三用。
- **不引任何重平台**（Dify/RAGFlow 等）：License 或技术栈不合 + 与自建 schema 双轨打架；按需嵌轻库（LlamaIndex 检索、LangGraph 复杂编排、mem0 作用域范式）。
- **三大差异化护城河**（调研共识）：① 角色/画风一致性闭环（全行业软肋）② 长篇一致性工程（多层摘要+四维检索）③ 知识驱动的提示词装配（prompt 是编译产物不是字面量，靠公共/项目两层知识 + 项目级偏好级联）。

## 总装配图

```
┌───────────────────────── 平台（自建 · FastAPI + React + PG）─────────────────────────┐
│  数字员工层   写作员工 / 绘画员工 / 导演员工 / 配音员工…（新建项目自动 seed，项目独立）    │
│  能力层       技能(SKILL.md 兼容) + 知识(公共/项目两层, pgvector 召回) + 项目级偏好级联   │
│  内容层       六大表: 基本信息/目录/正文/核心要素/附件/任务队列 (+会话/消息/项目记忆/资料) │
│  编排层       确定性 pipeline/DAG + SSE 流式; LLM 只用在拆解/装配, 不控流程              │
└──────────────┬──────────────────────────────────────────┬───────────────────────────┘
               │ LLM API (OpenAI 兼容)                     │ 工具接缝 (HTTP + 异步作业回写)
               ▼                                          ▼
     写作生成（AgentWrite 式分解 +            ┌───── 媒体引擎（独立 · 确定性）─────┐
     多层摘要/四维检索一致性 +                 │ ComfyUI (workflow=技能包)          │
     确定性规则预检）                          │ 一致性: LoRA + InstantID/PuLID/    │
                                              │   StoryDiffusion (先画后动)        │
                                              │ I2V: Wan2.2 + FLF2V 首尾帧续接     │
                                              │ 配音: CosyVoice  唇形: LatentSync  │
                                              │ 合成: FFmpeg (+FCPXML 差异化)      │
                                              └────────────────────────────────────┘
```

## 分域选型（含核实 star 与 License）

| 域 | 选型 | 取用方式 |
|---|---|---|
| 工程地基 | full-stack-fastapi-template 44.1k(MIT) + pgvector 22.1k + procrastinate 1.3k(MIT) + shadcn/ui 118k + hey-api/openapi-ts | 直接采用 |
| 数字员工/技能/知识/偏好 | 自建（mneme agents+kb_entries+content_* 范式）；技能格式兼容 anthropics/skills 159k 标准；偏好作用域抄 mem0 60.4k 的 user×project×agent 模型；级联抄 mneme rules 设计 | 自建 + 范式借鉴 |
| 写作员工 | oh-story-claudecode 3.8k(形态) + ainovel-cli 1.3k(一致性工程,Go 思路移植) + AI_NovelGenerator 5.6k(中文蓝本) + LongWriter/AgentWrite(方法论) + Novel-OS(确定性预检) | 思路移植（NovelForge AGPL 不抄码） |
| 绘画/导演员工 | ComfyUI 120k(编排内核) + LoRA/InstantID 12k/PuLID/StoryDiffusion 6.4k(一致性) + Wan2.2 16.6k(I2V, Apache) | 独立媒体引擎部署 |
| 配音/唇形 | CosyVoice 22k(Apache) + LatentSync 5.9k / Wav2Lip 13.1k | 独立引擎；⚠️ 动漫脸唇形先实测 |
| 可复用同类代码 | Jellyfish 5.1k(Apache) / LumenX 817(MIT, 阿里) | 唯二 License 安全的同类底座，工作台/模块划分参考 |
| RAG 检索 | LlamaIndex 50.7k(MIT, PGVectorStore) 按需嵌 | 库级嵌入 |
| 复杂编排（后期才需要） | LangGraph 36.8k(MIT, checkpoint 落 PG) | 库级嵌入 |

## 明确不采用 + 理由

| 项目 | 排除理由 |
|---|---|
| Dify 148k / FastGPT 28.9k / n8n 196k | License 商用限制（多租户转售/白标/SaaS 受限）；且重平台与自建 schema 双轨 |
| MaxKB 22k | GPLv3 传染 |
| coze-studio 21.1k / Flowise 54.4k / AnythingLLM 62.9k | Go/Node 后端与 Python 栈不合；AnythingLLM 的 Workspace 信息架构仅作 UI 参考 |
| AutoGen 59.6k | 已进维护模式 |
| BigBanana / NovelForge / openframe / dramatiq | CC-NC 冻结 / AGPL / AGPL / GPL——只借思路不抄码 |
| AI-Writer / ai-comic-factory / arq | 停更 / 已归档 / maintenance-only |

## 关键工程共识（跨调研互证）

1. **prompt 是编译产物**：每镜/每章的提示词由「公共知识块（镜头/动作/画风轴）+ 项目知识（角色卡/世界观）+ 项目级偏好（级联，窄覆盖宽）」装配而成，专业提示词留知识库按需召回、不塞项目基本信息（防膨胀）。
2. **先画后动**：一致性在"图"这层解决（LoRA+一致性首帧），再 I2V——防人物变形公认最优解；免训练 ID 方案动漫脸吃亏只当补丁。
3. **确定性骨架 + LLM 局部**：同类漫剧项目无一用 agent 动态控流程；长任务走任务队列异步 + 产物回写协议（pending→progress→done→回挂附件表）。
4. **一库三用的 PG**：业务+向量+队列同库，早期零 Redis/独立向量库；升级路径清晰不推倒重来。
5. **风格偏好可落地已被验证**："用莫言的语言写" = 项目记忆表一条 soft 偏好，装配期注入写作员工上下文（oh-story 去 AI 味 skill、Maliang 用户级 prompt 管理均为同类先例）。

## 建议下一步

1. 定架构文档：数据模型细化（六表 DDL + 项目记忆/资料表）+ 数字员工 seed 模板（新建项目自动生成哪几个员工、各挂什么默认技能）。
2. 公共知识首批入库：镜头语言/动作/视觉风格拆正交轴成可组合块（参考 mneme knowledge-driven-storyboard 的块结构：正/负词+LoRA+参数）。
3. 两个最大风险先实测：① 动漫脸唇形（LatentSync/Wav2Lip 拿真实画风素材）② 角色 LoRA 训练成本与效果基线。
