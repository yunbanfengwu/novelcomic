# Tapflow 新建节点持久化约定

生产画布里的新建节点分两类数据，不能混存：

| 数据 | 存储位置 | 示例 |
|---|---|---|
| 节点定义 | `workflows.graph.nodes` | 类型、坐标、尺寸、标题、执行体、系统提示词、技能、知识库、质检配置 |
| 用户输入 | `node.config.ui.state` | 生成条提示词、手编冻结标记、手选参考节点、直接编辑的文本 |
| 运行结果 | `workflow_node_runs.outputs` | 生成文本、图片/视频/音频地址、最终提示词、质检结果 |
| 媒体实体 | `content_attachments` | 自由生成的图片等可复用项目素材，`meta.node` 关联画布节点 id |

## 保存与恢复

1. 场景首次改动画布时，从公共模板 fork 一份 `origin@subject-id` 专属画布。
2. 结构或用户输入变化后自动保存专属 graph；运行过程状态不触发 graph 保存。
3. 每次运行把节点结果写进 `workflow_node_runs.outputs`，媒体同时写入附件表。
4. 重开画布时先加载 graph 恢复定义和用户输入，再调用
   `GET /api/workflows/{slug}/nodes/latest`，按 `node_key` 分别恢复每个节点最近一次产物。

按节点取最新结果是必要的：分支 A 与分支 B 可能被分别单独运行，只读取最后一次 run
会丢掉另一条分支已经生成的内容。

## 各节点约定

- Text：生成条内容作为本次 LLM `instruction`；生成文本保存在 node run 中。
- Image：生成条内容作为最终 `prompt`；自由出图默认执行体为 `gen_canvas_image`，产物落附件。
- Video / Audio：定义、用户输入、参考关系和历史产物按同一协议保存；执行前仍必须选择可用执行体。
- Upload：节点定义保存于 graph；接入真实上传选择器后，资源地址应作为 value 配置持久化。
- Flow：保存引用工作流的 slug/version，运行产物按该引用节点恢复。

## 不做的事

- 不把模型生成文本或媒体地址反写成系统提示词。
- 不因运行状态、进度徽标变化创建画布版本。
- 不把场景专属节点写回公共模板。
