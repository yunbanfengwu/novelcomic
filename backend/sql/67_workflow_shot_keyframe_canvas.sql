-- 分镜首帧 Tapflow 对比画布：纯新增，不替换现有 ShotSopCanvas / InfiniteMediaCanvas。
-- 两条生产入口最终都跑 gen_keyframe，参考资产都从 content_reference_links 解析。
INSERT INTO workflows(slug,name,description,version,status,input_schema,output_schema,graph,seq,tags)
VALUES(
  'shot-keyframe-canvas','分镜首帧·Tapflow 对比',
  '旁路对比画布：分镜上下文 + 三端统一参考资产 → 首帧提示词 → gen_keyframe → 原业务字段回写。',
  1,'published',
  '{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
    "shot_id":{"type":"int","required":true,"desc":"分镜","seq":1}}'::jsonb,
  '{"keyframe_url":{"type":"string"}}'::jsonb,
  $g${
    "nodes":[
      {"id":"start","type":"start","position":{"x":40,"y":220},
       "config":{"ui":{"tap":"start","title":"开始"}}},
      {"id":"context","type":"action","position":{"x":420,"y":180},
       "config":{"name":"shot.keyframe.context",
                 "args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"},
                 "ui":{"tap":"text","title":"分镜数据与统一参考资产","show":"summary","w":420,"h":320}}},
      {"id":"gen","type":"gen","position":{"x":920,"y":180},
       "config":{"modality":"image","node_id":"{{input.shot_id}}",
                 "assemble":{"name":"shot.keyframe.layers",
                   "args":{"project_id":"{{input.project_id}}","shot_id":"{{input.shot_id}}"}},
                 "step":"gen_keyframe","payload":{"use_storyboard":true},
                 "skip_if":{"sql":"SELECT meta->>'keyframe_url' FROM content_nodes WHERE id=$1",
                            "args":["{{input.shot_id}}"],
                            "reason":"该分镜已有首帧，跳过（生成条发送可强制重出）"},
                 "ui":{"tap":"gen","title":"分镜首帧","w":460,"h":273,"model":"系统出图模型"}}},
      {"id":"end","type":"end","position":{"x":1440,"y":210},
       "config":{"outputs":{"keyframe_url":"{{gen.url}}"},
                 "ui":{"tap":"next","title":"next · 回写分镜首帧",
                       "next":{"writes":["content_nodes.meta.keyframe_url"],"attach":true,"notify":["任务中心"]}}}}
    ],
    "edges":[{"from":"start","to":"context"},{"from":"context","to":"gen"},{"from":"gen","to":"end"}]
  }$g$::jsonb,
  930,'{canvas,shot,keyframe,compare}'::text[]
)
ON CONFLICT(slug,version) DO NOTHING;
