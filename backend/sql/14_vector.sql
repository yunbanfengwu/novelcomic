-- 向量检索（pgvector）：给 kb_entries 加 1024 维嵌入 + HNSW 余弦索引。
-- 维度 1024 对应 BAAI/bge-m3（见 backend/app/embeddings.py EMBED_DIM）。
--
-- 跨环境安全：pgvector 未安装时（本地原生 PG / 换镜像前的线上）整段跳过，
-- 不会让后端启动崩溃。装了 pgvector（线上换 pgvector/pgvector:pg16 镜像后）自动建齐。
-- 幂等：IF NOT EXISTS + 可重复执行。vector 类型 DDL 用 EXECUTE 动态执行，
-- 避免无扩展环境在解析期就因未知类型报错。
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector;
    EXECUTE 'ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS embedding vector(1024)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS kb_entries_embedding_idx '
            'ON kb_entries USING hnsw (embedding vector_cosine_ops)';
    RAISE NOTICE 'pgvector: kb_entries.embedding(1024) + HNSW 索引已就绪';
  ELSE
    RAISE NOTICE 'pgvector 未安装，跳过向量建表（换 pgvector 镜像后重启自动补齐）';
  END IF;
END $$;
