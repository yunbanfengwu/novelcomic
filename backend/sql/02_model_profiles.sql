-- 模型注册表（2026-07-08，参考 cocc-work model_profiles + purpose 路由）
CREATE TABLE IF NOT EXISTS model_profiles (
    id         BIGSERIAL PRIMARY KEY,
    purpose    TEXT        NOT NULL,
    provider   TEXT        NOT NULL,
    name       TEXT        NOT NULL,
    base_url   TEXT        NOT NULL,
    api_key    TEXT        NOT NULL DEFAULT '',
    model_name TEXT        NOT NULL,
    extra      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    is_active  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (purpose, name)
);
COMMENT ON TABLE  model_profiles IS '模型注册表：文本/图片/视频/语音/向量各挂多个服务商 profile，每 purpose 一个 active，系统管理页可切换';
COMMENT ON COLUMN model_profiles.purpose  IS '生成链路（会被 get_active 取用）：text=LLM / image=生图 / video=生视频 / tts=语音 / embedding=向量嵌入；专用挂档（仅登记额度，任何生成步骤都不会取）：math=数学 / code=代码 / rerank=重排 / ocr=OCR / translate=翻译 / other=其它';
COMMENT ON COLUMN model_profiles.provider IS 'openai_compat=OpenAI兼容chat / grsai=GRSAI图视频 / ark=火山引擎(Seedream图+Seedance视频)';
COMMENT ON COLUMN model_profiles.is_active IS '每 purpose 仅一个 active（激活接口保证）';

-- 参考图/附件数量上限（2026-07-15）：调大模型常因参考图过多 400，生成时按此上限自动截断多余附件不提交。
-- NULL/0 = 不额外限制，沿用各 provider 内置默认（ARK 生图/生视频默认 4 张）
ALTER TABLE model_profiles ADD COLUMN IF NOT EXISTS max_refs INTEGER;
COMMENT ON COLUMN model_profiles.max_refs IS '参考图/附件数量上限；NULL/0=用 provider 默认（ARK 4 张），生成时超出自动截断';
