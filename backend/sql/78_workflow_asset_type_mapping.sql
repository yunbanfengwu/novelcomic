-- Standard production contracts for existing canvases. Legacy step/role stay for runtime compatibility.
UPDATE workflows
SET graph = jsonb_set(graph, '{nodes}', (
  SELECT jsonb_agg(CASE WHEN n->>'id'='gen' THEN
    jsonb_set(n, '{config}', (n->'config') || '{"asset_type":"pro.scene.sheet"}'::jsonb)
  ELSE n END)
  FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='scene-sheet-canvas' AND origin_slug IS NULL;

UPDATE workflows
SET graph = jsonb_set(graph, '{nodes}', (
  SELECT jsonb_agg(CASE WHEN n->>'id'='gen' THEN
    jsonb_set(n, '{config}', (n->'config') || '{"asset_type":"pro.shot.keyframe"}'::jsonb)
  ELSE n END)
  FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='shot-keyframe-canvas' AND origin_slug IS NULL;
