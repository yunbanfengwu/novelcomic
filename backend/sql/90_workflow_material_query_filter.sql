-- Keep the existing smart material-kind picker as an optional select filter.
UPDATE workflows
SET input_schema = input_schema || '{"material_kind":{"type":"string","required":false,"seq":5,"label":"素材类型"}}'::jsonb,
    graph = jsonb_set(graph, '{nodes}', (
      SELECT jsonb_agg(CASE WHEN node->>'id' IN (
        'resolve_prompt_elements','resolve_material_list','resolve_material_select'
      ) THEN jsonb_set(node, '{config,args,material_kind}', '"{{input.material_kind}}"'::jsonb)
      ELSE node END ORDER BY ord)
      FROM jsonb_array_elements(graph->'nodes') WITH ORDINALITY AS item(node, ord)
    )), updated_at = now()
WHERE slug = 'multi-element-smart-generation' AND version = 1;
