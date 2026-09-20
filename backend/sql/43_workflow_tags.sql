-- 智能体编排：加标签字段 tags（2026-07-30）
--
-- 多值 TEXT[]，一个字段混三个维度，靠约定不靠 schema：
--   阶段：项目 / 要素 / 章节 / 镜头 / 音色 / 工作流 —— **第一个标签兼当列表页分组名**
--   类别：生成 / 查询 —— 查询类（q.*）和生成类分开看；组合编排另加「组合」
--   产物：文本 / 图片 / 视频 / 音频 / 向量 —— 这张编排最终产出什么
-- 「向量」目前没有编排产出，先进前端词表占位（lib/agentTags.ts），出现即可过滤。
--
-- 幂等：只给 tags='{}'（未打标）的行赋值——用户在画布上改过的标签不被容器重启刷回，
-- 与 36/42 号同一条纪律。

ALTER TABLE workflows ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

WITH t(slug, tags) AS (VALUES
  -- ═══ 项目级 ═══
  ('a.project-info',        ARRAY['项目','生成','文本']::text[]),
  ('a.project-outline',     ARRAY['项目','生成','文本']),
  ('a.element-kinds',       ARRAY['项目','生成','文本']),
  ('c.project-bootstrap',   ARRAY['项目','生成','组合','图片']),

  -- ═══ 要素级 ═══
  ('a.character-sheet',     ARRAY['要素','生成','图片']),
  ('a.scene-sheet',         ARRAY['要素','生成','图片']),

  -- ═══ 章级 ═══
  ('a.chapter-breakdown',   ARRAY['章节','生成','文本']),
  ('a.chapter-expand',      ARRAY['章节','生成','文本']),
  ('a.chapter-blocking',    ARRAY['章节','生成','文本']),
  ('a.scene-empty',         ARRAY['章节','生成','图片']),
  ('a.scene-blocking',      ARRAY['章节','生成','图片']),
  ('a.chapter-stills',      ARRAY['章节','生成','文本']),
  ('a.chapter-grid',        ARRAY['章节','生成','图片']),
  ('c.chapter-to-storyboard', ARRAY['章节','生成','组合','文本']),
  ('c.episode-elements',    ARRAY['章节','生成','组合','图片']),
  ('c.episode-scenes',      ARRAY['章节','生成','组合','图片']),

  -- ═══ 镜级 ═══
  ('a.shot-storyboard',     ARRAY['镜头','生成','文本']),
  ('a.shot-prompt',         ARRAY['镜头','生成','文本']),
  ('a.shot-keyframe',       ARRAY['镜头','生成','图片']),
  ('a.shot-lastframe',      ARRAY['镜头','生成','图片']),
  ('a.shot-video',          ARRAY['镜头','生成','视频']),
  ('c.episode-keyframes',   ARRAY['镜头','生成','组合','图片']),
  ('c.episode-video',       ARRAY['镜头','生成','组合','视频']),
  ('ep-batch-keyframe',     ARRAY['镜头','生成','组合','图片']),

  -- ═══ 音色 ═══
  ('a.voice-sample',        ARRAY['音色','生成','音频']),

  -- ═══ 取数（q.*）：查询类，与生成类分开 ═══
  ('q.project-info',        ARRAY['查询','文本']),
  ('q.element',             ARRAY['查询','文本']),
  ('q.chapter-shots',       ARRAY['查询','文本']),
  ('q.scene-groups',        ARRAY['查询','文本']),
  ('q.shot-elements',       ARRAY['查询','文本']),

  -- ═══ 工作流引擎种子 ═══
  ('element-sheet',         ARRAY['工作流','生成','图片']),
  ('shot-prepare-elements', ARRAY['工作流','生成','图片'])
)
UPDATE workflows w SET tags = t.tags
  FROM t
 WHERE w.slug = t.slug AND w.tags = '{}';
