-- 首帧/视频两条镜头产线的适配 SOP：补齐画布实例投影的编排来源。
-- asset_role 保存 flow.Step kind（gen_keyframe / gen_video），与 20 号适配模板同构；幂等。
INSERT INTO visual_sops(code,title,asset_role,version,status,spec,published_at)
SELECT v.code,v.title,v.target,1,'published',
       jsonb_build_object(
         'adapter_step_kind',v.target,
         'skill_name',v.skill_name,
         'knowledge_folder',v.folder,
         'generation',jsonb_build_object('max_retries',1),
         'quality_gates',jsonb_build_object(
           'prompt',jsonb_build_object('enabled',true,'mode','blocking','min_score',80,
                                      'requirements',to_jsonb(v.requirements::text[]))),
         'nodes',v.nodes::jsonb,
         'edges','[{"source":"facts","target":"deps","type":"dep"},{"source":"deps","target":"skill","type":"dep"},{"source":"skill","target":"knowledge","type":"dep"},{"source":"knowledge","target":"assemble","type":"dep"},{"source":"assemble","target":"prompt_qc","type":"chain"},{"source":"prompt_qc","target":"execute","type":"chain"},{"source":"execute","target":"result_qc","type":"chain"},{"source":"result_qc","target":"persist","type":"chain"},{"source":"persist","target":"next","type":"chain"}]'::jsonb
       ),now()
FROM (VALUES
 ('shot_keyframe_sop','首帧生成 SOP','gen_keyframe','分镜提示词装配','',
  ARRAY['人物身份与设定图一致','场景昼夜光线锁定','首切定格构图明确','禁止补剧情'],
  '[{"id":"facts","label":"读取镜头事实","stage":"before","enabled":true},{"id":"deps","label":"检查场景组与要素","stage":"before","enabled":true},{"id":"skill","label":"技能调用：提示词装配","stage":"before","enabled":true},{"id":"knowledge","label":"知识调用：出图方法","stage":"before","enabled":true},{"id":"assemble","label":"装配首帧提示词","stage":"run","enabled":true},{"id":"prompt_qc","label":"提示词质检","stage":"run","enabled":true},{"id":"execute","label":"图像模型生成","stage":"run","enabled":true},{"id":"result_qc","label":"成图检查","stage":"next","enabled":true},{"id":"persist","label":"保存并回填首帧","stage":"next","enabled":true},{"id":"next","label":"提供给视频生成","stage":"next","enabled":true}]'),
 ('shot_video_sop','视频生成 SOP','gen_video','分镜提示词装配','',
  ARRAY['首帧与要素参考齐备','运镜与剪辑覆盖可执行','台词与声线对应','禁止补剧情'],
  '[{"id":"facts","label":"读取镜头事实","stage":"before","enabled":true},{"id":"deps","label":"检查首帧与音频预检","stage":"before","enabled":true},{"id":"skill","label":"技能调用：提示词装配","stage":"before","enabled":true},{"id":"knowledge","label":"知识调用：运镜方法","stage":"before","enabled":true},{"id":"assemble","label":"装配视频提示词","stage":"run","enabled":true},{"id":"prompt_qc","label":"提示词质检","stage":"run","enabled":true},{"id":"execute","label":"视频模型生成","stage":"run","enabled":true},{"id":"result_qc","label":"成片检查","stage":"next","enabled":true},{"id":"persist","label":"保存视频与封面","stage":"next","enabled":true},{"id":"next","label":"进入连贯性检查","stage":"next","enabled":true}]')
) AS v(code,title,target,skill_name,folder,requirements,nodes)
WHERE NOT EXISTS (SELECT 1 FROM visual_sops s WHERE s.code=v.code);
