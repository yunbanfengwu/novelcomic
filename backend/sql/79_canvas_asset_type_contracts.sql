-- Public contracts for the two production canvases. The fixed type is passed by
-- their project entry points; the backend also injects it for legacy callers.
UPDATE workflows
SET input_schema = input_schema || '{"asset_type":{"type":"asset_type","required":true,"ui":{"hide":true},"desc":"固定资产类型"}}'::jsonb,
    graph = jsonb_set(graph, '{nodes}', (
      SELECT jsonb_agg(CASE WHEN n->>'type'='gen' THEN jsonb_set(n, '{config}',
        (n->'config') || '{"output_asset_type":"pro.scene.sheet"}'::jsonb)
        ELSE n END)
      FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='scene-sheet-canvas' AND origin_slug IS NULL;

UPDATE workflows
SET input_schema = input_schema || '{"asset_type":{"type":"asset_type","required":true,"ui":{"hide":true},"desc":"固定资产类型"}}'::jsonb,
    graph = jsonb_set(graph, '{nodes}', (
      SELECT jsonb_agg(CASE WHEN n->>'type'='gen' THEN jsonb_set(n, '{config}',
        (n->'config') || '{"output_asset_type":"pro.shot.keyframe"}'::jsonb)
        ELSE n END)
      FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='shot-keyframe-canvas' AND origin_slug IS NULL;
