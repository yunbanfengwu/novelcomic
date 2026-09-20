# 编排 ↔ 实际执行 对齐待办（2026-07-30，交接给后端会话）

> **2026-07-30 后端侧 1→4 已全部完成并本地实测（项目 25 / 镜 819，dry 零模型调用）。**
> 详见文末「已完成（后端侧）」；前端只差把 `step_chain` 渲染成只读节点。

## 提示词（整段复制给另一个会话即可）

在 `D:\aiwok\agent-nc-workbanch\backend` 里做「智能体编排 ↔ 实际执行」的对齐，
以 `a.shot-keyframe`（智能体编排清单.md 第 27 条）为样板。核心问题：编排画布画的是
workflows.graph 手写配置，而 run-unit 跑 `gen_keyframe` 时执行的是 `_shot_gen_before`
守卫链——两边各画各的，编排图没有真的驱动/反映实际产出。按本文件「待办」1→4 逐条做：
先把 seed graph 改成守卫链的如实投影（改 backend/sql 种子，保持幂等），再让 run-unit
带 step 的编排复用 production-canvas 同一链路，然后暴露守卫链清单端点给前端（格式见
待办 3），最后给 preview-batch 条目加产物 url 字段。**不要动 frontend/**（编排 UI
由另一个会话维护，前端已完成的部分见「已完成」一节）；改完后端跑
`docker build -t t ./backend` 或确认新依赖都在 requirements.txt；只在本地改，不要 push。


> 背景：智能体编排（/admin/wf）的「编排画布」画的是 workflows.graph 手写配置，
> 「运行画布」现已直接复用分镜页的真实镜头无限画布（ShotSopCanvas，前端已落地）。
> 问题：两边各画各的来源——编排里手写的前置只是 step 真实守卫链的粗略子集，
> run-unit 跑 step 时后端照样执行自己的守卫，编排图并没有真的驱动/反映实际产出。
> 以 `a.shot-keyframe`（清单第 27 条）为样板先对齐，再推广到其余 a.* / c.*。

## 待办（按优先级）

### 1. seed graph 如实投影守卫链（快改，先落）
`a.shot-keyframe` 的 seed graph（backend/sql 里的编排种子）改成如实声明
`_shot_gen_before` 的守卫链，每个守卫一个前置节点：
- 连续性检查（assert_shot_generation_ready）
- 镜级要素预检补建
- 场景站位兜底
- 提示词装配（依赖 a.shot-prompt，保留）
- 质检缓存 / 角色硬闸 + 参考图 ≤4
next 段如实声明：回写 `content_nodes.meta.keyframe_url` + `_backfill_seam_for` 接缝回填 + 通知。
> 目标：编排态五段和运行态真实画布**逐节点对得上**，不再是另一份手写近似。

### 2. 单一事实来源（治本）
`run-unit` 对带 `step` 的编排直接复用 production-canvas 节点实例
（`runProductionCanvasNode` 同一链路），编排的前置/next 从 step 的依赖声明
**自动生成**而非手写——以后永远不会再漂移。

### 3. 暴露守卫链清单给前端（接口约定）
给前端一个端点（或并入 GET /api/workflows/{slug} 响应）：
`step -> [{ id, label, kind: 'guard'|'dep'|'write'|'notify', status? }]`。
前端编排画布把「step 内置守卫」渲染成只读节点（带状态点），与真实执行对齐。
> 前端侧（编排画布渲染守卫节点）由编排 UI 会话接，约好格式即可。

### 4. preview-batch 条目带产物 URL（小改）
`agent_batch.resolve` 的 items/skipped 各加 `url`（如 `meta->>'sheet_url'` /
`keyframe_url`）。前端批量运行画布的「生成的图片」格子即可回显已有产物图
（单镜流已用真画布不受此限，批量流缺这个字段）。

## 已完成（前端侧，不用重复做）
- 运行态：`gen_keyframe` + 选中具体镜 → 直接挂载真实 ShotSopCanvas（同组件同数据）。
- 运行上下文：卷/章 → 镜 级联选择；选好即自动 preview-batch 零成本回显。
- run-unit 新旧两种结果形状（平铺 / run|output|next 嵌套）前端都已兼容（normResult）。

## 已完成（后端侧，2026-07-30）

1. **seed 如实投影**：`backend/sql/44_agent_unit_align_keyframe.sql`。守卫链**没有**写进
   config/graph——前端 `graphAdapter.unitConfig` 会折叠所有节点 config，塞守卫节点会污染
   配置且手写必漂移；守卫链改由端点投影（见 3）。seed 把 `a.shot-keyframe` 的对齐键定成
   权威（`||` 覆盖，幂等）：`writes=content_nodes.meta.keyframe_url`（缺才跑判据）、
   `notify=[frontend.refresh]`、`attach=no`、`task=""`（真实链路提示词由
   gen_keyframe.before 重装配产出，编排层的自由 LLM 是白花钱且必被覆盖，置空即运行段不跑）。
2. **单一事实来源**：新增 `backend/app/services/production_canvas.py`。
   `step_payload()` 是镜级 step（gen_shot_storyboard / gen_prompts / gen_keyframe /
   gen_video）唯一的 payload 装配，`api/shots.py` 画布节点执行与 `agent_unit._one`
   带 step 入队都只调它。顺带修复真实漂移：编排路径此前不带 `prompt_overridden`，
   用户手编的首帧/视频提示词会被 Step.before 重装配冲掉，现在与画布同语义。
3. **守卫链端点**：并入 `GET /api/workflows/{slug}` 响应，unit 配了 `step` 时多一个
   `step_chain: [{id, label, kind: 'guard'|'dep'|'write'|'notify'}]`（无 status——
   运行态状态由真实 ShotSopCanvas 提供）。来源是 STEPS 注册表的
   `dep_kinds/soft_deps/before_notes/next_notes`（`production_canvas.step_chain`），
   顺序=真实执行顺序；`gen_keyframe.before_notes` 已补齐「连续性守卫」「场景站位兜底」。
4. **preview-batch 带产物 URL**：`agent_batch.SOURCES` 全部 7 个源加 `url` 列
   （sheet_url / empty_url / sheet_url / keyframe_url），`resolve()` 的
   items/skipped 条目都带 `url`（无产物为 null）。

实测（本地库）：`a.shot-keyframe` dry 入队 payload_keys=
`[prompt, prompt_overridden, reference_images]`、`a.shot-video` dry =
`[duration_s, prompt, prompt_overridden, prompt_textonly, ratio, reference_images]`，
均与生产画布节点完全一致；step_chain 输出 1 dep + 1 soft + 8 guard + 2 write + 1 notify；
`ctx.shots` 批量条目已回显 OSS keyframe URL；backend 82 个测试全过；无新增第三方依赖。
推广到其余 a.* / c.*：镜级四张（a.shot-storyboard / a.shot-prompt / a.shot-video 及
c.episode-*的 ref_each）payload 已自动走同一装配，无需再改；各自的 seed 对齐键
（writes/notify/task 置空）可照 44 号 seed 逐张补。

## ~~给编排 UI 会话的提示词~~（2026-07-30 前端渲染也已由后端会话完成，勿重复做）

> 已落地：`viewModel.buildView` 第 4 参接 `step_chain`，guard/dep 画进「前置」道、
> write 画进「next」道（notify 不重复画），只读节点 `.agi-ro` 虚线琥珀样式；
> `AgentCanvas` 新增 `stepChain` prop，`AgentFlowAdmin` 传 `cur.step_chain`；
> `runGraph.mergeRun` 已消费 preview 条目的 `url`（批量画布「生成的图片」回显）；
> `api.ts` 补 `StepChainItem` / `WorkflowDetail.step_chain` / `BatchItem.url`。
> tsc / lint / build 全过，浏览器已验证（20 节点 19 边，12 只读投影）。
>
> **运行态三形态收敛（2026-07-30 二轮）**：运行画布不再是另一张图——
> `AgRunView` 统一分派：批量→对象网格（AgRunCanvas）；单对象→`AgRunAligned`
> （**与编排同一张骨架**，守卫节点状态按 step_chain 新增的 `node` 字段从该镜
> `GET /shots/{id}/production-canvas` 的同名固定节点回读，输出产物节点直接亮
> 真实首帧缩略图）；单镜首帧选好镜后右上角「真实画布」可切 AgShotCanvas 深看。
> 未选上下文时运行态=编排原样（全 idle），「对象 1/2/3」假占位已删。
> 映射表在 backend `production_canvas._CHAIN_NODES`（改 before_notes 需同步）。
>
> **三态定稿（2026-07-30 三轮，按用户定调「编排独立；运行=生产统一，依赖编排」）**：
> - 编排态：定义骨架（五段 + step_chain 只读守卫），独立画布；
> - 运行态=生产态，一张画布按上下文分派（`AgRunView`）：
>   选中**镜** → 默认真实生产画布 AgShotCanvas（节点重跑/改提示词都在），
>   「对齐骨架」为切换视图；选中**整章** → `AgChapterAssets` 章级素材视图
>   （preview-batch ctx.shots，每镜一组直接亮已生成首帧，缺图标待跑，
>   「镜头画布」按钮下钻=细化 ctx 到该镜、右侧下拉联动）；未选上下文 → 编排同款
>   骨架全 idle。假占位「对象 1/2/3」仅剩零对象兜底。
> - 实测（后端 8804 新代码 + 前端 5261）：章 769 十三镜、11 张真实首帧回显、
>   下钻后真实画布挂载、上下文联动正确。
>
> **编排前置对齐生产逻辑（2026-07-30 四轮）**：
> - 「取本镜出场要素」改为智能体守卫节点（guard:2 文案：已列全直接取用、缺则模型
>   按正文补建入库），排在最前；45 号 seed 删掉了语义错误的 shot.elements 取数节点；
> - step_chain 新增 `_CHAIN_ORDER`（展示顺序=生产画布逻辑：要素备料→设定图→
>   连续性/站位→分镜剧本→组合提示词→质检→出图），并展开一层嵌套依赖
>   （dep:gen_shot_storyboard↔cuts）；执行顺序仍以 Step 代码为准；
> - **依赖吸收**：GET /{slug} 对 ref_flows 里承担链上依赖 step 的编排，在对应
>   chain 条目标 `flow/flow_name`；前端把该编排画在链的真实位置（可开子页签、
>   不可删），不再在链外另画手写近似——a.shot-prompt 就画在「组合提示词」位。
> - ⚠️ guard:i 下标被 _CHAIN_NODES/_CHAIN_ORDER 引用：改 before_notes 只能改文案，
>   增删/换序必须同步这两张表。
>
> **autoflow · 通用编排入口（2026-07-30 五轮定稿：纯编排驱动，与硬编码并存）**：
> `POST /api/agents/autoflow`（services/autoflow.py），两种模式：
> - **直跑**：`{flow:"a.shot-keyframe"|"gen_keyframe", project_id, node_id, dry?}`——
>   传智能体编排 slug，或老步骤类型（`resolve()` 按「哪张编排配了该 step / step_v2」
>   自动解析，**没有硬编码映射表**）；不认识的名字明确 400。
> - **自主规划**：只传 `task`（自然语言）→ 大模型对着编排清单（`catalog()`：
>   每 slug 最新版 + 名称/描述/必填入参/批量，排除工作流引擎 DAG 图）自主规划
>   调用哪些智能体、什么顺序，然后逐个执行；`plan_only:true` 只回方案。
>   每步各落一条 agent_runs，响应只带摘要（flow/run_id/ran/skipped），
>   完整结果凭 run_id 查 `/api/agents/runs/{id}`。一步失败停链、已跑的照样返回。
> - 执行核 `run_flow()` 与 run-unit 共用（run-unit 现在就是 autoflow 的直跑特例）。
> - 地基（同日完成）：守卫外化为 5 张可编排小编排 g.shot-elements / g.shot-sheets /
>   g.shot-blocking / g.shot-reassemble / g.shot-image-qc（46 号 seed 只建一次，
>   归画布编辑管；前置段直调 workflow_actions 新注册的 5 个守卫工具，全幂等带缓存），
>   出图走 `gen_keyframe_v2` 纯生成 Step（继承 v1 run/next；只留连续性硬门/缺提示词
>   Blocked/角色硬闸三道底线，不反向派发）。改配置/删守卫/换顺序=真实改变执行。
> - **老硬编码链一行未动**：分镜页/批量/组图照旧走 gen_keyframe v1；重要功能先迁、
>   逐步迁——迁移一个场景 = 守卫工具 + g.* 编排 + *_v2 纯生成 Step，调用方换成 autoflow。
> - 实测（8804）：直跑 slug/类型解析 ✓；自主规划 6 步方案并逐步 dry 执行 ✓
>   （run 63-68）；真跑缺才跑零成本跳过 ✓；错误路径（未知 flow / flow+task 全空）✓。
> - 已知：规划器有时会把目标编排的前置也排进方案（幂等+缓存，重复执行零成本，
>   结果仍正确）；要更紧凑可再调 plan() 的系统提示词。
>
> **两套画布并存定稿（2026-07-30 六轮，前后端已落地）**：
> - 已迁移编排（step 为 *_v2）运行态**默认对齐骨架**（编排即真相）：前置编排节点
>   状态来自 agent_runs（整跑 before 段 + 单步重跑结果），内置守卫从生产画布回读，
>   输出节点亮真实产物图；老 ShotSopCanvas 降级为「真实画布」深看按钮。
>   未迁移编排（v1）保持老生产画布默认——它才反映 v1 的真实执行。
> - **节点级重跑（走新链）**：前置编排节点「重跑此步」= run-unit 真跑那张守卫/依赖
>   编排；输出节点 = api.autoflow 直跑本编排。全部不经过 v1 队列入口。
> - 前端：api.ts 补 `autoflow`/`runUnit.params+run_id`；AgRunAligned 持有单步重跑
>   状态机（busy→running、结果→done/failed、跑完刷新生产回读）；AgRunView 按
>   `step.endsWith('_v2')` 分派默认视图；AgNode 渲染「重跑此步」按钮（内置锁节点无）。
> - 实测（8804+5261）：v2 默认骨架 ✓；6 前置编排节点+输出节点共 7 个重跑按钮、
>   3 个内置守卫无按钮 ✓；单步真跑 g.shot-elements 缓存命中秒回、节点点亮 done、
>   落 agent_runs（run 69）✓。
> - **前置入参规范（用户定稿，替代早先的「先拆分镜」按钮方案）**：编排声明的必填
>   前置输入参数**未选择**或**没有可选的值**时，此功能**不可单独测试**——只说明原因
>   与该去哪，不越权代跑不属于本编排前置链的编排。两处落地：
>   ① AgRunView 通用横幅：按 cfg.inputs 必填声明对照 ctx，缺什么列什么；
>   ② 章级视图无分镜时提示「前置输入参数『镜』没有可选的值…请先用章级编排
>   a.chapter-breakdown 生成分镜」。早先的「先拆分镜」按钮与轮询已按此规范移除
>   （AgRunBar 保留通用 refresh prop 备用）。
> **注意**：守卫节点要显示出来，前端连的后端进程必须是新代码——
> 8765（run_dev --reload）已生效；8788/8796 等 uvicorn 无 reload 的旧进程需重启。

以下为原提示词存档：

在 `D:\aiwok\agent-nc-workbanch\frontend` 里给「智能体编排」（/admin/wf）的**编排画布**
渲染 step 内置守卫链。后端已完成：`GET /api/workflows/{slug}?version=N` 的响应在
unit 配了 `step` 时多一个字段：

```ts
step_chain: { id: string; label: string; kind: 'guard' | 'dep' | 'write' | 'notify' }[]
```

- 条目顺序 = 真实执行顺序（gen_keyframe 为例：1 dep + 1 soft-dep + 8 guard +
  2 write + 1 notify，共 13 条）；`id` 形如 `dep:gen_prompts` / `guard:0` / `write:1`。
- 把它们渲染成**只读节点**（不可编辑、不可删），挂在「运行」段与「输出产物」段之间
  （guard/dep 在运行前、write/notify 在产物后），与运行态真实画布（ShotSopCanvas）对齐。
- 无 status 字段——编排态只画结构；运行态状态已由真实镜头画布提供，不要重复造。
- `api.ts` 的 `WorkflowDetail` 类型补上 `step_chain?`；数据从 `useFlowTabs` 已有的
  getWorkflow 响应里直接取，不需要新请求。
- 另外 preview-batch（`/api/agents/preview-batch`）与 run-unit 结果里的批量条目
  现在带 `url`（已有产物图，无则 null）——批量运行画布的「生成的图片」格子可直接回显。
- 老坑别踩回去：不要用 `fitView`；节点要显式给 `handles`；改完跑 `npx tsc -b` 与
  `npm run lint`；只在本地改，不要 push。

## 相关文件
- 清单：智能体编排清单.md 第 27 条（gen_keyframe 守卫链描述）
- 后端：backend/app/services/agent_unit.py（run_unit）、shots 生产链 `_shot_gen_before`
- 前端已改：frontend/src/features/admin/agentflow/（AgShotCanvas / AgRunBar / runGraph）
