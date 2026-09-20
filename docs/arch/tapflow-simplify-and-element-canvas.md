# Tapflow 收敛与素材库画布改造提案（2026-09-18，待评审）

> **TL;DR**：本文是三轮实测分析（画布生成条显示 `{{input.instruction}}` 原文、
> 系统层文本回显进输入框、"从角色进入应自动带入信息/一画布挂一组挂载点"的讨论）沉淀出的
> 改造提案。核心判断：**tapflow 的"编排层"是工程师参数合同思维，该砍；内部已具雏形的
> AI 自主层（autoContext）该扶正为唯一主路；生产护栏（skip_if/QC/provenance/回写）全部保留。**
> 三个方案：**A. gen 节点收敛为「一句需求 + 材料包 + 工具箱」；B. 素材库进入即"备料可见"；
> C. 角色整体画布（scope 入参 + loop 展开 + mount 组 + 自动布局）。**
> 第 8 节是给并行功能开发者的**冲突评估检查单**——本文目前只是提案，未落任何代码。

---

## 1. 背景与实测问题（2026-09-18 用户实测）

三个现象，全部定位到了代码：

### 1.1 生成条显示 `{{input.instruction}}` 模板原文

- 画布 `core-element-image-generation`（`backend/sql/96_core_element_image_generation_canvas.sql`
  第 89 行）gen 节点配置 `"instruction": "{{input.instruction}}"`——提示词的"用户需求层"
  是一个指向运行入参的占位符，不写死提示词主体（主体由 `assemble=element.layers` 运行时装配）。
- 前端打开画布时把 `cfg.instruction` **原文**投影成生成条预填值
  （`frontend/src/lib/tapflowGraphAdapter.ts` 第 259 行 `prompt: String(cfg.instruction ?? '')`），
  于是未运行时生成条显示的是模板字符串。
- 运行入参 `instruction`（补充要求）为可空项；为空时运行回显 `outputs.prompt` 为空串，
  前端不回填（`frontend/src/lib/useTapflowRun.ts` 第 566 行判空），生成条**一直保留模板原文**。

### 1.2 "系统层"文本整段回显进输入框

- 引擎注释写明设计意图（`backend/app/services/workflow.py` 第 1352–1354 行）：
  "系统层（实体叙事/画布上文/系统提示词/技能）由节点绑定隐式挂载……**不回显、不占用户的输入框**"。
- 但该承诺只在**配了 charter** 的分支兑现（`_write_prompt_by_charter`，第 1532 行：用文本模型
  把材料重写成纯出图提示词，生成条显示的才是干净结果）。而核心要素画布的 gen 节点**没有
  charter 字段**，走"装配器兜底"分支：`user = material; prompt = compose(user, anchor)`——
  **material 整段（【本次需求】+【画布上文】+要素叙事）直接成为最终提示词**，随
  `out["prompt"]` 落库，前端回填生成条（`useTapflowRun.ts` 第 566 行）。用户在炸开的输入框里
  看到整段"画布上文"，无法区分哪些是给自己的、哪些是给模型的。
- `【画布上文】`块由 `_canvas_context`（workflow.py 第 1058–1168 行）拼装：项目行/入参行/
  上游文本行，格式与实测截图逐行吻合。

### 1.3 占位符字面量进入最终提示词

- 用户点生成条上的"按需生成"是 **verbatim 语义**（`useTapflowRun.ts` 第 770–786 行注释：
  "一律照框里这段出图，不管改没改"）。生成条预填的模板原文 `"{{input.instruction}}"`
  被**原样**作为 `node_overrides[gen].prompt` 发回后端。
- 后端 override 优先级链（workflow.py 第 1355–1359 行）：`override.prompt` 非空即用，
  **跳过了 `_instruction` 的占位符解析**（第 633 行：整串占位符走 `_resolve`）→
  `【本次需求】{{input.instruction}}` 以字面量进入发给模型的材料。

### 1.4 复杂度量化

| 模块 | 规模 | 说明 |
|---|---|---|
| `backend/app/services/workflow.py` | 2214 行 | 引擎全部：调度、占位符、装配、QC、落库、mount、loop |
| `frontend/src/lib/useTapflowRun.ts` | 1219 行 | 运行编排：回填/冻结/覆盖/轮询 |
| `frontend/src/lib/tapflowGraphAdapter.ts` | 449 行 | 纯投影：后端 config ↔ 前端节点模型 |
| workflow.py 内"实测踩坑"注释 | 21 处 | 全是翻车后打的人肉规则补丁 |

仅"生成条里那句话"就叠了 **5 种语义**：预填模板 → 运行回填 → `edited` 手编冻结 →
`verbatim` 照发 → `rewrite` 重写。取值链 `override.prompt > override.instruction > cfg.instruction`；
占位符解析分整串（`_resolve`）/句中（`_fill`）/整串判定（`_FULL_TPL`）三套。

---

## 2. 诊断：把"复杂"拆成三层，分别对待

| 层 | 内容 | 处置 |
|---|---|---|
| **参数合同层** | `{{input.x}}`/`{{info.id}}`/`{{@in.url}}` 传参网、assemble.args/payload 配置、前端投影回填、override 优先级链 | **砍**（复杂度主体，"不 AI"的部分） |
| **AI 自主层** | `autoContext`（workflow.py `_write_prompt_by_charter` 内："上下文查询方式交给 AI 自主规划"）、`canvasAgent`、`tapflow_ai.readonly_tool_names()` 只读工具集 | **扶正为唯一主路** |
| **生产护栏层** | `skip_if` 缺才跑、出图前提示词质检、产物落库回写 + provenance、参考图 ≤4 合同、手编冻结 | **全部保留**——AI 输出不确定，这些确定性护栏比以前更重要 |

关键认知：引擎现在花两千行做的事，本质是**把一堆参数解析、拼装成一份"材料文本"（material）
再喂给模型**——参数网的终点不过是加工出一段人话。取数、组织、写提示词恰恰是模型最擅长的。
`_canvas_context` 的演进轨迹（无条件注入 → 连线拓扑即上下文 → 标注必须如实）证明：
**用规则逼近 AI 的判断，边际成本越来越高**。

---

## 3. 方案 A：gen 节点收敛为「一句需求 + 材料包 + 工具箱」（引擎主路）

### 3.1 目标形态

```
gen 节点 = 需求句（人写，一句话）+ 材料包（引擎备料）+ 只读工具箱（模型自主取用）
```

- **画布作者只写需求句**，不再配 `assemble.args`/`payload`/`{{input.x}}` 传参链；
- **引擎从"解析参数"改为"备料"**：把连线产物、项目档案、要素档案序列化成带标注的材料包
  （`_canvas_context` 这套**保留**——它是备料，不是参数）；
- **autoContext 从可选项扶正为默认**：模型拿材料包 + 只读工具自主写出图提示词；
  charter 从"系统提示词配置"退化为可选的风格指令段；
- **兜底拼串分支退役**：写不出提示词就报错，不悄悄降级成 `compose(user, anchor)`。
  两条路并存正是回显语义分裂（1.2）的根源；
- **占位符保留最小子集**：循环体 `{{__item__.prompt}}` 这类批处理场景确实需要确定性，
  保留；其余 `{{input.x}}`/`{{info.id}}` 传参链用"节点声明需要什么，引擎自动喂"替代。

### 3.2 生成条语义砍到两条

保留：
- **需求句**：可编辑，永远原样发送（不再有"预填模板原文"这种东西——需求句默认空）；
- **最终提示词**：AI 写的那份，可改后重出，`edited` 冻结语义保留。

删除：
- 预填 `cfg.instruction` 模板原文（tapflowGraphAdapter 第 259 行的投影）；
- `verbatim` 照发语义（其合理部分——"用户没改就直接发需求句"——由"需求句默认空 +
  原样发送空 = 不覆盖"自然覆盖）；
- `override.prompt` 与 `override.instruction` 的双键歧义（统一为"需求句"一个键）。

### 3.3 不改的清单（明确划出，防误伤）

- `skip_if`（缺才跑，省钱）、出图前/后质检环、`_qc_prompt_loop`；
- 产物落库回写（variants[].sheet_url、外貌指纹）与 provenance；
- 参考图两入口合一（`reference_images` ≤4、`_apply_refs`）；
- `{{__item__.*}}` 循环占位符与 loop 展开机制；
- mount 挂载点机制本体（`_mount_upstream`/`apply_mount_binding`）。

---

## 4. 方案 B：素材库"进入即备料、备料可见"

> 回答的问题："从角色点进画布，角色名称这些应该直接传入；是否需要先在系统管理里配置？"

**结论：不需要任何新的系统管理配置。** 角色数据（名称/叙事/外貌指纹/variants/现有设定图）
已全在 `content_elements`；入口已传引用（`ElementPreview.openElementImageTapflow` →
`inputs: { project_id, target_ref: "element:{id}", variant_id }`）；引擎已自动备料
（`assemble=element.layers`：user=要素叙事+画风锚、hair=角色发型发饰、refs=现有设定图）。

缺的不是数据链路，是**可见性**。要做三件事：

1. **info 节点显示档案摘要卡**：把节点标题/内容从 `{{info.name}}` 模板原文换成解析后的
   档案摘要（名称、要素类型、叙事摘要、造型变体列表、现有设定图缩略图）。用户一眼确认
   "信息真的带进来了"。
2. **gen 节点需求层默认"沿用要素档案"**：补充要求留空即可出图，角色名零输入
   （layers.name 已在材料里）。生成条上明示"未填写需求时按要素档案生成"。
3. **档案完整度检查**：info 节点检查叙事/外貌指纹是否为空；缺了在画布上提示
   "该要素档案缺 X，建议先补全"，或让写提示词的模型用只读工具现场查库补全（autoContext）。
   ——**缺档案的解法是补档案，不是加配置**。

全局性配置（画风库、质量锚、出图模型档位）已存在并经 `anchor` 段生效，维持现状。

---

## 5. 方案 C：角色整体画布（scope 入参 + loop 展开 + mount 组 + 自动布局）

> 回答的问题："一张画布是否允许传入一组挂载点？进入角色整体画布时，是否应该把该角色下
> 多个产物的生成节点加载在同一张画布内并自动布局？"

**结论：应该，且机制大半现成。** 不走"画布里静态摆 N 个 gen 节点各连各线"的老路
（那是参数网变本加厉：每加一种图类型就要改画布）。

### 5.1 现有积木盘点

| 需要的能力 | 现状 |
|---|---|
| 挂载点（归宿声明） | ✅ mount 节点已有：`config.target/subject(kind,id)+variant`；`_mount_upstream`（workflow.py 第 336 行，上游 BFS 找产物）+ `apply_mount_binding` 回写；"连到挂载点的产物才落"由 BFS 天然保证 |
| 按清单展开 N 个节点 | ✅ 引擎已有 loop 节点（workflow.py 第 10 行注释："循环不是原语，是展开"；第 918 行 `_run_loop_node`），`{{__item__}}` 引用每项；前端每个循环产物一张独立投影卡、可单独重跑（`useTapflowRun.runProjectedNode`） |
| 角色的变体/产物清单 | ✅ `variants_of()`（`element_variants.py` 第 50 行，惰性兼容：无 variants 合成默认形态）；`skip_if` 已按 variant 维度判"该形态已有设定图" |
| 画布自动布局 | ❌ 现在节点 position 是画布定义里写死的 x/y，无自动布局 |

### 5.2 目标形态：入参从"单图"扩成"作用域"

```
inputs: { project_id, target_ref: "element:{id}", scope: "variant" | "all", variant_id? }
```

- `scope=variant`（点某张图进来，现状）：聚焦单卡，行为与今天一致；
- `scope=all`（点角色整体进来）：引擎取该要素的变体清单 + **产物族清单**，
  loop 节点按清单展开 N 个 gen 子节点，每个自动挂一个 mount
  （`subject={kind:"element", id}`，`variant=item.id`），画布拓扑：
  `start → 素材信息 → loop[ gen×N 并排 ] → end`。

### 5.3 新设计点（唯一真正要新发明的）：产物族数据结构

variants（造型维度）有数据结构，但"三视图/表情包/场景动作"这类**图类型**目前没有统一定义。
提案：在要素类型定义（或 `content_elements.meta`）增加 `product_kinds` 清单：

```jsonc
// content_elements.meta 增量（示意）
{
  "variants": [ { "id": "default", "name": "主造型" }, { "id": "kitchen", "name": "厨房新手" } ],
  "product_kinds": [ { "id": "sheet", "name": "设定图" }, { "id": "turnaround", "name": "三视图" } ]
}
```

- 惰性兼容：无 `product_kinds` = 只有默认"设定图"，行为与今天一致（与 variants 的
  惰性兼容策略同款，存量要素零迁移）；
- `scope=all` 的展开清单 = variants × product_kinds（或笛卡尔积取子集，评审时定）；
- `skip_if`、mount 回写、provenance 全部按 `(element_id, variant_id, product_kind)` 三元组
  落位。

### 5.4 资产类型合同的历史包袱顺势化解

引擎有"一张画布恰好声明一个 asset_type"的合同（`_apply_asset_type_contract`），当初核心
要素画布为通吃角色/场景/道具只能不带合同（见 96 号 SQL 头注释）。挂载点自带
subject/kind 之后，**合同可以下沉到挂载点级**，"一画布通吃"不再是绕开合同的特例。

### 5.5 自动布局（前端）

循环体拓扑天然清晰（start → info → N 张循环卡 → end），按拓扑分层横向排开即可：
手写分层（按 `graph.edges` 求层级，同层均分 y）或引入 dagre。只对 `scope=all` 展开后的
动态卡生效，手摆的静态画布维持用户拖的位置不变。

### 5.6 风险与对策

| 风险 | 对策 |
|---|---|
| 一次展开 N 张图 = N 倍出图 + 质检成本 | 分批/`stop_after`（已有）+ 单卡强制重跑（`run_node` 已有）；默认只展开"缺"的（skip_if 语义天然支持） |
| 整组风格漂移 | loop 各轮 anchor 取**同一份**画风锚（引擎保证同源），不各拼各的 |
| 展开清单过大 | product_kinds 上限 + 展开前列清单让用户勾选 |
| 整组重跑 vs 单卡重跑语义 | 整组走 loop 重展开（skip_if 只补缺），单卡走 `run_node` 强制（两者并存，入口区分） |

---

## 6. 落地顺序与依赖

```
① 方案 B（备料可见）          ← 地基：信息带入与否看得见，C 的每张卡才有可信信息基座
② 方案 A（gen 收敛）          ← 主路；与 ① 可并行（一个改入口展示，一个改引擎）
③ 方案 C（角色整体画布）      ← 依赖 ①+②：展开的每张卡吃备料 + AI 自主主路
```

- ① 与 ② 交集成点：charter 分支成为唯一分支后，方案 B 的"备料可见"才能稳定展示
  （兜底分支退役前，回显语义仍是两套）；
- ③ 依赖 ②：loop 各轮的 gen 走统一主路，整组展开才有意义。

---

## 7. 改动面清单（评估冲突用）

### 7.1 会动的文件与机制

| 文件 / 机制 | 改什么 |
|---|---|
| `backend/app/services/workflow.py` | gen 执行段（`_run_gen_node`、`_instruction` 第 633 行、`_write_prompt_by_charter` 第 1532 行）：兜底分支退役、override 取值链简化为"需求句"单键 |
| `frontend/src/lib/tapflowGraphAdapter.ts` | 删 `base.gen.prompt` 预填模板投影（第 259 行）；info 节点投影档案摘要卡 |
| `frontend/src/lib/useTapflowRun.ts` | 发送语义重构：删 verbatim 照发；`node_overrides` 构造简化（第 740–800 行）；回填仅"AI 写的最终提示词" |
| `backend/sql/96_core_element_image_generation_canvas.sql` | 画布模板改版：需求句留空、去掉 `{{input.instruction}}`/`{{info.name}}` 展示型占位符、（C 阶段）加 loop+mount 组与 scope 入参 |
| `frontend/src/features/projects/ElementPreview.tsx` | 入口加 `scope`（单图 / 角色整体两个入口按钮） |
| `backend/app/services/element_variants.py` 或新文件 | 产物族 `product_kinds` 数据结构与惰性兼容读点 |
| 画布前端（tapflow 组件） | 自动布局；scope=all 的展开卡渲染 |

### 7.2 明确不动的（已在别处依赖）

- `services/flow.py` 前置→执行→next 管线（见 `docs/arch/generation-flow-guards.md`）；
- `steps.py` 的 `gen_element_sheet` 产线本体（落附件 + 回写 variants + 外貌指纹）；
- QC 环、provenance、`_apply_asset_type_contract`（仅从画布级下沉到挂载点级，机制保留）；
- loop/subflow/collect 机制、`{{__item__}}` 占位符；
- mount 回写链（`tapflow_ai.apply_mount_binding`）。

---

## 8. 给并行功能开发者的冲突评估检查单

如果你正在做以下任何一项，请对照评估是否与本提案冲突（本文未落代码，只求提前撞汇）：

1. **动生成条（prompt 编辑框）**：预填/回显/冻结/verbatim/rewrite 任一语义的改动——
   本提案会重写这套语义（3.2），请对齐；
2. **动 `node_overrides`**（`prompt`/`instruction`/`text`/`ref_nodes` 键）：取值链将收敛为
   单一"需求句"键，若你的功能依赖 `override.prompt` 与 `override.instruction` 的区分，需对齐；
3. **动素材库入口 / ElementPreview / 设定图画廊**：入口入参会加 `scope`，打开行为分支
   （4 与 5.2），请确认不冲突；
4. **动 mount / 归宿回写**：本提案只把资产类型合同下沉到挂载点级，回写链不动——
   若你在加挂载点新能力，请对齐 5.2 的 `(element_id, variant_id, product_kind)` 三元组；
5. **动 loop / 循环投影 / 画布自动布局**：方案 C 直接建在这上面，请对齐 5.2/5.4；
6. **在 `content_elements.meta` 上加新字段**：若与 `product_kinds` 命名或语义重叠（5.3），
   请提前撞汇，避免两套产物清单；
7. **动 `_canvas_context` / 画布上文格式**：本提案保留它并让它成为唯一备料口，
   若你在改上文标注/注入规则，请对齐 3.1。

任何一项命中，建议在本文档下追加一节"冲突结论"（谁改、先后、合并策略），再动代码。

---

## 9. 预期收益与代价

**收益**：
- workflow.py 的 gen 执行段、adapter 投影、override 优先级链三大块代码量预计砍近一半；
- 翻车面收窄：现在每加一种节点类型要同步三处语义（模板/投影/装配），收敛后只剩
  "备料 + 写提示词"一处；
- 用户侧：打开画布即见"带入了什么信息"，角色出图零输入，角色整体画布一张看全、自动布局。

**代价（如实）**：
- AI 自主 = 成本波动、质量波动、可复现性下降——对策不是退回参数网，而是保留全部护栏
  （QC/skip_if/冻结/provenance），并给写提示词模型的输出保留现有结构化兜底
  （主体名补头、画风关键词补尾，`_write_prompt_by_charter` 内已有实现）；
- 迁移期双格式并存：存量画布（含 `{{}}` 模板与 charter 配置）需要一段兼容读——
  兼容策略与 variants 的惰性兼容同款：读到旧格式按旧语义跑，不迁移存量数据。

---

## 10. 冲突结论（2026-09-18，智能规划链路执行方核对）

> 本节由「画布智能规划 + 对话联动」功能的开发者按第 8 节检查单逐项核对后追加。
> 结论先行：**提案对智能规划能力是辅助而非冲突**——AI 自主主路正是对话层 ACTION 协议
> （update_node_prompt / run_node）的同盟军；已按第 6 节顺序落地 ①② 的引擎主路与投影清理。

### 10.1 检查单逐项核对

| # | 检查项 | 结论 |
|---|---|---|
| 1 | 动生成条语义 | **已对齐**：update_node_prompt 动作写的是需求句（gen.prompt + edited），与 3.2 收敛后的唯一键一致；adapter 不再把 {{}} 模板原文投影成预填值（需求句默认空） |
| 2 | 动 node_overrides | **兼容**：动作只写 prompt 单键；后端取值链 override.prompt > override.instruction > cfg.instruction 原样保留（instruction 运行入参的补充要求继续生效），双键收敛不改键名 |
| 3 | 动素材库入口 | 未动 ElementPreview；scope 入参（方案 C）留待后续，入口行为不变 |
| 4 | 动 mount / 回写 | 未动 |
| 5 | 动 loop / 自动布局 | 未动（方案 C 本轮未落地） |
| 6 | content_elements.meta 加字段 | 未加 product_kinds（方案 C 阶段再做） |
| 7 | 动 _canvas_context | **原样保留**，并随 charter 分支扶正成为唯一备料口；对话侧前端 contextBuilder（画布节点清单摘要）与它职责不同（一个喂对话模型、一个喂提示词规划模型），两者并存 |

### 10.2 本次落地内容（对应第 3/4 节）

1. **提示词分析前置于出图/出视频**（_write_prompt_by_charter 改版）：
   - charter 为空的 gen 节点不再回落拼串（compose 兜底退役），改用内置默认规划员；
   - 规划模型输出【分析】+【提示词】两段：分析要点（1~3 条）随 outputs.prompt_analysis
     返回，前端 run 卡明细单列「提示词分析：…」行；【提示词】段成为最终提示词；
   - 模型调用失败或输出为空 → WorkflowError 如实上报，**不再悄悄降级成 material 拼串**；
   - 主体名补头 / 画风名补尾两个结构化兜底保留（第 9 节对策）。
2. **模板原文不进生成条**（tapflowGraphAdapter）：cfg.instruction 含 {{}} 时投影为空需求句；
   引擎侧占位符合同保留（运行入参 instruction 的补充要求仍生效）。
3. 生成条发送语义（verbatim/edited 冻结）**本轮未动**：需求句默认空后，verbatim 照发
   空串 = 不覆盖，自然收敛到提案 3.2 的两条语义，无需破坏性改动。

### 10.3 对智能规划能力的影响评估

- **辅助**：规划模型（引擎内）与对话规划（chat.py REPLY/PLAN）现在语义同源——
  对话 AI 改需求句 → 引擎规划员分析材料并写提示词 → 分析要点回流 run 卡，
  「AI 改需求 → 分析把关 → 生成」全链路可见、可对话追问。
- **无破坏**：ACTION 协议、meta.steps 落库、run_node 触发链路与本提案零交集；
  run 卡紧凑摘要样式（图1 定稿）与本次分析行兼容（分析行在展开明细内）。


### 10.4 实测结果（2026-09-18，提示词分析全链路）

| 线路 | run | 结果 |
|---|---|---|
| 出图（core-element-image-generation，直连 API） | #477 | 分析 3 条（需求可执行/材料支撑/类型匹配）+ 最终提示词融合要素叙事 + 图产出 |
| 出视频（trailer 画布，对话触发） | #478 | 思考过程「分析提示词合理性→生成」→ run_node → 分析 3 条进 run 卡明细 → mp4 产出 |
| 对话改需求 → 分析联动 | #479 | 对话改需求句「30秒横屏…」→ AI 判断合理 → update_node_prompt + run_node → 分析**引用新需求**（并如实指出材料缺口）→ 新视频产出 |

三线均验证：提示词规划失败如实报错（不再拼串降级）；主体名/画风名兜底保留。
