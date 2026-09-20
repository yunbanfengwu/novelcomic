-- Material query is a user-facing intent, not a required internal source object.
-- `select` uses the existing resolver's context inference: shot, chapter, then project.
UPDATE workflows
SET input_schema = '{
  "project_id":{"type":"int","required":true,"seq":0,"label":"项目"},
  "material_query_code":{"type":"string","required":false,"seq":1,"label":"素材查询方式","allowed_values":["select","list","prompt"]},
  "chapter_id":{"type":"int","required":false,"seq":2,"label":"本集"},
  "shot_id":{"type":"int","required":false,"seq":3,"label":"分镜"},
  "prompt_text":{"type":"string","required":false,"seq":4,"label":"定格提示词 / 分析文本"},
  "related_element_ids":{"type":"object","required":false,"seq":5,"label":"上游素材列表","ui":{"hide":true}},
  "filters":{"type":"object","required":false,"seq":6,"label":"素材类型筛选","ui":{"hide":true}}
}'::jsonb,
graph = '{
  "asset_types":["pro.scene.sheet","com.image"],
  "nodes":[
    {"id":"start","type":"start","config":{"ui":{"tap":"start","title":"素材查询"}}},
    {"id":"source_select","type":"condition","config":{"branches":[
      {"id":"prompt","kind":"if","clauses":[{"left":"{{input.material_query_code}}","operator":"equals","right":"prompt"}]},
      {"id":"list","kind":"else_if","clauses":[{"left":"{{input.material_query_code}}","operator":"equals","right":"list"}]},
      {"id":"select","kind":"else"}],"ui":{"tap":"condition","title":"选择素材查询方式","w":420,"h":210}}},
    {"id":"resolve_prompt_elements","type":"action","config":{"name":"asset.resolve_prompt_elements","args":{"project_id":"{{input.project_id}}","prompt_text":"{{input.prompt_text}}","shot_id":"{{input.shot_id}}","chapter_id":"{{input.chapter_id}}","filters":"{{input.filters}}"},"ui":{"tap":"tool","title":"按提示词获取要素"}}},
    {"id":"resolve_material_list","type":"action","config":{"name":"asset.resolve_generation_source","args":{"project_id":"{{input.project_id}}","source_type":"explicit.element_ids","related_element_ids":"{{input.related_element_ids}}","filters":"{{input.filters}}"},"ui":{"tap":"tool","title":"项目内直接提供素材列表"}}},
    {"id":"resolve_material_select","type":"action","config":{"name":"asset.resolve_generation_source","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}","chapter_id":"{{input.chapter_id}}","filters":"{{input.filters}}"},"ui":{"tap":"tool","title":"项目内按筛选条件选择"}}},
    {"id":"route_loop","type":"loop","config":{"source":"{{@in.descriptors}}","body":["scene_sheet","common_image"],"concurrency":3,"failure_policy":"required_blocks","ui":{"tap":"loop","title":"按资产类型路由","show_loop_body":true,"loop_action":"逐项生成素材"}}},
    {"id":"scene_sheet","type":"subflow","config":{"slug":"scene-sheet-canvas","run_if":{"value":"{{__item__.asset_type}}","equals":"pro.scene.sheet"},"inputs":{"project_id":"{{input.project_id}}","target_ref":"{{__item__.target_ref}}","asset_type":"pro.scene.sheet"},"ui":{"tap":"gen","title":"场景设定图"}}},
    {"id":"common_image","type":"gen","config":{"step":"gen_canvas_image","run_if":{"value":"{{__item__.asset_type}}","equals":"com.image"},"modality":"image","asset_type":"com.image","operation":"generate","output_slot":{"role":"com.image"},"instruction":"{{__item__.prompt}}","payload":{"element_id":"{{__item__.element_id}}"},"ui":{"tap":"gen","title":"通用素材图"}}},
    {"id":"end","type":"end","config":{"outputs":{"descriptors":"{{route_loop.results}}","routed_results":"{{route_loop.results}}"},"ui":{"tap":"next","title":"素材汇总"}}}
  ],
  "edges":[
    {"from":"start","to":"source_select"},
    {"from":"source_select","to":"resolve_prompt_elements","branch":"prompt"},
    {"from":"source_select","to":"resolve_material_list","branch":"list"},
    {"from":"source_select","to":"resolve_material_select","branch":"select"},
    {"from":"resolve_prompt_elements","to":"route_loop"},{"from":"resolve_material_list","to":"route_loop"},{"from":"resolve_material_select","to":"route_loop"},
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
      'material_query_code', 'prompt',
      'prompt_text', '{{prompt.text}}',
      'shot_id', '{{input.shot_id}}'
    ))
  ELSE node END ORDER BY ord)
  FROM jsonb_array_elements(graph->'nodes') WITH ORDINALITY AS item(node, ord)
)), updated_at = now()
WHERE slug = 'shot-keyframe-canvas' AND version = 1;
