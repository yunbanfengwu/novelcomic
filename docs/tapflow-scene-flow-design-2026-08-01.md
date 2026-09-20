# tapflow 单场景生成：定稿设计与实现（2026-08-01）

前端草稿已定型，本文按草稿重写设计并记录后端实现。取代
[report-scene-flow-redesign](report-scene-flow-redesign-2026-08-01.md) 的方案部分（那份保留为决策过程）。
装配三层的原理见 [tapflow-node-assembly-design](tapflow-node-assembly-design-2026-08-01.md)。

## 一、画布形态（四节点）

```
开始（只定位：项目/章可空，场景必填）
 → 关联·场景要素（action element.upsert，运行态隐藏）
 → 场景介绍（llm，缺才跑；产物回写 element.brief）
 → 场景设定图（gen：三层装配 + 质检 + 出图，三合一）
 → next · 回写与通知（end）
```

两条定下来的原则：

- **开始节点只定位，不填内容。** 「场景说明」是产物不是入参（场景介绍节点生成）；
  参考图有正当来源（要素已有的 `extra_refs`、上游连进来的图片节点），不该手填。
- **装配 + 质检 + 出图对用户是一件事**（「给我出这张图」），拆成三张卡只会让画布
  变成流程图而不是创作台。

## 二、属性面板 ⇄ 运行的对应关系

| 面板配置 | 运行时干什么 |
|---|---|
| 系统提示词 charter | LLM 节点的 system 段（稳定、可复用） |
| 「+ 引用」/ 正文里 @ | 运行时才有值的动态上下文，**拼进 user 段**，不进 system |
| 技能 / 知识 / 工具 | `agent_runtime.assemble`：技能渐进披露、知识圈范围、工具给 schema |
| 缺才跑 | `skip_if` 探到产物就跳过（LLM 节点尤其重要，每跑一次都是真实模型调用） |
| 质检（技能/知识/时机/阈值/重试） | `_qc_prompt_loop` / `_qc_image_loop` |
| 生成条里的提示词 | **最终提示词**，装配后预填；改过 → `node_overrides.prompt` 整段覆盖 |
| 比例 / 画风 | 只读，来自开始节点的项目设定（后端本来就按项目算尺寸与画风块） |

### 生成条 = 最终提示词，不是指令层

一度做成「生成条写这次想强调什么」，是多余的一层。定稿与系统既有做法一致
（`meta.image_prompt`：装配写回、前端可编辑、改过打 `_edited` 冻结）：
装配结果预填 → 可改 → 改过就冻结，`node_overrides.prompt` 整段覆盖装配。

## 三、质检怎么接（三条踩出来的规矩）

**① 只判 user 段，不判 anchor 段。**
anchor 里本来就有画风库的 `cinematic, masterpiece, best quality` 词表，以及项目画风原文
（本项目是「飞龙有可信的生物结构与皮膜细节」）。拿判叙事的尺子去量它，轮轮不合格；
而 anchor 是系统锁死的，用户和模型都改不动，判了也没有出路。**能改的才判。**

**② 回退用「重构提示词」全文，不能拼问题清单。**
质检返回体里本来就有 `重构提示词` 字段（`_REVIEW_JSON_TAIL` 强制）。
把问题清单拼回提示词等于对着出图模型念质检意见——实测模型会把
「去掉龙族遗骸描述」当画面内容画进去。

**③ 判法来自技能，输出结构由代码强制。**
规则放 kb（`kind='skill'`, `agent_code='reviewer'`，项目级可覆盖全局），
`{合格,得分,问题,重构提示词}` 的契约由代码追加。技能只管「判什么」，
不管「怎么回话」——否则回退逻辑读不到结论。

阈值与重试次数不写进技能：同一套质检技能，角色卡要 85、场景图 75 就够，
那是**这条产线的策略**。

## 四、后端实现清单

| 位置 | 做了什么 |
|---|---|
| `element_sheet.element_prompt_layers` | 装配主体原样抽层（user/anchor/negative/hair），零副作用，预检可直接调 |
| `element_sheet.element_refs` | 参考图筛选唯一实现（收敛了端点与 workflow action 的两份拷贝） |
| `storyboard.review_by_skill` | 通用质检：复用 `_reviewer_system` + `_REVIEW_JSON_TAIL`，支持文本与视觉 |
| `workflow_actions.element.layers` | 把分层产物暴露给画布 |
| `workflow_actions.qc.review` | 质检执行体 |
| `workflow_actions.element.set_brief` | LLM 写的介绍回写 brief（具名动作，不往写库白名单塞自由 SQL） |
| `workflow.py` `type=llm` | 落 `agent_runtime.run_batch`；支持 skip_if 缺才跑 + write 具名回写 |
| `workflow.py` `type=gen` | 三层装配 + 上游类型化投影 + 质检 + 入队既有 Step + 产物直出 |
| `workflow.py` `_fill` | **句子里**的占位符替换（`_resolve` 只认整串是占位符的情况） |
| 种子 56 / 57 | v6 画布 + 场景设定图质检技能 |

### `_fill` 这个坑值得记一笔

`_resolve` 只在「整串就是一个占位符」时求值（那样才能保住 int/list 原类型）。
LLM 节点的 task 是句子——`项目 {{input.project_id}} 的场景「{{input.scene_name}}」`——
不填就把字面量发给模型。实测模型回「**因不知具体场景名，以『黄昏港口』为例**」，
写出来的介绍完全跑偏，但每个节点状态都是 done，从状态上看不出问题。

## 五、验证（2026-08-01，真实出图）

| 用例 | 结果 |
|---|---|
| A 新建场景「锈锚渔市·晾网栈桥二期」 | 建要素 198 → LLM 写介绍 93 字 → 回写 brief → 质检 2 轮 80 分通过 → 43s 出图 |
| B 已有场景「黄昏港口」(force 重出) | 介绍**缺才跑跳过**（用库里已有那份）→ 质检 2 轮通过 → 31s 出图 |
| 落库 | 附件 716 / 717，两个要素 `meta.sheet_url` 均已回写 |
| 素材库 | 两张都在「要素设定图」组，图片 200 / 1005KB、854KB |
| 数据安全 | 只增不删：黄昏港口原有的附件 419 仍在，force 重出只追加新行 |

## 六、未解决 / 已知限制

**1. 「无项目」出图这条路走不通（本次未做）。**
`content_elements.project_id` 与 `content_attachments.project_id` 都是 **NOT NULL**，
没有项目就既建不了要素、也挂不了附件——产物只能落 OSS + `gen_logs`，进不了素材库。
要支持需要产品决策：给自由素材一个默认项目，还是放宽约束。

**2. 场景 anchor 与「骨骸类场景」冲突（既有实现的缺陷，本次只记录）。**
`element_sheet` 的场景硬约束写死了 `no dragon, no monster`，而场景「龙骨峡谷」的设定
就是「峡谷中遍布龙族的遗骸」——**装配出来的提示词自相矛盾**，质检如实抓到并停链。
这是质检的价值体现，但根因在生产装配器里。修它要动 anchor 段（画风关键路径，
有逐字节对拍护着），建议单独一轮。

**3. 出图后质检（stage=image）只判不重出。**
钱已经花掉了，自动再花一遍不合适；给出结论与问题，是否重来交回给人。

**4. 引擎内部仍是串行等待子任务。**
单场景没问题，批量几十个场景会堵住 worker 槽。要真并发得改成「节点入队 + 工作流重入」，
表结构不用动（`workflow_node_runs` 已按 `(run_id,node_key,iteration)` 记断点）。
