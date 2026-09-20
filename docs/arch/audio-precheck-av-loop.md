# 音色标注 · 音频预检 · 音画闭环（已落地实测 2026-07-11）

> **TL;DR**：补齐"角色发声"三块闭环拼图——①角色卡生成期即标注发声形态 `voice_profile`（vocal_mode/language/timbre_brief，拟人动物=speech、真动物=call、小黄人式=hybrid 自创语言、器物=silent），选角期 LLM 终判回写、存量项目一键补标注；②视频生成前**音频预检**（与提示词质检同范式）：确定性 gate（未捏音色=error、silent 有台词=error、call 有文字台词=warn）+ best-effort 补音频小样（TTS 欠费降级不阻塞）+ LLM 四维评审，结果落 `shot.meta.audio_precheck`；③**图像+音频→视频闭环**：预检顺手产出 `audio_refs`，worker 透传，media 层按 model id 判能力拼 `reference_audio` 模态（仅 Seedance 2.0、有对白才传、必须伴随图、≤3 段总时长≤14s），ARK 拒收音频时剔除重试一次。**预检永不阻断生成**，不合格只降级为"不传参考音频"。已实测：镜 197 两段参考音频（养父/陈砚 CosyVoice 小样）随 2 张设定图提交 Seedance 2.0，成片带音轨转存 OSS。

## 一、角色卡发声标注（voice_profile）

`element.meta.voice_profile = {vocal_mode, language, timbre_brief, source}`，三处写、后者覆盖前者：

| 写入时机 | source | 位置 |
|---|---|---|
| 生成要素时 LLM 判定 | `gen_elements` | `pipeline._ELEMENTS_SYS`（判定依据=故事中实际呈现形态而非物种） |
| 存量批量补标注 | `backfill` | `POST /api/projects/{pid}/elements/annotate-voices`（缺标才标，幂等；输入含对白证据） |
| 捏音色选角终判 | `voice_casting` | `voice_casting.design_voice`（三级依据：voice_profile 设定意图 → `_vocal_evidence` 对白证据事实校验 → 形态兜底） |

绑定 `meta.voice` 冗余 `vocal_mode/language`（预检零 join）；新建音色条目 `kb_entries.meta` 也带两字段，试听文案按模式选（call/hybrid 用拟声长音+语气指令）。样本生成时写 `sample_duration_s_est`（有效字数÷4÷语速，与字幕打轴同惯例，免解析 mp3）。

## 二、音频预检（services/audio_precheck.py）

编排 `precheck_shot_audio`：gate → best-effort 小样 → LLM 评审 → audio_refs → 落 `meta.audio_precheck`。

- **对白解析**：`meta.dialogue`（"角色：台词"，`/` 与**换行**两种分隔并存——实测数据两种都有）+ `cuts[].action` 内嵌 `说："…"`（speaker=subject）；speaker 精确名→名字包含于 subject 兜底。
- **gate（零 token，errors/warns 分层，`合格 = not errors`）**：A1 角色不存在=warn（路人）；A2 未捏音色=error；A3 无 voice_profile=warn；A4 silent 有台词=error、call 有文字台词（剥拟声字后汉字>4）=warn；A5 样本缺失=warn 触发补生成、URL 可达性 head 检查（网络异常=warn 不 error）。
- **best-effort 小样**：缺样本且 speech/hybrid → 走 admin 试听同链路（prosody→TTS→OSS→kb 回写+时长估算）；TTS 403/欠费 → `degraded=true, tts_error`，不影响合格判定。
- **LLM 评审**（gate 干净且未降级才评，`purpose="review"`）：音色气质×台词 / 形态×台词形态 / 语言一致 / 情绪覆盖 mood；≥80 合格；**无重构环节**（音色重构=重新捏音色，只给修改建议）；不合格仅记 warn 不阻断。
- **audio_refs 组装**：出场顺序去重 → 仅 speech/hybrid 且样本可用 → 单段 2-15s、≤3 段、累计 ≤14s（超限截断记 warn）。
- **接入**：worker 镜级生成前置③（gen_video，不受 prompt_overridden 豁免，异常只 log 不传音频）；手动 `POST /shots/{id}/audio-precheck`。

## 三、音画闭环（media._build_ark_content）

content 拼装抽成纯函数（可 dry-run 断言，7 用例已过）：

- `use_audio = audio_refs 且 "seedance-2" in model 且 (首帧|尾帧|参考图)`——ARK 硬约束**音频必须伴随至少 1 张图**，降级级联纯文本终态自动掐音频，worker 无需特判；
- 模态：`{"type":"audio_url","audio_url":{"url":…},"role":"reference_audio"}`（≤3 段）；提示词前置 `@audioN 是角色「X」的声线参考…按参考音频的音色与节奏开口，台词内容以提示词为准`；
- **音频级回退**：提交 400 且响应提及 audio → 剔除音频重试一次（镜像生图去参考图回退）；
- worker 降级级联三次提交全透传 `audio_refs`。

## 四、模型档守护（models_registry）

seed 新增「火山 Seedance 2.0」条目带两个守护：`seed_key="model"`（按 purpose+model_name 判重——默认 purpose+provider 会被已有 ark video 档挡住；**不能全局改判重**，否则 text 档 Qwen 会被重插激活压掉 doubao 兜底）；`no_auto_active=True`（跳过"ARK 有 key 即激活"，绝不压掉现 active 档）。实际库中 2.0 档（id=7，cocc-work 导入）已存在且 active，判重正确跳过未重复。音频能力判定沿用 `"seedance-2" in model_name`，fast 版天然命中。

## 五、实测记录（2026-07-11）

- TTS 余额恢复确认（30001 解除），样本真实生成转存 OSS；
- 项目 1 补标注 5 角色（守碑人/国师零台词判 silent，证据驱动）；批量选角复用契合音色，binding 带 vocal_mode/language；
- 镜 30 预检：未捏音色=error 路径 ✓ → 选角后 合格/得分80/自动补小样/refs=1 ✓；QA 镜 288（新建保留）：silent 有台词=error ✓；
- **task 117**（镜 197 无 refs 时）零回归成片；**task 118**（修复换行分隔 bug 后 refs=2）：2 段 reference_audio + 2 张 reference_image 提交 Seedance 2.0 → 成片带音轨 → OSS。声线贴合度靠人耳对比两版验收。

## 六、已知边界

- reference_audio 只定声线/节奏驱动口型，**非端到端音色克隆**（ARK 无 voice_clone 参数）；台词准确性以提示词为准；
- call（兽鸣）样本是 TTS 拟声占位，不作 reference_audio，成片兽吼走音效素材层（见 voice-timbre-design 五b）；
- 时长是估算值，失误由 14s 余量+ARK 400+音频级回退三层兜底；
- 前端展示（角色卡形态标签/预检 tag/试听/生成确认）下一轮。
