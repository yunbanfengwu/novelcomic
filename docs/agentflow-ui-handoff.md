# 智能体编排 · 前端样式交接（2026-07-29）

> 直接把「## 提示词」整段贴给另一个会话即可。下面的「## 现状」是给它的背景，
> 「## 别碰」是硬边界——同期我在改后端，改花了会冲突。

---

## 提示词

在 `D:\aiwok\agent-nc-workbanch\frontend` 里改「智能体编排」（`/admin/wf`）的三处交互。
先在浏览器里把现状跑一遍再动手，每做完一件先给我看效果，不要一次改一大片。

### 1. 悬浮工具条从左侧移到右侧，且同时只开一个浮窗

现在左侧是一竖排 icon（`AgRail.tsx`：新建最小集 / 资产库 / 运行 / 保存），
展开的面板贴在 rail 右边、跟画布抢地方。要改成：

- 整条 rail 移到**画布右侧**，竖排 icon 不变。
- 「运行」也收进这条 rail（现在它是 rail 里的一项，保持，但面板形态要统一）。
- 每个 icon 点击弹出**浮窗**，浮窗从 rail 左侧展开、悬浮在画布之上。
- **同一时刻只允许一个浮窗打开**——点另一个 icon 自动关掉上一个。目的是减少浮窗
  占用的画布面积，现在几块面板可以同时开着，画布被挤没了。
- 已打开的 icon 要有明确的选中态；再点一次收起。

### 2. 集成运行画布

`AgRunCanvas.tsx` 已经是独立的运行态画布，弹窗 header 上有「编排 / 运行」切换。
现在运行画布的信息还很薄——只有对象节点和批量预览。要把它做成真正能看的运行态：

- 每个对象一组节点：**提示词 / 生成的图片 / 引用的资产**，参考「无限画布」
  （`features/storyboard/` 下的 GenerationFlowMap）的节点表现。
- 复用无限画布的连线风格（虚线贝塞尔）和分组盒子，不要另造一套。
- 运行中/成功/失败三态在节点上要看得出来。

### 3. 属性面板只跟随画布选中

`AgInspector.tsx` 顶部现在有一排 tab（开始 / 前置 / 运行 / 输出产物 / next），
点 tab 能切换显示哪一段。**把这排 tab 整个去掉。**

- 唯一的选中入口是**点画布上的节点**：点哪个节点，右边就显示哪个节点的属性。
- 没选中任何节点时显示占位文案（现有的「点画布上的节点看它的属性。」保留）。
- 面板顶部的折叠按钮 `›` 保留，已经能用。

### 顺手补两个数据（后端已上线，前端是静态表没跟上）

`nodeTypes.ts` 的 `BATCH_OVER`（输出产物段的「遍历对象」下拉）加两项：

```ts
{ value: 'ctx.scene_groups_empty', label: '本章场景组（空场景图）' },
{ value: 'ctx.scene_groups_sheet', label: '本章场景组（站位图）' },
```

后端 `/api/agents/assets` 的 `batch_sources` 本来就返回全量清单——更好的做法是
把 `BATCH_OVER` 改成从 assets 动态取，静态表只做兜底。

另外 `run-unit` 请求体新增了 `params: Record<string, string|number>`（自由入参），
响应新增 `run_id`；历史记录接口 `GET /api/agents/runs`、`GET /api/agents/runs/{id}`
可以直接喂运行画布。

### 硬约束

- 只在本地改，**不要 push**。
- 前端硬规则见 `frontend/.claude/CLAUDE.md`：单文件 ≤200 行、渲染里禁 emoji
  （用 `<Icon name="…" />`）、`title` ≤5 字、CSS 分层（组件样式只能以同级或更高
  特异度覆盖 `styles/base.css`）。
- 改完必须跑 `npx tsc -b` 和 `npm run lint`；动了样式再跑 `npm run build`。
- 保持横向流，不要改成竖向。

### 别碰（我这边同期在改，会冲突）

- `backend/` 全部
- `frontend/src/api.ts` 里 `runUnit` / `previewBatch` 的入参类型
- `frontend/src/features/admin/agentflow/nodeTypes.ts` 的 `ParamDecl` / `PARAM_KINDS`
- `frontend/src/features/admin/agentflow/AgParams.tsx`

---

## 现状（背景，不用照做）

画布上一张卡 = 一个最小集，卡内五段：开始 → 前置 → 运行 → 输出产物 → next。
最小集之间靠「前置段引用别的编排」互相嵌套。相关文件：

| 文件 | 作用 |
|---|---|
| `AgentFlowAdmin.tsx` | 卡片列表 + 弹窗容器，持有 `mode`（编排/运行）与运行上下文 |
| `agentflow/AgentCanvas.tsx` | 编排画布 |
| `agentflow/AgRunCanvas.tsx` | 运行画布（要扩充的） |
| `agentflow/AgRail.tsx` | 左侧竖排 icon（要移到右边的） |
| `agentflow/AgInspector.tsx` | 右侧属性面板（要去 tab 的） |
| `agentflow/AgRunBar.tsx` | 运行浮窗里的上下文选择 |
| `agentflow/viewModel.ts` | 由 config 确定性生成分组盒子 + 节点 + 连线 |
| `agentflow/agentflow.css` | 本域样式 |

两个已经踩过的坑，改的时候别踩回去：

- **不要用 `fitView`**。弹窗是打开后才定尺寸的，`fitView` 会压到 minZoom 0.5。
  现在是自己算视口调 `setViewport`。
- **节点上要显式给 `handles`**。窗格不可见时 ResizeObserver 不触发，React Flow
  测不到节点尺寸，连线就一根都不画。
