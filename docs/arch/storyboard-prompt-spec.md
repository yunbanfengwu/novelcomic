# 分镜故事板提示词规范(定稿 · 2026-07-09 · 已实现并实测)

> 定义 novelcomic 分镜环节的**专业颗粒度标准**:哪些电影字段保留、哪些技术参数效果化转译、AI 视频三硬约束、装配规则与零 token 校验 Gate。调研来源:狄金斯《1917》《银翼杀手2049》公开访谈(焦段/布光实拆)、北电拉片法、StudioBinder/Boords Shot List 字段。金标准样例见 [../samples/storyboard-golden-sample.md](../samples/storyboard-golden-sample.md)。

## TL;DR

- **颗粒度原则:拉片字段的叙事层全保留,技术层做"效果化转译"**——景别/角度/运镜/焦段感原样进提示词(模型有统计学响应);光圈 T 值→"浅景深",灯具方案→"该灯产生的画面效果"(如 256 盏 Fresnel 环形追逐 → "环绕流动的水波光")。
- **AI 视频三硬约束**:①一镜只写**一个相机动作 + 一个主体动作**(复合运镜必崩);②单镜 **2–8s**,时长曲线即情绪(恐惧慢/搏斗快/释放放长);③**两段式**——首帧提示词(文生图,含全部静态信息)+ 视频提示词(图生视频,只写运动增量)。
- **剪辑节奏 ASL 3–4s**:静止镜 ≤4s、场景内 ≥3 镜远近交替硬切、平均镜长 >4.5s 打回;AI 默认慢漂移用 pace 块显式对抗(固定镜"机位完全锁定"/动作镜"真实速度禁止慢动作")。
- **身份层每镜重复**:角色外貌块由装配器注入每一镜,是文本侧一致性的唯一手段(与设定图参考互补)。
- 分镜 meta 新增七字段:`angle`(角度)/`lens_feel`(焦段感)/`lighting`(光线)/`palette`(色调)/`mood`(情绪功能)/`action`(主体单动作)/`element_ids`(关联要素);`scale` 收窄为纯景别。
- 校验 Gate 零 token:必填/枚举/时长界/连续同景别≤2/单动作启发式/固定镜头≤50%/相邻信息去重,拆镜后自动跑,error 打回重拆。
- **分镜级要素关联**:每镜 `element_ids` + `element_appearances`(shot 级)双落——角色/场景设定图按镜召回作参考图,不再只挂章节。
- **员工=四层装配**:章程(agents 表)+技能(kb kind=skill,项目覆盖全局)+知识块(按镜内容召回)+项目偏好(级联)→ 编译成最终系统提示词;枚举与输出格式由代码强制(校验 Gate 单一来源)。
- **故事板双轨**:黑白板=可选人审构图层,不进生成链(实测作 I2V 首帧必出黑白片);生产链=彩色首帧关键帧(gen_keyframe)→I2V,画风三重锁(style 块入首帧提示词+设定图参考+视频提示词画风锚词)。

## 一、颗粒度决策(为什么是这一档)

| 层 | 专业拉片级(狄金斯访谈) | 本项目采用 | 理由 |
|---|---|---|---|
| 景别/角度/构图 | ✅ | ✅ 原样保留 | 模型响应最强的控制杠杆 |
| 运镜 | 复合运动(Trinity 一镜到底) | **单一动作** | 当前视频模型最大崩点 |
| 焦段 | 40mm Signature Prime | ✅ 保留焦段感词 | 24mm 广角空间感/85mm 长焦压缩是廉价透视控制;《1917》全片仅 40/35/47 三焦段——**克制即专业,默认焦段+有理由才偏离** |
| 光圈 | T1.8 | ❌ 转译"浅景深/背景虚化" | 模型不懂 T 值,懂效果 |
| 布光 | 灯具/瓦数/位置 | ❌ 转译画面光效 | 写"环绕流动的水波光"而非"256 盏 Fresnel" |
| 时长 | 任意 | **2–8s 硬界** | 视频模型单镜上限;节奏=情绪的载体 |

**每镜只回答一个问题**(他在哪?/他看到什么?/他什么反应?)——回答两个问题的镜头必须拆成两个。关键信息独占一镜(哪怕只有 2s 的大特写)。

## 二、分镜字段规范(content_nodes.meta, kind=shot)

```jsonc
{
  "shot_no": 1, "scene": "场景/时间/地点", "scene_element": "关联场景要素名",
  "scale": "景别",          // 大远景/远景/全景/中景/近景/特写/大特写
  "angle": "角度",          // 平视/仰拍/俯拍/鸟瞰/过肩/主观POV/荷兰角
  "camera_move": "运镜",    // 固定/推镜/拉镜/摇镜/移镜/跟拍/升降镜头/手持晃动/环绕镜头 —— 单选!
  "camera_path": "运动线(箭头语言)",
  "lens_feel": "焦段感",    // 16mm超广角/24mm广角/35mm标准/50mm标准/85mm长焦/100mm微距
  "lighting": "光线",       // 画面光效描述:光源方向+质感(如"晨昏侧逆光勾轮廓,丁达尔光柱")
  "palette": "色调",        // 主色调+冷暖(如"冷蓝主调,一点淡金")
  "mood": "情绪功能",       // 本镜在情绪曲线上的职责(恐惧铺垫/动作爆点/情绪支点/释放)
  "action": "主体单动作",   // 一个动作,一句话
  "duration_s": 4,          // 2-8
  "description": "画面(首帧可独立绘制)", "dialogue": "无", "sfx": "无",
  "motion_hint": "动作关键词(召回 motion 块用)", "characters": ["出场角色名"],
  // ↓ 装配器写回
  "storyboard_prompt": "...", "image_prompt": "...", "video_prompt": "...", "reference_images": []
}
```

**景别×角度=情绪** 速查(进知识库 angle 块 content):特写+俯拍=脆弱恐惧;特写+仰拍=威压崇拜;中景+荷兰角=日常不安;远景+鸟瞰=渺小与地理;垂直俯拍↔仰拍对切=情绪反转(坠落→翱翔)。

## 三、装配规则(prompt=编译产物)

```
storyboard_prompt(黑白故事板) = 黑白分镜块 + 景别块 + 角度块 + 画面 + 运动线标注
image_prompt(彩色首帧)      = 画面+action + 画风块 + 景别/角度/焦段/光线块 + 场景块 + 身份层(角色外貌) + 色调 + 质量词
video_prompt(运动增量)      = 主体动作前置 + 身份层 + 场景 + 镜头(景别/角度/运镜/运动线) + 焦段/光线锚词 + 画风锚词 + 一致性约束 + 时长
```

- 身份层(角色外貌提示词)**每镜必注入**,不省略;设定图 URL 进 reference_images。
- 视频提示词首 20–30 词权重最高 → 主体+动作永远最前。
- 节奏自检:输出分镜表后检查时长曲线是否与情绪段落对应(紧张段 1-3s、铺垫段 4-6s、释放段 6-8s)。

## 四、校验 Gate(零 token,拆镜后自动跑)

| # | 规则 | 级别 |
|---|---|---|
| G1 | 必填字段齐:scale/angle/camera_move/lens_feel/lighting/action/duration_s/description | error |
| G2 | 枚举合法:scale/angle/camera_move/lens_feel 在白名单内 | error |
| G3 | 2 ≤ duration_s ≤ 8 | error(自动夹紧) |
| G4 | camera_move 单选(不含"+"、"、"、"然后"等复合迹象) | error |
| G5 | 连续同景别 ≤ 2 | warn |
| G6 | characters 中的名字在项目 character 要素中存在 | warn |
| G7 | action 单动作启发式(不含两个及以上动词短语连接词"接着/然后/再") | warn |
| G8 | 总镜头数 12–24;全片时长曲线非恒定值(至少两档时长) | warn |
| G9 | 固定镜头 ≤ 全片 50% | error |
| G10 | 相邻镜 action 相似度 > 0.7(信息重复) | warn |
| G11 | **固定镜头 > 4s**(视觉疲劳头号来源) | error |
| G12 | **平均镜长(ASL)> 4.5s**(当代电影 ASL 2.5–4s,动作段 <2s) | error |
| G13 | 单场景 < 3 镜(缺硬切交替) | warn |

error 打回重拆(带违规明细重试一次),warn 落 meta.validation 供前端展示。

**节奏铁律(2026-07-09 增补)**:①静止镜头一律 ≤4s,>4s 必须是运动镜头且有叙事理由(一镜到底只留给情绪释放);②同一场景至少拆 3 镜,远近景别交替硬切(特写↔全景),对话正反打,关键情绪插反应镜——观众注意力靠切换喂养;③**AI 视频默认输出缓慢漂移运镜+慢动作,必须显式对抗**:固定镜写"机位完全锁定",动作镜写"真实速度、禁止慢动作、禁止缓慢漂移"(pace 知识块,按 mood/motion_hint 召回);action 字段必须带速度感("猛地转身"而非"转身")。

**九宫格预览(表达层工具)**:`POST /chapters/{id}/storyboard-grid` 把前 9 镜编成一张 3×3 黑白格(每格带镜号/景别/运镜),一图审全场构图与节奏——它是给人看的,不进视频生成链;数据层保持"章→镜"平铺 + scene 字段分组,不引入"子分镜"层(镜头即剪切间的原子单位,行业无更细粒度)。

## 五、故事板双轨决策(黑白 vs 彩色,2026-07-09 拍板)

| | 黑白故事板 | 彩色首帧关键帧 |
|---|---|---|
| 职责 | 人审构图/运镜的**预览层**,可选 | 生产链 I2V 的**第一帧**,必经 |
| 优点 | 便宜快、聚焦构图、不锚定风格 | I2V 首帧=视频第一帧,画风构图双锁定,一致性最强 |
| 缺点 | **实测作 I2V 首帧必出黑白片**;多一轮成本 | 构图错需重生成(成本略高) |

社区共识(2026):规模化 AI 视频生产收敛为**三层栈**——故事板静图层→生成模型层→编排层;I2V 模式因"首帧即第一帧+持续引用防色漂"成为一致性最佳实践;黑白草图仅在研究管线(如 DrawVideo)中作结构输入。本项目结论:**黑白板降级为可选预览,彩色首帧为生产正轨**;"最终视频符合全文画风"由三重锁保证:①style 块编译进首帧提示词 ②角色/场景设定图作生成参考 ③视频提示词带画风锚词。

## 六、来源资料

- 《1917》:全片 ~90% 用 Signature Prime 40mm,地堡 35mm(幽闭)、河流 47mm(减背景)——[Y.M.Cinema](https://ymcinema.com/2020/02/23/roger-deakins-summarizes-the-making-of-1917/) / [British Cinematographer](https://britishcinematographer.co.uk/exclusive-interview-roger-deakins-cbe-bsc-asc-on-1917-bc97/)
- 《银翼杀手2049》:人物 32mm、巨景 14/16mm;华莱士办公室 256×300W Fresnel 环形追逐+8×10K 打水面反射 → "流动水波光"——[PremiumBeat 布光拆解](https://www.premiumbeat.com/blog/blade-runner-2049-lighting-cinematography/) / [狄金斯官方论坛](https://www.rogerdeakins.com/forums/topic/focal-length-on-blade-runner-2049-shot/)
- 拉片法与 Shot List 字段:[StudioBinder 镜头大全](https://www.studiobinder.com/blog/ultimate-guide-to-camera-shots/) / [Boords 16 种镜头角度](https://boords.com/blog/16-types-of-camera-shots-and-angles-with-gifs) / [知乎:什么是拉片](https://zhuanlan.zhihu.com/p/466189351)
- AI 提示词公式:[AnimationGuides 镜头角度提示词指南](https://www.animationguides.com/guide-camera-angles-shots-ai/)
- 故事板双轨依据:[2026 AI Video Pipeline 三层栈](https://aividpipeline.com/blog/ai-video-pipeline-complete-guide) / [I2V 首帧一致性最佳实践](https://www.mindstudio.ai/blog/storyboards-character-sheets-ai-video-generation) / [DrawVideo:黑白草图作结构输入(研究管线)](https://arxiv.org/html/2605.23508v1) / [参考图模型横评](https://app.cinevva.com/guides/long-reference-video-models)
