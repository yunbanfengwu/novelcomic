# 启动与验证（已实测跑通 · 2026-07-08）

> 本机开发环境启动手册。数据库：本机 PostgreSQL 18（postgres/123456），库 `novelcomic`（后端启动时自动幂等建表 + seed 公共知识 32 块）。

## 启动

```powershell
# 后端 → http://127.0.0.1:8765（含任务队列 worker）
cd D:\myai\novelcomic\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# 前端 → http://localhost:5173（/api 代理到 8765）
cd D:\myai\novelcomic\frontend
npm run dev
```

## 用户旅程（全部已实测）

1. **贴草稿建项目** `POST /api/projects` → LLM 生成书名/梗概/**文风评估**/**画风评估**/主线/建议章数，自动 seed 4 个数字员工（写作/导演/绘画/配音）
2. **生成目录** `POST /api/projects/{id}/outline {count}` → 每章带故事发展流水账 + 伏笔标注（先问用户要多少章，默认 AI 建议值）
3. **生成核心要素** `POST /api/projects/{id}/elements` → 角色/场景/剧情线/冲突线/伏笔 + **要素×章节出现索引**预填
4. **项目级偏好** `POST /api/projects/{id}/memories` → 如「写作员工用莫言的语言写」(agent_code=writer)
5. **写章节** `POST /api/projects/{id}/chapters/{nid}/write` → 检索管线（流水账+要素状态+出现索引）→ 生成 → 回写三件
6. **拆分镜** `POST /api/projects/{id}/chapters/{nid}/storyboard` → 无正文时按目录故事线直接拆（"直接生成第一章视频"路径），每镜自动装配专业提示词（黑白故事板/关键帧/视频三套）
7. **生成黑白故事板** `POST .../shots/{sid}/storyboard-image` → 异步任务 → 黑白铅笔分镜图**自带镜头运动线箭头**（实测出图见任务队列 id=3）
8. **生成视频** `POST .../shots/{sid}/video` → 异步任务队列

## 第二批功能（2026-07-08 追加，均已实测）

- **要素设定图**：`POST /api/projects/{pid}/elements/{eid}/sheet` → 角色=**角色身份版**（三视图 front/side/back + 特写 + 表情表 + 动作 + 服装细节 + 色板，版式由 `sheet/角色设定图` 知识块驱动）；场景=场景概念图。异步任务回挂 `element.meta.sheet_url` + 附件表。实测陈砚设定图含掌心龙鳞印记特写（来自要素外貌提示词）。
- **系统管理**：`/api/admin/kb*` CRUD + 前端「⚙️ 系统管理」页——知识库·专业提示词块（按镜头语言/运镜/肢体动作/视觉风格/设定图版式分组，可编辑/新增/删除）+ 知识 + 技能三个 tab。
- **分镜工作台角色侧栏**：本章出场角色的设定图横条（Character Design & Casting），角色按要素出现索引过滤。

## 模型管理（第四批 2026-07-08 追加，均已实测）

**模型注册表**（`model_profiles` 表，参考 cocc-work）：文本/图片/视频各挂多档服务商 profile，每用途一个 active；**系统管理 → 🤖 模型配置** tab 可新增/编辑/激活切换（api_key 掩码显示，编辑留空=不改 key）；运行时 `models_registry.get_active(purpose)`（30s 缓存）路由，llm.py/media.py 全部走注册表，.env 只作兜底。

当前档位（key 已从 cocc-work 库静默导入，不经终端）：

| 用途 | active | 备选 |
|---|---|---|
| 文本 | 硅基流动 Qwen2.5-72B ✅ | — |
| 生图 | **火山 Seedream 4.0** ✅（实测出图+落OSS） | Seedream 4.5 / GRSAI nano-banana（额度尽） |
| 视频 | **火山 Seedance 1.5 Pro** ✅（**实测真 I2V**：故事板图作首帧→5s mp4→落OSS） | Seedance 2.0 / GRSAI veo（额度尽） |

导入脚本：`scripts/import_ark_profiles.py`（从 cocc-work ai_worker_v3_pg 库 DB→DB 拷 key，零打印）。
接口形状：ARK 生图=OpenAI 形 `/images/generations`（支持 size）；ARK 视频=`/contents/generations/tasks` 提交+轮询，content 带 first_frame/last_frame 参考图。

## 第三批功能（2026-07-08 追加，均已实测）

- **cocc-work 知识迁移**：14 种视觉风格（写实科幻/姜文/张艺谋/王家卫/诺兰/昆汀/赛博朋克/史诗奇幻/韦斯安德森/黑色电影/吉卜力/新海诚/皮克斯/中国水墨，写实类含"绝非动画"声明+英文锚词+禁忌）+ 24 个动作术语（武术格斗8/超英特技8/轻功武侠4/受击反应4）+ 大特写景别 + 金庸武侠文风。现共 **74 条知识**（style 19/motion 32/camera 10/camera_move 8/sheet 2/quality 2/文风 1）。启动幂等 seed（`knowledge_seed_cocc.py`）。
- **OSS 转存**：生成产物（图/视频）从第三方 CDN（GRSAI 的 aitohumanize.com，有失效风险）自动转存到自己的阿里云 OSS（bucket=taskox，配置来源 cocc-work），失败兜底原 URL 不阻塞。存量迁移脚本 `scripts/migrate_cdn_to_oss.py` 已跑：8 个产物全部转存并验证公开可访问。

## 第五批：视频链路修正 + 真异步队列（2026-07-09，实测出彩色成片）

**三条实测得出的铁律**：
1. **黑白故事板不能作视频首帧**——I2V 首帧视觉锚定强于文字指令，黑白首帧必出黑白片（实测 0% 彩色像素）。正解=**纯文生视频**：故事板的构图/运镜以文字进提示词（camera path/景别/运镜锚词），画风由风格知识块锚定，实测出片彩色 21%（国漫水墨调）、构图与故事板一致。
2. **视频画幅全项目统一 16:9**（ratio 参数强制），故事板尺寸可不一致；实测 1280×720。
3. **ARK 限制：first/last frame 与 reference_image 不能混用**（400 InvalidParameter）；且 reference_image 仅 Seedance 2.0 支持。当前策略：无首帧+Seedance 2.0 时角色/场景设定图走 reference_image，否则角色外貌以文本进提示词。⚠️ 账户对 seedance-2-0 设了推理限额（SetLimitExceeded 已暂停），火山控制台调限后 2.0 参考图通道即生效。

**视频提示词范式（2026-07-09 按 Seedance 官方指南重写）**：中文为主、主体动作前置（模型对前 20-30 词加权最重），结构=主体动作→角色设定（中文简介+英文外貌词）→场景→镜头（景别/运镜/运动线）→画风锚词→全彩+电影级调色→**一致性约束（同一角色/面部稳定/服装不变/发型不乱）**→画质时长。**"图片N是角色X的造型设定图"引用句在提交时动态前置**——仅 Seedance 2.0 且无首帧时参考图真的会传（reference_images 含 name/kind/url），1.5 下靠文字外貌描述。知识召回加 0.12 相似度地板（修"练字"误召回"武打"块）。

**队列真异步**（火山图/视频均异步范式）：worker 3 协程并发；ARK 视频提交即释放 worker（status=waiting_external + external_task_id），独立 poller 每 5s 收割（下载→OSS→回挂附件+分镜 meta）。分镜关联场景要素（scene_element，拆镜时从项目场景清单选），角色+场景设定图 URL 存 shot.meta.reference_urls。

## 已知事项

- GRSAI 生图**不要传 `size`**（400/超时），已在 `media.generate_image` 默认不传
- 后端启动不带 `--reload` 时改码需手动重启
- pgvector 未装（PG18 无此扩展包）：知识召回走 pg_trgm，足够当前用；后续要向量召回再装
- 任务队列为自建 task_queue 表 + FOR UPDATE SKIP LOCKED worker（单进程多协程安全）
