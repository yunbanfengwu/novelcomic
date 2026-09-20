-- 功能配置（模型管理→功能配置）：功能 code（后端 feature_registry.py 写死）→ 有序模型档。
-- seq 最小的一条是该功能的默认模型；没配置任何行的功能回退该 purpose 的 active 档。
CREATE TABLE IF NOT EXISTS feature_model_prefs (
    feature_code TEXT NOT NULL,
    model_profile_id BIGINT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (feature_code, model_profile_id)
);

-- 九宫格出厂默认：MiniMax image-01（沿用 91 模板原来的绑定语义）。
-- 仅在该功能一行都没配过时种入——用户清空列表后下次启动会恢复出厂默认（回退语义一致）。
INSERT INTO feature_model_prefs (feature_code, model_profile_id, seq)
SELECT 'nine_grid', id, 0 FROM model_profiles
WHERE purpose='image' AND provider='minimax' AND model_name='image-01'
  AND NOT EXISTS (SELECT 1 FROM feature_model_prefs WHERE feature_code='nine_grid')
ORDER BY id DESC LIMIT 1;

-- 九宫格模板改走功能配置：91 每次启动都会把节点回填成钉死的 MiniMax profile id，
-- 本文件按文件名顺序在其后执行，把钉死改为 feature_code（模型顺序在功能配置页维护）。
UPDATE workflows SET graph=jsonb_set(jsonb_set(jsonb_set(jsonb_set(graph,
  '{nodes,2,config,model_profile_id}', '0'::jsonb, true),
  '{nodes,2,config,feature_code}', '"nine_grid"'::jsonb, true),
  '{nodes,2,config,model_profile_name}', '"按功能配置：九宫格生成"'::jsonb, true),
  '{nodes,2,config,ui,model}', '"按功能配置"'::jsonb, true),
  updated_at=now()
WHERE slug='nine-grid-keyframe-reference' AND version=1;
