# tapflow 后端设计(2026-07-31 重评估)

> 取代旧设计文档中「画布另建一套节点执行模型」的思路。结论:**执行模型不动,画布是投影**。
> 前端 tapflow 实现(`frontend/src/lib/tapflowData.ts` 的 TapNode 模型)是视觉/交互基准,
> 后端不为它重写引擎——两者之间由投影层(`config.ui` + 前端 adapter)对齐。

## 一、为什么不按前端节点模型重写后端

前端 TapNode 有 start/qc/link/gen/next 等类型、输入输出变量表、`{{节点.变量}}` 引用。
逐一对照后发现现有工作流解释器(`services/workflow.py`)已经**语义等价**:

| tapflow 前端概念 | 后端已有等价物 |
|---|---|
| 开始节点入参声明 | `workflows.input_schema` + start 节点 |
| `{{节点.变量}}` 输入引用 | 解释器 `_resolve` 的 `{{node.key}}` 模板 |
| 拖线即引用(多图连进生成节点) | `{{@in.url}}` 聚合 |
| 关联落库节点(link) | `action` 节点(element.upsert 等,写库 action) |
| 生成节点「引用最小集」 | `subflow` 节点引用原子工作流 / `task` 节点包 Step |
| 质检圆点 | 只读 `action`(element.sheet_exists 等) |
| 缺才跑 / 强制重跑 | `skip_if` + run 入参 `force=[节点id]` |
| next 回写与通知 | Step.next 落库(附件+meta 回写)——单一实现红线,不在画布层再写一份 |
| 运行态点亮/回放 | `workflow_runs` + `workflow_node_runs` |

重写一套「画布原生」引擎 = 生成/装配/落库全部第二实现,直接违反 CLAUDE.md 单一实现红线。

## 二、架构:画布 = 后端 graph 的投影

```
workflows.graph(执行真相,解释器只读执行语义)
  └─ 每个节点可带 config.ui(纯展示提示,解释器不读):
       { tap: start|link|gen|qc|text|next, title, w, h, hide_in_run, hide }
        ↓ GET /api/workflows/{slug}
frontend/src/lib/tapflowGraphAdapter.ts(投影唯一实现)
  ├─ graph.nodes + config.ui → TapNode[](种子坐标 x×2.1 适配 tapflow 宽卡)
  ├─ input_schema → 开始节点入参声明(project_id/scene_name→ctx 参数,*_url→图片)
  ├─ ui.hide 节点(end)不画并桥接连线;hide_in_run 运行态隐藏(visibleFlow)
  └─ startInputs():画布入参值 → run inputs(「25 · 标题」取前缀 id)
```

流程列表:`workflows` 表 `tags` 含 `canvas` 且 `status='published'` 的图,与本地演示假数据
(`TAPFLOWS`,保留作视觉对齐基准)并列展示,演示卡带「演示」角标。

## 三、运行协议(前端 useTapflowRun)

1. `POST /api/workflows/{slug}/run` `{mode:"async", inputs, force:[gen节点id…]}` → `run_id`
2. 轮询 `GET /runs/{run_id}` + `GET /runs/{run_id}/nodes`(2s):
   - node running → 节点「生成中」;done → 蓝勾 + outputs.sheet_url 上卡;
   - skipped → 勾 + skip_reason 进日志(缺才跑);failed → 红字错误。
3. run done → 整体 outputs 的 sheet_url 兜底回显到无产物的 gen 节点。
4. **预检**:入参齐了(600ms debounce)调 `POST /{slug}/preview`(零副作用)——
   `element.find` 替身探出已有 sheet_url/sheet_prompt/extra_refs,回显到画布
   (产物上卡、真实提示词进生成条)。「缺才跑」在跑之前就看得见。

注意:asyncpg 未注册 jsonb codec,`outputs/inputs` 到前端是 JSON 字符串,
adapter 的 `jsonbObj()` 统一解包。

## 四、生成质量 = 与既有链路逐字节一致(构造保证)

`scene-sheet-canvas` 的生成节点是 subflow 引用 `element-sheet`(33 号种子):
`element_sheet.prepare` action → **`assemble_element_sheet_prompt`(与项目页
「生成设定图」端点同一份唯一实现)** → `gen_element_sheet` Step。装配要素:

- 场景主体 = brief + 世界观/年代锚(`character_context.world_clause`)+ profile 场景特征(人群密度/时段/氛围)
- kb 版式块「场景设定图」+ 画风锚(`recall_blocks` 按 art_style)+ 通用质量词/负面词 + 项目偏好画师
- 双字段 user/anchor,手编冻结(`*_edited`)照常尊重
- 参考图 = `meta.extra_refs` − `sheet_ref_off` + 「沿用上一张」注入(与端点同一段逻辑,在 prepare action 里)
- 落库 = `ElementSheetStep.next`:`content_attachments`(element_id 挂靠)+ `meta.sheet_url` + 外貌指纹

素材库可见性零新增代码:`/api/projects/{id}/asset-library` 本来就把 element 附件列成
「要素设定图」组——画布产物与按钮产物是同一条落库路径。

## 四.5 画布节点形状(v4)

v1 只有 开始→关联→生成→质检 四个节点,画布上「场景是什么」「产物往哪写」全是黑盒。
v4(54 号种子)是当前形状:

```
开始(入参)
 → 关联·场景要素(link, element.upsert, ui.hide_in_run —— 运行态隐藏,照常执行)
 → 场景信息(text, element.get → ui.show=summary, 只读取数)
 → [提示词装配] (element_sheet.prepare, ui.hide + ui.feeds=gen —— 画布不画)
 → 场景设定图(gen, subflow element-sheet, 缺才跑)
 → 质检·设定图(qc, element.sheet_exists)
 → next · 回写与通知(end, ui.next 标出落点)
```

三条展示层约定(都写在 `config.ui`,解释器不读):

| 字段 | 语义 |
|---|---|
| `show: "<字段名>"` | 文本节点直出哪个输出字段(`element.get` → summary) |
| `hide_in_run: true` | 编排态可见、运行态隐藏,连线自动桥接(关联落库这类) |
| `hide: true` + `feeds: "<节点id>"` | 画布完全不画,但照常执行,产物送进目标图片节点的**生成条** |

`feeds` 是为「出图提示词属于图片本身」这条 tapflow 语义准备的:提示词与参考图不该在画布上
另占一张卡,而是选中图片炸开后,在下方生成条里(参考图缩略图 + 提示词 + 模型/参数)看到。
v3 曾把装配画成文本卡,一大段提示词占半屏,已废弃。

只读/幂等 action 在 preview 阶段就真执行——参数一填,场景信息与出图提示词立刻到位,
不必等运行。adapter 把 `show`/`feeds` 收集成映射交给 useTapflowRun,运行与预检共用同一套投影。

`element.get` 为此新增 `summary` 字段(要素的人类可读摘要:名称/简介/外貌/profile/形态/参考图数)。
只做取数排版,**不掺任何提示词工程**——出图提示词仍只有 `assemble_element_sheet_prompt` 一份。

## 五、本次落地清单

后端:`element.get` 补 `summary`(唯一实现的取数摘要)+ 52/53/54 号种子(画布 v2→v4);
引擎、API、既有 action 与落库路径均零改动。
前端(纯新增/扩展,演示假数据未动):
- `api.ts`:`runWorkflowAsync` / `previewWorkflow` / `workflowRun` + 类型
- `lib/tapflowGraphAdapter.ts`(新):graph→画布投影 / 入参映射 / jsonb 解包
- `lib/useTapflowRun.ts`(新):async run + 轮询点亮 + 预检回显(与 useTapflowSim 同签名)
- `lib/useTapflowCtx.ts`(新):真实项目/场景/角色/章镜候选(`/api/agents/context`)+ 项目设定卡
- `TapflowPage`:真实流程卡(canvas 标签)与演示卡并列
- `TapflowModal`:real 分流(真实 hook / 模拟 hook)、项目卡带出、自动预检
- `TapflowRunPanel`:真实 ctx 候选(项目下拉、场景 datalist 可手填新名);真实流程隐藏运行范围(整图执行)

## 六、后续(不在本次)

- 画布保存回写 graph(拖动坐标 → `POST /api/workflows`,种子用 DO NOTHING 防冲回)
- 真实流程的截段运行(range)——需要解释器支持从中间节点起跑
- 分镜关键帧画布流程(`flow-shot-keyframe` 演示的真实化):同一投影模式,
  引用 g.shot-* 守卫 action 链 + gen_keyframe_v2
