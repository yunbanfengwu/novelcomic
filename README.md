# novelcomic — 小说 + 漫剧 + 运营视频 智能生成平台

> 一个"技能 + 知识 + 数字员工 + 项目级用户偏好"驱动的创作平台：用户新建项目后自动生成一套数字员工（写作员工 / 绘画员工 / 导演员工…），每个项目独立管理；写作员工可按项目偏好写作（如"用莫言的语言写"），绘画员工可按项目画风要求出图，最终产出小说正文与漫剧（分镜 → 一致性角色图 → 视频/配音）。
>
> 创建日期：2026-07-08 ｜ 当前阶段：**MVP 已跑通**（草稿→基本信息→目录→要素→分镜→黑白故事板→异步视频全链路实测，启动见 [docs/runbook/start.md](docs/runbook/start.md)）

## 界面预览

**工作台首页**：即刻创作入口 + 项目一览

![工作台首页](docs/images/screenshot-home.jpg)

**分镜视频总览**：逐镜生成视频/首帧，右侧为本章关联要素（角色/场景设定图）与分镜故事板总览

![分镜视频总览](docs/images/screenshot-storyboard-video.jpg)

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python（FastAPI） |
| 前端 | React + TypeScript |
| 数据库 | PostgreSQL（一库三用：业务数据 + pgvector 向量 + 任务队列） |
| 媒体引擎 | 独立引擎（ComfyUI 等），经工具接缝接入，不塞进平台主体 |

技术底座路线：**自建为主**，数据模型参考 `D:\mneme\banckend` 的 content_* 模型（详见 [docs/arch/data-model-and-knowledge-layering.md](docs/arch/data-model-and-knowledge-layering.md)）。

## 两条核心原则

1. **1000 章不断、不飘**：整条故事线落地成数据——项目基本信息 + 目录表逐章「故事发展简介流水账」+ 核心要素（状态随章更新）+ **要素出现章节索引**；每章生成前按需检索这四路信息、写完回写，不靠模型上下文记忆。
2. **专业**：画风/视频生成用专业知识——镜头语言、肢体动作、运镜等专业提示词沉淀在知识库，生成时动态按需获取装配（prompt 是编译产物，专业度来自知识资产而非模型即兴）。

详见 [docs/arch/data-model-and-knowledge-layering.md](docs/arch/data-model-and-knowledge-layering.md)。

## 核心概念

- **数字员工（agent）**：项目内的角色化智能体（写作员工/绘画员工/导演员工…），可挂技能与知识；新建项目时自动生成一套，每个项目略有不同、独立管理。
- **技能（skill）**：教员工"怎么做"的可挂载指令包（如"网文章节六步生成法"、"去 AI 味"、"某画风出图工作流"）。
- **知识（knowledge）**：分两层——**公共知识**（镜头语言/动作/视觉风格等全局块）与**项目级知识**（本项目小说资料、参考资料）。
- **项目级用户偏好**：作用域=项目的持久化偏好（如"写作用莫言的语言"、"全片冷色调竖屏"），生成时按作用域级联注入。

## 项目数据六大核心表

基本信息（content_projects）· 目录（content_nodes）· 核心要素（content_elements）· 附件（content_attachments）· 正文（content_bodies）· 任务队列（task_queue）；按需扩展：会话表、会话消息表、项目记忆表、项目资料表。

## 文档

全部文档见 [`docs/index.md`](docs/index.md)。文档规范：每篇带日期与状态；新增文档同步更新索引。

## 部署与依赖约定

- **后端新增第三方包 → 必须加进 [`backend/requirements.txt`](backend/requirements.txt)**。生产镜像只 `pip install -r requirements.txt`，漏写会导致线上容器启动即崩（如文件上传缺 `python-multipart`）。
- **数据库 schema 改 [`backend/sql/*.sql`](backend/sql)**，保持幂等（`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`）；后端启动自动应用，无需手动建表。
- **部署**：push 到 `main` 触发 CNB 流水线（[`.cnb.yml`](.cnb.yml)）自动打镜像 + 部署到服务器。详细工程约定见 [`CLAUDE.md`](CLAUDE.md)。
