# tapflow 生成节点:提示词与参考图怎么组装(2026-08-01)

回答三个问题:①LLM/图片/视频/音频节点的提示词与参考如何装配 ②单场景设定图该怎么编排
③后端与运行引擎该怎么设计。基准是演示画布「分镜关键帧-单镜」(`FLOW_DATA`)表达的语义。

> **状态:已实现并端到端验证(2026-08-01)。** 走的是第四节的路线 B。
> 落地清单见第七节;验证记录见第八节。

## 一、系统里已经有三份装配器(不要写第四份)

| 装配器 | 适用 | user 段(叙事) | anchor 段(结构) | 参考图来源 |
|---|---|---|---|---|
| `element_sheet.assemble_element_sheet_prompt` | 要素设定图 | brief/外貌/profile + 世界观锚 | 版式块(角色/生物/场景/道具)+画风锚+质量词+偏好画师+防真人句 | `extra_refs` − `sheet_ref_off` + 沿用上一张 |
| `storyboard.assemble_shot_prompts` | 镜级首帧/视频/尾帧 | 画面/动作/对白/时间轴 + 角色身份层 + 场景描述 | 景别/角度/焦段/运镜/光效块 + 画风 + 质量词 | 要素设定图/空场景/站位图/接缝帧,带 `media.ref_intro_line` 引用句 |
| `asset_gen.assemble_asset_prompt` | 自由素材(无限画布/素材面板) | 用户提示词 +(开关)世界观锚 | (开关)画风块 + 质量词 | 调用方传入 |

三者形状完全一致:**`prompt_fields.compose(user, anchor)` 两段式**,块都出自
`knowledge`,引用句都出自 `media.ref_intro_line`。差别只在「各自怎么取数」。

所以 tapflow 生成节点要的不是新装配器,而是**「选哪份装配器 + 画布补哪些料」的机制**。

## 二、连线语义:同一根线,喂进不同的层

演示画布 `FLOW_DATA` 里连线不是一种意思,按 (上游类型 → 下游类型) 分流:

| 上游 → 下游 | 演示画布里的例子 | 语义 | 落到 payload |
|---|---|---|---|
| text/llm → image | `t3 → i1..i8` | 提示词素材 | user 段的「上游文本」子段,按连线序拼 |
| image/upload → image | `u1 → i2,i4,i5` | 参考图 | `reference_images`(≤4,带引用句) |
| image → video | `i2,i3,i4,i5 → v1` | **首帧/尾帧**,不是参考图 | `first_frame_url` / `last_frame_url` |
| text/llm → text/llm | `t1,t2 → t3` | 上下文素材 | LLM 的 task 上下文段 |
| audio → video | — | 参考声线 | `reference_audio` |
| ctx 入参 → 任意 | `start → *` | 业务实体定位 | project_id/element_id/shot_id,交给装配器取数 |

**必须点名的坑**:ARK Seedance I2V 只吃首帧(+可选尾帧)。演示画布把 4 张图连进一个
video 节点是**表意**的,真跑时中间两张进不了模型。引擎要显式取头尾,并把丢弃的那几张
**写进运行日志**——静默截断会让用户以为四张都参与了(CLAUDE.md「no silent caps」)。

同理图片参考图上限 4 张,超出要报,不要默默切片。

## 三、三层装配(任何生成节点的最终 payload)

```
prompt = compose(
  user   = [实体叙事段(装配器取数)]
         ⊕ [上游 text/llm 节点的产物]
         ⊕ [本节点生成条里的用户指令],      ← 越靠后解释权越强
  anchor = [装配器的结构段:版式 + 画风锚 + 质量词 + 负面词 + 偏好画师]
)
refs   = [装配器算出的实体参考图] + [上游图片节点产物]
         → 去重 → 按 kind 造「图片N是…」引用句 → 截到模型上限(超出要报)
```

三条不可协商的规矩:

1. **anchor 层永远来自 bind(最小集/知识库),不许在画布上手写。** 这是质量护栏,
   也是「画风库改了、版式升级了,存量画布自动跟上」的前提。
2. **user 层三个来源顺序固定**:实体取数 → 上游文本 → 用户指令。用户指令在最后,
   拥有最终解释权,但改不动 anchor。
3. **手编冻结照旧生效**:生成条里改过提示词就打 `*_edited`,下次装配不覆盖那段
   (`prompt_fields` 已有的语义,不另造)。

各模态的差异只在装配器内部,不外溢到画布:图片吃质量词、视频不吃(质量词是生图词表)、
视频要 duration/ratio、音频要参考声线与台词。

## 四、单场景设定图该怎么编排 —— 两条路线

### 路线 A(当前 v4):画布 = 编排既有原子能力

gen 节点 = `subflow(element-sheet)`,装配整体是黑盒。

- 优点:质量与项目页按钮 100% 同源,零风险,今天就能跑通(已验证出图落库)。
- 缺点:画布上**改不了任何一层**。用户在生成条里改了提示词也送不进去——
  `element_sheet.prepare` 会按实体重新装配一遍,把手改冲掉。生成条现在只能"看",不能"用"。

### 路线 B(已采纳并实现):通用生成节点 + 声明式装配

把 `assemble_element_sheet_prompt` **就地拆成三个可独立调用的段**(它自己也调这三段,
所以仍是一份实现,不是复制):

| 新 action | 产物 | 从哪来 |
|---|---|---|
| `context.element` | user 叙事段 | 现 `assemble` 里 subject 的那段 |
| `anchor.image` | anchor 结构段 | 现 `assemble` 里 blocks/prefs/防真人的那段 |
| `refs.element` | 实体参考图列表 | 现 `element_sheet.prepare` 里筛 extra_refs + 沿用上一张 |

画布的生成节点变成通用节点:

```json
{"id":"gen","type":"gen","config":{
  "modality":"image",
  "user":   ["{{context.text}}", "{{@in.text}}", "{{node.instruction}}"],
  "anchor": "{{anchor.text}}",
  "refs":   ["{{refs.items}}", "{{@in.url}}"],
  "write":  {"target":"element.sheet_url","element_id":"{{ensure.id}}"},
  "skip_if":{...}}}
```

- 画布上**能看见并修改**指令层(生成条就是它的编辑器),anchor 层仍锁死;
- 落库仍走同一条路(附件 + meta 回写),素材库不变;
- 换成角色/道具只是换 `context.*`/`anchor.*` 的参数,画布形状不变。

### 推荐:走 B,但分两步

**第一步是纯重构:拆层,行为必须逐字节不变。** 用现有场景做对拍——
同一 element_id 走「老 assemble」与「三段拼」,`assert` 提示词完全相同,再删老路。
**第二步才上通用 gen 节点。** 一步到位会让「质量回归」和「引擎新特性」混在一起,
出问题分不清是哪边。

## 五、运行引擎要补的五件事

现引擎节点类型 `start/value/action/task/subflow/loop/end`,缺:

1. **`gen` 节点(通用媒体生成)**:`modality=image|video|audio`,做三层装配 + 上游投影 +
   入队对应 Step + **产物 url 直接回 outputs**。
2. **`llm` 节点**:直接落到 `agent_runtime.run_batch`(charter/skills/folder_ids/tool_names
   全都现成,前端 `TapGenConfig` 的 `bind` 早就是按这个建模的)。今天画布上的"文本节点"
   只能是取数 action,不能真让模型写一段——分镜关键帧演示里的 `t3` 就是这类节点。
3. **task 节点产物直出**:`_run_task_node` 现在只返回 `{task_id}`,画布拿不到 url,
   v3/v4 是靠 `skip_if` 二次探绕过去的。应正规化:task 完成后按声明的产物列回读。
4. **`@in` 的类型化投影**:`{{@in.url}}` 现在无差别聚合,应按第二节的表按
   (上游类型→下游类型) 分流成 refs / first_frame / context / audio,并对丢弃项发日志。
5. **指令层进 run**:现在 run 只送 start 的 inputs,生成条里改的提示词送不进去。
   run 入参要支持 `node_overrides: {节点id: {instruction, refs...}}`。

第 3、4、5 是小改;第 1、2 是新增节点类型;真正要小心的只有第四节说的装配拆层。

## 六、与既有实现的边界(防止长第四份)

- 通用 `gen` 节点的**出图/出视频本体**必须复用 `media.generate_image` /
  `asset_gen.generate_video_asset` / 既有 Step,不新写供应商调用;
- 「用户提示词 + 可选项目锚 + 可选知识库」这套自由素材装配已有 `asset_gen.assemble_asset_prompt`
  ——通用 gen 节点在**没绑最小集**时就用它,不另写;
- 引用句只能是 `media.ref_intro_line`;画风锚只能是 `knowledge.style_anchor`;
  两段合成只能是 `prompt_fields.compose`。

## 七、落地清单(已实现)

**后端**
- `element_sheet.element_prompt_layers`(新):装配主体原样抽出,返回 user/anchor/negative/hair
  四层,**零副作用**(不写 meta),所以运行预检能直接调;
  `assemble_element_sheet_prompt` 变成它的薄封装(合成 + 落库),全站仍一份实现。
- `element_sheet.element_refs`(新):参考图筛选的唯一实现。**收敛掉一处真实漂移源**——
  此前 `api/projects.gen_element_sheet` 端点与 `workflow_actions.element_sheet_prepare`
  各写了一份一模一样的筛选(含「真人项目禁沿用上一张」这条安全规则),现在两边都调它。
- `workflow_actions.element.layers`(新):把分层产物 + 参考图暴露给画布。
- `workflow.py`:
  - `type: "gen"` 通用生成节点——三层装配 + 上游类型化投影 + 入队 `config.step`
    指名的既有 Step + **产物 url 直出 outputs**;
  - `type: "llm"` 节点——落到 `agent_runtime.run_batch`(技能/知识库/工具那套现成的);
  - `_upstream_media`:按上游产物字段分流(文本类→提示词素材,媒体类→参考图/帧);
  - `_apply_refs`:按模态放参考(image ≤4;video 取首/尾帧;audio 取参考声线),
    **被丢弃的一律写进 outputs.notes**,不静默截断;
  - `task` 节点跑完也回读 `skip_if` 产物直出 `outputs.url`(不再让下游绕只读 action);
  - `run_workflow(overrides=…)` + `RunIn.node_overrides`:指令层入口;
  - `preview_workflow` 支持 gen(算真实提示词与参考图)与 llm(只报待运行,不烧钱)。
- 种子 `55_workflow_scene_canvas_v5.sql`:单场景画布的生成节点换成通用 `gen`。

**前端**
- adapter:`type=gen` 节点投影(bind.unit = 装配器 → 步骤;model 取 `ui.model`);
- `TapNode.assembled`(新字段)+ 属性面板「装配后的完整提示词」只读回显;
- **生成条 = 指令层**(用户自己的话),运行时收成 `node_overrides` 送进 run——
  这才对得上演示画布里 `gen.prompt` 是「帮我生成一张破旧的马车…」而不是系统提示词;
- 预检把真实提示词/参考图带回画布(装配器零副作用才敢这么做)。

## 八、验证记录(2026-08-01)

| 项 | 结果 |
|---|---|
| 装配拆层零回归 | 40 个要素(角色/场景/道具混合),老实现 vs 新实现:`sheet_prompt`/`user`/`anchor`/`negative`/`hair` + 参考图筛选**逐字节相同**,0 处差异 |
| 预检零副作用算提示词 | 已有场景预检直出 1438 字提示词 + 1 张参考图,不写库、不入队 |
| 未创建的场景 | 如实报「要素不存在」,不假装有(库里无数可取,装配不出来是正确行为) |
| 指令层生效 | 带 `node_overrides` 跑:最终提示词 1503 字(基线 1438 + 指令),`gen_logs.modality = text[1503字]` 与之吻合——指令确实到了模型 |
| anchor 锁定 | 同一次运行里「强制纯场景多景别版式」等锚定段原样保留,用户指令改不动它 |
| 出图落库 | run #33 → 附件 #713(type=sheet)+ `meta.sheet_url` + 素材库「要素设定图 · 灯塔守夜人的瞭望平台·设定图」,图片 HTTP 200 / 989 KB |
| 数据安全 | 全程只新建要素与新增附件,未删除任何历史数据(强制重出也只追加附件行,旧图仍在素材库) |
