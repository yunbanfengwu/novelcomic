# 生产态画布：本对象专属副本 + 能跑的自由节点（2026-08-01）

解决两件事（用户提出）：

1. 素材库点一个场景进画布，**改了什么都存不下**——关掉弹窗全丢，下次进来还是模板。
2. 从节点端口拖出来的新节点**毫无作用**：没有执行体、跑到它必报错。

前置背景见 [tapflow-scene-flow-design](tapflow-scene-flow-design-2026-08-01.md)（画布形态与装配三层）。

## 一、为什么是「独立 slug 的画布实例」

候选方案里最诱人的是「给模板开一个特殊版本，关联到元素 ID」。不能这么做：

`load_workflow(slug)` 不带版本时取的是**最新已发布版**（[workflow.py:126](../backend/app/services/workflow.py)），
subflow 引用、业务入口、编排列表全靠它。把某个场景的私有画布挤进模板的版本线，
别人打开模板就会拿到你的场景图；要躲开就得再加「实例版本不参与 latest」的过滤——
等于在版本语义上挖一个洞，以后每处读版本的代码都要记得绕开它。

独立 slug 天然隔离，而且什么都不用新写：

| | 模板 | 实例 |
|---|---|---|
| slug | `scene-sheet-canvas` | `scene-sheet-canvas@element-206` |
| 归属 | `subject_id IS NULL` | `subject_kind='element' subject_id=206` |
| 版本 | 草稿/发布两态（改完要发布） | 永远 v1 published，**存即生效** |
| 编排列表 | 在 | 不在（`GET /api/workflows` 默认过滤） |
| 运行/预检/运行历史 | 现成引擎 | 同一套，零新增运行时 |

「上次运行回填」跟着 slug 走，于是实例天然按场景分开——这是白捡的正确行为。

⚠ 列叫 `subject_*` 不叫 `owner_*`：`workflows.owner_id` 早被用户所有权占了
（[sql/35](../backend/sql/35_users_and_ownership.sql)，`TEXT NOT NULL DEFAULT 'sys_dev'`）。
同名两义必然出事——「按 owner_id IS NULL 过滤掉实例」在那一列上永远筛不出东西。

### 踩到的坑：启动时的白名单 DELETE 会把实例删光

[sql/60](../backend/sql/60_drop_agent_units.sql) 是**每次启动都跑**的
`DELETE FROM workflows WHERE slug NOT IN (白名单)`。实例的 slug 天然不在名单里，
后端一重启就把用户的专属画布连同 `workflow_runs` 一起 CASCADE 删掉
（实测：实例存好、跑了一半，重启后 run 行也没了）。已改为豁免 `subject_id IS NOT NULL`，
并用 `information_schema` 守卫——60 的序号在 65 之前，全新库第一次启动时那几列还不存在。

## 二、什么时候 fork：首次结构改动

打开画布**不** fork（只跑不改的用户永远停在模板，也就不会平白多出一堆实例）。
拖出节点 / 删节点 / 连线 / 挪位置 / 改节点配置——任一发生就静默 fork + 防抖自动保存，
顶部给一句「已保存到本对象的专属画布」。

- 触发判据：[useTapflowAutosave](../frontend/src/lib/useTapflowAutosave.ts) 的**结构指纹**。
  跑出来的图片 url / 正文 / 质检徽标不进指纹——那些是运行结果不是编排，
  算进去的话每跑一步都会存一版，还会把运行态的临时值焊进图里。
- **安顿期 1.5s**：画布挂载后会按实测卡片高度整图重排一次坐标（`autoLayout`），
  那是渲染的一部分。不豁免的话，光是打开画布就 fork 一份什么都没改的实例。
- fork 后 `flow.slug` 换成实例——**运行也跟着换**（[TapflowLaunch](../frontend/src/features/tapflow/TapflowLaunch.tsx) 持有 flow）。
  漏了这一步就会「改动存进副本、跑的还是模板」。
- 保存合并底稿随保存滚动更新（存进去的那份就是下次的底稿），否则新节点里画布模型
  不认识的键（payload / skip_if）每存一次就被按空对象重建一次。

坐标能存住还要靠一条：`adaptWorkflow` 现在回报 `placed`（全部节点都有 `ui.xy`），
画布据此**跳过挂载时的整图重排**。不然用户拖的位置存下去了，下次打开又被排版推回原位。

## 三、拖出来的节点凭什么能跑

三块缺失，缺一不可，补齐在 [tapflowCustomNode.ts](../frontend/src/lib/tapflowCustomNode.ts)：

1. **执行体**：新增 Step `gen_canvas_image`（提示词 + 上游图当参考 → 出图 → 落项目附件）。
   刻意不复用 `gen_element_sheet`——那条会回写要素的**正式设定图**，
   用户拖出来试个构图就把正式图换掉，不可接受。自由节点的产物只落一条附件
   （`meta.type='canvas'`，素材库看得见），不动任何要素。
2. **payload**：带上 `node_key`，产物落附件时记 `meta.node`。
3. **缺才跑探针** `skip_if`：按 `meta.node` 回查本节点上次出的那张。没有它，
   整图每跑一遍就重出一次这张图——真金白银。

引擎侧配套：`_await_task` 现在把 `task_queue.result` 一并带回，gen/task 节点在
**没有 skip_if 时用任务产物兜底**取 url。否则自由节点跑完了卡片还是空的。

投影层的老毛病一并收掉：出媒体的四种 tap（`gen/image/video/audio`）后端都是 `type=gen`，
但正向投影、执行体下拉、运行状态回填都只认 `'gen'`——画布上拖出来的是 `tap=image`，
于是存下去再打开就成了没有 bind、没有生成条、没有落点可选的哑卡。统一走
`isGenType`（[tapflowData](../frontend/src/lib/tapflowData.ts)）。

新节点 id 也换了：原来是 `new-1` 计数器，存过一次再拖一个还叫 `new-1`，
与库里那个撞 id，`validate_graph` 判「id 重复」，整张图存不下去。

## 四、生产态放开了多少编排能力

只放开**用户自己加的节点**（`config.ui.custom`）：选中即展开属性面板，可改执行体、
系统提示词、技能/知识库、质检、缺才跑。模板那几个节点仍然只读——
它们的编排语义是产线的一部分，要改去编排台改模板，一改就是所有场景一起变。

## 五、验证（2026-08-01，本地 8824 + 5291）

| 用例 | 结果 |
|---|---|
| fork 幂等 | 同一对象重复 POST 只有一份实例，slug 确定性 `模板@element-206` |
| 只开不改 | 等 6s 不 fork、无保存条（安顿期豁免生效） |
| 拖出节点 | 自动 fork + 自动保存，节点带 `step/payload/skip_if/ui.custom` 与连线一并落库 |
| 重开画布 | 打开的是实例，自建节点与坐标都在 |
| 自由节点真出图 | run #108：上游缺才跑跳过 → 自由节点出图 → 附件 744（`meta.node` 已记） |
| 缺才跑 | run #109：同一节点第二次跑被 skip，回带上次的 url |
| 预检回显 | 打开画布即回显自由节点上次那张图 |
| 编排列表 | 默认不含实例（`?include_instances=true` 才给） |

**已知环境坑（不是代码问题）**：同一个库上跑着两个后端时，新 Step 的任务可能被
**旧代码的 worker** 抢走，报「未知的任务类型: gen_canvas_image」。加了新 Step 就得让
所有 worker 都是新代码（线上单容器不存在这个问题）。

## 六、遗留

- 实例目前只有「有没有」，没有「回到模板」的入口。真要重置就是删掉那条 workflow——
  等有人提再做，别提前造管理界面。
- 视频/音频类新节点不给默认执行体：现成的执行体都焊在镜级上下文里，随手绑上只会跑一半才炸。
  这类节点落下来仍需在属性面板里挑。
- `Maximum update depth exceeded`（打开画布时一串）是**既有问题**，与本轮无关——
  已用 HEAD 版对拍确认（HEAD 也复现）。属于 [handoff-todo](tapflow-handoff-todo-2026-08-01.md) P2 那批未验交互的一部分。
