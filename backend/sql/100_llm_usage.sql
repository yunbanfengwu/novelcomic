-- ═══════════ 100 · LLM Token 用量（P4 · 2026-09-17）═══════════
--
-- 计费地基：每次非流式模型调用的 usage 落一行（采集点 llm._post，
-- 见 services/llm_usage.py）。口径：按 (日 × 模型) 聚合对账。
-- 绝不阻断生成：写入由调用方 fire-and-forget，本表任何异常都静默。

CREATE TABLE IF NOT EXISTS llm_usage (
    id                BIGSERIAL PRIMARY KEY,
    model             TEXT   NOT NULL,          -- 请求里的 model 名（计费主体）
    prompt_tokens     INT    NOT NULL DEFAULT 0,
    completion_tokens INT    NOT NULL DEFAULT 0,
    total_tokens      INT    NOT NULL DEFAULT 0,
    duration_ms       INT,                      -- 端到端耗时（含 429 退避）
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS llm_usage_day_idx   ON llm_usage (created_at DESC);
CREATE INDEX IF NOT EXISTS llm_usage_model_idx ON llm_usage (model, created_at DESC);

COMMENT ON TABLE llm_usage IS 'LLM token 用量：按 日×模型 聚合计费；llm._post 咽喉采集，流式暂不采';
