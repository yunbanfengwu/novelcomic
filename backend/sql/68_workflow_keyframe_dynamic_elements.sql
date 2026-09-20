-- 分镜关键帧：编排态保持“分析 → 要素图片循环 → 关键帧”，运行态按要素动态展开。
-- loop body 是隐藏的 element-sheet 子流程；loop 完成就是天然的 fan-in 屏障，之后才跑 gen。
UPDATE workflows
SET description='分镜上下文分析 → 按关联要素动态生成/复用设定图 → 汇聚全部统一参考 → 生成关键帧。',
    graph=$g${
      "nodes":[
        {"id":"start","type":"start","position":{"x":40,"y":220},
         "config":{"ui":{"tap":"start","title":"开始"}}},
        {"id":"context","type":"action","position":{"x":420,"y":180},
         "config":{"name":"shot.keyframe.context",
                   "args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                   "ui":{"tap":"text","title":"分析分镜关联要素","show":"summary","w":420,"h":320}}},
        {"id":"elements","type":"action","position":{"x":700,"y":520},
         "config":{"name":"shot.elements","args":{"shot_id":"{{input.shot_id}}"},
                   "ui":{"hide":true}}},
        {"id":"each_element","type":"loop","position":{"x":920,"y":180},
         "config":{"source":"{{elements.items}}","body":["ensure_sheet"],"concurrency":4,
                   "ui":{"tap":"loop","title":"要素图片生成","w":420,"h":180}}},
        {"id":"ensure_sheet","type":"subflow","position":{"x":920,"y":520},
         "config":{"slug":"element-sheet","version":1,
                   "inputs":{"project_id":"{{input.project_id}}","element_id":"{{__item__.id}}","variant_id":null}}},
        {"id":"gen","type":"gen","position":{"x":1420,"y":180},
         "config":{"modality":"image","node_id":"{{input.shot_id}}",
                   "assemble":{"name":"shot.keyframe.layers",
                     "args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"}},
                   "step":"gen_keyframe","payload":{"use_storyboard":true},
                   "skip_if":{"sql":"SELECT meta->>'keyframe_url' FROM content_nodes WHERE id=$1",
                              "args":["{{input.shot_id}}"],"reason":"该分镜已有首帧，跳过"},
                   "ui":{"tap":"gen","title":"分镜关键帧","w":460,"h":273,"model":"系统出图模型"}}},
        {"id":"end","type":"end","position":{"x":1940,"y":210},
         "config":{"outputs":{"keyframe_url":"{{gen.url}}"},
                   "ui":{"tap":"next","title":"next · 回写分镜首帧",
                         "next":{"writes":["content_nodes.meta.keyframe_url"],"attach":true,"notify":["任务中心"]}}}}
      ],
      "edges":[
        {"from":"start","to":"context"},
        {"from":"context","to":"elements"},
        {"from":"elements","to":"each_element","mapping":"each"},
        {"from":"each_element","to":"gen","mapping":"collect"},
        {"from":"gen","to":"end"}
      ]
    }$g$::jsonb,
    updated_at=now()
WHERE slug='shot-keyframe-canvas' AND version=1;
