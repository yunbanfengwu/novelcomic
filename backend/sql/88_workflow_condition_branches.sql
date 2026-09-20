-- Condition nodes route by edge.branch. The two resolvers are independent tools
-- and meet again at the loop through the generic inbound aggregate.
UPDATE workflows
SET graph = '{
  "asset_types":["pro.scene.sheet","com.image"],
  "nodes":[
    {"id":"start","type":"start","config":{"ui":{"tap":"start","title":"素材来源"}}},
    {"id":"source_select","type":"condition","config":{"branches":[{"id":"if-1","kind":"if","clauses":[{"left":"{{input.source.prompt_text}}","operator":"truthy"}]},{"id":"else","kind":"else"}],"ui":{"tap":"condition","title":"提示词是否指定要素","w":420,"h":180}}},
    {"id":"resolve_prompt_elements","type":"action","config":{"name":"asset.resolve_prompt_elements","args":{"project_id":"{{input.project_id}}","prompt_text":"{{input.source.prompt_text}}","candidate_source_type":"{{input.source.source_type}}","candidate_source_ref":"{{input.source.source_ref}}","candidate_element_ids":"{{input.source.related_element_ids}}","material_kind":"{{input.source.material_kind}}","filters":"{{input.source.filters}}","shot_id":"{{input.source.shot_id}}"},"ui":{"tap":"tool","title":"按提示词获取要素"}}},
    {"id":"resolve_generation_source","type":"action","config":{"name":"asset.resolve_generation_source","args":{"project_id":"{{input.project_id}}","source_type":"{{input.source.source_type}}","source_ref":"{{input.source.source_ref}}","related_element_ids":"{{input.source.related_element_ids}}","material_kind":"{{input.source.material_kind}}","filters":"{{input.source.filters}}","shot_id":"{{input.source.shot_id}}"},"ui":{"tap":"tool","title":"按来源获取要素"}}},
    {"id":"route_loop","type":"loop","config":{"source":"{{@in.descriptors}}","body":["scene_sheet","common_image"],"concurrency":3,"failure_policy":"required_blocks","ui":{"tap":"loop","title":"按资产类型路由","show_loop_body":true,"loop_action":"逐项生成素材"}}},
    {"id":"scene_sheet","type":"subflow","config":{"slug":"scene-sheet-canvas","run_if":{"value":"{{__item__.asset_type}}","equals":"pro.scene.sheet"},"inputs":{"project_id":"{{input.project_id}}","target_ref":"{{__item__.target_ref}}","asset_type":"pro.scene.sheet"},"ui":{"tap":"gen","title":"场景设定图"}}},
    {"id":"common_image","type":"gen","config":{"step":"gen_canvas_image","run_if":{"value":"{{__item__.asset_type}}","equals":"com.image"},"modality":"image","asset_type":"com.image","operation":"generate","output_slot":{"role":"com.image"},"instruction":"{{__item__.prompt}}","payload":{"element_id":"{{__item__.element_id}}"},"ui":{"tap":"gen","title":"通用素材图"}}},
    {"id":"end","type":"end","config":{"outputs":{"descriptors":"{{route_loop.results}}","routed_results":"{{route_loop.results}}"},"ui":{"tap":"next","title":"素材汇总"}}}
  ],
  "edges":[
    {"from":"start","to":"source_select"},
    {"from":"source_select","to":"resolve_prompt_elements","branch":"if-1"},
    {"from":"source_select","to":"resolve_generation_source","branch":"else"},
    {"from":"resolve_prompt_elements","to":"route_loop"},
    {"from":"resolve_generation_source","to":"route_loop"},
    {"from":"route_loop","to":"scene_sheet","mapping":"each"},{"from":"route_loop","to":"common_image","mapping":"each"},
    {"from":"scene_sheet","to":"end","mapping":"collect"},{"from":"common_image","to":"end","mapping":"collect"}
  ]
}'::jsonb, updated_at = now()
WHERE slug = 'multi-element-smart-generation' AND version = 1;
