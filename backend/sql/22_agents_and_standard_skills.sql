-- WorkBuddy 式四层模型：标准 Skill → 数字员工 → 专家团 → SOP。
CREATE TABLE IF NOT EXISTS agent_templates (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    charter TEXT NOT NULL DEFAULT '',
    model TEXT,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill_packages (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '0.1.0',
    source_url TEXT,
    license TEXT,
    skill_md TEXT NOT NULL,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'installed'
        CHECK(status IN ('installed','disabled','invalid')),
    legacy_kb_id BIGINT UNIQUE REFERENCES kb_entries(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill_package_files (
    id BIGSERIAL PRIMARY KEY,
    skill_id BIGINT NOT NULL REFERENCES skill_packages(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    sha256 TEXT,
    UNIQUE(skill_id,path)
);

CREATE TABLE IF NOT EXISTS agent_template_skills (
    agent_template_id BIGINT NOT NULL REFERENCES agent_templates(id) ON DELETE CASCADE,
    skill_id BIGINT NOT NULL REFERENCES skill_packages(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(agent_template_id,skill_id)
);

CREATE TABLE IF NOT EXISTS agent_skill_bindings (
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_id BIGINT NOT NULL REFERENCES skill_packages(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(agent_id,skill_id)
);

CREATE TABLE IF NOT EXISTS expert_teams (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    planner_config JSONB NOT NULL DEFAULT '{"mode":"dag","allow_parallel":true}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expert_team_members (
    team_id BIGINT NOT NULL REFERENCES expert_teams(id) ON DELETE CASCADE,
    agent_template_id BIGINT NOT NULL REFERENCES agent_templates(id) ON DELETE CASCADE,
    role_in_team TEXT NOT NULL DEFAULT 'member',
    seq INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(team_id,agent_template_id)
);

INSERT INTO agent_templates(code,name,role,description,charter,model,config)
SELECT DISTINCT ON (a.code) a.code,a.name,a.role,'项目默认数字员工模板',a.charter,a.model,a.config
FROM agents a
WHERE NOT EXISTS (SELECT 1 FROM agent_templates t WHERE t.code=a.code)
ORDER BY a.code,a.id;

-- 旧 kb skill 无损迁移为兼容包；原条目仍保留供旧运行路径读取。
INSERT INTO skill_packages(slug,name,description,version,skill_md,manifest,legacy_kb_id)
SELECT 'legacy-skill-'||e.id,
       e.name,e.description,'0.1.0',
       '---'||E'\n'||'name: legacy-skill-'||e.id||E'\n'
       ||'description: '||replace(replace(e.description,E'\n',' '),':','：')||E'\n'
       ||'---'||E'\n\n# '||e.name||E'\n\n'||e.content,
       jsonb_build_object('format','agentskills.io','legacy',true,
                          'legacy_agent_code',e.agent_code,'category',e.category),
       e.id
FROM kb_entries e
WHERE e.kind='skill'
ON CONFLICT (legacy_kb_id) DO NOTHING;

INSERT INTO agent_template_skills(agent_template_id,skill_id)
SELECT t.id,s.id
FROM skill_packages s
JOIN kb_entries e ON e.id=s.legacy_kb_id
JOIN agent_templates t ON t.code=e.agent_code
ON CONFLICT DO NOTHING;

INSERT INTO agent_skill_bindings(agent_id,skill_id)
SELECT a.id,s.id
FROM skill_packages s
JOIN kb_entries e ON e.id=s.legacy_kb_id
JOIN agents a ON a.code=e.agent_code
ON CONFLICT DO NOTHING;

INSERT INTO expert_teams(code,name,description)
VALUES
 ('project-visual-team','项目视觉专家团','负责项目视觉定位、角色与场景定妆、封面海报。'),
 ('chapter-storyboard-team','章节分镜专家团','负责章节正文、连续性、拆镜、分镜脚本与质检。')
ON CONFLICT(code) DO NOTHING;

INSERT INTO expert_team_members(team_id,agent_template_id,role_in_team,seq)
SELECT team.id,t.id,
       CASE t.code WHEN 'director' THEN 'lead' WHEN 'artist' THEN 'visual' ELSE 'member' END,
       CASE t.code WHEN 'director' THEN 10 WHEN 'artist' THEN 20 ELSE 30 END
FROM expert_teams team JOIN agent_templates t ON t.code IN ('director','artist')
WHERE team.code='project-visual-team'
ON CONFLICT DO NOTHING;

INSERT INTO expert_team_members(team_id,agent_template_id,role_in_team,seq)
SELECT team.id,t.id,
       CASE t.code WHEN 'director' THEN 'lead' WHEN 'writer' THEN 'writer' ELSE 'reviewer' END,
       CASE t.code WHEN 'director' THEN 10 WHEN 'writer' THEN 20 ELSE 30 END
FROM expert_teams team JOIN agent_templates t ON t.code IN ('director','writer')
WHERE team.code='chapter-storyboard-team'
ON CONFLICT DO NOTHING;
