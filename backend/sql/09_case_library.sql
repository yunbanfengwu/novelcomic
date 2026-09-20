-- 案例库：优秀生成案例的浏览型资料（标题+生成结果+提示词+参考素材）。
-- 与 kb_entries 知识库完全分离：案例是「原始示例」而非提炼后的知识，
-- 规划引擎的召回（recall_blocks 等）不感知本表——仅供人工浏览参考与后台维护。
-- 后期项目内产出的优秀镜头可发布进来（source='project' + project_id/shot_id 溯源）。
CREATE TABLE IF NOT EXISTS case_groups (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,                       -- 分组名，如「游戏制作 · 场景设计」
    seq         INT  NOT NULL DEFAULT 0,             -- 展示顺序，小者在前
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS case_entries (
    id           SERIAL PRIMARY KEY,
    group_id     INT REFERENCES case_groups(id) ON DELETE SET NULL,
    title        TEXT NOT NULL DEFAULT '',           -- 方向/案例名，如「动效复现」
    prompt       TEXT NOT NULL DEFAULT '',           -- 提示词原文
    note         TEXT NOT NULL DEFAULT '',           -- 补充说明（可空）
    result_kind  TEXT NOT NULL DEFAULT 'video',      -- 生成结果类型：video | image
    result_url   TEXT NOT NULL DEFAULT '',           -- 生成结果 OSS URL
    result_cover TEXT NOT NULL DEFAULT '',           -- 视频封面 OSS URL（图片结果留空）
    refs         JSONB NOT NULL DEFAULT '[]'::jsonb, -- 参考素材 [{kind:image|video|audio, label, url, cover}]
    source       TEXT NOT NULL DEFAULT 'manual',     -- manual=后台手建 | project=项目镜头发布
    project_id   INT,                                -- 发布来源项目（source='project' 时）
    shot_id      INT,                                -- 发布来源镜头（source='project' 时）
    seq          INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE case_entries IS '案例库条目：浏览型生成案例，不参与知识召回；refs 为带标签的参考素材列表';
