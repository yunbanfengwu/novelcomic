-- Scene-sheet runs are scoped to an element variant, not the element's primary sheet_url.
UPDATE workflows
SET graph = jsonb_set(graph, '{nodes}', (
  SELECT jsonb_agg(
    CASE
      WHEN n->>'id' = 'ensure' THEN jsonb_set(n, '{config,args,element_id}', '"{{input.element_id}}"'::jsonb, true)
      WHEN n->>'id' = 'gen' THEN jsonb_set(n, '{config}', (n->'config') || jsonb_build_object(
        'output_slot', jsonb_build_object('role','scene.sheet','variant','{{input.variant_id}}'),
        'skip_if', jsonb_build_object(
          'sql', 'SELECT COALESCE((SELECT v->>''sheet_url'' FROM jsonb_array_elements(COALESCE(meta->''variants'',''[]''::jsonb)) v WHERE v->>''id''=COALESCE($2,''default'') LIMIT 1), CASE WHEN COALESCE($2,''default'')=''default'' THEN meta->>''sheet_url'' END) FROM content_elements WHERE id=$1',
          'args', jsonb_build_array('{{ensure.id}}','{{input.variant_id}}'),
          'reason', 'This image variant already has a sheet')))
      ELSE n
    END)
  FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='scene-sheet-canvas' AND origin_slug IS NULL;
