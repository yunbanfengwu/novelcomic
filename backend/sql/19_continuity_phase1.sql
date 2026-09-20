-- Phase 1 连续性数据层。全部新增表，不搬迁、不覆盖旧分镜 meta。
CREATE TABLE IF NOT EXISTS narrative_scenes (
    id          BIGSERIAL PRIMARY KEY,
    project_id  BIGINT NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    chapter_id  BIGINT NOT NULL REFERENCES content_nodes(id) ON DELETE CASCADE,
    scene_code  TEXT NOT NULL,
    title       TEXT NOT NULL,
    seq         INT NOT NULL,
    source_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chapter_id, scene_code)
);

CREATE TABLE IF NOT EXISTS scene_continuity_contracts (
    id                 BIGSERIAL PRIMARY KEY,
    narrative_scene_id BIGINT NOT NULL REFERENCES narrative_scenes(id) ON DELETE CASCADE,
    version            INT NOT NULL,
    hard_locks         JSONB NOT NULL,
    initial_state      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status             TEXT NOT NULL DEFAULT 'draft',
    parent_version_id  BIGINT REFERENCES scene_continuity_contracts(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (narrative_scene_id, version)
);

CREATE TABLE IF NOT EXISTS story_beats (
    id                 BIGSERIAL PRIMARY KEY,
    narrative_scene_id BIGINT NOT NULL REFERENCES narrative_scenes(id) ON DELETE CASCADE,
    beat_code          TEXT NOT NULL,
    seq                INT NOT NULL,
    description        TEXT NOT NULL,
    script_evidence    JSONB NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (narrative_scene_id, beat_code)
);

CREATE TABLE IF NOT EXISTS shot_continuity_states (
    id                BIGSERIAL PRIMARY KEY,
    shot_id           BIGINT NOT NULL REFERENCES content_nodes(id) ON DELETE CASCADE,
    version           INT NOT NULL,
    scene_contract_id BIGINT NOT NULL REFERENCES scene_continuity_contracts(id) ON DELETE RESTRICT,
    beat_ids          BIGINT[] NOT NULL,
    script_evidence   JSONB NOT NULL,
    before_state      JSONB NOT NULL,
    action_transition JSONB NOT NULL,
    after_state       JSONB NOT NULL,
    status            TEXT NOT NULL DEFAULT 'draft',
    parent_version_id BIGINT REFERENCES shot_continuity_states(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shot_id, version)
);

CREATE INDEX IF NOT EXISTS shot_continuity_states_latest_idx
    ON shot_continuity_states (shot_id, version DESC);

CREATE TABLE IF NOT EXISTS continuity_checks (
    id                BIGSERIAL PRIMARY KEY,
    project_id        BIGINT NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    chapter_id        BIGINT REFERENCES content_nodes(id) ON DELETE CASCADE,
    shot_state_id     BIGINT REFERENCES shot_continuity_states(id) ON DELETE CASCADE,
    check_type        TEXT NOT NULL,
    passed            BOOLEAN NOT NULL,
    errors            JSONB NOT NULL DEFAULT '[]'::jsonb,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
