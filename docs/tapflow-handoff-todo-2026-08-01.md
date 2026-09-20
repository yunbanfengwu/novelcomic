# tapflow 待办交接清单（2026-08-01）

给接手会话看的。**已完成**的部分见
[tapflow-scene-flow-design](tapflow-scene-flow-design-2026-08-01.md) 与
[tapflow-node-assembly-design](tapflow-node-assembly-design-2026-08-01.md)，本文只列**还没做完的**。

按优先级排，每项都写清楚「为什么」——不写背景的待办，接手的人只能猜。

---

## P0 · 阻断性缺口

### 1. 画布编辑不落库（属性面板的配置全是演示态）

> **已解决（2026-08-01 晚）**：反向投影 `tapflowGraphWrite` + 编排台保存条已上；
> 生产态改走「本对象专属画布」——首次结构改动自动 fork 实例并自动保存，
> 拖出来的节点也补齐了执行体/缺才跑探针，落下即可跑。
> 见 [tapflow-canvas-instance](tapflow-canvas-instance-2026-08-01.md)。下面是当时的记录。

**现状**：`api.saveWorkflow` 存在，`AgentFlowAdmin` / `WorkflowEditor` 在用，
但 **tapflow 画布一次也没调过**（`grep saveWorkflow src/features/tapflow/` 无结果）。

后果：属性面板里配的 charter / 技能 / 知识 / 工具 / 质检 / 引用、画布上拖动的节点坐标、
新建的节点与连线——**关掉弹窗全丢**。真实流程的行为完全由 SQL 种子决定。

后端是就绪的：`_run_llm_node` 已经消费 `cfg.charter`（`workflow.py:662`），
`validate_graph` 会在保存时查环。缺的只是前端把画布投影**反向**转回 graph 再 POST。

- 入口：`TapflowModal`（需要一个「保存」动作）
- 反向投影：`lib/tapflowGraphAdapter.ts` 目前只有 graph→canvas，需要 canvas→graph
- ⚠️ 反向投影要保住 `config` 里**画布不认识的字段**（skip_if / assemble / payload / preview…）。
  只回写画布改过的那几项，别拿画布模型整个覆盖 graph，否则种子里的执行语义会被抹平。

### 2. 「无项目」通路走不通（需要产品决策，不是代码问题）

`content_elements.project_id` 与 `content_attachments.project_id` 都是 **NOT NULL**。
没有项目就既建不了要素、也挂不了附件，产物只能落 OSS + `gen_logs`，**进不了素材库**。

开始节点已经把项目做成可空、并预留了「整体设定」入参（`TAP_OVERALL_KEY`），
但后端没有对应通路。两条路二选一，要先定：
- 给自由素材一个默认项目（改动小，但会有个「杂项」项目）
- 放宽两张表的 NOT NULL（改动大，影响面广）

---

## P1 · 已知缺陷

### 3. 场景 anchor 与「骨骸类场景」自相矛盾

`element_sheet` 的场景硬约束写死了 `no dragon, no monster`，而场景「龙骨峡谷」的设定
就是「峡谷中遍布龙族的遗骸」——**装配出来的提示词自己跟自己打架**，质检如实抓到并停链。

质检没判错（`57_qc_scene_skill_fix.sql` 已经把「遗骸属于地貌」写进技能了），
根因在**生产装配器**里。修它要动画风关键路径，好在有逐字节对拍脚本护着
（`scratchpad/assembly_diff.py`，40 个要素 0 差异）。建议单独一轮，改完重跑对拍。

### 4. 引擎串行等待子任务

`WorkflowStep` 在自己的 `run()` 里串行驱动整张图，一次运行占住一个 worker 槽。
单场景无所谓，**批量几十个场景会堵**。要改成「节点入队 + 工作流重入」——
表结构不用动，`workflow_node_runs` 已按 `(run_id, node_key, iteration)` 记了断点。

### 5. 生成条的模型名是假的

显示「系统出图模型」，实际出图是 `doubao-seedream-4-5-251128`。
当初写死「Seedream 4.0」对不上，我改成了不撒谎但也没信息量的措辞。
要显示真型号得从 app_config 的出图配置带出来。

---

## P2 · 未验证（**全部只到编译层，没在浏览器里点过**）

这是本轮最大的欠债。原因：dev server 名额一直被其他会话占满，
`preview_start` 失败 8 次以上。**浮窗点不中那个 bug 反复改了三轮**就是这么来的——
接手第一件事应该是起服务把下面这些一次性验完。

**画布交互**
- [ ] 浮窗 portal（`TapPickMenu` → `.rx-modal`）：能否真的点中选项、点外/ESC 能否关闭
- [ ] 滚轮在生成条/正文卡内滚动（`useTapflowView.scrollableAt` 按能力判断的新逻辑）
- [ ] 文本卡双击进编辑：能否正常选中文字、失焦提交、与「点空白收面板」是否打架
- [ ] 节点执行中的流光边框——尤其**质检圆点那条**（`.tap-card-qc.flowing-border` 圆形是新写的）
- [ ] 跳过/失败胶囊跨在卡片上沿的位置（`top: 5px`）

**生成条**
- [ ] 右上角状态徽标（`top: -12px`）会不会被上方工具条盖住
- [ ] 参考条的 `+` 选择与 `×` 删除
- [ ] 文本卡工具条：复制 / 编辑 / 重新生成
- [ ] 「发送」= 单节点重跑（引擎侧已实跑验证，前端这段没验）

**面板**
- [ ] 系统提示词框：引用方块条、`@` 插入行内标签、退格整块删、粘贴取纯文本
- [ ] 质检段：前/后分段、技能未选的边框示警、重试成本的黄字
- [ ] Radix Switch 在 tapflow 内的样式（轨道底色/滑块位置——被 `.tap-page button` 复位坑过一次）
- [ ] 强制重新生成开关
- [ ] 开始节点新版式：画风示意图、比例角标、Seg 按钮组、整体设定块
- [ ] 属性/运行按钮的模式联动（属性→编排态，运行→运行态）

**后端未实跑**
- [ ] `node_overrides.ref_nodes` 过滤（手选参考节点）——已实现未验
- [ ] 质检 `stage=image`（画面质检，走视觉模型）——已实现未验
- [ ] llm 节点的 `override.text` 手编覆盖——已实现未验

已实跑验证过的（不用重验）：`stop_after` + `force` 单节点重跑（run #49）、
装配拆层逐字节对拍、两条完整出图链路（run #46/#48）。

---

## P3 · 结构债

### 6. 超行数硬线的文件（前端规则 ≤ ~200 行）

| 文件 | 行数 | 说明 |
|---|---|---|
| `lib/tapflowData.ts` | 712 | 类型 + 假数据混在一起，建议假数据拆到 `tapflowDemo.ts` |
| `features/tapflow/TapflowCanvas.tsx` | 367 | 容器件（拖拽/连线/菜单/视图变换），拆它是独立一轮 |
| `lib/useTapflowRun.ts` | 271 | 状态投影逻辑，可把 applyNode 那组抽成纯函数 |

`TapflowNode.tsx` 已经从 233 拆到 147（拆出 StartNode / NodeMedia / NodeText）。

### 7. 镜级质检仍是硬编码

`review_image_prompt` 的十维判据写死在 `storyboard.py`。画布这条路已经改成
「判法来自技能」（`review_by_skill` + kb 里的 reviewer 条目），但镜级那条老链没走这条路。
两套判据并存，迟早漂移。

---

## P4 · 用户明确说「后续再做」

- **其它查询类节点做成最小集**：场景介绍已抽成 `scene-brief`（58 号种子），
  `element.get` 这类还内联着
- **独立质检节点**：定位是「跨节点批量抽检」，与节点内置自检不是一回事，现在用不上
- **演示画布保留**：`FLOW_DATA` / `RUN_DATA` 是刻意留的视觉基准，别删

---

## 环境备忘

- 后端跑在 `127.0.0.1:8765`（这一轮一直用它跑 E2E）
- SQL 种子按文件名顺序幂等执行，当前最新是 `58_workflow_scene_brief_unit.sql`
- 画布工作流：`scene-sheet-canvas` v7（tags 含 `canvas`）；最小集：`scene-brief` v1、`element-sheet` v1
- 对拍脚本在 scratchpad：`assembly_diff.py`（装配零回归）、`e2e_v6.py`（两条链路）、
  `e2e_single.py`（单节点重跑）
- **测试数据只增不删**（用户明确要求）：强制重出只追加附件行，历史产物保留
