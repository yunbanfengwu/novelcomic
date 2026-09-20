-- Standard source selection: the condition chooses a source contract, while one
-- resolver tool turns that contract into typed assets. Re-running is idempotent.
UPDATE workflows
SET input_schema = input_schema - 'source_type' - 'source_ref' - 'material_kind'
      - 'filters' - 'related_element_ids' - 'shot_id'
      || '{"source":{"type":"object","required":true,"seq":2,"label":"素材来源","desc":"由上游工作流绑定的标准来源对象"}}'::jsonb,
    graph = '{
      "asset_types":["pro.scene.sheet","com.image"],
      "nodes":[
        {"id":"start","type":"start","config":{"ui":{"tap":"start","title":"素材来源"}}},
        {"id":"source_select","type":"condition","config":{"when":{"value":"{{input.source.prompt_text}}","operator":"truthy"},"then":{"kind":"prompt_matches","prompt_text":"{{input.source.prompt_text}}","source_type":"{{input.source.source_type}}","source_ref":"{{input.source.source_ref}}","related_element_ids":"{{input.source.related_element_ids}}","material_kind":"{{input.source.material_kind}}","filters":"{{input.source.filters}}","shot_id":"{{input.source.shot_id}}"},"else":{"kind":"related_elements","source_type":"{{input.source.source_type}}","source_ref":"{{input.source.source_ref}}","related_element_ids":"{{input.source.related_element_ids}}","material_kind":"{{input.source.material_kind}}","filters":"{{input.source.filters}}","shot_id":"{{input.source.shot_id}}"},"ui":{"tap":"condition","title":"提示词是否指定要素","w":380,"h":180}}},
        {"id":"resolve_source","type":"action","config":{"name":"asset.resolve_source","args":{"project_id":"{{input.project_id}}","source":"{{source_select.value}}"},"ui":{"tap":"tool","title":"智能获取素材","w":460,"h":280}}},
        {"id":"route_loop","type":"loop","config":{"source":"{{resolve_source.descriptors}}","body":["scene_sheet","common_image"],"concurrency":3,"failure_policy":"required_blocks","ui":{"tap":"loop","title":"按资产类型路由","show_loop_body":true,"loop_action":"逐项生成素材"}}},
        {"id":"scene_sheet","type":"subflow","config":{"slug":"scene-sheet-canvas","run_if":{"value":"{{__item__.asset_type}}","equals":"pro.scene.sheet"},"inputs":{"project_id":"{{input.project_id}}","target_ref":"{{__item__.target_ref}}","asset_type":"pro.scene.sheet"},"ui":{"tap":"gen","title":"场景设定图"}}},
        {"id":"common_image","type":"gen","config":{"step":"gen_canvas_image","run_if":{"value":"{{__item__.asset_type}}","equals":"com.image"},"modality":"image","asset_type":"com.image","operation":"generate","output_slot":{"role":"com.image"},"instruction":"{{__item__.prompt}}","payload":{"element_id":"{{__item__.element_id}}"},"ui":{"tap":"gen","title":"通用素材图"}}},
        {"id":"end","type":"end","config":{"outputs":{"element_ids":"{{resolve_source.element_ids}}","descriptors":"{{resolve_source.descriptors}}","routed_results":"{{route_loop.results}}"},"ui":{"tap":"next","title":"素材汇总"}}}
      ],
      "edges":[
        {"from":"start","to":"source_select"},{"from":"source_select","to":"resolve_source"},{"from":"resolve_source","to":"route_loop"},
        {"from":"route_loop","to":"scene_sheet","mapping":"each"},{"from":"route_loop","to":"common_image","mapping":"each"},
        {"from":"scene_sheet","to":"end","mapping":"collect"},{"from":"common_image","to":"end","mapping":"collect"}
      ]
    }'::jsonb,
    updated_at = now()
WHERE slug = 'multi-element-smart-generation' AND version = 1;

UPDATE workflows
SET graph = jsonb_set(graph, '{nodes}', (
      SELECT jsonb_agg(CASE WHEN node->>'id' = 'dynamic_assets' THEN
        jsonb_set(node, '{config,inputs}', jsonb_build_object(
          'project_id', '{{input.project_id}}',
          'source', jsonb_build_object(
            'prompt_text', '{{prompt.text}}',
            'source_type', 'shot.dynamic_elements',
            'source_ref', '{{input.target_ref}}',
            'shot_id', '{{input.shot_id}}'
          )
        ))
      ELSE node END ORDER BY ord)
      FROM jsonb_array_elements(graph->'nodes') WITH ORDINALITY AS item(node, ord)
    )), updated_at = now()
WHERE slug = 'shot-keyframe-canvas' AND version = 1;
