# 全栈技术选型调研：Python + React + PostgreSQL（调研完成 · 2026-07-08）

> 面向 novelcomic 工程地基：脚手架、向量检索、任务队列（生图/生视频长任务）、LLM SSE 流式、前端 UI 与类型化 API 客户端。所有 star 数均于 2026-07-08 实际抓取仓库页核实。

## TL;DR

- **PostgreSQL 一库三用**（业务数据 + pgvector 向量 + procrastinate 任务队列）：早期零外部中间件（不需要 Redis/RabbitMQ/独立向量库），运维最省；每个环节都有不推倒重来的升级路径（pgvector→pgvectorscale→Qdrant；procrastinate→Celery）。
- 脚手架直接用官方 **full-stack-fastapi-template（44.1k，MIT）**：FastAPI+SQLModel+React+TS+Vite+Tailwind+shadcn/ui+JWT+Alembic+CI 全内置，与拟定三件套完全吻合。
- SSE：FastAPI 0.135+ 已内置 `EventSourceResponse`，进阶用 sse-starlette。

## 一、全栈脚手架

| 项目 | Star | 技术栈 | 判定 |
|---|---|---|---|
| [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | **44.1k** | FastAPI+SQLModel+Pydantic v2 / React+TS+Vite+Tailwind+**shadcn/ui** / PG / Docker Compose+CI | ✅ **主脚手架**：JWT/密码哈希/Alembic/Pytest 内置，官方维护（v0.10.0 2026-01），MIT |
| [benavlabs/FastAPI-boilerplate](https://github.com/benavlabs/FastAPI-boilerplate) | 2.0k | FastAPI+SQLAlchemy 2.0+Redis+**Taskiq 队列**+限流+API Key | 纯后端参考：更贴"长任务+多租户"结构，MIT |
| Buuntu/fastapi-react | — | MUI，更新缓慢 | 历史参考，不采用 |

## 二、向量检索：pgvector 即可，不引独立向量库

| 项目 | Star | License | 判定 |
|---|---|---|---|
| [pgvector](https://github.com/pgvector/pgvector) | **22.1k** | PostgreSQL License | ✅ **首选**：HNSW/IVFFlat，向量与业务同库可 JOIN+事务；<百万级向量完全够用 |
| [pgvectorscale](https://github.com/timescale/pgvectorscale) | 3.1k | PostgreSQL License | 性能不够时叠加（StreamingDiskANN），不换库 |
| [Milvus](https://github.com/milvus-io/milvus) 45.1k / [Qdrant](https://github.com/qdrant/qdrant) 33k / [Chroma](https://github.com/chroma-core/chroma) 28.7k | — | Apache-2.0 | 对照组：亿级/延迟敏感才需要，本项目过度设计 |

## 三、任务队列（生图/生视频长任务异步化）

| 项目 | Star | Broker | 异步 | License | 判定 |
|---|---|---|---|---|---|
| [procrastinate](https://github.com/procrastinate-org/procrastinate) | 1.3k | **PostgreSQL**(LISTEN/NOTIFY+SKIP LOCKED) | asyncio 原生 | MIT | ✅ **首选**：复用 PG 零新增中间件，v3.9.0(2026-06) 活跃 |
| [Celery](https://github.com/celery/celery) | 28.7k | RabbitMQ/Redis | sync 优先 | BSD-3 | 重型回退项：生态最全但需引 Redis/RabbitMQ |
| [pgmq](https://github.com/tembo-io/pgmq) | 5.0k | PostgreSQL | 语言无关 | PostgreSQL | 更底层"PG 版 SQS"，需自写 worker |
| [arq](https://github.com/python-arq/arq) | 3.0k | Redis | asyncio | MIT | ⚠️ maintenance-only，新项目慎选 |
| [dramatiq](https://github.com/Bogdanp/dramatiq) | 5.3k | RabbitMQ/Redis | sync | ⚠️ LGPL/GPL | License 合规注意 |

> 注：mneme 项目自建了 `task_queue` 表 + worker 分发框架（daily_focus/research/tool_invoke/generate 等 kind），与用户拍板的"任务队列"六表之一同构——自建轻表也是被验证的路线，procrastinate 可作实现参考或直接引入。

## 四、LLM 直连 + SSE 流式

- **FastAPI 0.135+ 内置 `fastapi.sse.EventSourceResponse`**（Rust 侧 Pydantic 序列化）——锁新版则优先内置。
- [sse-starlette](https://github.com/sysid/sse-starlette)（838，BSD-3，v3.4.5 2026-06）：需要自定义 ping/心跳/断连回调时用。
- 模式：OpenAI 兼容上游 `text/event-stream` → 转发为分事件 SSE（token / tool_call / **生图生视频进度**分事件），前端步骤区+Markdown 区实时渲染（mneme 已验证同款模式）。

## 五、React 前端

| 项目 | Star | 判定 |
|---|---|---|
| [shadcn/ui](https://github.com/shadcn-ui/ui) | **118k** | ✅ 对话/资产卡片/分镜看板（drag-drop、dialog、command palette）全覆盖；官方脚手架已内置，MIT |
| [hey-api/openapi-ts](https://github.com/hey-api/openapi-ts) | 5.1k | ✅ 从 FastAPI OpenAPI 一键生成 TS 类型化客户端 + TanStack Query hooks，端到端类型安全，MIT |

## 六、推荐选型清单

| 层 | 选型 | 理由 |
|---|---|---|
| 脚手架 | fastapi/full-stack-fastapi-template | 官方 44.1k、三件套吻合、shadcn/JWT/Alembic/CI 内置 |
| 后端 | FastAPI + SQLModel/SQLAlchemy 2.0 + Pydantic v2 | async 原生，OpenAPI 自动生成 |
| 数据库 | PostgreSQL **一库三用** | 业务 + 向量 + 队列，外部依赖最少 |
| 向量 | pgvector（必要时 +pgvectorscale） | 同库 JOIN/事务，运维最低 |
| 队列 | procrastinate（或自建 task_queue 表参考 mneme） | PG 原生 asyncio，长任务异步化零新中间件 |
| LLM 流式 | FastAPI 内置 SSE / sse-starlette | token/进度分事件直转 |
| 前端 | React+TS+Vite+Tailwind+shadcn/ui | 模板内置，覆盖对话/资产/分镜工作台 |
| API 客户端 | hey-api/openapi-ts + TanStack Query | 改后端接口前端即时报错 |
