-- Material chunks are deliberately separate from kb_entries: they preserve the
-- source and offsets and can be re-summarized/indexed by a later agent.
CREATE TABLE IF NOT EXISTS project_material_chunks (
    id BIGSERIAL PRIMARY KEY,
    material_id BIGINT NOT NULL REFERENCES project_materials(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(material_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS project_material_chunks_material_idx
    ON project_material_chunks(material_id, chunk_index);
