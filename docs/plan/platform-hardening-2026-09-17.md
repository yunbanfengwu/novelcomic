# 平台补强计划：知识库 / 技能 / 规划 / 计量 / 团队（✅ P1-P5 全部完成 · 2026-09-17）

> 交付记录：5 个迁移(98-101)+8 个新文件+agent_runtime.kb_search 与 llm._post 两处加密文件最小修改，
> 全量 pytest 204 绿；真实 PG 冒烟：摄取/检索(含项目隔离)、计划全生命周期、token 落库聚合、团队 ACL 全过。
> 实现与计划的偏差：① docx 解析用 stdlib zipfile 自实现（zipfile 本就在零依赖内，比计划写的 try-import 更完整）；
> ② P4 采集点收敛在 llm._post 单点（计划里写的"四个 chat_* 分别捕获"实际一处搞定）；流式 chat_stream 暂不采；
> ③ trgm 路实测中文整句在 ctype=C 下相似度≈0，检索改为 整句+空白分词 逐词 ILIKE 兜底（冒烟发现，计划时未预见）。

> 结论先行：**留在自研底座上补模块，不并入开源平台**（Dify/Refly 形态不合、垂直产线迁不动）。
> 本计划只补短板，全部**零新 pip 依赖**（`requirements.txt` 被 Esafenet 加密，本机不可安全修改；
> pdf/docx 解析做成可选依赖，缺包时给出明确提示，待在可信环境补装）。
> 原则：新增文件为主；**加密文件（`app/main.py`、`app/llm.py`、`app/services/agent_runtime.py` 等）
> 只做最小必要修改，且用受信任的 venv Python 读改、改后立即验证**。

## 0. 现状校准（比口头评估的强）

| 模块 | 现状 | 真实缺口 |
|---|---|---|
| 技能 | SKILL.md 规范安装/校验/资源文件/员工挂载已备（`skill_packages.py`）；渐进披露 + `skill.read` 已接 agent runtime | 没有"试运行"闭环（装了不知道好不好用）；没有用量可见性 |
| 规划 | `agent_runtime.run` tool-calling 循环成熟（上下文强制覆盖/错误回喂/批量/审计） | 规划**无持久化**：计划只活在单次运行的 steps 里，断了无法恢复、不可重试 |
| 知识 | kb_folders + kb_entries + pgvector(bge-m3 1024) + `recall_blocks`（向量+trgm，仅 prompt_block 装配用） | ① 没有文档摄取管线（上传→解析→分块→向量化）② agent 工具 `kb.search` 只有 ILIKE 关键词，**没有向量** |
| 计量 | 无（模型调用不发不记） | token 用量零记录，计费无从谈起 |
| 团队 | users + owner_id 归属（35 迁移），但只有"个人所有" | 无团队实体、无项目分享、无跨用户访问控制 |

已知问题（本次不修，仅记录）：`tests/test_agent_before_blocked.py`、`test_agent_next.py`、
`test_agent_qc_retry.py` 三个文件 import 已被 60 号迁移删除的 `agent_unit` 模块，收集即报错。
跑测试时用 `--ignore` 排除；后续要么删掉要么按 workflow_actions 重写。

## 1. P1 知识库：文档摄取 + 混合检索（本批先做）

- **SQL** `backend/sql/98_kb_doc_ingest.sql`：kb_entries 加 `source_name/source_hash/chunk_seq`
  （幂等），建索引；复用 14 号迁移的 embedding 列。
- **服务** `app/services/kb_ingest.py`：
  - `chunk_text()`：按标题/段落切分（中文友好），块长 + 重叠可配，纯函数可测；
  - `ingest_document()`：解析（txt/md/json/csv 内置；pdf/docx try-import 可选）→ 分块 →
    批量 embed → 写 `kb_entries(kind='doc_chunk', scope, project_id, folder_id)` →
    按 `source_hash` 幂等重建；
  - `hybrid_search()`：向量（pgvector 在时）+ pg_trgm + ILIKE 兜底三级融合，
    排序融合为纯函数；embedding 不可用时自动降级，绝不阻断。
- **API** `app/api/kb_doc.py`：`POST /api/kb/doc/ingest`（multipart 或 JSON 文本）、
  `GET /api/kb/doc/search`（带分数与来源引用）、`GET /api/kb/doc/{source_hash}`（查看分块）。
- **agent 工具升级**：`agent_runtime.kb_search` 从纯 ILIKE 升级为同款混合检索（改加密文件，
  venv Python 精确替换 + 改后 import 验证）。
- **测试** `tests/test_kb_ingest.py`：分块边界（空/超长段/中英混排/重叠）、融合排序、
  降级路径；PG 可达时加冒烟（不可达自动 skip）。

## 2. P2 技能：试运行 + 用量可见

- **API** `app/api/skill_run.py`：
  - `POST /api/skills/{slug}/dry-run`：charter=SKILL.md 全文，走 `agent_runtime.run`
    （工具白名单=skill.read/kb.search，max_steps 收紧），返回 output + steps 轨迹；
  - `GET /api/skills/{slug}/usage`：从 `tool_calls` 审计聚合（被谁/哪里调了多少次）。
- **测试**：dry-run 装配与执行（mock `llm.chat_tools`），用量聚合 SQL 纯函数。

## 3. P3 规划：计划落库（断点可恢复、步骤可重试）

- **SQL** `backend/sql/99_agent_plans.sql`：`agent_plans`（goal/status/meta）+
  `agent_plan_steps`（seq/title/detail/tool_hints/status/result/error）。
- **服务** `app/services/planner.py`：LLM 生成步骤 JSON（容错解析）→ 落库；
  `advance`（跑下一步 → 回写状态 → 返回进度）、`retry_step`、`resume`（重启把 running 归位 pending）；
  状态机流转为纯函数（pending→running→done/failed，禁止跳跃）。
- **API** `app/api/plans.py`：建计划/查计划/推进一步/重试某步/按项目列表。
- **测试**：步骤 JSON 解析容错、状态机、advance/retry（mock agent_runtime + 假 pool）。

## 4. P4 Token 计量（计费地基）

- **SQL** `backend/sql/100_llm_usage.sql`：`llm_usage`（model/purpose/caller/project_id/
  prompt_tokens/completion_tokens/duration_ms/ok/ts）+ 聚合索引。
- **埋点** `app/llm.py`（加密文件，venv Python 最小修改）：`chat_text/chat_tools/chat_json/
  chat_vision_json` 从响应 `usage` 捕获 token 数 + 耗时 + 成败，fire-and-forget 落库，
  失败绝不阻断生成；流式（无 usage）本轮不记，注明。
- **API** `app/api/usage.py`：`GET /api/usage/summary?days=&by=model|purpose|caller`
  （group by 白名单防注入）。
- **对外计费/配额**：不在应用内做扣费，部署层接 New API/LiteLLM 网关（写 runbook，不改码）。
- **测试**：usage 提取容错（缺字段/0）、by 白名单。

## 5. P5 团队与项目分享（地基）

- **SQL** `backend/sql/101_teams.sql`：`teams` / `team_members`(role) / `team_projects`
  （项目→团队，read/write），全部幂等。
- **服务** `app/services/teams.py`：建团队/加成员/分享项目/取消分享 +
  `assert_project_access(project_id, user_id, write)`（owner 或团队成员），给后续所有 API 复用。
- **API** `app/api/teams.py` 最小集：团队 CRUD、成员管理、项目分享/列表。
- **测试**：ACL 判定纯函数（owner 直通 / 团队只读 / 写权限拒绝 / 未知项目拒绝）。

## 6. 交付与验证方式

- 每个阶段：单元测试先行跑通 → `python -m pytest backend/tests`（`--ignore` 三个坏文件）全绿；
- 本地 PG（`localhost:5432/novelcomic`，后端 dev 正在用）直接用 asyncpg 真跑新迁移 + 摄取/检索冒烟；
- `app/main.py` 注册 5 个新 router，改完用 venv Python 读回验证 + `docs/index.md` 同步更新。

## 7. P6 挂载点系统 + 连线可选中删除（2026-09-18）

### 7.1 挂载点：产物归宿是一等公民

- **动机**：产物落到哪个归宿（项目封面 / 角色设定图 / 分镜关键帧…）原先只能写在 end 节点的
  `config.store` 里——一处声明、一次执行，画布上看不见，多个产物要多个 end 才说得清。
- **模型**：独立节点类型 `mount`，`config = {target, subject:{kind,id}|null, variant?}`。
  连到它的产物就是挂载内容（沿入边反向 BFS 取 trace 里**最后带 url** 的那个节点，
  不按节点类型过滤——上传/素材节点连过来同样是真产物，「把现有这张图存成封面」是最常见用法）。
- **落库** `tapflow_ai.apply_mount_binding`：`project_cover` → `content_projects.config.cover_url`；
  资产类型码 → `workflow_artifacts`（asset_type + subject_kind/subject_id + variant + version 自增）。
- **幂等**：同一归宿 + 同一 url 反复跑不刷版本（封面比对 cover_url，资产比对最新一条 url）——
  挂载点语义是「这个归宿现在指向哪张」，不是每次运行记一笔流水。
- **唯一性**：同一 `(target, subject)` 在同一画布只允许一个挂载点，`addNode`（前端选中已有的）
  与 `validate_graph`（保存拒绝）双端强制。
- **入口默认**：从角色/封面进去，画布没有对应归宿的挂载点时自动补一个并接到链路末端，
  标题按业务对象命名（「陈砚 的挂载点」）——空挂牌无意义，默认挂载点必须真连在产物上。
- **测试** `tests/test_mount_node.py`（21 项）：上游选取/穿透/孤岛隔离、上传素材节点、
  非媒体输出忽略、project_cover 落库与幂等、资产落库/错 kind 拒/缺 subject 跳/未知 target 跳、
  subject 声明优先与入参回退、validate_graph 去重、收尾补漏落库。
- **真引擎验证**：临时画布（素材节点 → 挂载点，target=pro.character.sheet）真跑三次——
  首跑落 v1、同产物重跑不新增、换产物落 v2 且回填 artifact_id/source_node；跑完清理。

### 7.2 连线可选中删除

- 点击/框选选中连线，选中态蓝色高亮 + 线中点 ✕ 按钮 + Delete 键；运行态同样可删
  （拖端口建错边就是运行态的事）。桥接边（`id` 含 `~`）删除时一并移除其源边。
- **命中**：细的可见线本身接管命中（鼠标就悬在它上面，最直觉），外加 24px 透明命中线兜手抖；
  命中线用 `vector-effect: non-scaling-stroke`，命中宽度按屏幕像素算，缩到 0.4 也不缩水。
- **真凶**：组框（宫格）是一整块带半透明底的矩形、自己也要接指针事件，原先渲染在连线**之上**
  ——组内那段连线永远点不到。改为「组框 → 连线 → 节点」的层序（线只在 stroke 上命中，不挡拖组）。
- **保底入口**：属性面板列出入边，逐条断开——不在画布上跟 3px 的细线较劲。
