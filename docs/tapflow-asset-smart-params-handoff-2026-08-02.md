# TapFlow 资产类型、智能参数与子工作流交接

日期：2026-08-02  
状态：进行中。本文是下一次 Codex 对话的唯一交接入口；开始工作前仍需查看当前 `git status` 和 `git diff`，不得覆盖工作区已有修改。

## 一、用户最终目标

TapFlow 不再依赖“执行体”或把场景、分镜等业务对象当成唯一生成目标。工作流统一使用：

- `asset_type`：声明要生产、读取或引用什么资产；
- `target_ref`：声明资产关联的业务对象，例如 `element:166`、`content_node:819`；
- `output_slot`：声明节点产物在该业务对象上的语义槽位；没有业务落点时只进入项目素材库；
- 资产 ID、附件 ID、工作流产物 ID和业务对象 ID必须保持各自命名空间，不把裸数字猜成 `shot_id`。

一个资产类型代表一份稳定的生产与读写合同，可以注册多个画布入口。资产类型 code 不限制一段、三段或五段，只要求完整 code 全局唯一且不能根据 code 分段推断行为。

## 二、智能参数的新要求

运行模式只让用户操作一张“智能参数”卡片。筛选关系应为：

```text
项目
  → 资产类型
    → 该资产类型允许的业务范围/对象
      → 卷/章/分镜/场景/角色/道具/素材等必要的级联条件
```

项目下面必须新增“资产类型”。资产类型数据来自后端 `/api/assets/types`，前端不能维护场景、角色、道具的业务分支表。

选择结束后，智能参数卡片输出最小输入：

```json
{
  "project_id": 25,
  "asset_type": "pro.shot.keyframe",
  "target_ref": "content_node:819"
}
```

后端根据资产类型的 `target_ref_kind`、`target_content_kind` 和 `context_bindings` 补全 `shot_id`、`chapter_id`、`project_id` 等旧动作仍需要的兼容字段。下游节点、LLM、提示词技能、知识库、参考图和子工作流不得要求用户重复选择这些参数。

资产类型决定可选对象与存取合同，但不能把资产类型等同于某个固定画布 slug。画布是该合同的一个入口。

## 三、子工作流的强制架构原则

父工作流绝对不能重新实现一次子工作流的数据查询、提示词、技能或生成逻辑。

父级 subflow 节点只保存：

- 子工作流 `slug`、`version`；
- 父输入到子输入的最小映射；
- 父工作流为何选择这个子流程的路由条件；
- 子工作流输出合同到父级下游的映射。

正确调用链：

```text
父级智能参数
  → subflow 输入映射
    → 后端递归执行子工作流 preview/run
      → 子工作流自己查询资产、装配提示词、运行技能和生成节点
        → 子工作流 output_schema / end outputs
          → 父级消费输出
```

允许把子工作流节点显示在父画布上，但只能生成“运行态只读投影”，不能复制并保存进父图。投影节点应使用组合身份，例如：

```text
父subflow节点ID::子节点key::iteration
```

投影节点属性读取子工作流版本，状态读取对应 child run / child node run，媒体读取子工作流真实输出。子工作流提示词或技能更新后，父画布应自动反映所引用版本，而不是同步两份配置。

循环同样只是一种统一的 `aggregate/many` 状态和连线标签，不是另一套节点类型。真实 loop 与多产物 subflow 使用同一判断、同一 SVG、同一右侧连线位置。

## 四、当前已经实现的内容

- 后端代码定义的资产类型注册表位于 `backend/app/assets/`，每个内置类型独立 Python 文件。
- `AssetType` 已包含 `media_kind`、`tags`、`subject_kind`、`operations`、`target_ref_kind`、`target_content_kind`、`context_bindings` 等合同字段。
- 资产类型查询 API 位于 `backend/app/api/assets.py`。
- `backend/app/services/workflow.py` 已实现画布资产类型识别、输入合同投影和 `target_ref` 上下文补全。
- `pro.shot.keyframe` 已声明目标为 `content_node:shot`；分镜关键帧画布不应再接受章节 ID。
- 多要素工作流：`multi-element-smart-generation`，定义于 `backend/sql/80_multi_element_smart_generation_canvas.sql`。
- 分镜关键帧工作流：`shot-keyframe-canvas`，通过 `dynamic_assets` subflow 引用多要素工作流。
- 场景要素路由到 `pro.scene.sheet` / `scene-sheet-canvas`；尚无专属流程的角色、道具等暂时路由到 `com.image`。
- `preview_workflow()` 已开始递归预检 subflow；前端 `useTapflowRun.ts` 会把 `loop.aggregate` 的数组结果投影成运行态资源节点，空结果也会建立“等待查询关联资源”占位节点。
- 循环 SVG 已统一放在右侧连线位置，引用的多产物 subflow 仍保持原节点视觉类型。
- 已删除分镜关键帧默认画布中的“额外参考资产”节点；用户可自由添加普通图片节点。
- 新增通用只读资产解析器 `backend/app/assets/reader.py`。读取顺序为：精确类型工作流产物 → 同业务对象兼容媒体产物 → 旧业务表 meta → 附件。
- `asset.route_related_elements` 已在 descriptor 中补充 `url` 与 `existing_asset`。最近一次使用项目 25、`content_node:819` 预检得到 9 个 descriptor，9 个均带 URL。
- 最近一次回归：17 项后端测试通过，`compileall` 通过；前端此前构建通过。

## 五、必须继续完成的事项

- [ ] 智能参数卡片在“项目”下新增“资产类型”，并完成逐级筛选。
- [ ] 选择资产类型后，根据后端合同动态决定后续选择器；禁止在前端写 `if scene/character/prop/shot` 业务判断。
- [ ] 智能参数的最小选择结果必须真正进入 `startInputs()`、preview 和 run 请求。
- [ ] 后端以 `asset_type + target_ref` 补齐下游真实参数，并保证所有节点和子工作流收到同一份上下文。
- [ ] 把 subflow 预检、运行、输出读取收敛为统一机制；父工作流不得再次调用子工作流内部的资产查询工具。
- [ ] 实现通用的子工作流运行态投影器。需要显示内部节点时从子图和 child runs 映射，不能复制节点到父图。
- [ ] 验证分镜关键帧画布中 9 个动态资源节点实际显示图片。API 已返回 URL，但本轮尚未完成刷新后的 UI 验收。
- [ ] 检查浏览器网络和卡片 `src`，确认没有把 OSS URL丢掉或被旧端口代理覆盖。
- [ ] 检查多要素循环的落库目标。每次 iteration 必须使用 descriptor 自己的 `target_ref`；不能把外层分镜 `target_ref` 写成角色、场景、道具产物的 target。
- [ ] 对 `workflow_artifacts` 做端到端断言：`target_kind`、`target_id`、`asset_type`、`role`、`variant`、`attachment_id`、provenance 的 workflow/run/node/iteration 全部正确。
- [ ] 验证同类型已有资产能够查询并复用；缺少资产时节点显示占位并在真正运行后替换为媒体结果。
- [ ] 验证两个正式工作流的每一个节点：单场景生成、分镜关键帧生成。不得丢失 LLM 提示词技能、知识库、工具、参考图、QC 和输出槽位。
- [ ] 进行真实端到端出图，允许使用任意本地测试项目和素材；不删除测试结果。
- [ ] 更新 `docs/asset-type-management-checklist-2026-08-02.md` 的完成状态，不能把只有单元测试的项目标记为端到端完成。

## 六、重点检查文件

后端：

- `backend/app/assets/base.py`
- `backend/app/assets/registry.py`
- `backend/app/assets/reader.py`
- `backend/app/api/assets.py`
- `backend/app/services/workflow.py`
- `backend/app/services/workflow_actions.py`
- `backend/app/services/resource_refs.py`
- `backend/sql/80_multi_element_smart_generation_canvas.sql`
- `backend/sql/81_workflow_shot_keyframe_smart_dynamic_assets.sql`

前端：

- `frontend/src/features/tapflow/TapflowFixedParamCard.tsx`
- `frontend/src/features/tapflow/TapflowRunPanel.tsx`
- `frontend/src/features/tapflow/TapflowNode.tsx`
- `frontend/src/features/tapflow/TapflowCanvas.tsx`
- `frontend/src/lib/tapflowGraphAdapter.ts`
- `frontend/src/lib/tapflowLoad.ts`
- `frontend/src/lib/useTapflowCtx.ts`
- `frontend/src/lib/useTapflowRun.ts`

## 七、验证入口与命令

上次隔离测试使用：

```text
前端：http://127.0.0.1:5173
当前工作区后端：http://127.0.0.1:8766
```

不要默认使用 `8765`、`5176` 或 `5178`，这些端口此前出现过旧实例。新对话开始后必须先检查监听进程和前端代理目标。

关键页面：

```text
http://127.0.0.1:5173/tapflow/window?slug=shot-keyframe-canvas&variant=studio
```

后端回归：

```powershell
cd D:\aiwok\agent-nc-workbanch\backend
.\.venv\Scripts\python.exe -m compileall -q app
.\.venv\Scripts\python.exe -m pytest -q tests/test_asset_type_registry.py tests/test_tapflow_keyframe_fanin.py tests/test_shot_production_canvas.py
```

前端回归：

```powershell
cd D:\aiwok\agent-nc-workbanch\frontend
npm run build
```

## 八、可直接粘贴给新对话的提示词

```text
请阅读并严格按照以下交接文档继续工作：
D:\aiwok\agent-nc-workbanch\docs\tapflow-asset-smart-params-handoff-2026-08-02.md

先检查当前 git status、git diff、端口监听和前端代理，保留工作区所有已有修改，不要 reset、checkout 或删除测试数据。

本次目标不是在父工作流重复补丁，而是完成通用架构：
1. 智能参数卡片实现“项目 → 资产类型 → 业务对象”的级联选择；资产类型来自后端注册表。
2. 用户只选择最小参数，后端通过 asset_type + target_ref 自动补全所有下游真实参数。
3. 父工作流不得重复子工作流的查询、提示词、技能和生成逻辑；subflow 必须递归 preview/run 并直接消费子工作流输出。
4. 如需在父画布展示子流程，只创建运行态只读投影，不能复制或持久化子节点。
5. 保证多产物 subflow 和真实 loop 使用同一种 aggregate 状态、同一个右侧循环图标和同一套展开机制。
6. 修完后对单场景生成、分镜关键帧生成做真实端到端出图与落库验证，逐节点检查提示词技能、知识库、工具、参考图、QC、附件、资产类型、业务目标、产物槽位和 provenance。
7. API 已经能为 content_node:819 返回 9 个带 URL 的动态 descriptor，但 UI 刷新后的图片显示尚未完成验收，请从这里继续。

先给出你对根因和架构边界的复述，然后直接实施，不要只写方案。完成与未完成项同步更新 docs 清单。
```

## 九、验收底线

以下任一情况出现都不能宣称完成：

- 父工作流存在一份与子工作流相同的查询或提示词逻辑；
- 选择资产类型后仍要求用户手填 `shot_id`、`chapter_id` 等兼容参数；
- 子工作流升级后必须人工同步父画布复制节点；
- 运行态卡片有名字但没有实际媒体 URL，且数据库明明存在对应资产；
- 循环产物错误落到外层分镜或项目对象上；
- 只验证 preview，没有真实运行和数据库断言；
- 为场景、角色、道具分别写前端专用分支而没有使用资产类型合同。
