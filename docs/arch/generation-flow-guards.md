# 统一生成管线：前置→执行→next 守卫架构（已落地 2026-07-11）

> **TL;DR**：所有生成功能（拆分镜/提示词/设定图/首帧/视频/音色样本）重构为同一架构——
> **前置(before) → 执行(run) → next(收尾)**，参考 Vue 路由守卫模式。框架在
> `services/flow.py`（~300 行自建薄层，机制借鉴 procrastinate/DBOS 调研结论），业务在
> `services/steps.py`（7 个 Step）。异步任务全走 task_queue，业务状态落
> `content_nodes.meta.gen.<产线>`（刷新页面可恢复）；预检带缓存有效期（指纹+TTL）；
> next 重试有次数上限（默认 1 次）绝不无限循环；启动/周期双对账自愈热重载杀在途问题。
> 前端「重新生成提示词」+「质检并重构」两按钮合并为「生成提示词（含质检）」。

## 1. 架构总览

```
API (flow.enqueue)          worker (flow.run_task)                    poller
  │ 幂等去重/优先级            │                                        │
  ▼                          ▼                                        │
task_queue(pending) → before(守卫:查依赖,能补则补,补不了Blocked)          │
                       → run(纯执行; 外部任务返回external_id ────→ waiting_external
                       → next(质检/校验/回写/串下游)  ←──────────── 收割后回调 next
                       → done / failed / (RetryStep→重排,attempt+1)
```

- **before** = beforeEach 守卫：依赖检查。能确定性补齐的就补（缺设定图先生成），
  补不了 raise `Blocked`，error 带 `blocked:` 前缀写清缺什么。
- **run** = 渲染：只执行，不判断。ARK 视频"提交即释放"槽位（waiting_external）。
- **next** = afterEach + `next()` 流转：质检产物、回写状态、可 `flow.enqueue` 串下游任务
  （拆分镜完成 → 自动为每镜串出 gen_prompts）。不合格 raise `RetryStep`。

## 2. 七个 Step 的守卫分工（steps.py）

| kind | before | run | next |
|---|---|---|---|
| breakdown_chapter | 章节存在 | 拆镜（内部含 Gate 重拆+总审重拆闭环） | 每镜串出 gen_prompts（链深≤3 防环） |
| gen_prompts | 分镜存在 | 装配三套提示词 | 九维双评审→不合格自动重构→复审→有保留放行；结果带指纹+有效期 |
| gen_storyboard_image | — | 黑白草图→OSS | 附件+meta 回写 |
| gen_keyframe | ①补设定图(指纹)→重装配 ②质检缓存 | 生图（设定图作参考图） | 附件+keyframe_url |
| gen_video | ①同上 ②质检缓存 ③音频预检(缓存,永不阻断) | ARK 提交(降级级联)→external / GRSAI 同步 | OSS 转存→附件+video_url+status=rendered |
| gen_element_sheet | — | 生图→OSS | 附件+sheet_url+**sheet_fingerprint**（外貌改动→镜级前置自动重生成） |
| gen_voice_samples | — | 批量 TTS（单条失败不阻塞） | — |

## 3. 状态模型（两层）

**任务层 task_queue.status**：`pending → running → done/failed`；视频类多一段
`running → waiting_external → (收割) → done/failed`；`pending/waiting_external` 可 `canceled`。
新列：`attempt`（重试计数）、`root_task_id`（链追踪）、`priority`（单镜手点10 > 拆镜5 > 批量0）。

**业务层 content_nodes.meta.gen.<slot>**：`{state, task_id, at[, error]}`，
state ∈ pending/running/done/failed/canceled。**只由框架写**（enqueue/run_task/finish_external），
业务代码无权直接碰。前端刷新后从 `GET /tasks`（在途）+ `meta.gen`（终态含失败原因）恢复。

## 4. 预检缓存有效期（用户 2026-07-11 定稿）

双重有效性 = **源文本指纹匹配** 且 **未过期**（`flow.stamp_validity` / `flow.cache_valid`）：

| 预检 | 指纹源 | TTL | 落点 |
|---|---|---|---|
| 提示词质检（图/视频） | 最终提示词文本（重构后以重构版为准） | 72h | meta.prompt_review(_image) |
| 音频预检 | 对白全文 + 各角色音色绑定 kb_voice_id | 24h | meta.audio_precheck |
| 要素设定图 | 外貌提示词\|brief | 无限期 | element.meta.sheet_fingerprint |

命中缓存 → 生成前置零成本放行（不再每次生成重烧 30-60s 质检）。旧设定图无指纹视为有效
（不回溯重生成）。质检合格与否不影响缓存有效性——质检是"尽力修复+留档"，不阻断生成。

## 5. 重试与防环（用户 2026-07-11 定稿：默认仅允许一次）

- `Step.max_retries` 默认 **1**；`attempt < max_retries` 且错误**可重试**才重排（attempt+1），
  否则 failed。尝试历史留 `payload.attempts`（可观测）。
- **错误分类**：`flow.is_terminal`——欠费/配额/鉴权/参数错等终态错误**直接 failed 不重试**
  （盲目重试=烧循环，硅基欠费教训）；ARK 审核拒收走 run 内降级级联（不算失败不计重试）。
- **防环三保险**：①同 (node_id, kind[, element_id]) 唯一在途（enqueue 幂等去重）
  ②链深 `payload.chain_depth ≤ 3` ③重试上限。
- 手动重试：`POST /tasks/{id}/retry`（failed→新任务，attempt 归零，记 retry_of）；
  取消：`POST /tasks/{id}/cancel`（仅 pending/waiting_external）。

## 6. 对账自愈（热重载杀在途的根治）

- **启动 reconcile**：上一进程的 `running` 任务判 failed（错误写明"worker 重启"）并修正
  meta.gen；`waiting_external` 不动（外部任务还在跑，poller 继续收割）；pending 原样重调度。
- **周期 stalled 对账**（poller 每 5s 顺带）：running 超各 Step `timeout_s`、
  waiting_external 超 30min → 判死。
- 收割用 CAS（`UPDATE ... WHERE status='waiting_external'`）防重复。

## 7. 框架选型结论（调研 2026-07-11）

方案 A 自建薄层胜出：procrastinate（PG 队列，重试策略/stalled 恢复可抄但不支持
"提交即释放+poller 收割"模式）、DBOS Transact（PG 内嵌持久化工作流，断点续跑强但要接管
schema+改造 external 模式）、Temporal/Hatchet（要独立 server）、Celery/arq（要 Redis）均不整体采用；
机制清单（重试策略/attempt/错误分类/stalled 对账/唯一在途/尝试历史）逐条借鉴落进 flow.py。

## 8. 接口变化

- `POST /shots/{id}/prompts`：由同步装配改为**异步任务**（gen_prompts=装配+质检合并）；
  `POST /shots/{id}/prompt-review` 已删除（质检并入 next）。
- `POST /chapters/{id}/storyboard`：拆分镜改异步任务，返回 `{task_id}`；拆完自动串每镜提示词。
- 新增 `POST /tasks/{id}/cancel`（仅 pending/waiting_external）与 `POST /tasks/{id}/retry`
  （failed→新任务，attempt 归零）。
- 前端已完成最小适配（保持编译与主流程可用）：按钮合并「🔄 重新生成提示词」+「🧪 质检并重构」
  →「🔄 生成提示词（含质检）」；拆分镜改任务轮询；挂载时从任务列表恢复在途状态。

## 9. 前端待办（📋 2026-07-11 记，后端已就绪、纯前端工作）

1. **【bug】拆镜完成后串出的镜级任务未进轮询**：BreakdownStep.next 自动为每镜入队
   gen_prompts，但 ShotBoard 的"listTasks 恢复"只在挂载时跑一次——bdTask 完成 reload 后
   应重跑恢复逻辑，否则各镜 ⏳ 徽标不亮（刷新页面才出现）。
2. **失败/取消状态呈现**：利用 `meta.gen.<产线>.state=failed` 的 error（时间轴红徽标+
   悬浮错误原文），配「重试」按钮（POST /tasks/{id}/retry）与「取消」按钮
   （POST /tasks/{id}/cancel，仅排队/等待收割中可见）。
3. **质检缓存可视化（可选）**：ShotInspector 质检标签旁显示 valid_until 与
   "缓存有效/已过期将重检"提示。
4. **浏览器端到端走查**：按钮合并交互、异步拆镜全流程、刷新恢复（后端链路已 API 实测通过，
   UI 层未走查——本轮与另一会话的前端重构并行，避让）。

## 10. 依赖 DAG + SSE 实时化 + 流式拆镜（2026-07-13 落地）

本轮把管线从「推式 next 链」升级为「拉式依赖 DAG + 实时推送」，四件事一个架构收口
（参考模型：BullMQ FlowProducer 父子任务 / Dagster 资产物化 / Make 目标导向解析）。

### 10.1 依赖 DAG（flow.enqueue_with_deps，07_task_deps.sql）
- `Step.missing_deps(conn, project_id, node_id, payload)` 声明"我缺什么、谁能生产"：
  gen_video → [gen_prompts(缺 video_prompt), gen_keyframe(缺 keyframe_url 且未停用首帧)]；
  gen_keyframe → [gen_prompts(缺 image_prompt)]。
- `enqueue_with_deps` **单事务**递归解析成树（worker 另事务领 pending，看不到半棵树）：
  父 status=waiting_deps + deps_remaining=N；边落 `task_deps`（多父 DAG——幂等去重把
  视频链与首帧链共享的 gen_prompts 合并为同一子任务，天然菱形）。
- 子 done → `release_parents`：全部父 deps_remaining-1，归零转 pending（callFun 逐级向上）；
  子 failed/canceled → `fail_parents` 连锁 blocked 向上（盲跑白烧钱）。
- 崩溃窗口/解析竞态由 `reconcile_waiting_deps`（poller 每 5s）对账自愈：
  waiting_deps 且无在途子 → 有失败子连锁 failed，否则转 pending。
- API 变化：`POST /shots/{id}/keyframe|video` 与批量首帧不再 400"请先生成提示词"，
  返回 `{task_id, planned:[整棵新建任务树]}`；retry 走依赖解析（缺前置自动重新派发）；
  cancel 支持 waiting_deps 并连锁父任务。
- VideoStep.before 提交前按 meta 实时刷新 first_frame_url（依赖子任务出的首帧要用得上）。

### 10.2 事件总线 + SSE（services/events.py，GET /api/projects/{id}/events）
- 进程内 pub/sub（与 enqueue 幂等去重同样的单进程假设；多进程时换 LISTEN/NOTIFY）。
- 任务每次状态转移经 `flow.notify_task` 广播摘要（含 parents 边/deps_remaining/镜号标注）；
- SSE 连接即发全量快照（在途全量+最近 30 条），断线重连快照收敛；15s 心跳保活；
  响应带 `X-Accel-Buffering: no`，容器 nginx 另有 events 专用 location（禁缓冲+1h 读超时）。

### 10.3 流式拆镜（storyboard_stream.py）
- 粗拆改 `llm.chat_stream` + **固定 MD 模板**（JSON 反流式：不到闭合括号解析不了；
  MD 以「## 镜N」为块界，每块独立解析，截断只损失最后半镜）。
- 一镜解析完立即落库（meta.provisional=true）+ 广播 `{type:shot}` → 前端实时逐镜显示；
  每轮（首拆/校验重拆/总审重拆）开头清场并广播 `shots_reset`；流式异常自动回退一次性 JSON。
- 质检链（merge 镜头组/零 token 校验/四维总审/对白顺序）不变，收敛后终局事务落权威列表
  并广播 `shots_reset(final)`——流式镜只是过程可见性，最终一致性与旧版等同。

### 10.4 前端（lib/taskCenter.ts + features/projects/TaskQueue*）
- 全局任务中心：每项目一条 EventSource + useSyncExternalStore 单一 store，
  取代 ShotBoard/usePendingTasks 两套 4s 轮询；刷新页面由快照自动恢复在途状态。
- 顶栏全屏按钮右侧「任务队列」按钮（徽标=在途数/失败警示）：面板按 task_deps 边渲染
  依赖任务树（waiting_deps 显示"等待前置·差N项"），支持取消/重试、失败原因展示。
- 第 9 节前端待办 1/2 已由本轮覆盖（SSE 实时驱动，无恢复时机问题；失败呈现进队列面板）。
