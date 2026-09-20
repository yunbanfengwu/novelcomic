-- 对齐单场景设定图 Tapflow：提示词约束/技能/知识/工具/QC/画幅筛选归属于 gen 节点，
-- 不在主画布散成独立节点。主图只表达真实的上游产物与 1:N 图片引用。
UPDATE workflows
SET description='分镜事实与脚本 + 动态要素图片 + 额外参考 → 关键帧生成。提示词生成约束、技能、知识、工具、质检和模型适配均归属于最终图片节点。',
    graph=$g${
      "nodes":[
        {"id":"start","type":"start","position":{"x":20,"y":260},"config":{"ui":{"tap":"start","title":"开始"}}},
        {"id":"facts","type":"action","position":{"x":250,"y":520},
         "config":{"name":"shot.keyframe.context","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"continuity","type":"action","position":{"x":470,"y":520},
         "config":{"name":"shot.assert_continuity","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"analyze","type":"action","position":{"x":440,"y":180},
         "config":{"name":"shot.ensure_elements","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                   "ui":{"tap":"text","title":"分析分镜关联要素","show":"summary","w":400,"h":300}}},
        {"id":"blocking","type":"action","position":{"x":700,"y":520},
         "config":{"name":"shot.ensure_blocking","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"elements","type":"action","position":{"x":920,"y":520},
         "config":{"name":"shot.elements","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},"ui":{"hide":true}}},
        {"id":"script","type":"action","position":{"x":900,"y":500},
         "config":{"name":"shot.keyframe.script","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                   "ui":{"tap":"text","title":"分镜脚本","show":"text","w":410,"h":310}}},
        {"id":"each_element","type":"loop","position":{"x":930,"y":100},
         "config":{"source":"{{elements.items}}","body":["ensure_sheet"],"concurrency":4,"failure_policy":"required_blocks",
                   "ui":{"tap":"loop","title":"要素图片生成","w":420,"h":180}}},
        {"id":"ensure_sheet","type":"subflow","position":{"x":1180,"y":520},
         "config":{"slug":"element-sheet","version":1,"inputs":{"project_id":"{{input.project_id}}","element_id":"{{__item__.id}}","variant_id":"{{__item__.variant_id}}"}}},
        {"id":"extra_refs","type":"action","position":{"x":1370,"y":500},
         "config":{"name":"shot.keyframe.extra_references","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                   "ui":{"tap":"upload","title":"额外参考资产","show":"refs","w":340,"h":210}}},
        {"id":"gen","type":"gen","position":{"x":1510,"y":170},
         "config":{"modality":"image","node_id":"{{input.shot_id}}",
                   "charter":"你是分镜关键帧提示词设计师。先阅读绑定的《分镜提示词装配》技能，结合绑定知识库、工具取到的项目/章节/分镜事实以及所有上游引用，写出一段可直接交给图片模型的中文关键帧提示词。只允许使用已有镜头事实，不得补写剧情；只能描述一个明确的静态定格瞬间。必须明确主体动作、景别与焦段、角色身份和服装、场景空间与站位、时间天气光源色调；角色、场景、道具必须与上游要素一致。远景不得写面部细节，近景不得遗漏身份特征。末尾给出项目画风、质量以及禁止文字字幕水印约束。只输出最终提示词正文，不要标题、分析或解释。",
                   "skills":["legacy-skill-98"],"folder_ids":[1,5],
                   "tools":["project.info","chapter.info","shot.info"],
                   "assemble":{"name":"shot.keyframe.layers","args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"}},
                   "instruction":"根据分镜脚本选择最能代表本镜剧情走向的唯一静态定格画面。",
                   "step":"gen_keyframe","payload":{"use_storyboard":true,"prompt_overridden":true},
                   "max_refs":4,"require_upstream_success":true,
                   "qc":{"on":true,"skill":"首帧提示词质检","stage":"prompt","threshold":80,"retry":1},
                   "skip_if":{"sql":"SELECT meta->>'keyframe_url' FROM content_nodes WHERE id=$1","args":["{{input.shot_id}}"],"reason":"该分镜已有首帧，跳过"},
                   "ui":{"tap":"gen","title":"分镜关键帧生成","w":500,"h":300,"model":"当前激活图片模型"}}},
        {"id":"end","type":"end","position":{"x":2070,"y":200},
         "config":{"outputs":{"keyframe_url":"{{gen.url}}","reference_images":"{{gen.reference_images}}"},
                   "ui":{"tap":"next","title":"next · 保存并提供给视频","next":{"writes":["content_attachments","content_nodes.meta.keyframe_url"],"attach":true,"notify":["任务中心"]}}}}
      ],
      "edges":[
        {"from":"start","to":"facts"},{"from":"facts","to":"continuity"},{"from":"continuity","to":"analyze"},
        {"from":"analyze","to":"blocking"},{"from":"blocking","to":"elements"},{"from":"blocking","to":"script"},
        {"from":"analyze","to":"extra_refs"},{"from":"elements","to":"each_element","mapping":"each"},
        {"from":"each_element","to":"gen","mapping":"collect"},{"from":"script","to":"gen"},
        {"from":"extra_refs","to":"gen","mapping":"collect"},{"from":"gen","to":"end"}
      ]
    }$g$::jsonb,
    updated_at=now()
WHERE slug='shot-keyframe-canvas' AND version=1;
