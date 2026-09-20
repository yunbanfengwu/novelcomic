-- 资源包厂商维度（2026-08-01）：原表只有火山方舟一家；新增阿里百炼（免费额度 / Token Plan 资源包），
-- 前端按厂商过滤，插入模型管理时按厂商决定 provider/凭据（见 app/resource_map.py）。
-- 幂等：老数据默认补 'volc'。
ALTER TABLE resource_packages ADD COLUMN IF NOT EXISTS vendor TEXT NOT NULL DEFAULT 'volc';
UPDATE resource_packages SET vendor = 'volc' WHERE vendor IS NULL OR vendor = '';
COMMENT ON COLUMN resource_packages.vendor IS '厂商：volc=火山方舟 / bailian=阿里百炼';
