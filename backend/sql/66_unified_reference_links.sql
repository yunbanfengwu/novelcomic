-- 面板 / InfiniteMediaCanvas / Tapflow 共用的参考关系真源。
-- URL 只作当时快照；长期关系使用 element_id / attachment_id / canvas node key。
CREATE TABLE IF NOT EXISTS content_reference_links (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    subject_kind        TEXT NOT NULL,              -- shot | element | project | canvas
    subject_id          BIGINT NOT NULL,
    purpose             TEXT NOT NULL DEFAULT 'image', -- image | video | last | sheet
    source_kind         TEXT NOT NULL,              -- element | attachment | canvas_node | url
    source_key          TEXT NOT NULL,              -- 稳定去重键，如 element:12 / attachment:98
    source_id           BIGINT,
    source_canvas_slug  TEXT,
    source_node_key     TEXT,
    role                TEXT NOT NULL DEFAULT 'manual',
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    seq                 INT NOT NULL DEFAULT 0,
    snapshot            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id, subject_kind, subject_id, purpose, source_key)
);

-- 兼容本功能开发期间曾启动过的第一版表：当时唯一键遗漏 project_id。
-- 不能只依赖 CREATE TABLE IF NOT EXISTS，否则已有开发库会在 upsert 时找不到目标约束。
DO $$
DECLARE old_constraint TEXT;
BEGIN
    SELECT c.conname INTO old_constraint
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'content_reference_links'
      AND c.contype = 'u'
      AND pg_get_constraintdef(c.oid) =
          'UNIQUE (subject_kind, subject_id, purpose, source_key)'
    LIMIT 1;
    IF old_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE content_reference_links DROP CONSTRAINT %I', old_constraint);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'content_reference_links' AND c.contype = 'u'
          AND pg_get_constraintdef(c.oid) =
              'UNIQUE (project_id, subject_kind, subject_id, purpose, source_key)'
    ) THEN
        ALTER TABLE content_reference_links
          ADD CONSTRAINT content_reference_links_identity_key
          UNIQUE(project_id, subject_kind, subject_id, purpose, source_key);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS content_reference_links_subject_idx
    ON content_reference_links(project_id, subject_kind, subject_id, purpose, seq, id);
CREATE INDEX IF NOT EXISTS content_reference_links_source_idx
    ON content_reference_links(project_id, source_kind, source_id);

COMMENT ON TABLE content_reference_links IS
  '参考关系唯一真源：面板、旧无限画布、Tapflow 三端同读同写；业务 meta 数组仅作兼容镜像';
COMMENT ON COLUMN content_reference_links.snapshot IS
  '关系建立/运行时的名称、类型、URL 快照；展示默认解析源对象最新值，历史运行仍保留实际 URL';
