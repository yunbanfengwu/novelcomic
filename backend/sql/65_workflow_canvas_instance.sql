-- 画布实例（2026-08-01）：生产态画布的「本对象专属副本」。
--
-- 背景：素材库点一个场景进画布，跑的是模板 `scene-sheet-canvas`。用户在上面拖出新节点、
-- 挪位置、改配置——这些是**这个场景**的编排意图，不该写回被所有场景共用的模板。
-- 于是首次结构改动就从模板 fork 一份独立 slug 的画布，此后该场景永远打开自己那份。
--
-- 为什么是独立 slug 而不是「模板的一个特殊版本」：
--   load_workflow(slug) 不带版本时取的是**最新已发布版**（subflow 引用、别的入口都靠它）。
--   把某个场景的私有画布挤进模板的版本线，别人打开模板就会拿到你的场景图；
--   要躲开就得再加「实例版本不参与 latest」的过滤，等于在版本语义上挖洞。
--   独立 slug 则天然隔离：自己的版本线、自己的运行历史（「上次运行」回填正好是这个场景的），
--   运行/预检/发布全部复用现成引擎，零新增运行时。
--
-- 绑定关系直接落在 workflows 上，不另开表：实例**就是**一张工作流，只是多了「它是谁的副本」。
--
-- ⚠ 叫 subject 不叫 owner：`workflows.owner_id` 早就被用户所有权占了
-- （sql/35，TEXT NOT NULL DEFAULT 'sys_dev' = 这张图是谁建的）。同名两义必然出事——
-- 「按 owner_id IS NULL 过滤掉实例」在那个列上永远筛不出任何东西。
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS origin_slug  TEXT;   -- fork 自哪张模板
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS subject_kind TEXT;   -- element | project | …
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS subject_id   BIGINT; -- 该业务对象的主键
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS canvas_role  TEXT;   -- product slot / variant role

-- 唯一键带上 version：实例本身也是版本化的（同一 slug 可以有多版），
-- 少了 version 这一列，实例存出第二个版本就会撞索引。
-- 「一个对象只有一份实例」由 fork 端点的 find-or-create + 确定性 slug 保证。
DROP INDEX IF EXISTS workflows_instance_subject_idx;
CREATE UNIQUE INDEX IF NOT EXISTS workflows_instance_subject_role_idx
    ON workflows (origin_slug, subject_kind, subject_id, COALESCE(canvas_role,''), version)
    WHERE subject_id IS NOT NULL;

COMMENT ON COLUMN workflows.origin_slug IS
  '画布实例：fork 自哪张模板。NULL = 它自己就是模板/普通编排';
COMMENT ON COLUMN workflows.subject_id IS
  '画布实例所属业务对象的主键（配合 subject_kind）。非空即实例，不进编排列表。'
  '与 owner_id（用户所有权）无关';
