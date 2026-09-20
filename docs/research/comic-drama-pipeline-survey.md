# AI 漫剧生成流水线开源项目调研（调研完成 · 2026-07-08）

> 面向 novelcomic「绘画/导演数字员工」模块：把小说文本转成漫剧（文本→分镜→一致性角色图→出图→图生视频→配音→唇形）各环节的 GitHub 高星开源项目盘点。所有 star 数均于 2026-07-08 实际抓取仓库页核实。另参见 mneme 项目先行调研 `D:\mneme\banckend\docs\arch\professional-video-generation-research-and-architecture.md`（Wan 2.2 选型、先画后动、LoRA 一致性结论与本文互证）。

## TL;DR

- **角色一致性是漫剧成败核心、全行业软肋**：推荐 InstantID/PuLID（锁脸）+ StoryDiffusion（锁风格/服饰）叠加；跨几百镜的终极方案仍是角色/画风 LoRA（mneme 调研结论）。
- **ComfyUI（120k）是全案枢纽**：一致性/出图/图生视频/唇形几乎都有节点，「workflow = 可复用技能包」天然契合绘画员工"挂技能"的形态。
- 端到端一站式平台已出现（Toonflow 11.2k、Jellyfish 5.1k），可作产品参考；但自建可控流水线（方案 B）更契合本项目"数字员工+技能编排"定位。
- 许可雷区：BigBanana CC-NC 非商用且源码冻结、ai-comic-factory 已归档、NovelForge 系 AGPL——只借思路不抄码。

## 一、端到端漫剧/短剧平台（一站式）

| 项目 | Star | 技术栈 | 能力覆盖 | 契合点 / 注意 | 活跃度 |
|---|---|---|---|---|---|
| [Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | **11.2k** | TS/Electron，**API-first** 无本地 GPU | 编剧→分镜→角色→视频 | 完整"小说→动画短剧"编排产品，产品级参考架构 | 2026-06 活跃 |
| [Jellyfish](https://github.com/Forget-C/Jellyfish) | **5.1k** | Python 50%+TS 48%，前后端工作台 | 剧本拆解→结构化分镜→**一致性管理**→镜头→视频→导出 | Python 后端易扩展；**Apache-2.0 唯一可安全复用代码的同类底座** | 2026-04 活跃 |
| [BigBanana-AI-Director](https://github.com/shuyu-labs/BigBanana-AI-Director) | 1.5k | Docker+Web，API-first | Script-to-Asset-to-Keyframe 工业化工作流 | **一致性方法论（定妆照+先画后动）抄它**；⚠️ CC BY-NC-SA 非商用、源码冻结 | 镜像更新中 |
| [LumenX](https://github.com/alibaba/lumenx) | 817 | TS 66%+Python 32%，MIT | 剧本分析→角色定制→分镜→视频合成 | 阿里官方"AI-Native Motion Comic"，国产模型栈+角色三视图，MIT 可复用 | 较新观察 |
| [ai_story](https://github.com/xhongc/ai_story) | 1.0k | Python+Vue | 主题→脚本→分镜→图像→运镜→成片 | 结构清晰易改造；一致性偏弱 | 活跃 |

> 其他：openframe（80，唯一做 FCPXML/EDL 工程导出，AGPL 借思路）；MoneyPrinterTurbo（96.3k，是"关键词→解说短视频"非叙事漫剧，仅作合成参考）。

## 二、文本→漫画/分镜

| 项目 | Star | 技术栈 | 核心能力 | 契合点 |
|---|---|---|---|---|
| [StoryDiffusion](https://github.com/HVision-NKU/StoryDiffusion)（NeurIPS 2024 Spotlight） | **6.4k** | Python，需 GPU，兼容 SD1.5/SDXL | **Consistent Self-Attention 长序列角色/服饰/风格一致**，可出连环画/短视频 | 角色一致性明星方案，可挂任意底模换画风；有 ComfyUI 移植节点 |
| [DiffSensei](https://github.com/jianzongwu/DiffSensei)（CVPR 2025） | 923 | Python，需 GPU，MLLM+扩散 | **多角色可控黑白漫画**：页面布局→角色绘制→对话文字；自带 MangaZero 数据集 | 日漫/黑白漫画向的版面+多角色一致 |
| [ai-comic-factory](https://github.com/jbilcke-hf/ai-comic-factory) | 1.3k | Next.js，API-first 多后端 | LLM 分镜脚本 + SDXL 漫画格 | 多 LLM/渲染后端可插拔的编排范式参考；⚠️ 2025-10 已归档 |

## 三、角色一致性组件（绘画员工的"一致性技能"底层）

| 项目 | Star | 定位 | 用法 |
|---|---|---|---|
| [InstantID](https://github.com/instantX-research/InstantID) | **12.0k** | 单张人脸零样本身份保持 | 主角参考图→跨分镜同一张脸；ComfyUI 原生节点 |
| [IP-Adapter](https://github.com/tencent-ailab/IP-Adapter) | 6.6k | 图像提示适配器（脸/风格/构图通用） | 一致性编排基础组件，被无数流水线依赖 |
| [PuLID](https://github.com/ToTheBeginning/PuLID) | 3.5k | 对比对齐高保真身份，支持 SDXL+FLUX | FLUX 生态下角色一致新锐 |

⚠️ mneme 调研互证：免训练 ID 方案依赖 InsightFace 人脸检测，**动漫脸先天吃亏，只当补丁**；跨几百镜稳一致性的主力仍是**角色/画风 LoRA + 先画后动**（逐镜一致性首帧→I2V）。

## 四、出图编排引擎

| 项目 | Star | 判定 |
|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | **120k** | ✅ **绘画员工编排内核首选**：节点式工作流=可复用技能包，API 触发（POST /prompt→/history 取产物）；一致性/出图/I2V/唇形节点齐全 |
| [Stable-Diffusion-WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | 164k | 偏交互手动创作，自动化编排弱于 ComfyUI；更新趋缓，备选出图后端 |
| diffusers（HF 库） | — | Python 侧直接调底层模型（含 Wan2.2 I2V）的编程接口，自建后端可用 |

## 五、图生视频（"动起来"环节）

| 项目 | Star | 能力 | 判定 |
|---|---|---|---|
| [Wan2.2](https://github.com/Wan-Video/Wan2.2)（阿里） | **16.6k** | T2V/**I2V**/S2V/角色动画，720P@24fps，5B 版可跑 4090，Apache-2.0 | ✅ I2V 主力：一致性定帧→动态镜头 |
| Wan2.1 FLF2V-14B | — | 开源专用**首尾帧**模型（镜头续接） | ✅ 首尾帧主力（mneme 调研结论） |
| [ComfyUI-AnimateDiff-Evolved](https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved) | 3.5k | ComfyUI 内 AnimateDiff，无限长度滑动窗口 | 风格化短动画（漫画质感）最顺滑节点方案 |

## 六、配音（TTS）+ 唇形

| 项目 | Star | 能力 | 判定 |
|---|---|---|---|
| [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | **22.0k** | 零样本音色克隆，9+ 语种/18+ 中文方言，Apache | ✅ 配音首选：每角色固定声线（与角色一致性呼应） |
| [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) | 13.1k | 经典零样本唇形 | 基线：轻量成熟，清晰度一般（配超分） |
| [MuseTalk](https://github.com/TMElyralab/MuseTalk) | 6.1k | 实时潜空间唇形 30fps+ | 实时/高帧率优于 Wav2Lip |
| [LatentSync](https://github.com/bytedance/LatentSync) | 5.9k | 音频条件潜扩散，画质最高，含 anime 示例 | ✅ 成片质量优先 |

⚠️ **最大风险（mneme 调研互证）：动漫脸能否被唇形模型稳定检测/驱动不确定，进入配音环节前必须拿真实画风素材实测。**

## 七、结论：漫剧流水线组合

**方案 A · 快速落地**：拿 Jellyfish（Apache，Python 后端）或 Toonflow 二次开发，参考 LumenX 模块划分与 BigBanana 工作流理念（仅理念，非商用许可）。

**方案 B · 自建可控流水线（推荐，契合数字员工+技能编排）**：

| 环节 | 选型 | 理由 |
|---|---|---|
| ① 文本→分镜脚本 | LLM + 导演员工技能 | 小说切场景，产每镜画面/镜头/对白 prompt（prompt 是编译产物：公共知识块+项目知识+偏好装配） |
| ② 角色一致性 | 角色/画风 LoRA 为主 + InstantID/PuLID 补丁 + StoryDiffusion 锁风格 | 动漫场景免训练方案只当补丁 |
| ③ 出图编排内核 | **ComfyUI** | workflow=技能包，换画风=换底模/LoRA 不改流水线 |
| ④ 图生视频 | **Wan2.2 I2V** + Wan2.1 FLF2V（首尾帧续接）；短动画 AnimateDiff | 先画后动：一致性首帧→I2V，防人物变形公认最优解 |
| ⑤ 配音 | **CosyVoice** | 零样本克隆，每角色固定声线 |
| ⑥ 唇形 | LatentSync（画质）/ Wav2Lip（兜底） | ⚠️ 动漫脸先实测 |
| ⑦ 合成导出 | FFmpeg（+可选 FCPXML，参考 openframe 思路） | 工程导出几乎无人做，是空白差异化点 |

**对 novelcomic 的直接启示**：媒体重活不进平台主体——ComfyUI 舰队做独立确定性媒体引擎，平台（数字员工）只决定"生成什么"（装配提示词/选 workflow/回写产物），引擎负责"可靠生成"；同类 6+ 项目无一用 agent 动态编排流水线（都用固定流水线换稳定性），编排骨架应是确定性 DAG，LLM 只用在分镜拆解与提示词装配。
