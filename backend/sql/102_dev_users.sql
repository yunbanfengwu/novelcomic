-- ═══════════ 102 · 开发期内置账号（2026-09-17）═══════════
--
-- 35 号迁移只有 sys_dev / sys_admin 两个系统账号。开发阶段不接注册/登录
-- （避免挡 AI 流水线），多用户调试走首页「用户切换」下拉（X-User-Id 头）。
-- 这里补两个真实感测试账号，便于验证「各人只见各人的项目」的归属隔离。
--
-- 注意：历史数据 owner_id 全部是默认值 sys_dev，所以切换到新账号看到空列表是预期行为。

INSERT INTO users (id, name, role) VALUES
    ('zhangsan', '张三', 'dev'),
    ('lisi',     '李四', 'dev')
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE users IS '用户表（开发期无登录：首页下拉切换身份，X-User-Id 头携带）';
