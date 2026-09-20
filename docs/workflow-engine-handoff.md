# 工作流引擎 · 交接与待办（2026-07-29）

**当前状态：后端跑通并实测过；前端画布能用但未经浏览器验证；全部只在本地，未推送。**

目标是把生产流程从 `steps.py` 的硬编码里搬到数据里，让用户能在画布上编排。
采取"新旧并存"策略：老流程一行未动，工作流是纯增量，稳定后再逐个迁移、最后废弃硬编码。

---

## 一、已完成

### 后端（已实测）

| 文件 | 内容 |
|---|---|
| `backend/sql/32_workflow_engine.sql` | `workflows`（定义，slug+version）/ `workflow_runs`（运行，含 `parent_run_id` 嵌套）/ `workflow_node_runs`（节点级明细，含 `iteration`、`skip_reason`） |
| `backend/app/services/workflow.py` | 解释器：拓扑排序、节点分派、循环展开、子工作流嵌套、环检测 |
| `backend/app/services/workflow_actions.py` | 命名动作/工具注册表（**另一个会话正在扩展成统一工具注册表，勿擅自重写**） |
| `backend/app/api/workflows.py` | CRUD / publish / run / 运行记录 / 节点明细 |
| `backend/sql/33_workflow_seed_element.sql` | 工作流 `element-sheet` v1（已发布） |
| `backend/sql/34_workflow_seed_shot.sql` | 工作流 `shot-prepare-elements` v1（已发布） |

**节点类型**（语义详见 `workflow.py` 模块头）：

- `start` / `end` —— 声明入参/出参 schema，**这是工作流的签名**，没有它无法被当子工作流调用
- `task` —— 包一层 `steps.py` 里已注册的 Step，走现有任务队列
- `action` —— 调 `workflow_actions` 注册表里的工具（补"装配逻辑在 API 端点而非 Step 里"的缺口）
- `subflow` —— 嵌套调用另一工作流，按 `slug + 已发布版本`引用（不跟随 latest）
- `loop` —— 运行时把 `body` 子图展开成 N 份（参照 ComfyUI PR #2666，循环不是原语而是展开）

**关键语义：`skip_if`「缺才跑」。** `task` 和 `subflow` 默认产物已存在就跳过，想重跑要显式 `force`。
不这样做的话，每次批量都会把已有产物重新生成一遍覆盖掉——2026-07-28 批量首帧刚踩过这个坑。

**实测结果**（本地库，项目 25）：

```
element-sheet          阿砚(162) / 黄昏港口(166)  → gen 节点 skipped，零模型调用
shot-prepare-elements  镜1(819，5 个要素)
    each it=0..4 done  →  子运行 depth=1 × 5，全部 done
```

### 前端（未经浏览器验证）

- `@xyflow/react` ^12.11.2（Dify 用的同一个库，MIT）
- `features/admin/WorkflowAdmin.tsx` —— 卡片网格（复用 `.skill-grid`/`.skill-card`），点卡片开弹窗
- `features/admin/workflow/`
  - `WorkflowEditor.tsx` —— 弹窗内：顶部工具条（试运行在右）+ 画布 + 运行条
  - `WorkflowCanvas.tsx` —— React Flow 画布，拖放落点用 `screenToFlowPosition`
  - `WfPalette.tsx` —— 左侧浮动面板，分组（流程控制/基础流程/资产库）+ 搜索
  - `WfNode.tsx` —— 节点卡，端口左右（横向流），运行态叠在卡上、循环显示逐轮
  - `WfInspector.tsx` —— 右侧浮动属性面板，按节点类型出不同表单
  - `graphAdapter.ts` —— 后端 `graph` ↔ React Flow 双向转换
  - `nodeTypes.ts` —— 节点类型定义（面板/节点卡/属性表单三处共用一份）
- 菜单入口：`AdminView.tsx` 的 `'wf'` tab，标签「工作流」，在「生产 SOP」下方

---

## 二、待办（按优先级）

### P0 — 资产库是空的（面板最核心的部分，现在是空壳）

后端缺两个接口，前端 `WorkflowCanvas.tsx` 里 `tools` / `subflows` 两个 state 是写死的空数组：

1. `GET /api/workflows/tools` —— 列 `workflow_actions.specs()`（`name/title/description/params/writes`）
2. `GET /api/workflows/steps` —— 列 `steps.STEPS` 里已注册的 kind（含 `group`、`run_note` 供展示）

前端接上后，工具/Step 从资产库直接拖到画布即成节点（`WfPalette` 已支持 preset 预填 config）。

### P0 — 浏览器实测

**这是前几轮反复交付不到位的根因：改完 build 过就交，从没在浏览器点过。**
必须验证：拖拽落点是否准、连线能否吸附、浮动面板会不会挡住节点、
弹窗放宽后布局是否正常、保存后回读是否正确、点运行记录能否回放到节点上。

### P1 — 右侧面板补 tab

Dify 是「属性 / 调试 / 设计」三个 tab，当前只有属性。调试 tab 应能看本节点的
`workflow_node_runs`（输入/输出/错误/跳过原因）。

### P1 — 保存校验反馈

后端保存时会查环、校验开始/结束唯一，但前端只把错误显示成一行字，
没有在画布上标出是哪个节点的问题。

### P2 — 继续建工作流

已有 `element-sheet`、`shot-prepare-elements`。下一个是**场景两阶段**
（`gen_scene_empty` → `gen_scene_sheet` 串联），再往后是完整的单镜出图。
建之前先确认场景两阶段的装配逻辑在 Step 的 `before()` 里还是在 API 端点里
——如果在端点里，同样要先注册 action。

### P2 — 与「生产 SOP」收敛

生产 SOP 有编辑器但**没有运行时**（`steps.py` 里搜不到任何 `visual_sops`/`compiled` 引用，
那 15 个 SOP 是纯编排文档）。工作流有运行时。用户要求：**先并存，确认新画布可用后再删旧页**。
收敛时要把 SOP 的 `before/run/next` 三段式映射到节点类型。

---

## 三、约束（务必遵守）

1. **只在本地改，不要 push。** 用户明确要求。工作流相关的 `4c048ab`/`2a7f934` 已误推到线上
   （纯新增、不影响运行，用户说"线上先不管"），此后的改动一律不推。
2. **不要动 `backend/app/services/workflow_actions.py`** —— 另一个会话正在把它扩展成统一的
   工具注册表（已加 `title/description/params/writes` 元信息，指向 `services/tools.py`）。
   工作流的 `action` 节点和技能编排共用这一套注册表，不要另起第二套。
3. **不要改 `steps.py` 的现有语义。** 工作流是纯增量，老流程必须行为不变。
4. **不要用竖向流。** 用户明确说过不参考 Dify 的竖向布局，保持横向。
5. 前端硬规则见 `frontend/.claude/CLAUDE.md`：单文件 ≤200 行、禁 emoji（用 `<Icon>`）、
   `title` ≤5 字、样式分层（组件 CSS 只能以同级或更高特异度覆盖 base）。
6. 改完必须跑 `npx tsc -b` 与 `npm run lint`，动了样式再跑 `npm run build`。

---

## 四、本地验证怎么跑

后端不必起服务，直接调解释器（`assemble_*` 之类内部用全局池，必须先 `init_pool`）：

```python
import asyncio, sys; sys.path.insert(0, 'backend')
from app import db
from app.services import workflow as wf

async def m():
    await db.init_pool()                      # 会幂等执行 backend/sql/*.sql
    out = await wf.run_workflow(db.get_pool(),
        slug='shot-prepare-elements', version=None,
        project_id=25, node_id=819, inputs={"project_id": 25, "shot_id": 819})
    print(out)
    await db.close_pool()

asyncio.run(m())
```

挑测试数据的原则：**用产物已存在的对象**（要素已有 `sheet_url`、镜头的要素全有设定图），
这样 `skip_if` 会命中，全程走完循环与嵌套但**不产生任何模型调用**，不花钱。

本地库：`postgresql://postgres:123456@localhost:5432/novelcomic`
可用测试数据：项目 25「北境灯塔」；要素 162 阿砚 / 166 黄昏港口（有设定图）、165 李文博（无）；
镜头 819（5 个要素全有设定图）。
