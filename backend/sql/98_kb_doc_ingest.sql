-- 文档摄取（2026-09-17）：给 kb_entries 补"从整篇文档切块入库"的来源追溯三件套。
-- 复用既有列：embedding(14 号, vector(1024))、folder_id(06 号)、tags/scope/project_id。
-- 幂等：ADD COLUMN IF NOT EXISTS + 可重复执行；无 pgvector 环境只少了向量列，功能降级不崩。
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS source_name TEXT;
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS source_hash TEXT;
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS chunk_seq   INT;

COMMENT ON COLUMN kb_entries.source_name IS '来源文档名（doc_chunk 用）：上传的原始文件名';
COMMENT ON COLUMN kb_entries.source_hash IS '来源文档内容 sha256：同 hash 重复摄取=整篇重建（先删后插），保证幂等';
COMMENT ON COLUMN kb_entries.chunk_seq   IS '块序号（0 起）；doc_chunk 条目按 (source_hash, chunk_seq) 有序';

-- 重建整篇 / 按来源清理都走这个索引；检索过滤也用
CREATE INDEX IF NOT EXISTS kb_entries_source_idx ON kb_entries (kind, source_hash);
-- doc_chunk 的正文 trgm：长文档关键词召回的主通道（向量列可能不存在/未回填）
CREATE INDEX IF NOT EXISTS kb_entries_content_trgm_idx ON kb_entries USING gin (content gin_trgm_ops);
