# 音色库与配音链路设计(MVP 已落地 · 2026-07-10 · 音色库 41 条 + 捏音色技能上线)

> 调研语音克隆/TTS 方案,定稿音色资产化设计:**音色库=听觉版的角色设定图**。核心链路:建库(标签+形象图+试听样本)→ 选角(自动匹配+手动+试听)→ 生产(分镜 cue → TTS → 时长回写)。与字幕设计([subtitle-design.md](subtitle-design.md))同源对齐。

## TL;DR

- **用途本质**:角色声音一致性问题,与视觉一致性同构——设定图锚脸,音色库锚声。选型 MVP=**火山豆包语音**(预置上百标签化音色+声音复刻 5-10s 极速克隆,~150元/年/音色槽,与现有火山生态同 key);二期备选=**CosyVoice/IndexTTS 自托管**(zero-shot 参考音频驱动,无槽位费但需 GPU)。
- **数据模型零新表**:音色=kb_entries(kind='voice',meta 带 provider/voice_id/试听音频/形象图/标签);角色绑定=character.meta.voice;音频产物=attachments(kind='audio',与字幕 cue 一一对应)。
- **⚠️ 合规红线**:直接克隆"美国队长"(真人明星/配音演员)声音违反《民法典》声音权(参照肖像权保护)且必被平台审核拦截。正确姿势:**库里存"美国队长式"风格标签(正义/浑厚/领袖感/中年男声),源音色用平台商用授权音色或自有授权音频**——检索体验完全一致,法律干净。

## 一、用途还原(全局理解)

漫剧生产线的配音环节需要解决四件事:
1. **选角**:新角色(如"冷峻的二长老")该用什么声音?——需要可检索的音色资产库(标签:冷峻/威严/老年女声),支持自动匹配+人工改+**试听后拍板**
2. **一致性**:同一角色在全剧 1000 章里声音不能变——绑定关系落在角色要素上,随角色走
3. **生产**:分镜对白(字幕 cue 已含 speaker+text+秒区间)逐条 TTS,产物与镜/cue 挂钩
4. **对齐**:TTS 实测时长回写 cue/镜时长——音频、字幕、画面时长三者同源(subtitle-design 二期闭环)

## 二、调研结论(方案对比)

| 方案 | 能力 | 成本 | 适配 |
|---|---|---|---|
| **火山豆包语音**(MVP 首选) | [上百预置音色](https://www.volcengine.com/docs/6561/1257544)且自带风格标签(傲娇霸总/病弱少女/磁性男声…)天然适合标签检索;[声音复刻](https://www.volcengine.com/product/voicecloning) 5-10s 录音极速克隆,还原专业声优韵律,跨语言;REST+WebSocket 流式 | 音色槽约 [150元/年+1元/月存储](https://www.volcengine.com/docs/6561/1359369),按字符计费,新用户有免费额度 | 与现有 ARK 生态同 key 同计费,model_profiles 加 purpose='tts' 即插 |
| CosyVoice2/3(开源,原调研选型) | [zero-shot 3s 参考音频克隆](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B),3.0 已扩到 1.5B 支持 in-the-wild | GPU 自托管运维 | 二期备选:音色库存 ref_audio,合成时带参考,**无槽位费** |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 1min few-shot 质量高,5s zero-shot | 同上 | 精品角色专属训练 |
| [IndexTTS](https://arxiv.org/html/2502.05512v1)(B站) | 工业级,自称超 CosyVoice2/Fish-Speech/F5-TTS | 同上 | 关注其发展 |

**决策:MVP 用火山**(零运维、标签现成、复刻能力后备),音色库 schema 做成 **provider 无关**(ark/cosyvoice 双模字段),二期可平滑切换或混用。

## 三、数据模型(复用现有架构,零新表)

```jsonc
// 1) 音色库：kb_entries 新 kind='voice'（公共知识,全项目共享;项目级可加专属音色）
{
  "kind": "voice", "category": "timbre",
  "name": "苍穹卫队长（美国队长式）",           // 风格命名,非真人克隆
  "description": "正义、浑厚、领袖感的中年男声，语速沉稳，尾音坚定", // trgm 检索源
  "tags": ["正义", "浑厚", "男声", "领袖", "中年"],
  "meta": {
    "provider": "ark",                    // ark=火山 | cosyvoice=自托管
    "voice_type": "zh_male_XXX",          // 火山音色ID / 复刻槽位 speaker_id
    "ref_audio_url": null,                 // cosyvoice 模式：参考音频（OSS）
    "sample_audio_url": "https://oss…/voice_sample_xxx.mp3",  // 试听样本（固定文案合成）
    "image_url": "https://oss…/voice_face_xxx.jpg",           // 关联形象图
    "gender": "male", "age": "middle", "emotions": ["neutral","angry","solemn"]
  }
}

// 2) 角色绑定：content_elements(character).meta.voice
{ "voice_kb_id": 123, "provider": "ark", "voice_type": "zh_male_XXX", "default_emotion": "solemn" }

// 3) 音频产物：content_attachments kind='audio'（与字幕 cue 一一对应）
{ "node_id": <shot_id>, "kind": "audio",
  "meta": { "cue_index": 1, "speaker": "大长老", "text": "你母亲七年前违反了仪轨。",
            "duration_ms": 3120, "voice_kb_id": 123 } }
```

**关联图片和音频的落法**:直接存 meta URL(OSS 转存),与角色卡 sheet_url 同范式——上传/生成即回挂,前端卡片直接渲染缩略图+▶播放。

## 四、调用链设计

### ① 建库(系统管理 → 🎙 音色库 tab)
```
上传参考音频/挑选火山预置 → OSS 转存 → POST /api/admin/voices (kb entry)
→ 自动生成试听样本（固定文案“寒来暑往，秋收冬藏”用该音色合成 → sample_audio_url）
→ [可选] 声音复刻：POST /api/admin/voices/{id}/clone（火山复刻 API → speaker_id 回写）
→ [可选] 上传形象图 → image_url
```

### ② 选角(角色要素生成后自动 + 随时手动)
```
配音员工技能（voice agent 已 seed）: 角色 brief(性别/年龄/性格)
→ 音色库召回（tags 精确 + description trgm，同分镜知识块召回同款机制）
→ 自动绑定 top1 到 character.meta.voice
→ 前端角色卡：音色下拉（含标签+形象图）+ ▶试听（播 sample_audio_url）
→ [进阶试听] POST /voices/{id}/preview {text: 角色的一句台词} → 即时合成试听（缓存）
```

### ③ 生产(分镜 → 音频,与字幕同源)
```
分镜 cues（speaker+text+秒区间，字幕编译已产出）
→ POST /shots/{id}/voice → 逐 cue：查 speaker 绑定音色 → gen_voice 任务（worker）
→ TTS（火山 REST，情绪参数=cue 所在镜的 mood 映射）→ OSS → attachment(kind=audio) 回挂
→ 实测 duration_ms 回写 cue end / 镜 duration_s（字数÷4 估算的实测修正）
→ 合成层：音轨按全集时间轴偏移混入 + SRT 软字幕同源导出
旁白：项目级默认旁白音色（project.config.narrator_voice_kb_id）
```

## 五、合规红线(必须先说清)

- **不可直接克隆名人/影视角色声音**:《民法典》第1023条声音权参照肖像权保护;火山复刻协议也要求音频来源授权;输出侧平台审核同样会拦
- **正确姿势**:风格标签检索("美国队长式"作为条目名/标签完全没问题)+ 源音色三选一:①火山预置商用音色(已授权)②自录/授权音频复刻 ③开源模型+AI 生成的原创音色
- 库设计里 name 用"风格式命名"(苍穹卫队长/深渊女巫),description 写气质标签——检索与试听体验与"真名人库"完全一致

## 五b、双阶段策略(2026-07-10 定稿):预制选角 → 克隆定妆

**所有角色(含动物)先绑预制音色,真实生产时切声音克隆**——与视觉链的"文字外貌 → 设定图定妆"完全同构:

| 阶段 | 用什么 | 解决什么 |
|---|---|---|
| ① 选角期 | **预制音色库**(已 seed 41 条:26 人声 + 10 动物/生物 + 2 旁白 + AI/器灵),标签召回+试听 | 快速决策"这个角色大概是什么声",零成本试错、可批量 |
| ② 定妆期 | **声音克隆**:选角确认后,用(授权)参考音频克隆出该角色专属声线,`meta.voice` 从预置 voice_type 切换为克隆 speaker_id/ref_audio | 全剧千章的声音唯一性——预置音色可能撞声(两部剧共用),克隆声线是角色资产 |

动物/生物特殊处理:拟人台词走克隆/预置 TTS;**非语言吼鸣**(roar 情绪标签)另配音效素材或用变声处理,音色条目同时是"吼叫风格"的检索键。

## 五c、开源轻量克隆模型调研(2026-07-10)

| 模型 | 参数量 | 克隆方式 | 特点 | 适配判断 |
|---|---|---|---|---|
| [CosyVoice2-0.5B](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B) | 0.5B(Qwen2.5-0.5B 底座) | zero-shot 3s 参考音频 | 中文最强梯队,方言/口音控制,流式;3.0 已到 1.5B | **自托管首选**:小、中文好、ref-audio 模式与音色库 schema 直配 |
| [Spark-TTS](https://arxiv.org/pdf/2503.01710) | 0.5B(Qwen2.5) | zero-shot + **虚拟音色参数化**(性别/音高/语速可控) | 中文 CER 仅次于闭源 Seed-TTS;单流解码免独立声学模型 | 亮点:**无参考音频也能"捏音色"**——预制库条目可以直接用参数捏出来,不依赖火山 |
| [F5-TTS](https://arxiv.org/pdf/2503.01710) | **336M**(最小) | zero-shot 参考音频 | 流匹配非自回归,质量高;不可流式 | 离线批量配音够用,体积最小 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 小 | 5s zero-shot / **1min few-shot 微调** | few-shot 后质量拔尖,社区生态最大 | 主角级角色的"精修定妆"选项 |
| MegaTTS3(字节开源) | ~0.45B | zero-shot(稀疏对齐扩散) | 与 Seed-TTS 同源技术路线 | 观察项 |
| [ZipVoice](https://arxiv.org/pdf/2506.13053) | 小 | zero-shot 流匹配 | 主打快 | 观察项 |

**结论**:开源侧组合拳 = **CosyVoice2-0.5B(通用克隆)+ Spark-TTS(参数捏音色,预制库免火山)+ GPT-SoVITS(主角精修)**,全部单卡可跑;与火山付费线并存,靠 `meta.provider` 双模切换,不锁死任何一家。

## 五d、捏音色技能(2026-07-10 已上线)

**任意角色输入一句简单指令(或不输入),由配音员工按性格自主设计音色并绑定**——选角环节从"人工挑库"升级为"AI 捏+库复用"。

```
POST /api/projects/{pid}/elements/{eid}/voice   {instruction?: "再冷一点/像老船长"}   # 单角色
POST /api/projects/{pid}/voices/cast                                                  # 批量:所有未绑定角色
```

- **装配**:charter(voice 员工) + kb 技能「捏音色」(kind=skill,已 seed,项目级可覆盖) + JSON 输出格式;规则=指令优先 → 性格自主 → 库复用(match_existing) → 三层描述(气质/声学特征/适用) → 参数三档(pitch/speed/energy)
- **复用 or 新建**:LLM 判定库内有契合条目则直接绑定(如 巡夜→"远古深海巨灵");否则 INSERT 项目级 kb voice 条目(预置 voice_type 按性别轮换),绑定落 `character.meta.voice`
- **试听样本**:绑定后 best-effort 合成(欠费/失败不阻塞,仅日志)
- **前端**:角色详情面板 🎙 音色块 = 绑定名 + ▶试听 + 指令输入框 + 捏音色按钮
- **实测**(项目10 深澜纪):巡夜(无指令)正确复用库条目;阿澈(指令"未愈合的伤感+倔强底色")新捏「倔强寻母少女」;批量为三位长老各捏专属音色(冷峻女长老/沉默盲眼长老/威严守旧长老)

## 五e、语速与韵律：基线×场景调制(2026-07-10 调研定稿并落码)

**核心问题**:角色平时说话是正常语速,气氛紧张时要变快变急——这个"变"发生在哪一层?

**调研结论(行业共识)**:音色(timbre)和韵律(prosody)是两个正交维度——音色=谁在说(角色资产,永不变),韵律=怎么说(语速/停顿/重音/气口,**逐句在生成真实音频时决定**)。专业配音导演给演员的就是"per-line direction"(这句要急/这句带哽咽);AI 配音工具的主要痛点恰恰是**把每句当独立单元合成→全片均匀节奏**([Alibaba 工具对比](https://www.alibaba.com/product-insights/ai-anime-voice-dubbing-tools-elevenlabs-vs-dubverse-vs-heygen-do-they-preserve-emotional-timing):"in rapid-fire exchanges where tension builds through accelerating tempo, these tools default to uniform pacing unless manually overridden per line")。

**TTS 引擎的两条控制通道**(CosyVoice2 与火山 doubao 同构):

| 通道 | CosyVoice2([硅基接口](https://docs.siliconflow.cn/cn/api-reference/audio/create-speech)) | 火山 doubao([语音指令文档](https://www.volcengine.com/docs/6561/1871062)) | 特点 |
|---|---|---|---|
| 数值 | `speed` 0.25-4.0 | `speed_ratio` | 确定性时间缩放,时长可预算 |
| 语义 | 自然语言指令+`<|endofprompt|>` 前缀("用急促紧张的语气说") | emotion 参数+语音指令标签(愉悦/悲伤/愤怒/哭腔…) | 驱动停顿/重音/气口,更自然但时长不可精算 |

另:CosyVoice2 支持 `[laughter]`/`[breath]` 非语言标记([论文](https://funaudiollm.github.io/pdf/CosyVoice_2.pdf))——行业痛点"AI 配音没有叹气笑声"的解法。

**本系统落地 = 两层模型,全部确定性零 token**([prosody.py](../../backend/app/services/prosody.py)):

1. **基线层(角色资产)**:音色条目 `params.speed` 三档 → 0.88/1.0/1.12——"平时正常说话的样子",捏音色时由性格决定,永不随场景变
2. **调制层(生成时逐句判定)**:分镜 `mood` 字段(恐惧铺垫/动作爆点/对话交锋…拆分镜时 LLM 已编码场景气氛)关键词映射 → 语速倍率×基线 + 语气指令;句内标点微调(省略号=迟疑放慢/连叹号=上扬提速);终值钳制 0.7-1.4

`resolve_prosody(voice_meta, mood, text)` 是唯一入口:音色库试听样本不传 mood=纯基线;真实配音逐 cue 传所在镜的 mood=按气氛变速变气;`/voices/{id}/sample` 支持传 mood 做"情绪试听"。**为什么规则映射而非每句问 LLM**:mood 已是 LLM 在拆分镜时的产物,气氛→韵律是稳定的领域映射(同分镜 Gate 哲学:创意归 LLM,规则归代码)。

**行业其余难点与对策**:①情绪跨句跳变(分段合成情绪不连贯)→ 同镜 cuts 共享同一 mood 调制,天然镜内一致;②对白时长与画面对齐 → 字数÷4 估算已按 speed=1.0 校准,变速后实际时长≈估算÷speed,二期 TTS 实测时长回写闭环(五章③);③非语言声音缺失 → cuts 的 sfx 字段已有,二期映射 `[laughter]`/`[breath]` 标记注入。

## 五f、试听小样：角色定制 × 5 情绪 × persona 声线（2026-07-12 落码）

**问题**:①旧试听全库共用一句固定文案（"山高路远…"），皇帝与诸葛亮听同一句,无从判断"这声音配不配这角色";②CosyVoice2 预置音色只有寥寥数条、基础音质接近,同性别两角色被轮换到 alex/benjamin 纯属随机,音色与角色气质脱节。

**对策(两层,均零外部依赖、不切火山)**:

1. **persona 声线指令(治"音色不符角色")**([prosody.py](../../backend/app/services/prosody.py) `build_persona`):把音色资产的"谁在说"(gender/age/params.pitch·energy)确定性地翻成一句自然语言发声指令(如"苍老男性的嗓音,低沉、有力"),作为 CosyVoice2 `<|endofprompt|>` 指令常量前缀,让**同一底座预置音色按角色年龄/性别/音高/力度差异化发声**。与场景语气(mood tone)合成进同一条指令(只有一个前缀槽):`用{persona}，{tone}的语气说这句话`。**试听与本番配音走同一条 `resolve_prosody`**,所听即所得。这是不切火山/克隆时"让音色贴合角色"的主要抓手;真正的音色多样性上限仍需火山数百标签音色或声音克隆(见二/五节)。

2. **角色定制 5 情绪小样(治"试听内容雷同、看不出情绪表现力")**([voice_casting.py](../../backend/app/services/voice_casting.py) `generate_emotion_samples`):试听不再是一句通用文案,而是**先大模型按角色身份/时代/语域生成 5 句独有台词**(喜/怒/哀/乐/日常,皇帝有皇帝的口吻),再逐句 TTS——语速=角色基线×情绪因子,语气=persona+情绪 tone。产物存 `meta.samples=[{emotion,text,url,duration_s}]`(并保留 `sample_audio_url`=日常条,供旧前端/音频预检零改动)。非人声(call/hybrid/silent)无"情绪台词",退回单条拟声小样(`sample_plan`)。单条情绪 TTS 失败跳过不阻塞,全失败才报错(多半 TTS 欠费)。

- **入口**:`POST /api/admin/voices/{id}/emotion-samples`(单条);批量 `POST /voices/samples` worker(`VoiceSamplesStep`)对缺 `meta.samples` 的音色逐条生成;前端角色音色块与音色库卡片渲染 5 枚情绪按钮(`EmotionSamples` 组件)。
- **成本提示**:每条音色 = 1 次 LLM(出词) + 最多 5 次 TTS,批量 41 条约 200 次 TTS,属显式管理动作。

## 五g、角色库：身份原型 × 与音色库双向关联（2026-07-12 落码）

> **⚠️ 已废弃（2026-07-14）**：本节描述的"角色库"（`kb_entries` kind='role' + `role_library.py` + `RoleAdmin.tsx`）
> 经确认从未接入生成链路，已整体删除，由**独立表 `ark_characters`**（[sql/10](../../backend/sql/10_ark_characters.sql)、
> [character_library.py](../../backend/app/api/character_library.py)、系统管理独立「角色库」tab）取代——角色 = 形象图 + 名称/描述，
> 形象图单向注册火山私域虚拟人像库，生视频用 `asset://` 可信素材规避"疑似真人"拒收。历史 role 数据由
> [sql/11](../../backend/sql/11_drop_role_library.sql) 幂等清理。下文仅作历史留存。

**动机**:选角需要的不只是"声音",还需要可复用的**身份**——皇帝、军师、女将、老族长、女巫……这些是**身份而非姓名**(皇帝,而非李世民)。身份原型跨剧复用,与音色库同为"设定资产",二者**分开又关联**。

**数据模型(仍零新表)**:角色库 = `kb_entries` kind='role' category='archetype'(全局共享):

```jsonc
{ "kind": "role", "category": "archetype", "name": "皇帝",   // 身份,非姓名
  "description": "威严、多疑、久居上位的中年帝王；语速沉缓，句尾下压，命令感强", // 选角检索源
  "tags": ["威严", "帝王", "中年"],
  "meta": { "gender": "male", "age": "middle",
            "voice_kb_id": 123, "voice_name": "威严帝王",     // 绑定的音色库条目
            "vocal_mode": "speech", "designed_from_voice": false } }
```

**双向关联**([role_library.py](../../backend/app/services/role_library.py)):

| 方向 | 入口 | 行为 |
|---|---|---|
| 据角色→生成/绑定音色 | `POST /roles/{id}/voice` | 大模型据身份气质设计音色规格→复用库中契合条目或新建全局音色→绑定 `role.meta.voice_kb_id`→尽力生成情绪小样 |
| 据音色→反向创建角色 | `POST /voices/{id}/role` | 大模型据声线反推最适合的身份原型→新建 role 条目绑定该音色(`designed_from_voice=true`) |
| 手动绑定 | `POST /roles/{id}/bind-voice` | 把库中已有音色挂到角色 |
| 批量自动搜集 | `POST /roles/collect` | 大模型一次搜集一批**互不重复**的独有身份原型(按 name 去重),从零填库 |

- **前端**:系统管理新增「角色库」tab([RoleAdmin.tsx](../../frontend/src/features/admin/RoleAdmin.tsx)):卡片=身份+气质+标签+绑定音色(有情绪小样则内嵌 5 情绪试听)+[生成/重造音色]+[绑定已有音色下拉]+[删除];顶部[批量自动生成角色]+[＋新增身份]。音色库卡片增[据音色创建角色]。角色库 role→voice 多对一(一条音色可被多个身份复用)。
- **与项目角色的区分**:项目内具体角色仍是 `content_elements`(kind='character',有姓名/状态/分镜台词),其 `meta.voice` 绑定音色;角色库是**跨项目的身份原型资产**,二期可让项目角色"继承自"某身份原型(role_kb_id),自动带出音色与气质基线。

## 六、分期落地

| 期 | 内容 | 前置 |
|---|---|---|
| **MVP** | model_profiles 加 tts 档(火山);seed 10-20 个预置音色(标签化);角色自动/手动绑定+试听;单镜对白 TTS→attachment | 无,随时可做 |
| 二期 | 声音复刻(火山槽位)/CosyVoice ref-audio 双模;情绪参数(mood→emotion);**时长回写闭环**(音频/字幕/镜时长三统一) | MVP |
| 三期 | 合成层混音+SRT 软字幕;唇形(LatentSync 动漫脸实测风险项) | 合成层 |

## 七、来源

- [火山声音复刻产品页](https://www.volcengine.com/product/voicecloning) / [复刻 ICL 最佳实践](https://www.volcengine.com/docs/6561/1204182) / [音色列表](https://www.volcengine.com/docs/6561/1257544) / [计费](https://www.volcengine.com/docs/6561/1359369)
- [CosyVoice2-0.5B](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B) / [CosyVoice 3 论文](https://arxiv.org/html/2505.17589v2) / [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) / [IndexTTS](https://arxiv.org/html/2502.05512v1)
- [2026 TTS 选型对比(火山社区)](https://developer.volcengine.com/articles/7631922681029984306)
