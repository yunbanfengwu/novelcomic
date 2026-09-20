-- 智能体编排：加排序字段 seq（2026-07-30）
--
-- 列表原来 ORDER BY slug，字母序把「批量首帧」排到「基本信息」前头，跟产线顺序对不上。
-- seq 按**需求优先级 = 产线依赖顺序**赋值：先项目基本盘，再要素设定，再章级分镜/场景，
-- 最后镜级出图与批量组合；音色这类旁支垫底。间隔留 10，中间插新智能体不用全体重排。
--
-- 幂等：**只给 seq=0（未分配）的行赋值**。用户改过的排序不能被容器重启刷回去——
-- 与 36 号「只补缺的 key」同一条纪律。新建的编排默认 0，排在已排序的后面。

ALTER TABLE workflows ADD COLUMN IF NOT EXISTS seq INT NOT NULL DEFAULT 0;

WITH ord(slug, seq) AS (VALUES
  -- ═══ 项目级：基本盘，一切的前置 ═══
  ('a.project-info',        10),  -- 基本信息（题材/风格/受众）
  ('a.project-outline',     20),  -- 卷章目录
  ('a.element-kinds',       30),  -- 要素分类
  ('c.project-bootstrap',   40),  -- 项目级组合：一键把上面三步串起来

  -- ═══ 要素级：角色/场景设定图，出图链路的视觉真值 ═══
  ('a.character-sheet',     50),
  ('a.scene-sheet',         60),

  -- ═══ 章级：分镜两轮 → 场景规划 → 空场景/站位 → 关键格/宫格 ═══
  ('a.chapter-breakdown',   70),
  ('a.chapter-expand',      80),
  ('a.chapter-blocking',    90),
  ('a.scene-empty',        100),
  ('a.scene-blocking',     110),
  ('a.chapter-stills',     120),
  ('a.chapter-grid',       130),
  ('c.chapter-to-storyboard', 140),  -- 章级组合：正文到分镜
  ('c.episode-elements',   150),     -- 本集角色备料（批量角色设定图）
  ('c.episode-scenes',     160),     -- 本集场景备料

  -- ═══ 镜级：分镜 cuts → 提示词 → 首帧 → 尾帧 → 视频 ═══
  ('a.shot-storyboard',    170),
  ('a.shot-prompt',        180),
  ('a.shot-keyframe',      190),
  ('a.shot-lastframe',     200),
  ('a.shot-video',         210),
  ('c.episode-keyframes',  220),     -- 批量首帧
  ('c.episode-video',      230),     -- 批量视频

  -- ═══ 旁支 ═══
  ('a.voice-sample',       240),

  -- ═══ 取数（q.*）：给别的编排当前置用的查询件，排在产线之后 ═══
  ('q.project-info',       250),
  ('q.element',            260),
  ('q.chapter-shots',      270),
  ('q.scene-groups',       280),
  ('q.shot-elements',      290),
  ('ep-batch-keyframe',    300),  -- 早期批量首帧编排（c.episode-keyframes 的前身）

  -- 工作流引擎的两张种子（非智能体编排），垫在最后
  ('element-sheet',        900),
  ('shot-prepare-elements', 910)
)
UPDATE workflows w SET seq = o.seq
  FROM ord o
 WHERE w.slug = o.slug AND w.seq = 0;
