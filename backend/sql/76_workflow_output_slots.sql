-- Both production templates use the same target+slot contract. No workflow-specific skip SQL is needed for new outputs.
UPDATE workflows
SET graph = jsonb_set(graph, '{nodes}', (
  SELECT jsonb_agg(CASE WHEN n->>'type'='gen' THEN jsonb_set(n,'{config}',
    (n->'config') || jsonb_build_object('output_slot',
      CASE WHEN slug='shot-keyframe-canvas' THEN jsonb_build_object('role','shot.keyframe')
           ELSE COALESCE(n->'config'->'output_slot', jsonb_build_object('role','scene.sheet','variant','{{input.variant_id}}')) END))
    ELSE n END) FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug IN ('scene-sheet-canvas','shot-keyframe-canvas') AND origin_slug IS NULL;
