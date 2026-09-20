# AI 剧集连续性与分镜视频生成方案

> 文档用途：作为新 Codex 会话的唯一需求基线，避免依赖旧会话上下文。  
> 文档性质：问题复盘、行业调研结论、产品方案、数据契约与分阶段实施蓝图。  
> 当前阶段目标：先建立稳妥、可验证的剧集连续性与分镜生产流程。  
> 长期目标：在无人管理模式下，全自动生成画风一致、角色一致、场景一致、剧情连贯的分镜和最终视频。  
> 更新日期：2026-07-24。

---

## 0. 新会话必须先理解的结论

不要继续把“5 秒整集闪回视频 → 抽帧 → 自动拆成正式分镜”当作主生产链路。

行业更稳妥的生产顺序是：

```text
剧本拆解
→ 场景连续性设计
→ 剧情节拍 Beat
→ 镜头规划 Shot List
→ 静态分镜 Storyboard
→ 动态分镜 Animatic
→ 锁定剪辑
→ 逐镜生成最终视频
→ 自动合成整集
```

推荐的核心原则：

> Scene-first、Storyboard-first、Animatic-first、Shot-by-shot generation。

也就是：

1. 场景负责世界状态、时间、光线、空间与人物状态连续。
2. Beat 负责确保剧情没有遗漏、重复或擅自扩写。
3. Shot 负责摄影机、构图、景别和剪辑。
4. Panel 负责表达一个镜头内部的多个关键动作画格。
5. Animatic 负责低成本验证镜头顺序、节奏和整集连贯性。
6. 视频模型只生成已经通过连续性检查并锁定的镜头。
7. 失败时只重做单镜，不重做整集。

---

## 1. 用户的真实目标

### 1.1 长期目标

在无人管理模式下，系统能够：

- 从章节剧本自动拆出场景、剧情节拍和镜头。
- 自动生成角色、场景和动作连续的静态分镜。
- 自动组成可审看的动态分镜。
- 自动逐镜生成最终视频。
- 自动检测错误并只重做失败镜头。
- 自动拼接成完整剧集。

### 1.2 当前阶段目标

当前不要求每一处剧情细节都极端严格，优先验证：

- 不偏离主要设定。
- 不擅自加入关键剧情。
- 主要角色身份和当前状态一致。
- 场景、昼夜、天气和光线一致。
- 相邻镜头的人物位置、动作和空间关系连续。
- 画风保持一致。
- 分镜能够明确进入后续视频生成链路。

### 1.3 资源目标

尽量在调用昂贵视频模型前发现问题。优先使用：

- 文本镜头表。
- 低分辨率静态分镜。
- 关键动作画格。
- 静态画格组成的 Animatic。
- 自动视觉检查。

只有通过上述检查的镜头，才进入最终视频生成。

---

## 2. 已经遇到的问题

### 2.1 批量分镜画面效果一般

一次批量生成整组分镜，容易出现：

- 角色脸部、服装和体型漂移。
- 场景结构在不同镜头中变化。
- 构图重复或者动作不清楚。
- 每张图看起来单独成立，但剪在一起不连续。

根因是模型在生成每张图时缺少统一的场景状态和相邻镜头上下文。

### 2.2 上一镜正午，下一镜变成黄昏

这是场景级连续性失败：

- 同一剧情场景没有锁定 `time_of_day`。
- 光线、色温、阴影方向只存在于自然语言提示词中。
- 每个镜头被独立生成，模型把“山路”重新解释成了不同时间。

### 2.3 上一镜角色在马车外，下一镜突然在马车上

这是角色位置和动作状态失败：

- 系统只记录“角色是谁”，没有记录“角色此刻在哪里”。
- 没有保存上一镜结束状态。
- 没有验证下一镜开始状态是否能由上一镜自然到达。
- 剧本没有“上车”动作时，模型仍然自行补足了动作。

### 2.4 模型擅自加入摘要不存在的剧情

曾出现模型加入“首领、战舰、报仇、信号源”等摘要没有的内容。

根因包括：

- 生成提示词把模型当成了编剧，而不是导演和执行者。
- 没有建立“剧情证据字段”。
- 没有区分允许补充的视觉细节与禁止新增的剧情事实。
- 没有在生成前后进行剧情覆盖校验。

### 2.5 角色锁定方式不合理

只写角色外貌描述不能稳定锁定身份。正确形式应支持：

```text
阿澈@角色图
伊莎@角色图
巡夜@角色图
```

但角色图只负责“她是谁”，不能负责：

- 是否受伤。
- 当前服装是否破损。
- 武器在哪只手。
- 当前在马车外还是马车内。
- 当前情绪和动作阶段。

因此必须把“身份参考”和“镜头状态”分开。

### 2.6 不知道抽出的图到底是不是分镜

抽取 24 张关键帧，不等于得到 24 个镜头。

一张抽帧图可能是：

- 一个镜头的首画格。
- 一个镜头中间的动作画格。
- 一个镜头的尾画格。
- 两次真正切镜之间的任意画面。

如果系统把每张图都直接转换为一个 Shot，就会导致镜头数量虚高、剧情重复和节奏失真。

### 2.7 双时间轴难以理解

用户不知道：

- 为什么要拖动脚本宽度。
- 拖动后产生的是分镜、参考图还是视频片段。
- 下一步怎样生成最终视频。
- 脚本和视频哪个才是真正的主时间轴。

说明当前交互把内部数据校准过程暴露给了用户，却没有形成清晰的制作任务。

### 2.8 黑底白字镜号板实验失败

“黑底 + 白色镜号”的导演板用于自动识别切点，实际增加了生成负担和识别复杂度。

结论：

- 不再把镜号板作为默认切镜方法。
- 不依赖视觉识别镜号。
- 镜头边界应来自结构化镜头计划或明确的编辑时间线。

### 2.9 固定 5 秒、20 镜或 15 次切换不适合作为故事规则

这些数字可以是模型或接口的技术容量限制，但不能成为剧作规则。

例如把 5 分钟压缩成 5 秒，相当于 60 倍速。如果有 20 个镜头，每镜平均只有 0.25 秒，按 24fps 计算只有约 6 帧，无法稳定表达：

- 人物身份。
- 动作起因和结果。
- 空间关系。
- 情绪变化。
- 镜头内部的动作过程。

“每批最多 15 个”只能用于拆分生成任务，不能决定一个场景应该有多少镜头。

---

## 3. 已完成实验应如何定位

历史实验数据不得删除，但其产品定位需要调整。

### 3.1 整集 5 秒闪回

建议定位为：

- `Visual Synopsis`：视觉剧情摘要。
- `Style Reel`：画风检查带。
- `Continuity Proof`：角色和主要场景覆盖检查样片。

用途：

- 快速检查画风是否严重跑偏。
- 检查主要角色和核心场景是否出现。
- 检查剧集总体情绪是否大致正确。

不应用于：

- 决定正式镜头边界。
- 估算正式镜头时长。
- 直接生成正式分镜。
- 作为最终视频的时间基准。

### 3.2 抽帧

抽帧结果应叫：

- 候选动作画格。
- 候选构图参考。
- 候选 Panel。

不能未经判断直接叫正式 Shot。

### 3.3 预览母带

预览母带是参考媒体，不是最终成片，也不是剧情事实来源。

它可以为镜头提供：

- 动作姿态。
- 构图方向。
- 大致镜头运动。
- 场景氛围。

它不能覆盖：

- 原始剧本。
- 角色身份设定。
- 场景连续性契约。
- 已批准的分镜状态。

---

## 4. 必须统一的影视生产层级

```text
Episode 剧集
└─ Sequence 段落
   └─ Narrative Scene 剧情场景
      └─ Beat 剧情节拍
         └─ Shot 镜头
            └─ Panel 动作板 / 关键画格
               └─ Take / Version 生成版本
```

### 4.1 Episode

完整一集，负责整体剧情目标、片长和跨场景角色状态。

### 4.2 Sequence

由一个或多个具有时间、地点或剧情目的统一性的场景组成。

### 4.3 Narrative Scene

同一时空、同一批主要人物、一个连续剧情目的的叙事单元。

为了避免动画软件中 `Scene` 有时等同于 Shot 的歧义，产品界面建议显示为“剧情场景”。

### 4.4 Beat

剧情中发生的一件可描述的事件，例如：

```text
B01 三人进入峡谷
B02 发现敌人
B03 敌人发动攻击
B04 阿澈受伤
B05 巡夜反击
B06 敌人撤退
```

Beat 描述“发生了什么”，还不是摄影机镜头。

### 4.5 Shot

一次连续摄影机拍摄，从一个切点到下一个切点。

切镜意味着：

- 摄影机机位改变。
- 景别或视点改变。
- 叙事关注对象改变。
- 进入下一段独立的连续画面。

### 4.6 Panel

一个 Shot 内部可以有多张 Panel：

```text
Panel A：阿澈站在马车外
Panel B：阿澈抓住扶手
Panel C：阿澈踏上车辕
Panel D：阿澈进入车厢
```

这些 Panel 可以描述一个连续镜头的动作过程，不应全部变成独立镜头。

### 4.7 Take / Version

同一 Shot 的多个生成结果。系统应保留全部版本，允许选择 Approved Take，不覆盖历史数据。

---

## 5. 推荐的标准生产流程

### 阶段 A：剧本拆解

输入：

- 本章剧本。
- 角色设定。
- 已有场景资料。
- 上一章结束状态。

输出：

- Sequence。
- Narrative Scene。
- Beat。
- 每个 Beat 的剧情证据。
- 初步时长估计。

规则：

- 只能依据剧本和已批准设定拆解。
- 允许补充摄影和视觉表达。
- 禁止新增关键人物、组织、武器来源、动机、伏笔和剧情结果。

### 阶段 B：建立场景连续性包

每个剧情场景生成一个 `Scene Continuity Pack`，见第 6 节。

### 阶段 C：自动生成镜头方案

大模型根据场景、Beat 和 Coverage 规则生成 Shot List：

- 每镜覆盖哪些 Beat。
- 为什么需要切镜。
- 景别、机位、镜头运动。
- 预计时长。
- 需要多少张 Panel。
- 镜头开始和结束状态。

用户默认只需要：

- 接受。
- 合并。
- 拆分。
- 重新规划本场。

### 阶段 D：静态分镜

每个 Shot 生成 1 至 3 张低成本图：

- 首画格。
- 关键动作画格。
- 尾画格。

先检查连续性，再进入视频生成。

### 阶段 E：Animatic

将静态分镜按照预计时长播放，并加入：

- 临时对白。
- 旁白。
- 音效。
- 简单推拉摇移。
- 基础转场。

Animatic 的目标是验证：

- 剧情是否覆盖完整。
- 镜头顺序是否清晰。
- 镜头时长是否合理。
- 情绪和节奏是否成立。
- 场景和角色是否连续。

Animatic 可以完全由静态图组成，不需要昂贵视频模型。

### 阶段 F：锁定剪辑

只有通过检查的 Animatic 才能 `Lock Cut`。

锁定后：

- 镜头编号稳定。
- 镜头顺序稳定。
- 时长稳定。
- Scene、Beat、Shot 和 Panel 关系稳定。
- 后续修改产生新版本，不覆盖旧版本。

### 阶段 G：逐镜生成最终视频

系统为每个 Shot 生成独立的 `Shot Generation Package`，调用视频模型。

生成顺序：

```text
场景锚点
→ Shot 首画格
→ Shot 尾画格
→ 连续性检查
→ 生成 Shot 视频
→ 与相邻镜头上下文检查
→ 选择 Approved Take
```

### 阶段 H：自动合成

使用已批准 Shot 视频按照 Locked Cut 合成：

- 正式画面。
- 对白和旁白。
- 音效和音乐。
- 转场。
- 字幕。
- 最终输出。

---

## 6. Scene Continuity Contract：场景连续性契约

这是本方案最重要的数据结构。

### 6.1 场景硬锁

同一剧情场景默认不可变化：

```yaml
scene_id: SC_003
location_id: LOC_MOUNTAIN_ROAD
story_day: DAY_01
time_of_day: noon
weather: clear
lighting:
  direction: overhead
  color_temperature: warm-neutral
  shadow: short
palette: sunlit_earth
vehicle_id: PROP_BLACK_CARRIAGE
screen_direction: left_to_right
camera_axis: AXIS_01
locked: true
```

硬锁字段建议包括：

- 地点和场景版本。
- 故事日期。
- 昼夜。
- 天气。
- 光线方向。
- 色温和主色调。
- 固定地标。
- 主要道具。
- 摄影机轴线。
- 角色初始位置。

如果同一场景上一镜是正午，下一镜生成黄昏，应直接判定失败并重新生成，不能自动接受。

### 6.2 角色身份锚点

角色身份通过资产引用，不通过长篇外貌重述：

```yaml
character_id: CHAR_ACHE
reference: 阿澈@角色图
```

建议为角色建立 Character Plates：

- 正面。
- 左侧。
- 右侧。
- 背面。
- 半身。
- 全身。
- 常用服装版本。
- 常用装备版本。

### 6.3 角色动态状态

```yaml
character_state:
  character_id: CHAR_ACHE
  location_zone: carriage.exterior.left
  pose: standing
  facing: toward_carriage
  costume_version: travel_01
  injury:
    right_arm: none
  held_props:
    right_hand: reins
    left_hand: none
  emotion: alert
  wetness: dry
```

动态状态负责“这一刻她是什么样”，角色图负责“她是谁”。

### 6.4 空间 Blocking

每个场景应有简单的空间布局：

```yaml
blocking:
  阿澈: left_of_carriage
  伊莎: inside_carriage_right_window
  敌人: road_ahead
  exit: road_right
  movement_direction: left_to_right
  eyelines:
    阿澈: toward_伊莎
    伊莎: toward_阿澈
```

用于检查：

- 人物位置是否跳变。
- 眼神是否能对上。
- 运动方向是否反转。
- 是否越过 180 度轴线。
- 道具和地标是否在合理位置。

### 6.5 连续性变更原因

硬锁不是永远不能改变，但任何改变必须有明确原因：

```yaml
continuity_transition:
  type: explicit_script_action
  evidence: "阿澈抓住扶手，登上马车。"
  changes:
    阿澈.location_zone:
      from: carriage.exterior.left
      to: carriage.interior.front_seat
```

允许的变更来源：

- `explicit_script_action`：剧本明确动作。
- `explicit_time_jump`：剧本明确时间跳转。
- `scene_change`：进入新场景。
- `approved_director_override`：人工批准的导演处理。
- `match_cut`：批准的匹配剪辑。
- `montage`：明确蒙太奇结构。

没有变更原因时，系统不得自行改变状态。

---

## 7. Shot Continuity State：镜头前后状态

每个 Shot 必须包含：

```yaml
shot_id: SH_0030
scene_id: SC_003
beat_ids: [B02]

before_state:
  time_of_day: noon
  阿澈.location_zone: carriage.exterior.left
  阿澈.right_hand: reins
  carriage.motion: stopped

action:
  evidence: "阿澈松开缰绳，转头看向车厢。"
  visual_action: "松开缰绳后转头"

after_state:
  time_of_day: noon
  阿澈.location_zone: carriage.exterior.left
  阿澈.right_hand: none
  carriage.motion: stopped
```

默认规则：

```text
SH_0030.after_state == SH_0040.before_state
```

允许存在机位和景别差异，但世界状态必须相容。

### 7.1 马车外突然变马车上的处理

如果剧本没有上车动作：

```text
上一镜 after：阿澈位于马车外
下一镜 before：阿澈位于马车上
```

系统应：

1. 阻止下一镜进入生成。
2. 提示状态冲突。
3. 默认让下一镜继续保持马车外状态。
4. 不得擅自编造“阿澈跳上马车”。

如果剧本明确有上车动作：

系统可以：

- 为同一 Shot 增加多个 Panel 表达上车过程；或
- 增加一个有剧本证据的桥接 Shot。

### 7.2 正午突然变黄昏的处理

如果仍属于同一 Scene：

- 判定生成失败。
- 继承 Scene 的 `time_of_day=noon` 和光线锚点。
- 重新生成下一镜首画格。

如果剧本明确“数小时后”：

- 关闭当前 Scene。
- 创建新的黄昏 Scene。
- 在剧情结构中记录时间跳转。
- 使用建立镜头或转场明确告诉观众时间变化。

---

## 8. 剧情事实边界

### 8.1 允许模型补充

模型可以补充不改变剧情事实的视觉执行细节：

- 摄影机轻微推进。
- 衣物随风摆动。
- 水面反光。
- 人物呼吸和自然微动作。
- 符合当前场景的背景群众或环境动态。
- 不改变剧情的构图和景别。

### 8.2 禁止模型补充

未经剧本或设定支持，禁止新增：

- 新角色。
- 新组织。
- 新敌人首领。
- 新战舰。
- 新武器来源。
- 报仇动机。
- 信号源。
- 新伏笔。
- 新伤势。
- 新的角色关系。
- 改变剧情结果的动作。

### 8.3 每个 Shot 必须携带剧情证据

```yaml
script_evidence:
  source: chapter_script
  event_ids: [E012]
  quote: "阿澈松开缰绳，转头看向车厢。"
```

生成提示词只能把证据转换成镜头语言，不得扩写新事实。

### 8.4 无证据状态冲突的默认策略

按以下优先级处理：

1. 继承上一镜状态。
2. 重新生成当前镜头。
3. 如果剧本本身矛盾，标记为待确认。
4. 不得用自动补剧情掩盖矛盾。

---

## 9. 自动拆镜规则

### 9.1 先拆 Scene，再拆 Beat，最后规划 Shot

不能从一条压缩视频直接推断故事结构。

Scene 的拆分条件：

- 地点变化。
- 时间明显变化。
- 主要人物组合变化。
- 剧情目标发生变化。
- 角色状态发生不可逆变化。

#### 9.1.1 跨 Scene 转场按“连续主体”判断

换场不等于必须补过渡镜。先比较相邻镜头的具名角色集合：

- 没有连续角色：允许直接切换到新叙事线、平行叙事线或无人物环境镜。例如“警察局分析案情 → 犯罪分子异地逃跑”不需要展示路程。
- 有连续角色但只是普通、易懂的地点移动：允许使用叙事省略，不机械展示出门、走廊、上车和全部旅程。
- 有连续角色且出现依赖使能动作的重大状态变化：必须有剧本证据、明确时间跳跃/蒙太奇、导演批准的省略，或最小过渡 Beat。典型变化包括骑乘/载具、起飞、换装、受伤、被捕、装备出现及能力变化。
- 场景视觉状态与角色状态分开处理：新 Scene 重置光线、天气、建筑、色板和机位轴；连续角色仍继承服装、道具、伤势、骑乘关系和已建立能力。
- 群组动作必须明确能力主体，例如写“岚牙载着洛汐飞行”，不得写“洛汐和岚牙扇动翅膀飞行”而把坐骑能力复制给骑手。

机器判定至少输出 `new_lane_direct_cut / parallel_cut / same_subject_ellipsis /
explicit_time_jump / match_cut_or_montage / bridge_required` 之一。只有
`bridge_required` 阻止下游生成。

Beat 的拆分条件：

- 新信息出现。
- 行动开始或结束。
- 角色目标改变。
- 冲突升级。
- 情绪发生明显转折。
- 剧情结果形成。

### 9.2 什么时候切 Shot

建议切镜：

- 叙事关注对象改变。
- 角色反应比说话者更重要。
- 需要重新交代空间关系。
- 动作进入新的阶段。
- 需要强调重要道具或线索。
- 情绪强度需要改变景别。
- 摄影机视点或运动方式改变。

不建议切镜：

- 只是人物做了连续动作。
- 只是同一镜头内姿态发生变化。
- 只是为了达到固定镜头数量。
- 只是因为抽到了另一张图片。

### 9.3 Master Shot + Coverage

场景默认使用稳妥的 Coverage 规划：

1. Establishing / Master：建立人物与场景空间。
2. Medium Coverage：覆盖主要对话和动作。
3. Close-up / Reaction：强调情绪和反应。
4. Insert / Cutaway：展示重要道具或线索。
5. Return to Master：必要时重新确认空间。

不是每个场景都必须机械包含全部类型，大模型应根据剧情选择。

### 9.4 Shot 数量不设固定值

- 不强制 20 镜。
- 不强制 15 镜。
- 不强制每镜固定 5 秒。
- 不根据抽帧数量决定镜头数量。

如果生成模型单批最多处理 15 个单元：

- 只拆分生成批次。
- 不改变 Shot 编号。
- 不改变 Scene 和 Beat 结构。
- 不把技术批次展示为剧情结构。

### 9.5 时长估计

镜头时长来自：

- 对白朗读时间。
- 动作完成时间。
- 观众识别信息所需时间。
- 情绪停顿。
- 镜头运动。
- 前后镜头节奏。

不是由固定公式 `5/15` 决定。

技术上可以给出默认范围，但最终由 Animatic 校准。

---

## 10. 低成本分级生产

### Level 0：文字镜头表

输出：

- Scene。
- Beat。
- Shot List。
- 时长。
- 连续性状态。
- 切镜原因。

成本最低，先检查剧情结构。

### Level 1：静态分镜

每 Shot 生成 1 至 3 张低分辨率 Panel：

- 首画格。
- 动作关键画格。
- 尾画格。

先检查角色、场景、构图和连续性。

### Level 2：Animatic

使用静态分镜、简单镜头运动和临时声音组成动态分镜。

它是最重要的整集连贯性审片产物。

### Level 3：最终 Shot 视频

只有锁定的 Shot 才调用视频模型。

### Level 4：整集合成

将 Approved Takes 按 Locked Cut 自动拼接。

---

## 11. Scene Anchor Pack：视觉锚点

### 11.1 Character Plates

角色应至少具备：

- 中性正面。
- 左右侧面。
- 背面。
- 半身和全身。
- 常用服装。
- 常用装备。

角色图使用 `角色名@角色图` 或稳定的资产 ID 引用。

### 11.2 Environment Plates

场景应至少具备：

- 建立全景。
- 正向视图。
- 反向视图。
- 侧向视图。
- 重要区域和地标。
- 对应时间与光线版本。

例如“山路马车”不能只有一张风格图，应包含：

- 山路全景。
- 马车左侧。
- 马车右侧。
- 马车内部。
- 道路前方。
- 正午光线版本。

### 11.3 Style Anchor

每个项目或篇章锁定：

- 画风参考。
- 色彩脚本。
- 镜头质感。
- 光影风格。
- 景深与镜头语言。
- 禁止风格。

### 11.4 动作参考的职责

预览视频抽出的帧只约束：

- 姿势。
- 动作方向。
- 构图。
- 人物空间关系。

不能覆盖角色身份、场景硬锁和剧情事实。

---

## 12. Shot Generation Package：最终视频生成包

每个 Shot 进入视频模型前应形成完整数据包：

```yaml
shot_id: SH_0030
scene_id: SC_003
beat_ids: [B02]
duration_s: 4

script_evidence:
  event_ids: [E012]
  text: "阿澈松开缰绳，转头看向车厢。"

identity_refs:
  - 阿澈@角色图

scene_refs:
  - 山路正午@场景图
  - 黑色马车@道具图

style_ref:
  - PROJECT_STYLE_01

continuity:
  scene_contract_id: SCC_SC_003_V2
  before_state_id: STATE_0029
  after_state_id: STATE_0030

camera:
  shot_size: medium_close
  angle: front_left
  movement: slow_push
  screen_direction: left_to_right

keyframes:
  first_frame: KF_SH0030_A
  action_panels: [KF_SH0030_B]
  last_frame: KF_SH0030_C

negative_constraints:
  - 不得变为黄昏
  - 不得进入马车
  - 不得新增角色
  - 不得更换服装
```

### 12.1 首尾帧职责

- 首帧保证本镜从正确状态开始。
- 尾帧定义本镜动作完成后的状态。
- 下一镜继承尾帧的语义状态。
- 不同机位时，不要求像素完全相同。
- Match on Action 时，可以共享姿态锚点。

### 12.2 生成顺序

同一场景推荐：

1. 先批准场景锚点。
2. 先批准所有 Shot 首尾关键画格。
3. 再批量生成 Shot 视频。
4. 生成后在相邻镜头上下文中检查。

可以跨 Scene 并行，但同一 Scene 应共享同一版本的 Scene Contract。

---

## 13. AI 场记与连续性校验

系统需要一个独立的 `Continuity Supervisor`，不能把所有责任放进生成提示词。

### 13.1 生成前结构校验

检查：

- Scene ID 是否正确。
- 时间、天气、光线是否继承。
- 角色位置是否有依据变化。
- 服装、伤势、道具是否继承。
- `before_state` 是否兼容上一镜 `after_state`。
- 每个状态变化是否有剧本证据。
- Beat 是否漏拍或重复。

### 13.2 关键帧视觉校验

检查：

- 人脸和角色参考相似度。
- 场景结构相似度。
- 昼夜和色温。
- 人物是否在指定区域。
- 武器、道具、伤口、服装是否正确。
- 人物朝向和视线是否合理。
- 画面运动方向是否符合摄影机轴线。

### 13.3 视频后校验

检查：

- Shot 内人物身份是否漂移。
- 首尾状态是否符合计划。
- 是否出现未经允许的新对象。
- 动作是否完整。
- 与上一镜结尾和下一镜开头能否剪接。
- 实际时长是否满足 Locked Cut。

### 13.4 自动处理策略

```text
结构冲突
→ 不调用模型，先修正状态计划

关键帧失败
→ 只重做当前关键帧

视频失败
→ 保留关键帧，只重做当前 Shot 视频

相邻镜头剪接失败
→ 优先重做较低质量的一个 Shot

多次失败
→ 降级为人工确认，不擅自改剧情
```

---

## 14. 推荐的产品交互

不再把复杂双时间轴作为默认入口。

### 14.1 故事规划模式

界面重点：

```text
场景 SC_003：正午 · 山路马车旁
  B01 抵达马车
    SH_0010 建立全景
    SH_0020 阿澈走近马车
  B02 与车内伊莎对话
    SH_0030 阿澈中景
    SH_0040 伊莎反打
```

每个 Shot 显示：

- 覆盖的 Beat。
- 切镜原因。
- 景别和机位。
- 预计时长。
- Panel 数量。
- 连续性状态。

主要按钮：

- 自动生成镜头方案。
- 接受本场方案。
- 合并镜头。
- 拆分镜头。
- 重新规划本场。
- 生成静态分镜。

### 14.2 Animatic 审片模式

只保留一条主要 Shot 时间轴：

- 上方：Animatic 主预览。
- 下方：按顺序平铺 Shot。
- 选中 Shot：显示其 Panel、脚本证据和连续性状态。
- 脚本作为只读关联信息，不要求用户拖动脚本宽度。
- 用户主要调整 Shot 顺序和时长。

### 14.3 视频生成模式

每个 Shot 显示状态：

```text
规划完成
→ 关键帧生成中
→ 连续性检查
→ 可生成视频
→ 视频生成中
→ 待审
→ 已批准
```

主要按钮：

- 生成当前镜头。
- 生成本场全部镜头。
- 重做失败镜头。
- 选择 Approved Take。
- 合成本场。
- 合成整集。

### 14.4 用户应该看到的主流程

```text
生成镜头方案
→ 生成静态分镜
→ 播放动态分镜
→ 锁定剪辑
→ 生成全部镜头视频
→ 自动合成整集
```

任何内部映射、技术批次和模型容量都不应成为主操作。

---

## 15. 核心数据对象建议

建议至少建立以下独立对象：

- `Episode`
- `Sequence`
- `NarrativeScene`
- `StoryBeat`
- `SceneContinuityContract`
- `CharacterState`
- `BlockingState`
- `Shot`
- `ShotStateTransition`
- `StoryboardPanel`
- `AnimaticCut`
- `ShotGenerationPackage`
- `ShotTake`
- `ContinuityCheck`
- `ReviewDecision`

### 15.1 版本原则

- 所有 Scene Contract、Shot、Panel、Cut 和 Take 均版本化。
- 保存产生新版本，不覆盖旧版本。
- Approved 状态指向一个具体版本。
- 测试数据和历史实验不得删除。
- 重新生成不能抹掉旧媒体。

### 15.2 溯源原则

每个生成产物必须能追溯：

```text
剧本事件
→ Beat
→ Scene Contract
→ Shot
→ Panel
→ Generation Package
→ Take
→ Final Cut
```

---

## 16. 全自动模式的目标架构

```text
章节剧本
  ↓
Script Breakdown Agent
  ↓
Scene / Beat Plan
  ↓
Continuity Supervisor
  ↓
Scene Contract + State Graph
  ↓
Shot Planner
  ↓
Storyboard Generator
  ↓
Static Continuity QA
  ↓
Animatic Editor
  ↓
Cut Lock
  ↓
Shot Video Generator
  ↓
Video Continuity QA
  ↓
Selective Retry
  ↓
Final Assembly
```

### 16.1 无人管理不等于无校验

无人管理模式必须依靠自动闸门：

- 剧情证据闸门。
- Scene Contract 闸门。
- 状态继承闸门。
- 静态视觉闸门。
- 相邻镜头闸门。
- Locked Cut 闸门。

没有通过闸门的任务不能自动进入下一阶段。

### 16.2 自动重试必须可控

- 每个失败原因有明确分类。
- 每次重试只修改失败变量。
- 不允许在重试时放宽剧情事实。
- 达到重试上限后进入待确认。
- 所有失败版本继续保留，供后续分析。

---

## 17. 分阶段实施路线

### Phase 0：现状审计

目标：

- 阅读项目 `AGENTS.md`。
- 检查当前数据结构、时间线、分镜、场景、角色图和视频生成链路。
- 标记可复用能力和应降级为历史实验的能力。
- 不删除任何数据。
- 不直接开始大规模 UI 重构。

交付：

- 现状差距表。
- 可复用接口清单。
- 最小迁移路径。

### Phase 1：连续性数据层

实现：

- `NarrativeScene` 与现有场景概念的映射。
- `SceneContinuityContract`。
- Shot `before_state/action/after_state`。
- 剧情证据字段。
- 连续性规则校验器。
- 版本化保存。

优先验证：

- 正午不能无故变黄昏。
- 马车外不能无故变马车上。
- 受伤、武器、服装、人物位置能够继承。
- 无剧本证据时不允许新增剧情。

### Phase 2：自动镜头规划

实现：

- Scene / Beat 自动拆解。
- Shot List 自动规划。
- 每镜切镜原因。
- Panel 规划。
- 合并、拆分和重新规划。

不要实现：

- 固定 20 镜。
- 固定 15 镜。
- 按抽帧数量创建 Shot。

### Phase 3：静态分镜与 Animatic

实现：

- Scene Anchor Pack。
- Shot 首帧、动作 Panel、尾帧。
- 静态连续性检查。
- 单一 Shot 时间轴 Animatic。
- 临时对白、旁白和音效。
- Lock Cut。

### Phase 4：逐镜视频生成

实现：

- Shot Generation Package。
- 首尾帧生成。
- 逐镜视频。
- 相邻镜头上下文检查。
- Approved Take。
- 单镜重试。

### Phase 5：自动合成与无人管理

实现：

- 自动合成 Scene。
- 自动合成 Episode。
- 自动质量评分。
- 失败镜头选择性重做。
- 任务恢复、幂等和成本预算。

---

## 18. 验收标准

### 18.1 数据验收

- 每个 Shot 关联一个 Scene。
- 每个 Shot 至少关联一个 Beat。
- 每个 Shot 有剧情证据。
- 每个 Shot 有 before/action/after 状态。
- 每次状态变化有合法原因。
- 所有版本可追溯且不覆盖。

### 18.2 连续性验收

- 同一 Scene 中昼夜、天气、光线无无依据跳变。
- 角色位置无无依据跳变。
- 服装、伤势、武器和道具能够继承。
- 人物运动方向和眼神方向可解释。
- 上一镜 after 与下一镜 before 相容。

### 18.3 剧情验收

- 所有 Beat 至少被一个 Shot 覆盖。
- 不重复覆盖导致剧情反复。
- 不漏掉关键 Beat。
- 不新增剧本外关键事实。

### 18.4 产品验收

新用户能够回答：

- 当前在处理哪个 Scene。
- 当前 Shot 为什么存在。
- 当前 Shot 覆盖哪段剧情。
- 当前图是 Shot 还是 Panel。
- 下一步怎样生成视频。
- 失败后会重做什么。

### 18.5 资源验收

- 未通过静态检查的 Shot 不调用视频模型。
- 一个 Shot 失败不重做整集。
- 同一场景共享 Scene Anchor。
- 重试保留通过的关键帧和资产引用。

---

## 19. 明确不做的事情

- 不把整集 5 秒闪回作为正式 Shot 时间线。
- 不用抽帧数量决定镜头数量。
- 不强制每集 20 次切换。
- 不把每个关键画格变成独立 Shot。
- 不使用黑底白字镜号板作为默认拆镜方案。
- 不让用户手工拖动脚本轨来理解剧情关系。
- 不让模型通过新增剧情自动弥补状态矛盾。
- 不用角色外貌长描述替代角色资产引用。
- 不在连续性未通过前批量生成昂贵视频。
- 不删除已有实验、媒体、分镜或版本数据。

---

## 20. 行业参考

1. ScreenSkills - Script Supervisor / Continuity  
   https://www.screenskills.com/job-profiles/browse/film-and-tv-drama/technical/script-supervisor-film-and-tv-drama/

2. ScreenSkills - Script Supervisor Skills  
   https://www.screenskills.com/skills-checklists/scripted-film-and-tv/script-supervisor-department/script-supervisor-skills/

3. ScreenSkills - Previsualisation Artist  
   https://www.screenskills.com/job-profiles/browse/visual-effects-vfx/pre-production/previsualisation-previs-artist/

4. Toon Boom - About Timing  
   https://docs.toonboom.com/help/storyboard-pro-22/storyboard/timing/about-timing.html

5. Toon Boom - About Sequences  
   https://docs.toonboom.com/help/storyboard-pro-25/storyboard/structure/about-sequence.html

6. Toon Boom - About Panels  
   https://docs.toonboom.com/help/storyboard-pro-24/storyboard/structure/about-panel.html

7. Autodesk Flow Production Tracking - Episode / Sequence / Shot hierarchy  
   https://help.autodesk.com/cloudhelp/ENU/SG-Administrator/files/ar-get-started/SG_Administrator_ar_get_started_ar_episode_entity_html.html

8. Autodesk Flow Production Tracking - Cut workflow  
   https://help.autodesk.com/cloudhelp/ENU/SG-Editorial/files/SG_Editorial_ed_import_cut_html.html

9. Autodesk Maya - Animate in Context  
   https://help.autodesk.com/cloudhelp/2026/ENU/Maya-WhatsNew/files/GUID-CAF21860-F3FB-4F1F-8080-EDB51799D832.htm

10. OpenTimelineIO - Timeline / Track / Clip architecture  
    https://opentimelineio.readthedocs.io/en/v0.13/tutorials/architecture.html

11. Runway - Character Plates and Environment Plates  
    https://help.runwayml.com/hc/en-us/articles/26871350018835-How-to-create-longer-videos-and-films

12. Runway - Image References  
    https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References

13. Google Veo - First and Last Frame Video Generation  
    https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-first-and-last-frames

14. Adobe - Master Shot  
    https://www.adobe.com/au/creativecloud/video/production/cinematography/camera-shots-and-angles/master-shot.html

15. Adobe Premiere - Scene Edit Detection  
    https://helpx.adobe.com/premiere/desktop/edit-projects/change-clip-sequence/detect-edit-points-using-scene-edit-detection.html

---

## 21. 给新 Codex 会话的执行要求

新会话必须：

1. 完整阅读本文档。
2. 完整阅读项目根目录 `AGENTS.md`。
3. 先检查 `git status`，保护已有未提交修改。
4. 审计当前项目，不假设旧实现一定正确。
5. 不删除任何现有实验数据、媒体、分镜或历史版本。
6. 不直接把复杂双时间轴继续做大。
7. 先提交差距分析和分阶段计划。
8. 实施时优先从 Phase 1 连续性数据层开始。
9. 使用真实章节做端到端测试。
10. 测试结束后保留测试数据和版本。
11. 不得以“模型会理解”为由省略结构化状态和校验。
12. 后端新增第三方依赖必须同步更新 `backend/requirements.txt`。
13. 数据库变更必须通过幂等 SQL。

---

## 22. 可直接复制的新会话启动提示词

```text
请完整阅读并严格参考：
D:\aiwok\agent-nc-workbanch\docs\AI_EPISODE_CONTINUITY_AND_SHOT_GENERATION_SPEC.md

同时完整阅读项目根目录：
D:\aiwok\agent-nc-workbanch\AGENTS.md

这是当前任务的唯一需求基线，不需要继承旧会话内容。

目标：
按照文档中的 Scene-first、Storyboard-first、Animatic-first、Shot-by-shot generation 方案，重新审视当前项目的剧集分镜与视频生成流程。重点解决：
1. 同一场景上一镜正午、下一镜变黄昏；
2. 上一镜角色在马车外、下一镜无过渡出现在马车上；
3. 角色、服装、伤势、武器、道具和空间位置不连续；
4. 模型擅自加入剧本没有的关键剧情；
5. 抽帧、Panel 和正式 Shot 概念混乱；
6. 用户不知道怎样从剧本得到分镜、再得到最终视频。

执行方式：
1. 先检查 git status、现有代码、数据结构、场景能力、分镜能力、生成链路和历史实验；
2. 不删除、不覆盖任何现有实验数据、视频、图片、分镜和历史版本；
3. 不要立即大规模重构 UI；
4. 先输出“现状与文档目标的差距分析”；
5. 给出分阶段实施计划，优先实施 Phase 1：Scene Continuity Contract、Shot before/action/after 状态、剧情证据和连续性校验器；
6. 状态变化没有剧本证据时，默认继承上一镜，不得自行补剧情；
7. “每批最多15个”只能是技术批次限制，不能成为镜头数量规则；
8. 5秒整集闪回和抽帧实验继续保留，但降级为视觉摘要/候选 Panel，不作为正式分镜时间线；
9. 使用真实章节完成端到端验证，并保留测试数据；
10. 每完成一个阶段，都说明产物是什么、用户下一步做什么、怎样进入最终视频生成。

请先完成现状审计和实施计划；确认范围后，再开始修改。
```

---

## 23. 推荐的首个实施任务

如果希望新会话直接进入一个边界明确的开发任务，可使用：

```text
请参考：
D:\aiwok\agent-nc-workbanch\docs\AI_EPISODE_CONTINUITY_AND_SHOT_GENERATION_SPEC.md

本次只实施 Phase 1“连续性数据层”，不要扩展到完整剪辑 UI：

1. 为剧情场景设计并实现 Scene Continuity Contract；
2. 为 Shot 增加 before_state、action、after_state；
3. 每个 Shot 必须关联 script_evidence；
4. 实现相邻 Shot 状态继承校验；
5. 实现同一 Scene 的时间、天气、光线、角色位置、服装、伤势、武器和道具硬锁校验；
6. 无剧本证据的状态突变必须阻止生成，不得自动补剧情；
7. 所有保存产生新版本，不覆盖或删除旧数据；
8. 使用一个真实章节构造并验证两个回归案例：
   - 正午不能无故变黄昏；
   - 马车外不能无故变马车上；
9. 为后续 Shot Planner、Storyboard Panel、Animatic 和逐镜视频生成保留清晰接口；
10. 完成自动化测试和端到端测试，测试数据必须保留。

开始前先阅读 AGENTS.md、检查 git status，并给出计划；然后直接完成实现和验证。
```
