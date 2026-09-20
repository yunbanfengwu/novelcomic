# 资产类型管理与类型驱动 Tapflow 设计

## 1. 结论（2026-08-02 修订）

新增“资产类型管理”是合理且必要的。当前项目已经同时存在项目要素、分镜节点、附件、关键帧、通用图片/视频、Tapflow 产物槽位和工作流实例；它们的读取、写入、生成及画布入口规则分散在前端判断、工作流模板、Step 和业务表中。

资产类型管理应成为这些规则的统一注册表。它解决“这是什么资产、在哪、可做什么、默认如何读写”的问题；Tapflow 工作流仍解决“按什么提示词、技能、知识库、工具、质检和流程来生产”的问题。

资产类型不是“场景”这种业务主体，也不是一个泛化的产物槽位。资产类型是一种可独立生产、存储、读取、版本化和被下游引用的结果。例如 `pro.scene.brief` 与 `pro.scene.sheet` 是两个不同资产类型；场景要素只是它们共同关联的业务主体。

它不是新的执行体系统。禁止让用户在节点属性中挑选底层 Step 作为业务含义。运行适配器仍可在模板内部使用，但对使用者只暴露：资产类型、操作和产物槽位。

## 2. 目标与边界

目标：

- 项目内所有资产以稳定 `asset_type.code + id` 表示，替代按名称或 URL 推测身份。
- Tapflow 节点选择输入类型、输出类型或画布类型后，系统能解析查询范围、默认能力、产物存储和关联规则。
- 一个资产类型对应一份标准生产契约；允许多个画布作为该契约的不同入口，例如首次生成、变体重绘、风格迁移和批量入口。它们写入同一资产类型的实例集合，但画布自身的提示词、技能、工具、QC 和编排可以不同。
- 支持智能节点在运行时返回异构集合，并按类型分裂为可追溯的子任务。
- 保留现有 LLM 节点的 charter、skills、folder_ids、tools、引用、人工冻结提示词、QC、subflow 和 loop 功能。

非目标：

- 不把 `content_elements`、`content_nodes`、`content_attachments` 立即合并为一张大表。
- 不删除现有业务 Step；先把它们登记为资产能力的运行适配器。
- 不让类型注册表存放提示词正文、模型参数或完整工作流图。

## 3. 统一模型

```text
资产类型 AssetType
  定义：独立生产结果的身份、查询、存储、能力、标准生产流程

资产主体 Subject
  例如现有场景要素 element:265；资产可关联到主体，也可独立存在

资产实例 Asset
  例如 pro.scene.sheet，主体 element:265，variant=img，version=1

Tapflow 节点
  声明：输入资产类型、输出资产类型、操作
  编排：提示词、技能、工具、引用、QC、循环、子流程

运行适配器
  执行：调用既有 query/action/Step，并按 AssetType 规则读写
```

`target_ref`、role、slot 是现有兼容字段；新接口不向用户暴露它们。后端由“完整资产类型 code + 主体 + 可选 variant/version”推导并写入兼容字段。现有 `workflow_artifacts` 是资产实例、附件与运行溯源的基础表。

### 3.1 Code 规则

资产类型 code 不限制段数，不以点号段数驱动业务逻辑。唯一硬规则是全局唯一、稳定、非空且能在后端 registry 精确解析。`pro.scene.brief` 是推荐的可读写法，不是格式限制；`image`、`pro.scene.sheet`、`pro.character.costume.front.sheet` 都可以合法。

## 4. 初始资产类型目录

| code | 名称 | 主存储 | 关联主体 | 默认能力 |
|---|---|---|---|---|---|
| `pro.scene.brief` | 场景简介 | 场景 meta / 资产索引 | 场景要素 | 文本生成、读取、版本化 |
| `pro.scene.sheet` | 场景设定图 | 附件 + 资产索引 | 场景要素 | 图片生成、变体、参考图读取 |
| `pro.character.sheet` | 角色设定图 | 附件 + 资产索引 | 角色要素 | 图片生成、变体、参考图读取 |
| `pro.prop.sheet` | 道具设定图 | 附件 + 资产索引 | 道具要素 | 图片生成、变体、参考图读取 |
| `pro.shot.script` | 分镜脚本 | 分镜 meta / 资产索引 | 分镜节点 | 文本生成、读取、版本化 |
| `pro.shot.keyframe` | 分镜关键帧 | 附件 + 资产索引 | 分镜节点 | 图片生成、版本、参考图读取 |
| `pro.shot.video` | 分镜视频 | 附件 + 资产索引 | 分镜节点 | 异步视频生成、版本 |
| `com.image` | 通用图片 | 附件 + 资产索引 | 可无主体 | 上传、生成、查询、引用 |
| `com.video` | 通用视频 | 附件 + 资产索引 | 可无主体 | 上传、生成、查询、引用 |

说明：场景、角色、道具、分镜是现有业务主体；`pro.scene.sheet`、`pro.shot.keyframe` 等才是新资产类型。一个资产类型有一个标准生产契约，但允许多个画布作为首次生成、变体、批量或人工重绘的入口；所有画布都写入同一资产类型的实例集合。

## 5. 资产类型的管理字段

资产类型定义由后端受控注册，不提供任意编辑。系统管理页面第一阶段只读展示类型目录、能力和映射，用于理解、排错与审计；数据库保存运行时映射和关系，不把 Python 行为、SQL 或存储适配器开放为可编辑配置。

每条内置资产类型在后端注册时应声明：

`media_kind` 是技术媒介/数据类型（如 `text`、`image`、`video`、未来的 `math`、`vector`），用于模型能力、存储与连接校验；`tags` 是独立的多标签业务分类，用于管理页、素材筛选和画布路由。两者不互相推导，也不要求 `tags[0] == media_kind`。

| 字段 | 说明 |
|---|---|
| `code` | 稳定、不可轻易修改的机器标识，如 `project.scene` |
| `name` / `description` | 管理端和画布使用的展示语义 |
| `scope` | `project` 或 `common`；决定是否必须提供项目 ID |
| `target_kind` | 通用目标类型，如 `element`、`content_node`、`attachment` |
| `resolver` | 读取实例的注册查询器，例如 `content_elements + kind=scene` |
| `storage_adapter` | 创建、更新、关联产物时使用的业务适配器 |
| `capabilities` | `query`、`create`、`generate`、`attach`、`reference`、`derive` 等 |
| `operations` | 具名能力到默认工作流/运行适配器的映射 |
| `output_slots` | 可用产物槽位、是否允许 variant、媒体类型、是否可覆盖 |
| `async_policy` | `sync`、`async` 或 `provider_decides`，以及轮询/回调策略 |
| `input_types` / `output_types` | 可接收和可发出的资产类型，用于画布连线校验 |
| `enabled` / `system` | 是否可用；内置类型不可直接删除，只能停用或迁移 |

`operations` 示例：`project.scene.generate_sheet -> scene-sheet-canvas`；`project.keyframe.generate -> shot-keyframe-canvas`。工作流内部仍保留具体生图模型、提示词技能和 QC。

建议的代码组织：

```text
backend/app/assets/
  base.py                 # AssetType 抽象契约
  registry.py             # 内置类型与操作路由
  project_scene.py        # content_elements(kind=scene) 的查询、变体和落库
  project_character.py    # content_elements(kind=character) 的查询和落库
  project_prop.py         # content_elements(kind=prop) 的查询和落库
  project_shot.py         # content_nodes(kind=shot) 的查询和上下文
  project_keyframe.py     # 分镜目标上的 keyframe 产物规则
  common_image.py         # 附件库图片规则
  common_video.py         # 附件库视频规则
```

每个模块只处理一个资产类型的身份解析、查询、创建/更新、参考资料、产物落点、变体/版本和异步策略。`registry.py` 负责以 `asset_type + operation` 路由到对应模块及默认工作流；Tapflow 与前端不得直接依赖具体表名或 Python 类名。

## 6. Tapflow 的改动原则

### 6.1 画布类型

画布模板可声明一个或多个输入/主体资产类型。例如：

- 单场景生成画布：主体 `project.scene`，输出 `scene.sheet`。
- 分镜关键帧画布：主体 `project.shot`，输出 `shot.keyframe`。
- 通用图片画布：无强制主体，输出 `common.image`。

从项目素材卡片进入时，前端只传入 `target_ref`、`asset_type`、项目 ID 和可选变体；不得以素材名称推断目标。

### 6.2 节点属性

生成节点面板应显示：

- 输入资产类型或继承的上游类型。
- 操作（例如“生成场景设定图”），可选择业务能力而非底层 Step。
- 输出资产类型和产物槽位；未选择槽位时只进入项目素材库。
- 当槽位允许变体时显示 variant ID。

生成操作的 Step、装配器、provider 调用为模板内部配置，只读展示用于诊断。提示词、技能、知识库、工具、引用和 QC 保持原有可编辑能力。

### 6.3 查询与连线

查询节点以 `asset_type` + filter 声明查询，而不是分别硬编码“查角色/查场景/查道具”。

连线在类型层校验：例如 `project.character[]` 可以进入“参考图组装”，`common.image[]` 可以进入“参考素材”，而 `project.keyframe` 可以进入视频生成。允许显式转换节点处理不兼容类型。

## 7. 智能节点与动态子任务

“获取核心要素”应声明输出为 `AssetDescriptor[]`，每项至少包含：

```json
{
  "asset_type": "project.character",
  "target_ref": "element:161",
  "role": "required",
  "operation": "reference",
  "attributes": {"variant_id": "default"}
}
```

运行时处理规则：

1. 智能节点识别或查询核心要素，返回带类型的描述符集合。
2. loop 按描述符展开子任务，不按名称或数组位置判断类型。
3. 路由器按 `asset_type + operation` 查资产类型的能力映射，选择工作流节点或子工作流。
4. 每个子任务保留父运行、迭代序号、目标 ID、输入类型、输出槽位和失败原因。
5. required 子任务失败阻断下游；optional 子任务失败降级并显式记录。
6. 子任务产物以 `workflow_artifacts + provenance` 关联到其目标，不以“最近生成图”回填。

这使“核心要素”同时包含角色、场景、道具或未来类型时无需为每个类型复制一条工作流分支。

### 7.1 数据源合同：先确定业务范围，再路由资产类型

`AssetDescriptor[]` 的上游必须显式声明数据源，不能由 `meta.element_ids`、名称或页面上下文推断范围：

| source_type | source_ref | 查询范围 |
|---|---|---|
| `explicit.element_ids` | 可选 | 调用方明确传入的要素 ID 集合 |
| `shot.dynamic_elements` | `content_node:<shot_id>` | 该分镜在 `element_appearances` 中的直接关联要素 |
| `chapter.appearing_elements` | `content_node:<chapter_id>` | 本章及其分镜出现的要素 |
| `project.elements` | `project:<project_id>` | 项目全部要素，可由 `filters.kinds` 限定 |

`meta.element_ids` 是旧分镜的兼容缓存，只能由旧读取工具兜底；新智能生成工具不可用它推断“分镜/章节/项目”范围。分镜关键帧固定使用 `shot.dynamic_elements`，因此不会误把整章或全项目要素送入本镜生成。

### 7.2 被引用工作流的多子产物合同

每个工作流由后端根据终止节点自动计算 `output_cardinality`：若 `end/next` 的直接上游为 loop，或其直接汇聚多个独立产物，则为 `many`，否则为 `one`。引用方通过 `subflow_contracts` 读取该只读合同；`many` 工作流在画布显示为“循环聚合子产物”节点，但执行类型仍为 `subflow`，不可因展示而改写为 loop。

## 8. 实施计划

### 阶段 A：类型注册与兼容层

1. 建立幂等 SQL：资产实例/关系/运行映射所需表；资产类型的权威定义在 Python 注册表，不依赖可编辑配置表。
2. 在 `backend/app/assets/` 预置第 4 节的内置类型模块与初始能力映射。
3. 实现后端 `AssetTypeRegistry`，提供类型解析、目标校验、查询器和槽位校验。
4. 将现有 `resource_refs`、`workflow_artifacts` 适配到资产类型，但继续兼容 `element:id`、`content_node:id` 格式。
5. 为已有场景、角色、道具、分镜、关键帧创建迁移映射，不搬迁历史媒体数据。

验收：现有单场景和分镜关键帧工作流的输入、输出、变体、附件和溯源行为不变。

### 阶段 B：系统管理与项目入口

1. 新增只读“资产类型管理”页：内置类型列表、详情、能力、槽位、异步策略、存储映射和默认工作流。
2. code、主存储、核心适配器和工作流路由只允许通过后端代码评审与数据库迁移改动；管理端不提供编辑入口。
3. 项目素材库、分镜页和通用素材库使用资产类型目录渲染分类与可执行操作。
4. 由素材进入画布时统一传递 `asset_type + target_ref + canvas_role`。

验收：同一场景的多个变体能打开各自画布，且不能回退到另一变体或最近产物。

### 阶段 C：Tapflow 类型化节点

1. 扩展画布/节点 schema：`input_asset_types`、`operation`、`output_asset_type`、`output_slot`。
2. 节点属性面板替换底层 Step 下拉为资产类型、操作、产物槽位选择；保留只读诊断信息。
3. 图适配器、版本化保存、预检和运行记录完整保存类型声明。
4. 为类型不匹配连线提供编辑期错误与运行期防御。

验收：提示词技能、知识库、工具、QC、人工冻结、subflow、loop 的保存与运行完全不丢失。

### 阶段 D：智能节点路由

1. 增加 `AssetDescriptor[]` 的结构化输出与 loop 支持。
2. 新增 `route_by_asset_type` 内部节点/能力，按类型选择子流程或节点模板。
3. 加入 required/optional 失败策略、并发限制、类型级异步策略和回收机制。
4. 在运行视图显示每个动态实例的类型、目标、选中的能力、产物和溯源。

验收：一个“获取核心要素”节点返回角色、场景、道具后，可生成或查询各自资产并汇总到关键帧流程。

### 阶段 E：迁移与收口

1. 将旧的场景/角色/道具/关键帧专用判断逐步迁入 registry adapter。
2. 删除前端按名称、URL、单一 element ID 猜目标的逻辑。
3. 旧 workflow config 的 `step` 仅保留内部兼容用途；新模板改用 `operation`。
4. 补充管理操作审计、类型停用保护、历史类型迁移工具。

## 9. 具体改动点

| 层级 | 改动点 |
|---|---|
| 数据库 | 资产类型、能力映射、产物槽位三类配置表；保留现有业务表和 `workflow_artifacts` |
| 后端服务 | 新增类型注册与 resolver；将 `resource_refs` 扩展为类型感知；工作流运行时按 operation 路由 |
| 工作流引擎 | 节点 schema 支持输入/输出类型；loop 支持异构 `AssetDescriptor[]`；运行记录保存类型与路由决策 |
| 工作流动作 | 既有 `element.*`、`shot.*` 等成为注册的 adapter，不再由前端直接挑选 |
| 系统管理 | 新增资产类型管理页面与内置类型保护机制 |
| 项目前端 | 素材库、分镜与画布入口统一使用 `asset_type + target_ref` |
| Tapflow 前端 | 画布/节点类型选择、产物槽位、类型连线校验、动态节点投影 |
| 测试 | 类型解析、槽位校验、兼容目标、动态分裂、路由选择、场景变体与关键帧真实 E2E |

## 10. 风险与决策

- 不要把“资产类型”设计成任意用户可写 SQL 或任意函数名。resolver 和 storage adapter 必须来自受控注册表。
- 不要在类型表内复制完整工作流配置。类型只引用默认工作流版本或 operation；工作流保持独立版本化。
- `project.keyframe` 的目标仍为 shot ID，避免复制出第二个分镜身份源。
- 变体属于产物槽位维度，不应为每张场景图新建一个资产类型。
- 动态拆分必须使用稳定 ID 和显式类型，禁止根据中文名称匹配。
- 先做兼容层再切入口，避免破坏当前已可用的场景变体、画布实例和产物溯源。

## 11. 验收清单

1. 管理端可查看内置资产类型、能力、槽位和异步策略。
2. 场景、角色、道具、分镜、关键帧、通用图片/视频均能以类型和稳定 ID 被查询。
3. 点击同一场景的不同变体，进入各自的 `canvas_role` 画布并读取各自产物。
4. 未选业务槽位的生成结果只进入项目素材库；选中槽位后同时写入业务关联和完整溯源。
5. 单场景与分镜关键帧工作流的提示词、技能、知识库、工具、QC、循环和子流程全部保留。
6. “获取核心要素”返回混合类型时，动态子任务依据类型选择对应能力，required/optional 失败策略正确。
7. 对每个真实出图结果，能从资产类型、目标 ID、槽位、工作流运行、节点运行和迭代序号反查完整来源。
