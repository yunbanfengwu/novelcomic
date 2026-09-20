-- 弃用旧角色库（2026-07-14）：旧「角色库」是 kb_entries kind='role' 的知识库文件夹，
-- 经确认未接入任何生成链路，已由独立表 ark_characters（sql/10）取代。此处幂等清理历史数据：
--   1) 删除知识库里的「角色库」系统文件夹注册；
--   2) 删除全部 kind='role' 的身份原型条目（音色 kind='voice' 不受影响，仍在用）。
-- 幂等：DELETE 不存在的行为空操作，可随启动重复执行。
DELETE FROM kb_entries WHERE kind = 'role';
DELETE FROM kb_folders WHERE name = 'roles' AND system;
