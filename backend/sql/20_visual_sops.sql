-- 可编辑、可发布、可追溯的视觉资产 SOP。发布新版本只归档旧版本，不删除历史。
CREATE TABLE IF NOT EXISTS visual_sops (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT NOT NULL,
    title       TEXT NOT NULL,
    asset_role  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','published','archived')),
    spec        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE(code, version)
);
CREATE INDEX IF NOT EXISTS visual_sops_role_status_idx
    ON visual_sops(asset_role, status, version DESC);
CREATE UNIQUE INDEX IF NOT EXISTS visual_sops_one_published_idx
    ON visual_sops(code) WHERE status='published';

INSERT INTO visual_sops(code,title,asset_role,version,status,spec,published_at)
SELECT v.code,v.title,v.asset_role,1,'published',v.spec,now()
FROM (VALUES
  ('environment_anchor_sop','场景画风定位图 SOP','project_environment_style_anchor',
   '{"knowledge_folder":"visual_environment_style","planner":{"enabled":false,"temperature":0.3,"max_tokens":1800},"generation":{"max_retries":1},"quality_gates":{"prompt":{"enabled":true,"mode":"blocking","min_score":80,"requirements":["只使用项目事实","明确环境主体、材质、光色与镜头","禁止近景角色抢主体"]},"image":{"enabled":true,"mode":"warning","min_score":80,"requirements":["画风与项目定位一致","材质和物理光线可信","无文字水印","无近景角色抢主体"]}},"nodes":[{"id":"context","label":"读取项目事实","stage":"before","enabled":true},{"id":"skill","label":"技能调用：场景画风","stage":"before","enabled":true},{"id":"knowledge","label":"知识调用：场景方法","stage":"before","enabled":true},{"id":"compile","label":"提示词生成","stage":"run","enabled":true},{"id":"prompt_qc","label":"提示词质检","stage":"run","enabled":true},{"id":"generate","label":"图像模型生成","stage":"run","enabled":true},{"id":"image_qc","label":"成图质检","stage":"next","enabled":true},{"id":"persist","label":"版本化保存","stage":"next","enabled":true},{"id":"next","label":"提供给整剧场景组图","stage":"next","enabled":true}],"edges":[{"source":"context","target":"skill","type":"dep"},{"source":"skill","target":"knowledge","type":"dep"},{"source":"knowledge","target":"compile","type":"dep"},{"source":"compile","target":"prompt_qc","type":"chain"},{"source":"prompt_qc","target":"generate","type":"chain"},{"source":"generate","target":"image_qc","type":"chain"},{"source":"image_qc","target":"persist","type":"chain"},{"source":"persist","target":"next","type":"chain"}]}'::jsonb),
  ('character_ensemble_sop','主要角色风格定位图 SOP','project_character_ensemble_style_anchor',
   '{"knowledge_folder":"visual_character_ensemble","planner":{"enabled":false,"temperature":0.3,"max_tokens":1800},"generation":{"max_retries":1},"gates":{"require_character_refs":true,"native_black_background":true},"quality_gates":{"prompt":{"enabled":true,"mode":"blocking","min_score":85,"requirements":["固定原生纯黑背景","禁止任何场景","禁止白边、描边和贴纸效果","不得新增或复制角色"]},"image":{"enabled":true,"mode":"blocking","min_score":90,"requirements":["背景均匀纯黑","没有场景元素","没有白边或亮色描边","角色无重复且身份与参考图一致"]}},"nodes":[{"id":"context","label":"读取项目与角色事实","stage":"before","enabled":true},{"id":"refs","label":"检查主要角色设定图","stage":"before","enabled":true},{"id":"skill","label":"技能调用：角色群像","stage":"before","enabled":true},{"id":"knowledge","label":"知识调用：角色构图","stage":"before","enabled":true},{"id":"compile","label":"提示词生成","stage":"run","enabled":true},{"id":"prompt_qc","label":"提示词质检","stage":"run","enabled":true},{"id":"generate","label":"图像模型一次生成","stage":"run","enabled":true},{"id":"image_qc","label":"成图质检","stage":"next","enabled":true},{"id":"persist","label":"版本化保存","stage":"next","enabled":true},{"id":"next","label":"提供给封面与章节锚点","stage":"next","enabled":true}],"edges":[{"source":"context","target":"refs","type":"dep"},{"source":"refs","target":"skill","type":"dep"},{"source":"skill","target":"knowledge","type":"dep"},{"source":"knowledge","target":"compile","type":"dep"},{"source":"compile","target":"prompt_qc","type":"chain"},{"source":"prompt_qc","target":"generate","type":"chain"},{"source":"generate","target":"image_qc","type":"chain"},{"source":"image_qc","target":"persist","type":"chain"},{"source":"persist","target":"next","type":"chain"}]}'::jsonb),
  ('cover_poster_sop','封面海报 SOP','project_cover_poster',
   '{"knowledge_folder":"visual_cover_poster","planner":{"enabled":true,"temperature":0.35,"max_tokens":2200},"generation":{"max_retries":1},"gates":{"require_environment_anchor":true,"require_character_anchor":true,"forbid_story_invention":true},"quality_gates":{"prompt":{"enabled":true,"mode":"blocking","min_score":85,"requirements":["只借鉴参考电影的抽象版式","不得借用参考电影剧情和角色","必须有单一焦点、清晰层级和标题安全区","不得新增项目外剧情事实"]},"image":{"enabled":true,"mode":"warning","min_score":85,"requirements":["具有专业电影海报焦点和视觉层级","负空间与标题安全区有效","角色身份与视觉锚点一致","无文字水印且无剧情越界"]}},"nodes":[{"id":"context","label":"读取项目剧情事实","stage":"before","enabled":true},{"id":"refs","label":"检查场景与角色锚点","stage":"before","enabled":true},{"id":"skill","label":"技能调用：封面设计","stage":"before","enabled":true},{"id":"knowledge","label":"知识调用：候选版式","stage":"before","enabled":true},{"id":"plan","label":"大模型选择版式","stage":"run","enabled":true},{"id":"compile","label":"提示词生成","stage":"run","enabled":true},{"id":"prompt_qc","label":"提示词质检","stage":"run","enabled":true},{"id":"generate","label":"图像模型一次生成","stage":"run","enabled":true},{"id":"image_qc","label":"成图质检","stage":"next","enabled":true},{"id":"persist","label":"保存规划、质检与版本","stage":"next","enabled":true},{"id":"next","label":"提供给项目封面","stage":"next","enabled":true}],"edges":[{"source":"context","target":"refs","type":"dep"},{"source":"refs","target":"skill","type":"dep"},{"source":"skill","target":"knowledge","type":"dep"},{"source":"knowledge","target":"plan","type":"dep"},{"source":"plan","target":"compile","type":"chain"},{"source":"compile","target":"prompt_qc","type":"chain"},{"source":"prompt_qc","target":"generate","type":"chain"},{"source":"generate","target":"image_qc","type":"chain"},{"source":"image_qc","target":"persist","type":"chain"},{"source":"persist","target":"next","type":"chain"}]}'::jsonb)
) AS v(code,title,asset_role,spec)
WHERE NOT EXISTS (SELECT 1 FROM visual_sops s WHERE s.code=v.code);

-- 组合 SOP：节点引用独立 SOP，可串行或按 DAG 并行；不复制子流程内部定义。
INSERT INTO visual_sops(code,title,asset_role,version,status,spec,published_at)
SELECT v.code,v.title,v.target,1,'published',v.spec,now()
FROM (VALUES
 ('project_visual_bootstrap_sop','一键完成项目视觉定妆','composite:project_visual_bootstrap',
  '{"sop_type":"composite","execution_mode":"dag","nodes":[{"id":"prepare","label":"检查项目设定","stage":"before","enabled":true},{"id":"characters","label":"角色卡生成","stage":"before","enabled":true,"sop_code":"character_card_sop"},{"id":"environment","label":"场景画风定位图","stage":"run","enabled":true,"sop_code":"environment_anchor_sop"},{"id":"ensemble","label":"主要角色风格定位图","stage":"run","enabled":true,"sop_code":"character_ensemble_sop"},{"id":"cover","label":"封面海报","stage":"next","enabled":true,"sop_code":"cover_poster_sop"},{"id":"complete","label":"视觉定妆完成","stage":"next","enabled":true}],"edges":[{"source":"prepare","target":"characters","type":"dep"},{"source":"prepare","target":"environment","type":"dep"},{"source":"characters","target":"ensemble","type":"dep"},{"source":"environment","target":"cover","type":"dep"},{"source":"ensemble","target":"cover","type":"dep"},{"source":"cover","target":"complete","type":"chain"}]}'::jsonb),
 ('chapter_to_storyboard_sop','一键完成章节到分镜脚本','composite:chapter_to_storyboard',
  '{"sop_type":"composite","execution_mode":"dag","nodes":[{"id":"chapter_facts","label":"检查章节事实与上章状态","stage":"before","enabled":true},{"id":"chapter","label":"章节正文","stage":"before","enabled":true,"sop_code":"chapter_text_sop"},{"id":"scene_cards","label":"章节场景卡","stage":"run","enabled":true,"sop_code":"scene_card_sop"},{"id":"props","label":"章节道具卡","stage":"run","enabled":true,"sop_code":"prop_card_sop"},{"id":"split","label":"分镜拆分","stage":"run","enabled":true,"sop_code":"storyboard_split_sop"},{"id":"script","label":"分镜脚本","stage":"next","enabled":true,"sop_code":"storyboard_script_sop"},{"id":"complete","label":"进入分镜图生成","stage":"next","enabled":true}],"edges":[{"source":"chapter_facts","target":"chapter","type":"dep"},{"source":"chapter","target":"scene_cards","type":"dep"},{"source":"chapter","target":"props","type":"dep"},{"source":"chapter","target":"split","type":"dep"},{"source":"scene_cards","target":"script","type":"dep"},{"source":"props","target":"script","type":"dep"},{"source":"split","target":"script","type":"dep"},{"source":"script","target":"complete","type":"chain"}]}'::jsonb)
) AS v(code,title,target,spec)
WHERE NOT EXISTS (SELECT 1 FROM visual_sops s WHERE s.code=v.code);

-- 完整生产链适配模板。asset_role 对非视觉任务保存 flow.Step kind；
-- 执行仍复用统一 before→run→next 引擎，不另造任务框架。
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
         'nodes','[{"id":"facts","label":"读取事实与状态","stage":"before","enabled":true},{"id":"deps","label":"检查依赖与连续性","stage":"before","enabled":true},{"id":"skill","label":"技能调用","stage":"before","enabled":true},{"id":"knowledge","label":"知识调用","stage":"before","enabled":true},{"id":"plan","label":"规划与提示词生成","stage":"run","enabled":true},{"id":"prompt_qc","label":"提示词/结构质检","stage":"run","enabled":true},{"id":"execute","label":"模型执行","stage":"run","enabled":true},{"id":"result_qc","label":"结果质检","stage":"next","enabled":true},{"id":"persist","label":"版本化保存","stage":"next","enabled":true},{"id":"next","label":"触发下游","stage":"next","enabled":true}]'::jsonb,
         'edges','[{"source":"facts","target":"deps","type":"dep"},{"source":"deps","target":"skill","type":"dep"},{"source":"skill","target":"knowledge","type":"dep"},{"source":"knowledge","target":"plan","type":"dep"},{"source":"plan","target":"prompt_qc","type":"chain"},{"source":"prompt_qc","target":"execute","type":"chain"},{"source":"execute","target":"result_qc","type":"chain"},{"source":"result_qc","target":"persist","type":"chain"},{"source":"persist","target":"next","type":"chain"}]'::jsonb
       ),now()
FROM (VALUES
 ('character_card_sop','角色卡生成 SOP','gen_element_sheet','角色设定图','visual_character_ensemble',
  ARRAY['身份与外貌事实一致','形态与服装继承正确','不得新增剧情事实']),
 ('scene_card_sop','场景卡生成 SOP','gen_element_sheet','场景设定图','visual_environment_style',
  ARRAY['空间结构与场景事实一致','昼夜天气与连续性一致','禁止擅自增加地点']),
 ('prop_card_sop','道具卡生成 SOP','gen_element_sheet','道具设定图','',
  ARRAY['结构材质与用途一致','比例可信','禁止赋予剧本外能力']),
 ('chapter_text_sop','章节正文 SOP','write_chapter','章节写作','',
  ARRAY['只依据大纲和既有状态','角色状态正确继承','禁止擅自增加关键剧情']),
 ('storyboard_split_sop','分镜拆分 SOP','gen_storyboard','导演拆镜','',
  ARRAY['每镜有明确切镜理由','Beat覆盖完整','时长和动作可执行']),
 ('storyboard_script_sop','分镜脚本 SOP','gen_prompts','分镜提示词','',
  ARRAY['人物位置和状态继承正确','场景昼夜光线锁定','禁止补剧情','首尾状态可衔接'])
) AS v(code,title,target,skill_name,folder,requirements)
WHERE NOT EXISTS (SELECT 1 FROM visual_sops s WHERE s.code=v.code);
