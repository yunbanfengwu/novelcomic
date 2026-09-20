-- Asset-type-driven multi-element canvas. The router emits descriptors by stable
-- element ID; one upstream loop routes each descriptor into its matching body node.
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES (
  'multi-element-smart-generation','Multi-element smart generation',
  'Resolve persisted related elements or a shot’s dynamic elements, then route each by asset type.',
  1,'published',
  '{"project_id":{"type":"int","required":true,"seq":0,"label":"项目"},"prompt_text":{"type":"string","required":false,"seq":1,"label":"定格提示词","desc":"Optional prompt used to select canonical elements from the candidate scope"},"source_type":{"type":"string","required":true,"seq":2,"default":"explicit.element_ids","label":"来源类型","desc":"Candidate source contract","allowed_values":["explicit.element_ids","shot.dynamic_elements","chapter.appearing_elements","project.elements"]},"source_ref":{"type":"string","required":false,"seq":3,"label":"来源对象","desc":"Typed source ID, e.g. content_node:819 or project:25"},"material_kind":{"type":"string","required":false,"seq":4,"label":"素材类型","desc":"Optional single element kind filter, e.g. scene"},"filters":{"type":"object","required":false,"seq":5,"label":"筛选条件","desc":"Optional source filters, e.g. {kinds:[character,scene]}"},"related_element_ids":{"type":"array","required":false,"seq":6,"label":"指定要素","desc":"Candidate IDs for explicit.element_ids"},"shot_id":{"type":"int","required":false,"seq":99,"label":"兼容分镜","desc":"Legacy compatibility fallback for shot.dynamic_elements","ui":{"hide":true}}}'::jsonb,
  '{"element_ids":{"type":"array"},"descriptors":{"type":"array"},"routed_results":{"type":"array"}}'::jsonb,
  $graph${
    "asset_types":["pro.scene.sheet","com.image"],
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":280},"config":{"ui":{"tap":"start","title":"Generation source"}}},
      {"id":"prompt_elements","type":"action","position":{"x":300,"y":280},"config":{"name":"asset.resolve_prompt_elements","args":{"project_id":"{{input.project_id}}","prompt_text":"{{input.prompt_text}}","candidate_source_type":"{{input.source_type}}","candidate_source_ref":"{{input.source_ref}}","candidate_element_ids":"{{input.related_element_ids}}","material_kind":"{{input.material_kind}}","filters":"{{input.filters}}","shot_id":"{{input.shot_id}}"},"ui":{"tap":"tool","title":"从提示词提取关联要素","w":460,"h":280}}},
      {"id":"resolve_descriptors","type":"action","position":{"x":780,"y":280},"config":{"name":"asset.resolve_generation_source","args":{"project_id":"{{input.project_id}}","source_type":"explicit.element_ids","related_element_ids":"{{prompt_elements.element_ids}}","material_kind":"{{input.material_kind}}"},"ui":{"tap":"tool","title":"按要素 ID 装配生成参数","w":460,"h":280}}},
      {"id":"route_loop","type":"loop","position":{"x":1240,"y":280},"config":{"source":"{{resolve_descriptors.descriptors}}","body":["scene_sheet","common_image"],"concurrency":3,"failure_policy":"required_blocks","ui":{"tap":"loop","title":"Smart type router","show_loop_body":true,"loop_action":"Loop each typed asset"}}},
      {"id":"scene_sheet","type":"subflow","position":{"x":1670,"y":120},"config":{"slug":"scene-sheet-canvas","run_if":{"value":"{{__item__.asset_type}}","equals":"pro.scene.sheet"},"inputs":{"project_id":"{{input.project_id}}","target_ref":"{{__item__.target_ref}}","asset_type":"pro.scene.sheet"},"ui":{"tap":"gen","title":"Reference scene-sheet workflow"}}},
      {"id":"common_image","type":"gen","position":{"x":1670,"y":440},"config":{"step":"gen_canvas_image","run_if":{"value":"{{__item__.asset_type}}","equals":"com.image"},"modality":"image","asset_type":"com.image","operation":"generate","output_slot":{"role":"com.image"},"instruction":"{{__item__.prompt}}","payload":{"element_id":"{{__item__.element_id}}"},"ui":{"tap":"gen","title":"Generate common image"}}},
      {"id":"end","type":"end","position":{"x":2040,"y":280},"config":{"outputs":{"element_ids":"{{prompt_elements.element_ids}}","descriptors":"{{resolve_descriptors.descriptors}}","routed_results":"{{route_loop.results}}"},"ui":{"tap":"next","title":"Asset summary"}}}
    ],
    "edges":[
      {"from":"start","to":"prompt_elements"},{"from":"prompt_elements","to":"resolve_descriptors"},{"from":"resolve_descriptors","to":"route_loop"},
      {"from":"route_loop","to":"scene_sheet","mapping":"each"},{"from":"route_loop","to":"common_image","mapping":"each"},
      {"from":"scene_sheet","to":"end","mapping":"collect"},{"from":"common_image","to":"end","mapping":"collect"}
    ]
  }$graph$::jsonb,
  940,ARRAY['canvas','smart','asset-type','multi-element']
)
ON CONFLICT (slug,version) DO UPDATE SET
  name=excluded.name,description=excluded.description,status=excluded.status,input_schema=excluded.input_schema,
  output_schema=excluded.output_schema,graph=excluded.graph,seq=excluded.seq,tags=excluded.tags,updated_at=now();
