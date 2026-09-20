-- 故事板九宫格：产物是**一张 3×3 的故事板**（九个分镜画在同一张图上），不是单张关键帧。
-- 上游的 multi-element-smart-generation 负责把这段描述里的角色/场景/道具解析出来并备好
-- 设定图，九格共用这一套设定图锁一致性——这正是「同一个角色九格长得不一样」的解法。
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES (
  'nine-grid-keyframe-reference','故事板九宫格生成',
  '从九宫格分镜要素描述提取关键角色、场景和道具，复用 Multi-element smart generation 生成参考资产，再输出一张 3×3 故事板九宫格（九个分镜同图、角色与场景一致）。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"seq":0,"label":"项目"},"grid_prompt":{"type":"string","required":true,"seq":1,"label":"九宫格分镜要素","desc":"按 1~9 逐格描述：这一格拍谁、在哪、什么动作、什么景别"},"grid_reference_images":{"type":"array","required":false,"seq":2,"label":"九宫格构图参考图","desc":"可选：已有的九宫格草图/定格图，用作分格构图与人物站位的参考；不传则按逐格描述自行分格"}}'::jsonb,
  '{"image_url":{"type":"string"},"element_ids":{"type":"array"},"reference_images":{"type":"array"}}'::jsonb,
  $graph${
    "nodes":[
      {"id":"start","type":"start","position":{"x":20,"y":260},"config":{"ui":{"tap":"start","title":"九宫格分镜要素"}}},
      {"id":"elements","type":"subflow","position":{"x":460,"y":160},"config":{"slug":"multi-element-smart-generation","version":1,"inputs":{"project_id":"{{input.project_id}}","prompt_text":"{{input.grid_prompt}}","source_type":"project.elements","source_ref":"{{input.project_id}}"},"ui":{"tap":"gen","title":"Multi-element smart generation","w":500,"h":300}}},
      {"id":"generate","type":"gen","position":{"x":1060,"y":160},"config":{"step":"gen_canvas_image","modality":"image","model_profile_id":0,"model_profile_name":"MiniMax image-01","max_refs":4,"instruction":"分镜故事板（storyboard）九宫格：在一张图里画 9 个**彼此独立**的分镜画格，3 行 3 列排列，格与格之间是纯白间隔。\n最要紧的一条：**不是把一整张大图切成九块**。每一格都是一个单独拍的镜头，有自己的机位、景别和构图，格与格之间的画面互不连续、不共用同一片背景、人物也不跨格延续；相邻两格并排看上去必须像两张不同的照片，而不是一张照片被白线分开。\n下面九句依次对应这九个位置——左上、上中、右上、左中、正中、右中、左下、下中、右下，逐格照画，不要串位：{{input.grid_prompt}}。\n九格的景别要拉开差距（大远景、远景、中景、近景、特写交替），不要连着两格用同一景别。同一角色在九格里必须是同一个人——外形、发型、服装、配色以提供的角色/场景/道具设定图为准；场景与画风九格统一。若给了九宫格构图参考图，就照它的分格、人物站位与景别落位。不要添加画外文字：字幕、格号、对白框、水印一律没有。","payload":{"node_key":"storyboard-nine-grid","title":"故事板九宫格","reference_images":"{{input.grid_reference_images}}"},"ui":{"tap":"gen","title":"MiniMax 故事板九宫格","w":520,"h":300,"model":"MiniMax image-01"}}},
      {"id":"end","type":"end","position":{"x":1640,"y":220},"config":{"outputs":{"image_url":"{{generate.url}}","element_ids":"{{elements.element_ids}}","reference_images":"{{generate.reference_images}}"},"ui":{"tap":"next","title":"输出故事板九宫格"}}}
    ],
    "edges":[{"from":"start","to":"elements"},{"from":"start","to":"generate"},{"from":"elements","to":"generate","mapping":"collect"},{"from":"generate","to":"end"}]
  }$graph$::jsonb,
  950,ARRAY['canvas','storyboard','nine-grid','minimax']
)
ON CONFLICT (slug,version) DO UPDATE SET name=excluded.name,description=excluded.description,status=excluded.status,input_schema=excluded.input_schema,output_schema=excluded.output_schema,graph=excluded.graph,seq=excluded.seq,tags=excluded.tags,updated_at=now();

-- Keep the template bound to the MiniMax profile even if profile IDs vary by
-- environment.  The user configures the profile in model_profiles, never in JS.
UPDATE workflows SET graph=jsonb_set(graph, '{nodes,2,config,model_profile_id}', to_jsonb(COALESCE((
  SELECT id FROM model_profiles WHERE purpose='image' AND provider='minimax' AND model_name='image-01' ORDER BY id DESC LIMIT 1
), 0)), true), updated_at=now()
WHERE slug='nine-grid-keyframe-reference' AND version=1;
