# 编排节点 / Step 步骤 / 提示词一致性 · 全面调研（2026-07-31）

> 回答三个问题：
> ① 智能体编排里的节点是不是独立的工具/函数、能否互相引用？
> ② 旧的 step 几大步骤是不是也这样？
> ③ 为什么会不稳定——"角色生成的提示词调好了，分镜生成引用角色时却不一样"，是不是重复写了函数而不是复用？
>
> 结论先行：**执行层（Step/工具）是注册表驱动的、大体复用良好；不稳定的根子不在执行层，
> 而在"提示词与上下文装配层"——同一件事（角色是谁、参考图怎么介绍、缺不缺产物）
> 在 20+ 处各写了一份，且互相不一致。你的直觉是对的。**

---

## 一、问题①：编排节点是独立工具/函数吗？能互相引用吗？

**节点是数据库配置，不是代码函数；但节点执行时调用的底层能力是统一注册表里的独立函数，可以互相引用，且大多确实在复用。**

当前仓库里同时存在**两套编排引擎**（共用同一张 `workflows` 表，`sql/32_workflow_engine.sql:13`）：

| | 引擎 A：工作流 DAG | 引擎 B：智能体最小集（unit）——**产线实际在用的** |
|---|---|---|
| 解释器 | `services/workflow.py` | `services/agent_unit.py` |
| 图语义 | 多节点+边，拓扑排序 | **单节点**，全图 config 扁平合并（先到先得） |
| 节点类型 | start / end / action / task / subflow / loop（branch 声明未实现） | 只有 `unit`，五段配置：开始/前置/运行/输出产物/next |
| 存量 | 2 张（element-sheet / shot-prepare-elements） | ~30 张（a.\* / c.\* / q.\* / g.\*） |
| 入口 | `/api/workflows/{slug}/run` | `/api/agents/run-unit`、`/api/agents/autoflow` |

节点本身只是 JSONB 配置（`workflows.graph`）。真正干活的是三层**注册表**，节点按名字引用它们：

1. **统一工具注册表** `services/tools.py`（`specs()`/`invoke()`，`tools.py:142-191`）
   = 内置只读工具（db.schema/db.query）+ `workflow_actions.specs()`。
   被四方共用：DAG 的 action 节点（`workflow.py:239`）、unit 的前置取数（`agent_unit.py:234`）、
   规划引擎 tool-calling（`agent_runtime.py:198`）、管理台 HTTP（`api/tools.py:51`）。
2. **命名动作** `services/workflow_actions.py`（`@register`，`:26-46`）。
   绝大多数是**薄封装、真复用底层函数**：
   `shot.ensure_sheets` 直接调 `steps._ensure_element_sheets`（`workflow_actions.py:166-167`，注释明写"同包复用，不复制逻辑"）；
   `shot.reassemble_prompts` → `storyboard.assemble_shot_prompts`（`:202`）。
3. **Step 注册表** `services/flow.py:82-130`（`@register` 装饰器 + `STEPS` 字典），
   unit 的输出产物段配 `step=<kind>` 入队即引用。

**节点间能否互相调用？** 能：DAG 引擎有 `subflow` 节点（按 slug+版本嵌套，`workflow.py:333-359`）；
unit 靠前置段 `ref_flows`/`ref_each` 递归引用别的编排（`agent_unit.py:169-244`，防环 MAX_DEPTH=4）；
`autoflow.run_flow()` 是统一执行核，run-unit 现在就是它的直跑特例（`api/agents.py:135`）。

**引擎 B 的一个反直觉设计**：`merge_config` 把图里所有节点 config 扁平合并（`agent_unit.py:106-117`），
所以一张 unit 卡"多画几个节点"没有执行意义，只会互相污染配置——`sql/44` 的注释明确记录了这个坑。
批量/循环不是节点，是 `batch` 属性（`agent_batch.py:3-4`）。

## 二、问题②：旧的 step 几大步骤是不是也这样？

**是。旧链路同样是注册表驱动，不是复制粘贴的 if 链。**

- 框架：`flow.py` 定义 `Step` 基类（`missing_deps / before / run / next` 四钩子）+ `@register` 注册表；
  `worker.py:15` import steps 触发注册；`flow.run_task`（`flow.py:482-523`）统一驱动。
- 业务：`steps.py` 里 **20 个独立 Step 类**（19 个 v1 + `gen_keyframe_v2`）。
- 步骤间两种"边"：
  - **拉式硬依赖**：`missing_deps` 返回缺什么 → `enqueue_with_deps` 单事务递归建任务树（`flow.py:320-386`）。
    典型：`gen_video → gen_keyframe → gen_prompts → gen_shot_storyboard`。
  - **推式串链**：`Step.next` 里显式 `flow.enqueue`。典型：`breakdown_chapter → expand_shot_details → scene_blocking`。
- 复用做得对的地方（引用同一函数，勿动）：
  - `gen_keyframe_v2` / `gen_last_keyframe` **继承** KeyframeStep，只覆写 before/next，run 完全复用；
  - `assemble_shot_prompts` 被 `api/shots.py`、`steps.py`（两处）、`workflow_actions.py` 四方共用；
  - `assemble_element_sheet_prompt` 被手动端点（`api/projects.py:1909`）、自动前置（`steps.py:128`）、
    workflow action（`workflow_actions.py:76-78`）三方共用——**角色设定图的"生产"只有一份实现**；
  - `gen_element_profile`、`era_anchor`、`_names_match`、`production_canvas.step_payload` 等同理。

也就是说：**"角色生成"这个动作本身没有被重复实现**。不管从素材库手动点、
从首帧前置自动补、还是从编排跑，走的都是同一个 `assemble_element_sheet_prompt`。

## 三、问题③：不稳定的根因——装配层的重复实现

### 3.1 直接定位：分镜链路对"角色是谁"另有一套认知

你调好的角色生成提示词在 `element_profile.py:23-37`（`PROFILE_SYS`，产出
`身份称谓/年龄段/性别/身份/时代服饰/体貌/招牌动作/招牌眼神` 八个字段）和
`element_sheet.py:207-232`（把这些字段展开成"角色身份硬约束"段进设定图提示词）。

但分镜/首帧装配 `storyboard.assemble_shot_prompts` 对角色的**全部**认知只有三行
（[storyboard.py:1667-1669](../backend/app/services/storyboard.py:1667)）：

```python
desc_cn = e["brief"] or ""
if em.get("外貌提示词"):
    desc_cn = f"{desc_cn}（{em['外貌提示词']}）" if desc_cn else em["外貌提示词"]
```

**已核实：`storyboard.py` 全文对 `meta.profile` 零引用。** 两条链路唯一共享的是
`meta.外貌提示词` 这个**数据字段**，不是任何代码。所以：

- 改 `PROFILE_SYS` / 设定图提示词 → 只影响设定图那张图；
- 分镜里角色永远是"brief + 外貌标签"，档案里的身份称谓、招牌动作、年代锚一个字都进不去；
- 两边看起来"前置条件不一样"，因为**本来就是两份独立实现**。

### 3.2 重复实现清单（按危害排序）

#### 🔴 A. 角色上下文——同一件事至少 6 种写法

| # | 什么被重复了 | 各写一份的位置 | 不一致点 |
|---|---|---|---|
| A1 | 角色身份层装配 | `element_sheet.py:207-232` vs `storyboard.py:1646-1737`（内联，不可复用） | 前者用 profile 八字段，后者只用 brief+外貌 |
| A2 | 面部词表 | `element_sheet._FACE_TERMS`(22 中文词) vs `storyboard._FACE_WORDS`(13)+`_FACE_WORDS_EN`(17) | 前者含发型类词，后者不含 → 远景剔词与真人卡剔词不一致 |
| A3 | 年代/世界观锚 | `element_profile.era_anchor:56-64` vs `element_sheet._world_clause:124-133` | 兜底逻辑与措辞不同；**分镜链路两个都不用** |
| A4 | 角色名册喂 LLM | `storyboard.py:960`、`scene_blocking.py:283`、`shot_elements.py:91-96`、`steps.py:542-547` | 截断 40/40/30 字三种，是否带形态标签不一 |
| A5 | 角色简介行 | `trailer.py:96-99` vs `api/projects.py:511-514` | 逐字相同的两份，LIMIT 6 vs 5 |
| A6 | "取角色列表"SQL | 全仓 **24 处**独立 SELECT（见附录 A） | 过滤条件、字段、上限各不相同 |

#### 🔴 B. 取设定图：变体感知 vs 非变体感知两套并存

多形态角色（如"乞丐↔皇后"）按剧情选形态的正确实现在 `element_variants.pick_variant`，
但只有两处在用：

| 用法 | 位置 | 多形态 |
|---|---|---|
| ✅ `pick_variant` 影子覆盖 | `storyboard.py:1646-1651`（逐镜装配）、`steps.py:105-107`（前置补图） | 支持 |
| ❌ 顶层直读 `sheet_url` | `overview_grid.py:166-169`、`steps.py:1208-1211`（场景组图）、`steps.py:1832-1835`（首帧组图）、`scene_blocking.py:346-356`、`api/shots.py:330-332`、`trailer.py:65-66`、`agent_batch.py` 等 | 恒取主形态 |

后果：同一角色在逐镜首帧拿本镜形态图，宫格/组图/站位图却拿主形态图——**图源本身就不一致**。

#### 🔴 C. 参考图"图片N是…"引用句：两张映射表 + 5 份近似句式

- kind 标注不一致：装配期标 `character_style`（`storyboard.py:1687-1689`），
  但 `overview_grid.py:169`、`steps.py:1206`、`scene_blocking.py:353` 保留 `character`。
- 中文映射表有**两张**：`steps._REF_KIND_CN:200-207`（"角色"/默认"场景"）vs
  `media.py:482-486`（"备案角色身份"/"角色服化道造型"），句式与附加规则句都不同。
  → **同一批参考图，生图路径与视频路径拿到不同的介绍语义。**
  `steps.py:197-199` 的注释本身就记录过"两处引用句漏配落到默认『场景』"的事故。
- 引用句近似副本 5 份：`steps.py:637 / 671 / 1052 / 1507-1514 / 1653-1660` + `media.py:464-507`。

#### 🟡 D. 编排层的"第三份提示词"：charter 与代码常量各说各话

`sql/39_agent_unit_enrich.sql` 给每张编排 seed 的 charter（如 `a.chapter-breakdown` 的
"你是分镜导演，第一轮先拆出本章的分镜骨架"）与代码里真正生效的
`DIRECTOR_RULES`/`_STORYBOARD_COARSE_FORMAT`（`storyboard.py:28/65`）**是独立的两份**。
`sql/44` 已经承认这一点：把 `a.shot-keyframe` 的 `task` 置空，理由是"真实提示词由
`gen_keyframe.before` 重装配产出，编排层自由 LLM 白花钱且必被覆盖"。

⚠️ 更隐蔽的漂移面：`a.character-sheet` 等编排行的 `task` 字段（真正喂模型的自然语言）
**只存在数据库里**，仓库 SQL 全是 `UPDATE ... WHERE slug=`，代码 review 覆盖不到它。
且 `load_unit` 取**最新版不看 status**（`agent_unit.py:120-126`）——画布上改草稿即时生效于所有引用方。

#### 🟡 E. 机制层的并行实现（有意"并存"，但仍是漂移源）

| 什么 | 两份/多份的位置 | 风险 |
|---|---|---|
| 镜级守卫链 | v1 硬编码 `_shot_gen_before:307-334` vs v2 五个守卫工具+`g.shot-*` 编排（`sql/46`） | 底层函数复用，但**顺序/开关的表达**两份；改 v1 不改 seed 就漂移 |
| 守卫下标映射 | `production_canvas._CHAIN_NODES/_CHAIN_ORDER:92-135` 用 `guard:0..7` 数字下标 | 改 `before_notes` 增删/换序必须手工同步两张表（代码注释自警） |
| 缺才跑判据 | `agent_unit.has_artifact:37-55`、`agent_batch.SOURCES` 各源内嵌列、`workflow._already_done:306-314`、`workflow_actions.element_sheet_exists` 共 4 处 | `agent_next.py:63-64` 已点破：writes 键与批量判据对不上 → 批量重跑覆盖 |
| 占位符模板 | `agent_runtime.fill:268`、`agent_unit._subst:145`、`workflow._resolve:198` | 三套语法相近语义不同 |
| 角色在场判定 | 装配期 `_chars_present:474-486`（剧本文字+代词兜底） vs 生成期 `_drop_unmentioned_chars`（`steps.py:257-273`，判最终提示词全文） | 两层判据可能给出相反答案；且只闸 `character`，`character_style` 逃逸 |
| 参考图装配 15 行 | `api/projects.py:1918-1943` vs `workflow_actions.py:90-104` 逐行复制 | 改一处忘另一处 |
| 出图+落附件+回写 | `steps.py:128-153` / `steps.py:2065-2109` / `api/projects.py:1894-1904` 三份 | 同上 |
| 画风锚词 SQL | `api/projects.py:432`、`:534`、`trailer.py:43-49` 三份逐字复制（`knowledge.get_block` 现成没人用） | 同上 |
| 本镜要素取法 | `storyboard.py:1582-1596`（meta.element_ids）/ `shot_elements.py:86-89`（全项目）/ `workflow_actions.py:127-130`（element_appearances JOIN） | 三者返回集合可能不一致 |
| 母带 `_prompt_context` | `episode_adaptive.py:128-155` vs `episode_adaptive_duration.py:51-84` 近乎逐字 | 措辞微差已发生 |
| 时长夹紧 | `storyboard.py:553/581/656/517/1085/1217` 各自 `max(4,min(...))`，上限 10/8/15 不一 | 行为不一致 |
| 死代码 | `steps._sheet_source:45`（已无调用方，正确版在 `element_variants.sheet_source`） | 误导后来人 |

### 3.3 提示词到底存在几个地方（为什么"改了A处B处没变"）

| 层 | 存哪 | 改动影响面 |
|---|---|---|
| ① 编排 charter/task | `workflows.graph`（数据库，仓库不可见） | 单张编排私有；对配了 step 的编排**基本是装饰**（被 Step.before 重装配覆盖） |
| ② 技能包 | `skill_packages.skill_md` | 共享——legacy-skill-182 被 3 张编排同时引用，改一动三 |
| ③ 知识库 | `kb_entries`（prompt_block/skill/负面清单） | 共享，项目级可覆盖全局；`_director_skill` 先查库、查不到才回退代码常量 |
| ④ 数字员工章程 | `agents.charter` | 项目内共享 |
| ⑤ 代码常量 | `storyboard.py`/`scene_blocking.py`/`element_profile.py`/`pipeline.py` 等的大段硬编码 | **真正干活的主体**，全局共享，改一次全链变 |

"不稳定"的完整机理：**你在某一层调了提示词，但目标链路读的是另一层/另一份拷贝**；
再叠加 B（图源不一致）、C（引用句不一致）、E（在场判定/缺才跑判据不一致），
同一个角色在不同环节呈现出的前置条件自然对不上。

---

## 四、收敛建议（按投入产出排序，均为最小手术，不改行为语义）

1. **P0 · 角色上下文单一来源**：新建 `services/character_context.py`，把
   `element_sheet.py:30-90` 的 `_character_age_gender / _character_action_gaze /
   _character_appellations` 三个 helper 与 `era_anchor` 收进去；
   `element_sheet` 与 `storyboard.assemble_shot_prompts` 同时引用，
   分镜侧按景别决定注入粒度（远景只注体貌轮廓，近景注全量）。
   这一刀直接治"角色生成调好了、分镜引用不一样"。
2. **P0 · 取设定图统一走 `element_variants.pick_variant`**：把 3.2-B 表里 ❌ 的 7+ 处
   顶层直读改为调同一函数（无形态时行为不变，纯收敛）。
3. **P1 · 参考图引用句单一来源**：合并 `steps._REF_KIND_CN` 与 `media.py` 的映射表，
   5 份"图片N是…"句式收敛为一个 `ref_intro()`；同时统一 kind 标注（都用 `character_style`）。
4. **P1 · 缺才跑判据对表**：把 `agent_batch.SOURCES` 的 has_artifact 谓词与
   `agent_unit._ARTIFACT_SQL` 白名单收敛成一张声明表，`writes` 键校验用同一来源。
5. **P2 · 编排 task 入库入仓**：把数据库里各编排的 `task` 全量导出成 seed SQL 纳入版本管理，
   并决策 `load_unit` 是否改为只取 published（清单 §3.6-3 已列为待决策）。
6. **P2 · 清杂**：删死代码 `steps._sheet_source`；画风锚词三处改用 `knowledge.get_block`；
   母带两份 `_prompt_context` 合一；时长夹紧常量统一。

---

## 五、收敛落地记录（2026-07-31 同日完成）

「单一实现」已写入 CLAUDE.md 成为工程红线（含权威入口表）。本轮已收敛（82 个后端测试全过）：

1. **角色上下文单一来源** `services/character_context.py`（新增）：
   年龄性别/招牌表演/身份称谓 helper 从 element_sheet 移入；`era_anchor` 从 element_profile
   移入（原路径再导出兼容）；`world_clause` 同源合并；面部词表收敛为 FACE_TERMS+HAIR_TERMS
   按用途组合（真人卡剔发型、远景不剔——两表差异是有语义的，不粗暴合并）；
   名册行 `roster_line`/`roster_inline` 两种格式各一份。
   **分镜身份层改走 `identity_desc`**（[storyboard.py](../backend/app/services/storyboard.py) 装配处）：
   档案的年龄性别/身份称谓现在会进分镜提示词——"角色调好了分镜对不上"的病根修复。
   招牌动作/眼神有意不注入（逐镜动作由剧本决定）。
2. **取设定图统一走 `element_variants.effective_meta`**（新增唯一入口）：
   storyboard 逐镜、steps 首帧组图/场景组图 fresh refs、scene_blocking 站位、overview_grid
   宫格全部改走；各按本镜提示词/组剧本/章剧本作选形态语料。项目级参考池（预告片/视觉锚点/
   封面）无语料，顶层镜像=主形态是设计语义，保留直读（已在 CLAUDE.md 标注为唯一例外）。
3. **参考图引用句单一实现 `media.ref_intro_line`**：6 份「图片N是…」副本与两张 kind 映射表
   收敛为一张 `REF_KIND_CN`（+视频层 `REF_KIND_CN_VIDEO` 身份/造型细分叠加），
   steps 5 处 + media 视频路径全部改走；`_REF_KIND_CN`/`_ref_kind_cn` 已删。
4. **缺才跑判据单一声明**：`agent_batch._artifact_cols` 由同一字段声明派生判据列+url 列；
   每个遍历源标注对应 `writes` 落点；`writes_mismatch()` 校验接入 `run_unit`（配了 batch+writes
   不同源时告警）。
5. **清杂**：删死代码 `steps._sheet_source`；画风锚词三份 SQL 收敛为 `knowledge.style_anchor`；
   母带两份 `_prompt_context` 收敛为 `episode_flash.prompt_context`（取后期定稿措辞，
   连续性一句按模式参数化）；trailer/projects 两份角色简介行收敛为 `roster_inline`。

**缓办项也已全部落地（2026-07-31 二轮，按推荐方案执行）**：
6. **时长夹紧单一声明**：`storyboard.clamp_shot_seconds` + 具名常量
   （SHOT_MIN_S=4 / SHOT_DECLARED_MAX_S=10 / SHOT_NO_CUTS_MAX_S=8 / SHOT_DIALOGUE_MAX_S=6 /
   时间轴路径=_PROVIDER_MAX_S=15），8 处散落的 `max(4,min(...))` 全部改走；
   **各上限值一个没改**（差异有语义：LLM 声明值不可信到 15、无切镜必须走 cuts 才配长时长）。
   media._post_ark_task 的 4-15 夹紧保留为供应商 API 边界防御，已注释区分。
7. **场景图版本链**：轮换逻辑抽为 `steps._rotate_group_image` 唯一实现，
   `_write_scene_image` 与 `SceneSheetsGroupStep.next` 共用；事务/FOR UPDATE 结构
   两处本就不同（单组 vs 批量 zip），保持不动。
8. **default_refs 消歧**：trailer 侧改名 `default_character_refs`（模块内唯一调用点已更新），
   与 episode_flash.default_refs（硬校验+备案身份绑定）不再同名，docstring 互相指认，勿合并。
9. **编排 task 入仓**：新增 `backend/scripts/dump_agent_units.py`（只读导出，非 seed），
   首份快照 [agent-units-snapshot-2026-07-31.md](agent-units-snapshot-2026-07-31.md)
   （34 unit + 3 DAG，含全部 charter/task/writes/inputs）。做成自动 seed 会在部署时
   冲掉画布手编，故选快照方案；`load_unit` 取最新版的语义维持现状（改 published-only
   会让现有 draft 编排全部失效）。

## 附录 A：全仓"取角色列表/拼角色上下文"的 24 个独立实现点

`storyboard.py:945-948,960`（粗拆名册）· `storyboard.py:1583-1605`（逐镜装配）·
`steps.py:542-547`（详细分镜校验）· `scene_blocking.py:280-283`（组内名册）·
`scene_blocking.py:345-359`（站位图）· `shot_elements.py:86-96`（镜级预检）·
`episode_flash.py:59-66`（身份锚，唯一另一处读 profile 的地方、只读 2 字段）·
`episode_flash.py:28-33` / `trailer.py:61-69`（同名 `default_refs` 两实现）·
`episode_adaptive.py:128-155` / `episode_adaptive_duration.py:51-84`（两份拷贝）·
`trailer.py:94-99` / `api/projects.py:510-514`（逐字相同两份）·
`project_visual_assets.py:41-50` · `voice_casting.py:293-302` / `:406-423` ·
`continuity_records.py:216-220` · `overview_grid.py:186-190` · `audio_precheck.py:102,144` ·
`agent_batch.py:25-46` · `workflow_actions.py:125-133` / `:250-274` ·
`api/projects.py:1092-1094` · `api/shots.py:329-332`

## 附录 B：正确复用（引用同一函数）的清单——收敛时勿动

`era_anchor`（3 处 import 同一个）· `gen_element_profile`（3 处）·
`assemble_element_sheet_prompt`（3 处）· `assemble_shot_prompts`（4 处）·
`steps._ensure_element_sheets`（workflow_actions 直接复用）·
`_names_match / _name_in_text`（3 处 import 自 storyboard）·
`production_canvas.step_payload`（画布与编排共用，sql/44 对齐成果）·
`prompt_fields.compose/split_edit_text`（4 处全复用）·
`gen_keyframe_v2 / gen_last_keyframe` 继承 KeyframeStep ·
统一工具注册表 `tools.py`（四方共用，模块头明言"不另起第二套"）
