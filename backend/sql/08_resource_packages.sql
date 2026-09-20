-- 火山引擎资源包剩余（2026-07-13）：从控制台导出的资源包总览里，
-- 只留「有余量的模型类资源包」，供系统管理页浏览 + 一键插入模型管理/设为默认。
-- 原始列裁剪为用户要求的字段；真实模型名 + 模态标签由后端 resource_map 派生（不落库，随映射逻辑一致）。
CREATE TABLE IF NOT EXISTS resource_packages (
    instance_id     TEXT        PRIMARY KEY,          -- 实例ID
    product         TEXT        NOT NULL,             -- 产品
    config_name     TEXT        NOT NULL,             -- 配置名称
    spec            TEXT        NOT NULL DEFAULT '',   -- 规格
    spec_unit       TEXT        NOT NULL DEFAULT '',   -- 规格单位
    total           DOUBLE PRECISION NOT NULL DEFAULT 0,  -- 总量
    remaining       DOUBLE PRECISION NOT NULL DEFAULT 0,  -- 余量
    status          TEXT        NOT NULL DEFAULT '',   -- 状态（生效中/已用完…，内部用于过滤）
    purchased_at    TEXT        NOT NULL DEFAULT '',   -- 购买时间(UTC+8)
    effective_at    TEXT        NOT NULL DEFAULT '',   -- 生效时间(UTC+8)
    expires_at      TEXT        NOT NULL DEFAULT '',   -- 失效时间(UTC+8)
    provider_entity TEXT        NOT NULL DEFAULT '',   -- 服务主体
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE resource_packages IS '火山资源包剩余：只存有余量的模型类资源包；种子若空则由后端从 data/resource_packages_seed.json 补齐，可重传 CSV 刷新';
