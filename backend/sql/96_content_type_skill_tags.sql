-- 内容类型路由：技能包与知识条目共用标签 code（如 brand_ad、film_drama）。
-- 空标签表示通用能力；视频项目只会召回显式匹配其类型的技能。
ALTER TABLE skill_packages ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';
UPDATE skill_packages s
SET tags = e.tags
FROM kb_entries e
WHERE e.id = s.legacy_kb_id
  AND (s.tags IS NULL OR s.tags = '{}')
  AND e.tags IS NOT NULL AND e.tags <> '{}';
CREATE INDEX IF NOT EXISTS skill_packages_tags_idx ON skill_packages USING gin(tags);
