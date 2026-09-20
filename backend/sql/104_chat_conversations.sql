-- 公共对话面板的会话持久化（2026-09-18）
-- 作用域（scope）决定会话隔离：画布 = 'tapflow' + 'slug@version'，项目 = 'project' + 'project:{id}'。
-- 每个 scope 同时只有一个「活跃」会话（archived=false，部分唯一索引兜底）；
-- 「新对话」把旧会话 archived=true 再建新的，历史保留不删，后续可做会话列表回放。
CREATE TABLE IF NOT EXISTS chat_conversations (
  id         BIGSERIAL PRIMARY KEY,
  scope_kind TEXT NOT NULL,
  scope_key  TEXT NOT NULL,
  title      TEXT NOT NULL DEFAULT '新对话',
  archived   BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_conversation_active
  ON chat_conversations (scope_kind, scope_key) WHERE archived = false;

CREATE TABLE IF NOT EXISTS chat_messages (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL,                    -- 'user' | 'assistant'
  content         TEXT NOT NULL,                    -- 正文（Markdown；已剥离动作行）
  meta            JSONB NOT NULL DEFAULT '{}',      -- 附加数据（动作指令、卡片类型等）
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages (conversation_id, id);
