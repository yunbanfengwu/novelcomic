-- ═══════════ 101 · 团队与项目分享（P5 · 2026-09-17）═══════════
--
-- 此前只有"个人所有"（owner_id，35 号迁移）；本迁移加"团队"实体与项目分享：
--   teams          = 团队
--   team_members   = 成员（admin=可管团队 / member=普通成员）
--   team_projects  = 项目分享（can_write 区分只读/可写）
--
-- 设计约束：
-- · 归属仍以 content_projects.owner_id 为根，分享只是**授权视图**——
--   取消分享不迁移数据，owner 永远直通（见 services/teams.decide_access）；
-- · ACL 判定收敛在 services/teams.assert_project_access，后续 API 逐个接入复用；
-- · 全部 IF NOT EXISTS 幂等。

CREATE TABLE IF NOT EXISTS teams (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT   NOT NULL UNIQUE,
    description TEXT,
    created_by  TEXT REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id   BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id   TEXT   NOT NULL REFERENCES users(id),
    role      TEXT   NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS team_projects (
    team_id    BIGINT  NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    project_id BIGINT  NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    can_write  BOOLEAN NOT NULL DEFAULT FALSE,   -- FALSE=只读分享
    shared_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, project_id)
);
CREATE INDEX IF NOT EXISTS team_projects_project_idx ON team_projects (project_id);

COMMENT ON TABLE  teams         IS '团队：多人协作的分组实体（P5 地基）';
COMMENT ON TABLE  team_members  IS '团队成员：admin 可管成员与分享，member 只消费授权';
COMMENT ON TABLE  team_projects IS '项目分享：项目→团队授权视图，can_write=FALSE 只读；owner 权限不受影响';
