-- 用户与数据归属（2026-07-29）。
--
-- 现在还没有登录/鉴权，本次只做**数据侧的地基**：先让每一条数据都有主人，
-- 将来接真正的用户系统时只需要把 owner_id 的来源从「默认值」换成「登录态」，
-- 不用再回头给几十张表补列、补回填。
--
-- 只有两个用户：sys_dev（开发）/ sys_admin（管理员）。
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,     -- 登录名即主键：业务表直接存这个字符串，查归属不用 join
    name       TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'dev' CHECK (role IN ('dev', 'admin')),
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE  users IS '用户表（暂无登录，仅 sys_dev/sys_admin 两个内置账号）';
COMMENT ON COLUMN users.id   IS '登录名，同时作为各业务表 owner_id 的取值';
COMMENT ON COLUMN users.role IS 'dev=普通开发 / admin=管理员（工具菜单里的写类工具只放给 admin）';

INSERT INTO users (id, name, role) VALUES
    ('sys_dev',   '系统开发',  'dev'),
    ('sys_admin', '系统管理员', 'admin')
ON CONFLICT (id) DO NOTHING;

-- ═══════════ owner_id：只加在「所有权根表」上 ═══════════
--
-- 根表 = 不带 project_id 的业务表。分镜/正文/要素/附件/任务这些子表**不加**：
-- 它们的归属由 project_id 反查 content_projects.owner_id 得到。
-- 若子表也存一份 owner_id，就存在「分镜的主人 ≠ 其项目的主人」这种不可能状态，
-- 迟早对不上；不存它，这个 bug 就不可能发生。
--
-- 注意 model_profiles / resource_packages / app_config 是系统级配置，
-- 它们的 owner_id 只表示「谁建的档」，不是访问控制。
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'content_projects',
        'kb_entries', 'kb_folders',
        'tag_groups', 'tags',
        'case_groups', 'case_entries',
        'ark_characters',
        'agent_templates', 'skill_packages', 'expert_teams',
        'visual_sops', 'workflows',
        'model_profiles', 'resource_packages', 'app_config'
    ] LOOP
        CONTINUE WHEN to_regclass('public.' || t) IS NULL;

        EXECUTE format(
            'ALTER TABLE %I ADD COLUMN IF NOT EXISTS owner_id TEXT NOT NULL DEFAULT ''sys_dev''', t);
        -- FK 没有 IF NOT EXISTS，自己查一次 pg_constraint 保幂等
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_owner_fk') THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (owner_id) REFERENCES users(id)',
                t, t || '_owner_fk');
        END IF;
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (owner_id)', t || '_owner_idx', t);
    END LOOP;
END $$;

-- ark_characters 早就自带了一个 owner_user（默认 ''、无外键、注释写着「将来接用户系统」）。
-- 不做破坏性变更：保留原列，把已有取值搬进 owner_id。
UPDATE ark_characters SET owner_id = owner_user
 WHERE owner_user <> '' AND owner_id = 'sys_dev'
   AND EXISTS (SELECT 1 FROM users u WHERE u.id = ark_characters.owner_user);

-- ═══════════ 工具调用审计 ═══════════
-- 工具会被技能/工作流/管理台三处调用，出了问题必须能回答「谁在什么时候用什么参数调了它」。
CREATE TABLE IF NOT EXISTS tool_calls (
    id          BIGSERIAL PRIMARY KEY,
    tool        TEXT NOT NULL,
    caller      TEXT NOT NULL DEFAULT 'sys_dev' REFERENCES users(id),
    source      TEXT NOT NULL DEFAULT 'admin_ui',  -- admin_ui | workflow | skill | api
    project_id  BIGINT REFERENCES content_projects(id) ON DELETE SET NULL,
    args        JSONB NOT NULL DEFAULT '{}'::jsonb,
    ok          BOOLEAN NOT NULL DEFAULT TRUE,
    row_count   INT,                                -- 查询类：返回了几行
    error       TEXT,
    duration_ms INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tool_calls_recent_idx ON tool_calls (id DESC);
CREATE INDEX IF NOT EXISTS tool_calls_tool_idx   ON tool_calls (tool, id DESC);
COMMENT ON TABLE tool_calls IS '工具调用审计：谁(caller)从哪(source)用什么参数(args)调了哪个工具、结果如何';
