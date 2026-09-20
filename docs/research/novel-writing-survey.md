# AI 小说写作开源项目调研（调研完成 · 2026-07-08）

> 面向 novelcomic「写作数字员工」模块：GitHub 高星开源项目盘点，重点看**多智能体协作写作、长篇一致性、中文网文向、可挂技能/知识、项目级偏好（如"用莫言的语言写"）**。所有 star 数均于 2026-07-08 实际抓取 GitHub 仓库页核实。

## TL;DR

- **没有一个项目可整体拿来当底座**，但各家把"写作员工"要解决的四个子问题分别做透了：**形态范式**（oh-story-claudecode：skill+agent+hooks）、**长篇一致性工程**（ainovel-cli：多层摘要+四维检索+断点恢复）、**可挂技能/知识的结构化生成**（NovelForge：JSON Schema+知识注入）、**中文功能蓝本**（AI_NovelGenerator：向量长记忆+伏笔跟踪）。
- **"用莫言的语言写"这类风格偏好**已有成熟落地样式：oh-story-claudecode 的"去 AI 味"skill、MaliangAINovalWriter 的系统级/用户级 prompt 管理——印证"风格=可挂载技能/偏好注入"路线可行。
- 底层方法论押 **LongWriter/AgentWrite**（长文分解生成）+ **RecurrentGPT**（自然语言可编辑记忆）；省 token 一致性预检借鉴 **Novel-OS** 的确定性规则引擎。

## 一、第一梯队：功能完整 / 高星

| 项目 | Star | 技术栈 | 核心能力 | 契合点 | 活跃度 |
|---|---|---|---|---|---|
| [AI_NovelGenerator](https://github.com/YILING0013/AI_NovelGenerator) | **5.6k** | Python GUI，多 LLM + 向量 embedding | 设定工坊(世界观/人物/蓝图)→多阶段章节生成→**状态跟踪(人物弧线+伏笔)**→**向量检索长程一致性**→本地知识库→自动校对矛盾 | 向量长记忆=长篇一致性；本地知识库=「挂知识」；伏笔/状态跟踪=网文刚需。中文最主流蓝本 | 2025-03 放缓 |
| [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode) | **3.8k** | JS，Claude Code skill 包：7 agent + 13 skill + hooks | 网文全流程：扫榜→拆文→长/短篇写作→一致性检查→**去 AI 味**→封面。适配起点/番茄/晋江/七猫 | **与"作家数字员工"契合度最高**——本身就是"skill 可挂载 + agent 编排 + hooks 质检"形态；"去 AI 味"skill 可直接借鉴做风格控制 | 2026-06 非常活跃 |
| [AI-Writer](https://github.com/BlinkDL/AI-Writer) | 3.8k | Python，自研 RWKV 本地模型 | 中文玄幻/言情网文生成 | ⚠️ 训模型路线，README 自述已被取代；**仅历史参考** | 2022 停更 |

## 二、第二梯队：工程化底座（星中等，架构价值高）

| 项目 | Star | 技术栈 | 核心能力 | 契合点 | 活跃度 |
|---|---|---|---|---|---|
| [ainovel-cli](https://github.com/voocel/ainovel-cli) | **1.3k** | Go | Coordinator 驱动 **Architect/Writer/Editor** 三子代理；**Step 级断点恢复**；卷-弧双层滚动规划；**多层摘要(卷→弧→章)+四维检索(伏笔/人物出场/状态变化/关系)**；**实时干预**(写作中注入指令+影响评估+选择性重写) | **长篇一致性工程最成熟**；"实时干预"≈项目级偏好实时生效。Go 实现需移植思路 | 2026-07 非常活跃 |
| [NovelForge](https://github.com/RhythmicWave/NovelForge) | **991** | FastAPI+SQLModel+SQLite/Neo4j；Electron+Vue3。AGPL-3.0 | **Schema-first 卡片式创作**(JSON Schema 约束 AI 输出)；@DSL 上下文引用；**自定义卡片+知识库动态注入 prompt**；Neo4j 人物关系图谱 | **可扩展性架构最契合"挂技能/知识"**——Schema 约束+知识注入正是偏好/知识注入的成熟实现。⚠️ AGPL 只借思路 | 2026-06 非常活跃 |
| [MaliangAINovalWriter](https://github.com/Deng-m1/MaliangAINovalWriter) | 828 | Flutter Web + Spring Boot/WebFlux + MongoDB + Chroma。Apache-2.0 | 四级富文本(作品→卷→章→场景)；多模型"抽卡"多剧情方向；AI 拆书知识提取；**系统级+用户级 prompt 管理**；管理后台(可观测/成本/RBAC/计费) | **商用全栈样板**：系统/用户级 prompt 管理≈项目级偏好；LLM 可观测/计费是运营必备 | 2025-11 活跃 |

## 三、第三梯队：学术 / 机制参考

| 项目 | Star | 核心机制 | 借鉴点 |
|---|---|---|---|
| [LongWriter](https://github.com/THUDM/LongWriter)（清华，ICLR 2025） | 1.9k | **AgentWrite**：长写作拆段级子任务顺序生成拼接，单次 10,000+ 字；LongBench-Write 评测 | 长章节生成引擎方法论；数据集可用于微调 |
| [RecurrentGPT](https://github.com/aiwaves-cn/RecurrentGPT) | 998 | 自然语言模拟 LSTM：长期记忆(语义检索历史摘要)+短期记忆(每步更新)，**记忆对人可见可编辑** | "作家可干预、偏好可见"的记忆机制原型 |
| [Novel-OS](https://github.com/mrigankad/Novel-OS) | 21 | 五角色流水线 + 持久化 story state(JSON) + **确定性一致性引擎(本地免费预检伏笔/时间线/角色缺席，零 token)** | 调 LLM 前先过规则引擎，省 token 的工业思路 |
| [ai-book-writer](https://github.com/adamwlarson/ai-book-writer) | 392 | AutoGen 多 agent（Planner/World Builder/Memory Keeper/Writer/Editor） | 早期多 agent 写书编排参考 |
| [ai-novel-lab](https://github.com/xindoo/ai-novel-lab) | 49 | DeepSeek 实跑 42.8 万字 100 章成品，一致性评分 73→93 | 实战 case 数据 |

## 四、结论：写作员工怎么组合

| 目标 | 首选 | 复用点 |
|---|---|---|
| 数字员工形态/编排范式 | oh-story-claudecode | skill 可挂载 + agent 编排 + hooks 质检 + 去 AI 味风格 skill |
| 长篇一致性引擎 | ainovel-cli（思路移植到 Python） | 多层摘要 + 四维检索 + 断点恢复 + 实时干预 |
| 挂技能/知识 + 结构化输出 | NovelForge（思路，AGPL 不抄码） | JSON Schema 约束生成 + 知识库注入 prompt |
| 中文功能蓝本 | AI_NovelGenerator | 向量长记忆 + 伏笔/状态跟踪 + 本地知识库 |
| 商用全栈参考 | MaliangAINovalWriter（Apache-2.0） | 系统/用户级 prompt 管理、可观测、RBAC |
| 底层生成方法 | LongWriter/AgentWrite + RecurrentGPT | 任务分解长文生成 + 可编辑自然语言记忆 |

**对 novelcomic 的直接启示**：写作员工 = 「章节生成技能（AgentWrite 式分解）+ 一致性知识（向量召回：伏笔/人物状态/关系）+ 项目级偏好注入（风格 prompt 块，如莫言语言 = 一条项目记忆/偏好，装配期注入）」；一致性检查用确定性规则预检 + LLM 复核两层。
