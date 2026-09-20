-- 关键帧主链：先生成唯一静态定格提示词，再从提示词中的规范要素名做闭集提取；
-- 只把实际写进提示词的要素交给智能要素子工作流，全部准备完成后才生成最终关键帧图片。
UPDATE workflows
SET description = '生成定格画面提示词 → 从提示词提取关联要素 → 智能生成所需要素资产 → 生成最终关键帧图片。',
    output_schema = '{"keyframe_url":{"type":"string"},"prompt_text":{"type":"string"},"prompt_element_ids":{"type":"array"},"reference_images":{"type":"array"}}'::jsonb,
    graph = $g${
      "nodes":[
        {"id":"start","type":"start","position":{"x":20,"y":260},
         "config":{"ui":{"tap":"start","title":"开始"}}},
        {"id":"candidates","type":"action","position":{"x":240,"y":520},
         "config":{"name":"shot.ensure_elements","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"facts","type":"action","position":{"x":450,"y":520},
         "config":{"name":"shot.keyframe.context","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"continuity","type":"action","position":{"x":670,"y":520},
         "config":{"name":"shot.assert_continuity","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"blocking","type":"action","position":{"x":890,"y":520},
         "config":{"name":"shot.ensure_blocking","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"candidate_scope","type":"action","position":{"x":1100,"y":520},
         "config":{"name":"asset.resolve_generation_source","args":{"project_id":"{{input.project_id}}","source_type":"shot.dynamic_elements","source_ref":"{{input.target_ref}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"script","type":"action","position":{"x":470,"y":180},
         "config":{"name":"shot.keyframe.script","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                   "ui":{"tap":"text","title":"分镜脚本","show":"text","w":410,"h":310}}},
        {"id":"prompt","type":"llm","position":{"x":950,"y":140},
         "config":{"charter":"你是分镜关键帧提示词设计师。只允许使用上游镜头事实、分镜脚本和候选要素，不得补写剧情。输出一个明确的静态定格瞬间，必须写明主体动作、景别与焦段、角色身份和服装、场景空间与站位、时间天气光源色调。凡画面中出现的项目要素，必须使用候选列表中的完整规范名称；不得用别名代替，不得写入候选集外的角色、场景或道具。远景不得写面部细节，近景不得遗漏身份特征。末尾给出项目画风、质量以及禁止文字字幕水印约束。只输出最终提示词正文，不要标题、分析或解释。",
                   "task":"候选要素描述符：{{candidate_scope.descriptors}}\n请结合分镜脚本，写出本镜唯一关键帧定格画面提示词。",
                   "skills":["legacy-skill-98"],"folder_ids":[1,5],
                       "tools":["project.info","chapter.info","shot.info"],
                       "skip_if":{"sql":"SELECT meta->>'image_prompt' FROM content_nodes WHERE id=$1","args":["{{input.shot_id}}"],"reason":"该分镜已有定格画面提示词，复用"},
                       "write":{"name":"shot.set_image_prompt","args":{"shot_id":"{{input.shot_id}}","text":"{{prompt.text}}"}},
                   "ui":{"tap":"text","title":"生成定格画面提示词","show":"text","w":460,"h":330}}},
        {"id":"dynamic_assets","type":"subflow","position":{"x":1490,"y":150},
         "config":{"slug":"multi-element-smart-generation","version":1,
                   "inputs":{"project_id":"{{input.project_id}}","prompt_text":"{{prompt.text}}",
                             "source_type":"shot.dynamic_elements","source_ref":"{{input.target_ref}}",
                             "shot_id":"{{input.shot_id}}"},
                   "ui":{"tap":"gen","title":"智能生成提示词关联要素","w":500,"h":300}}},
        {"id":"gen","type":"gen","position":{"x":2050,"y":150},
         "config":{"modality":"image","node_id":"{{input.shot_id}}",
                   "skills":["legacy-skill-98"],"folder_ids":[1,5],
                   "tools":["project.info","chapter.info","shot.info"],
                   "assemble":{"name":"shot.keyframe.layers","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}","prompt_text":"{{prompt.text}}","include_element_refs":false}},
                   "instruction":"严格使用上游定格画面提示词，并以智能要素工作流返回的图片作为角色、场景和道具参考。",
                   "step":"gen_keyframe","payload":{"use_storyboard":true,"prompt_overridden":true},
                   "asset_type":"pro.shot.keyframe","operation":"generate","output_slot":{"role":"shot.keyframe"},
                   "max_refs":4,"require_upstream_success":true,
                   "qc":{"on":true,"skill":"首帧提示词质检","stage":"prompt","threshold":80,"retry":1},
                   "skip_if":{"sql":"SELECT meta->>'keyframe_url' FROM content_nodes WHERE id=$1","args":["{{input.shot_id}}"],"reason":"该分镜已有首帧，跳过"},
                   "ui":{"tap":"gen","title":"生成最终关键帧图片","w":500,"h":300,"model":"当前图片模型"}}},
        {"id":"end","type":"end","position":{"x":2630,"y":180},
         "config":{"outputs":{"keyframe_url":"{{gen.url}}","prompt_text":"{{prompt.text}}",
                                 "prompt_element_ids":"{{dynamic_assets.element_ids}}","reference_images":"{{gen.reference_images}}"},
                   "ui":{"tap":"next","title":"保存并提供给视频","next":{"writes":["content_attachments","content_nodes.meta.keyframe_url"],"attach":true,"notify":["任务中心"]}}}}
      ],
      "edges":[
        {"from":"start","to":"candidates"},{"from":"candidates","to":"facts"},{"from":"candidates","to":"script"},
        {"from":"candidates","to":"candidate_scope"},{"from":"facts","to":"continuity"},{"from":"continuity","to":"blocking"},
        {"from":"facts","to":"prompt"},{"from":"script","to":"prompt"},{"from":"blocking","to":"prompt"},
        {"from":"candidate_scope","to":"prompt"},{"from":"prompt","to":"dynamic_assets"},
        {"from":"dynamic_assets","to":"gen","mapping":"collect"},
        {"from":"prompt","to":"gen"},{"from":"gen","to":"end"}
      ]
    }$g$::jsonb,
    updated_at = now()
WHERE slug = 'shot-keyframe-canvas'
  AND version = 1
  AND graph IS NOT NULL;
