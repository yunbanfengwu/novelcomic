-- 早期消息仍保留原文；摘要仅供模型规划/作答，不能作为可见消息展示。
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS history_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS history_summary_through_id BIGINT NOT NULL DEFAULT 0;
