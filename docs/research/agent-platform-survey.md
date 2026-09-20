# 智能体平台 / 数字员工框架开源调研（调研完成 · 2026-07-08）

> 面向 novelcomic 底座抽象「技能 + 知识 + 数字员工（挂技能）+ 项目级用户偏好」：盘点 ① Agent 编排框架（库级）② LLM 应用平台（前后端一体可自部署）③ 记忆/偏好持久化组件 ④ 技能标准。所有 star 数均于 2026-07-08 实际抓取仓库页核实。

## TL;DR

- **底座路线已定"自建为主"**：没有开源平台 8 项全中（Python+React+pgvector+多项目隔离+商用友好+四层抽象）；最接近的 Dify 有多租户/去 Logo 商用限制，AnythingLLM 是 Node 后端。自建时按需嵌库：编排参考 LangGraph/Agno，偏好持久化范式抄 mem0，技能格式对齐 Anthropic Agent Skills 标准。
- **"项目级用户偏好"最原生的开源对应是 mem0（60.4k）**：`user_id × app_id(项目) × agent_id(员工)` 参数化作用域，检索时组合过滤——即使不引其库，这个作用域模型也应照搬进自建的项目记忆表。
- **技能格式对齐 [Anthropic Agent Skills 标准](https://github.com/anthropics/skills)（159k）**：技能=文件夹（SKILL.md：YAML name+description+Markdown 正文），已被 ~40 客户端采纳成事实标准，按需动态加载。
- ⚠️ AutoGen（59.6k）已进维护模式，新项目勿选。

## 一、Agent 编排框架（库级，可嵌入自建后端）

| 框架 | Star | License | PG/pgvector | 四层抽象契合 | 状态 |
|---|---|---|---|---|---|
| [AutoGen](https://github.com/microsoft/autogen) | 59.6k | MIT | ✗ | 多 agent 群聊编排 | ⚠️ **维护模式，勿选** |
| [CrewAI](https://github.com/crewAIInc/crewAI) | **55.1k** | MIT | ✗(SQLite+Chroma) | **role-based agent（角色即岗位）最贴"数字员工团队"**；Tools=技能、Knowledge 内建 | 极活跃 |
| [LlamaIndex](https://github.com/run-llama/llama_index) | 50.7k | MIT | ✅ PGVectorStore | **RAG 事实标准库**，知识层底座；agent 偏检索 | 极活跃 |
| [Agno](https://github.com/agno-agi/agno)（原 phidata） | **41k** | **Apache-2.0** | ✅ 会话/记忆/知识全落用户自有 PG+pgvector | **四层映射最完整**：Agent=工具+知识+记忆一体，多租户+JWT/RBAC+定时任务 | 极活跃 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 36.8k | MIT | ✅ checkpoint-postgres | 有状态长运行 agent+长期记忆(namespace 隔离)，human-in-the-loop | 极活跃 |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | 27.7k | MIT | ✗ | 轻量：指令+工具+护栏+handoffs | 极活跃 |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | 18.3k | MIT | ✗ | 强类型结构化输出+依赖注入（DI 天然适合注入项目级偏好） | 极活跃 |
| [MS Agent Framework](https://github.com/microsoft/agent-framework) | 11.9k | MIT | ✗ | AutoGen 接班者，但深绑 Azure | 活跃 |

## 二、LLM 应用平台（前后端一体，可自部署）

| 平台 | Star | 后端 Python | 前端 React | PG/pgvector | License / 商用 | 四层抽象契合 |
|---|---|---|---|---|---|---|
| [Dify](https://github.com/langgenius/dify) | **148k** | ✅ | ✅ Next.js | ✅ PG 主库+可选 pgvector | ⚠️ Dify OSS License：**多租户 SaaS 转售须买商业授权、前端不得去 Logo**（内部自用不限） | Workspace 多租户成熟；Agent+Workflow+知识库全有 |
| [n8n](https://github.com/n8n-io/n8n) | 196k | ✗ Node | ✗ Vue | 可用 PG | ⚠️ Sustainable Use：**禁 SaaS 转售/白标嵌入** | 通用自动化非 RAG 产品 |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 84.6k | ✅(＋Go) | ✅ | ✗（ES/Infinity） | ✅ Apache-2.0 | 深度文档理解 RAG 最强；依赖重(ES/MinIO/Redis/MySQL) |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | 62.9k | ✗ Node | ✅ | 可选 pgvector（默认 LanceDB） | ✅ **MIT 最宽松** | **Workspace 隔离最纯正**（每工作区独立文档/上下文/配置）——最贴"每项目独立管理" |
| [Flowise](https://github.com/FlowiseAI/Flowise) | 54.4k | ✗ Node | ✅ | 可选 | ✅ Apache-2.0（社区版） | 可视化拖拽编排 |
| [FastGPT](https://github.com/labring/FastGPT) | 28.9k | ✗ Node | ✅ | ✅ pgvector 可选 | ⚠️ 自定义 License 含商用限制 | 团队隔离+可视化工作流 |
| [MaxKB](https://github.com/1Panel-dev/MaxKB) | 22k | ✅ Django | ✗ Vue | ✅ **默认内置 pgvector** | ⚠️ **GPLv3 传染** | 唯一 Python+默认 pgvector，但 License 不宜 |
| [coze-studio](https://github.com/coze-dev/coze-studio)（字节） | 21.1k | ✗ Go | ✅ | ✗（MySQL 为主） | ✅ Apache-2.0 | Agent 开发平台全套可视化；开源较新成熟度低 |

## 三、记忆 / 偏好持久化（对应"项目级用户偏好"）

| 项目 | Star | Python | PG/pgvector | 作用域模型 | 判定 |
|---|---|---|---|---|---|
| [mem0](https://github.com/mem0ai/mem0) | **60.4k** | ✅(+TS) | ✅ 可选 | **`user_id / agent_id / app_id / run_id` 参数化组合过滤** | ✅ **项目级偏好最原生**：user×项目(app_id)×员工(agent_id) 组合即偏好隔离，Apache-2.0 |
| [Letta](https://github.com/letta-ai/letta)（原 MemGPT） | 23.7k | ✅ | ✅ 默认 PG+pgvector | agent-scoped **Memory Blocks + Shared Blocks**（多 agent 共享块，一处更新处处可见） | 共享块适合"项目级共享偏好"，但以 Agent 为中心建模较重；⚠️ 主力已迁 letta-code 新仓库 |
| [Cognee](https://github.com/topoteretes/cognee) | 27.3k | ✅ | ✅ 默认（单 PG 实例承载全部） | 知识图谱+ECL 管道(remember/recall/forget/improve) | 偏结构化知识层，轻量偏好键值不如 mem0 直接 |

## 四、技能标准

- **[anthropics/skills](https://github.com/anthropics/skills)（159k，Apache-2.0）**：Agent Skills 开放标准（agentskills.io）——技能 = 文件夹（`SKILL.md`：YAML frontmatter `name`+`description` + Markdown 正文，可附脚本/资源），按需动态加载（渐进式披露）。已被 Cursor/Copilot/VS Code/Codex/Gemini CLI 等 ~40 客户端采纳。**novelcomic 的"技能"表设计应兼容此格式（可导入/导出 SKILL.md 包）**。

## 五、结论：自建底座怎么用它们

| 抽象 | 落法 | 参考/嵌入 |
|---|---|---|
| 数字员工（agent） | 自建 agents 表（agent_code + charter/prompt + 挂技能知识），**新建项目时按项目类型模板自动 seed 一套员工**（写作/绘画/导演） | 形态参考 CrewAI role-based、Agno（Agent=工具+知识+记忆一体）；mneme 的 agents+kb_entries 现成范式 |
| 技能（skill） | 独立技能记录，格式兼容 SKILL.md（name+description 触发 + 结构化正文），检索召回注入 | Anthropic Skills 标准；mneme kb_entries(kind=skill) |
| 知识（knowledge） | 公共知识（全局作用域）+ 项目知识（项目作用域），pgvector 混合检索 | LlamaIndex 可作检索库；mneme 三层召回（固定绑定+情境召回+通用兜底） |
| 项目级用户偏好 | 项目记忆表：`(user_id, project_id, agent_code?)` 作用域键 + soft(注入)/hard(校验) 两类 | **作用域模型抄 mem0**；级联设计抄 mneme rules 表（project/stage/entity 窄覆盖宽） |
| 编排 | 后端自持简单 pipeline/DAG；不引重框架 | 需要复杂图时再嵌 LangGraph（MIT，checkpoint 落 PG） |
| UI 交互范式 | 每项目一个工作区（会话+资产+分镜工作台） | AnythingLLM Workspace、Dify Workspace 的信息架构参考 |
