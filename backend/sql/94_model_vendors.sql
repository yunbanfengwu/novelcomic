-- 模型厂商（模型管理→模型厂商）：登记厂商凭据（名称/接口类型/Base URL/API Key）。
-- 登记后出现在模型配置编辑弹框的「API Key 来源」下拉里（ref=vendor:{id}），
-- 与 .env 内置预设（settings:*）、已有档沿用（profile:*）同一套 key_ref 机制。
CREATE TABLE IF NOT EXISTS model_vendors (
    id BIGSERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
