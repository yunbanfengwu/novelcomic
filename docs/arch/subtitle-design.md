# 视频字幕设计(调研定稿 · 2026-07-10 · 未改码)

> 调研字幕文件格式与行业实践,定稿本项目字幕方案:**字幕=分镜数据的编译产物**(继提示词/时间轴脚本之后第三次运用该哲学)。独立文件、与时间轴挂钩、与分镜挂钩,永不手工打轴。

## TL;DR

- **行业现状**:短剧字幕大多在剪辑期烧录成硬字幕,后续要复用只能 OCR 反提——结构丢失。本项目**天然领先**:对白与秒区间已经结构化地存在于分镜表(dialogue + cuts),字幕只是再编译一次。
- **格式选型**:Web 播放器用 **WebVTT**(浏览器 `<track>` 原生);成片交付用 **SRT**(兼容之王,mp4 可 `mov_text` 软内挂);需要样式/发布烧录时输出 ASS。同一编译器,三种序列化。
- **三层挂钩**:字幕 cue 存 shot.meta(镜内相对时间)→ 镜级 VTT(独立文件,随分镜同生死)→ 章级 VTT/SRT(按分镜时长累加偏移,自动对齐全集时间轴)。分镜重排/改时长 → 重编译即可。

## 一、格式对比(调研结论)

| 格式 | 定位 | 本项目用途 |
|---|---|---|
| **WebVTT** | 浏览器原生(`<track kind="subtitles">`),HLS/DASH 流媒体标准,cue 可带 id | **Web 工作台播放**(镜级+章级) |
| **SRT** | 最大兼容(序号+时间区间+文本),mp4 软内挂 `-c:s mov_text` | **成片交付**(软字幕/外挂发行) |
| ASS/SSA | 样式/特效(字体/位置/卡拉OK) | 发布层烧录需求时的可选输出 |

硬字幕(烧进画面)只作为**发布层的最后一步选项**,生产素材永不烧录(与水印同原则)。

## 二、数据模型(与分镜挂钩)

```jsonc
// shot.meta.subtitles —— 镜内相对时间(秒),编译产物,人工可改
[
  { "start": 0.0, "end": 3.0, "text": "你母亲七年前违反了仪轨。", "speaker": "大长老" },
  { "start": 3.0, "end": 5.0, "text": "她是为了救当年被困的采集队。", "speaker": "阿澈" }
]
```

**编译规则(零 token,确定性)**:
- 有 cuts:遍历切,含对白(`说：“…”`)的切 → 一条 cue,start/end=该切的秒区间,speaker=切主体——**cuts 的时长校准(字数÷4)已经把打轴做完了**;
- 无 cuts 的对白镜:整镜一条 cue(多句按 `/` 分拆均分);
- 无对白镜:无 cue。
- 编译时机:拆镜后自动生成;`meta.subtitles` 已存在且被人工改过则不覆盖(force 参数重编译)。

## 三、接口设计(独立文件 + 时间轴挂钩)

```
GET /api/projects/{pid}/shots/{sid}/subtitle.vtt        # 镜级:相对时间,cue id=shot{no}-{i}
GET /api/projects/{pid}/chapters/{nid}/subtitle.vtt     # 章级:按 shot_no 顺序累加 duration_s 作偏移
GET /api/projects/{pid}/chapters/{nid}/subtitle.srt     # 同上,SRT 序列化(成片交付)
```

- **章级时间轴对齐**:全集时间 = 前序镜 duration_s 之和 + 镜内相对时间——分镜增删/重排/改时长后重新请求即自动对齐,**永不手工打轴**;
- **与分镜反查**:VTT cue id 携带镜号(`shot15-2`),前端点字幕可跳转对应分镜;
- **前端挂载**:单镜播放器 `<track src=镜级vtt>`;"播放整集"逐镜切换 video,各挂各的镜级 vtt(与分镜同生死,天然不串轴);
- **成片阶段**:FFmpeg 合成时 `-i chapter.srt -c:s mov_text` 软内挂,或外挂发行;需烧录时走 ASS burn-in(发布层)。

## 四、与配音的关系(二期)

配音(CosyVoice)落地后,TTS 实测时长回写 cue 的 end 与后续镜的时长——**字幕与音频同源对齐**(都由分镜表驱动,配音时长是对"字数÷4 估算"的实测修正)。届时时长校准链变为:估算(拆镜)→ TTS 实测(配音)→ 回写(字幕/分镜时长/成片)。

## 五、来源

- [字幕格式对比 SRT/WebVTT/ASS/TTML (2026)](https://vocova.app/blog/subtitle-file-formats-complete-guide) / [SRT vs WebVTT 平台兼容](https://vocova.app/blog/srt-vs-vtt)
- [FFmpeg 嵌入字幕(软/硬)完整指南](https://blog.eimoon.com/p/how-to-embed-srt-subtitles-with-ffmpeg/) / [MP4 字幕嵌入指南(pyVideoTrans)](https://pyvideotrans.com/_posts/subtitles-srt-ass-ffmpeg)
- [短剧硬字幕 OCR 反提链路(火山)](https://developer.volcengine.com/articles/7633793623414276102) —— 行业"没有独立字幕文件"的反面教材,佐证结构化源头的价值
- [字幕格式平台兼容踩坑指南](https://www.toolbox365.cn/tutorials/subtitle-format-platform-compatibility/)
