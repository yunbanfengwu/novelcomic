-- 分镜关键帧（动态要素）的开始节点补一个「章」入参：镜挂在章下面，
-- 只给项目 + 分镜，运行面板的分镜下拉就是全项目上千个镜平铺，根本挑不动。
-- 章不设 required：业务入口（分镜工作台的 Tapflow 对比）是点着某个镜进来的，
-- 只预填 project_id/shot_id，章设成必填会把那条入口卡死在「还差必填项」。
-- 引擎不读 input.chapter_id（各 action 只要 shot_id），它纯粹是选镜的定位层。
UPDATE workflows
SET input_schema='{"project_id":{"type":"int","required":true,"desc":"项目","seq":0},
                   "chapter_id":{"type":"int","required":false,"desc":"章","seq":1},
                   "shot_id":{"type":"int","required":true,"desc":"分镜","seq":2}}'::jsonb,
    updated_at=now()
WHERE slug='shot-keyframe-canvas' AND version=1;
