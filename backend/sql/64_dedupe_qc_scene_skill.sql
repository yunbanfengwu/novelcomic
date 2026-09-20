-- 清理「场景设定图质检」重复行（2026-08-01）。
--
-- 成因：56_workflow_scene_canvas_v6 那条 INSERT 原本写 ON CONFLICT DO NOTHING，但 kb_entries
-- 上没有任何唯一约束（只有 pkey 与普通索引），冲突判定永远不成立——本文件每次后端启动都
-- 新插一条同名技能。skill_packages 又按 kb id 一对一派生 legacy-skill-<kb_id>，于是同名技能
-- 在管理页里列出几十上百条。实测本地开发库 128 条 / 生产每部署一次 +1。
-- 56 号已改成 WHERE NOT EXISTS 止血，这里把历史脏行收干净。
--
-- 保留 id 最小的那条（最早创建的即产线一直在引用的那条），其余连同派生的 skill_packages 删掉。
-- 幂等：跑第二遍时只剩一条，三个 DELETE 都命中 0 行。
--
-- 判重键与 knowledge_seed._seed_skills 一致：scope + kind + agent_code + name。

-- 0) 先把挂在重复包上的绑定改挂到保留包，避免级联删除时把绑定一起带走
WITH keep AS (
  SELECT min(id) AS kb_id FROM kb_entries
   WHERE scope='global' AND kind='skill' AND agent_code='reviewer' AND name='场景设定图质检'
), keep_pkg AS (
  SELECT p.id FROM skill_packages p JOIN keep k ON p.legacy_kb_id = k.kb_id
), dup_pkg AS (
  SELECT p.id FROM skill_packages p
   WHERE p.legacy_kb_id IN (
           SELECT id FROM kb_entries
            WHERE scope='global' AND kind='skill' AND agent_code='reviewer'
              AND name='场景设定图质检')
     AND p.id NOT IN (SELECT id FROM keep_pkg)
)
INSERT INTO agent_skill_bindings(agent_id, skill_id, enabled, config)
SELECT DISTINCT b.agent_id, kp.id, b.enabled, b.config
  FROM agent_skill_bindings b, keep_pkg kp
 WHERE b.skill_id IN (SELECT id FROM dup_pkg)
ON CONFLICT (agent_id, skill_id) DO NOTHING;

WITH keep AS (
  SELECT min(id) AS kb_id FROM kb_entries
   WHERE scope='global' AND kind='skill' AND agent_code='reviewer' AND name='场景设定图质检'
), keep_pkg AS (
  SELECT p.id FROM skill_packages p JOIN keep k ON p.legacy_kb_id = k.kb_id
), dup_pkg AS (
  SELECT p.id FROM skill_packages p
   WHERE p.legacy_kb_id IN (
           SELECT id FROM kb_entries
            WHERE scope='global' AND kind='skill' AND agent_code='reviewer'
              AND name='场景设定图质检')
     AND p.id NOT IN (SELECT id FROM keep_pkg)
)
INSERT INTO agent_template_skills(agent_template_id, skill_id, enabled, config)
SELECT DISTINCT t.agent_template_id, kp.id, t.enabled, t.config
  FROM agent_template_skills t, keep_pkg kp
 WHERE t.skill_id IN (SELECT id FROM dup_pkg)
ON CONFLICT (agent_template_id, skill_id) DO NOTHING;

-- 1) 删派生的重复 skill_packages（级联带走 skill_package_files 与残留绑定）
DELETE FROM skill_packages p
 WHERE p.legacy_kb_id IN (
         SELECT id FROM kb_entries
          WHERE scope='global' AND kind='skill' AND agent_code='reviewer'
            AND name='场景设定图质检')
   AND p.legacy_kb_id <> (
         SELECT min(id) FROM kb_entries
          WHERE scope='global' AND kind='skill' AND agent_code='reviewer'
            AND name='场景设定图质检');

-- 2) 删重复的 kb_entries，只留 id 最小的一条
DELETE FROM kb_entries
 WHERE scope='global' AND kind='skill' AND agent_code='reviewer' AND name='场景设定图质检'
   AND id <> (
         SELECT min(id) FROM kb_entries
          WHERE scope='global' AND kind='skill' AND agent_code='reviewer'
            AND name='场景设定图质检');
