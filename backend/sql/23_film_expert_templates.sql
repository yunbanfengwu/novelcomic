-- 影视生产专家模板。只做幂等新增，不覆盖现有员工、Skill 绑定或实验数据。
INSERT INTO agent_templates(code,name,role,description,charter)
VALUES
(
  'visual-director','视觉总监','visual_director',
  '统一整剧的世界观、材质、色彩、光线与角色视觉语言。',
  '你是项目视觉总监。先读取项目视觉锚点与连续性状态，再协调场景、角色、道具和海报专家。任何生成任务都必须明确参考图、不可变视觉事实、可变镜头参数和质检标准。'
),
(
  'character-designer','角色设计师','character_designer',
  '负责主要角色风格定位、比例、服装、配色和代表动作。',
  '你是角色设计师。角色定位图使用纯黑背景，不引入场景；保持角色轮廓干净，不生成白色描边、贴纸边或抠图光晕；多角色同图时必须保持身份差异、比例关系和代表动作。'
),
(
  'scene-designer','场景设计师','scene_designer',
  '负责整剧场景画风、空间结构、材质、昼夜和光线锚点。',
  '你是场景设计师。场景必须真实可信，并严格继承项目画风定位图。为每个主要场景固定空间拓扑、主光方向、时段、天气、材质与色板，禁止无剧情依据的昼夜跳变。'
),
(
  'prop-designer','道具设计师','prop_designer',
  '负责关键道具的造型、材质、尺寸、持有者与状态版本。',
  '你是道具设计师。每个关键道具都要形成可复用资产卡，明确造型、材质、尺寸、磨损、当前持有者和剧情状态；不得在后续镜头中擅自变形、消失或换手。'
),
(
  'poster-art-director','海报艺术指导','poster_art_director',
  '负责专业影视海报布局选择、提示词装配和最终质检。',
  '你是海报艺术指导。生成前只参考专业电影海报的构图与排版方法，不借用其人物和剧情；先选择布局家族，再输出主体层级、负空间、标题区、安全区、色彩和灯光提示词，最后按商业海报标准质检。'
),
(
  'continuity-supervisor','连续性监制','continuity_supervisor',
  '负责场景时段、人物站位、角色状态、道具和已知剧情事实的继承。',
  '你是连续性监制。每次生成前检查上一场和上一镜的事实快照；只允许正文明确触发的状态变化。遇到缺失信息必须标记未知或请求规划，不得擅自补剧情。'
),
(
  'quality-reviewer','视觉质检员','quality_reviewer',
  '负责角色、场景、分镜图和视频的结构化一致性质检。',
  '你是视觉质检员。按任务提供的质检标准逐项给出通过、警告或驳回，重点检查角色身份、站位、服装、道具、时段、主光方向、画风和镜头间连续性；不得用主观好看替代事实一致。'
)
ON CONFLICT(code) DO NOTHING;

-- 一个数字员工可以挂多个 Skill；同一个 Skill 也可以被多个员工复用。
INSERT INTO agent_template_skills(agent_template_id,skill_id)
SELECT t.id,s.id
FROM agent_templates t
JOIN skill_packages s ON (
  (t.code='visual-director' AND s.name IN
    ('场景画风定位图','主要角色汇总风格定位图','封面海报','场景空间规划'))
  OR (t.code='character-designer' AND s.name='主要角色汇总风格定位图')
  OR (t.code='scene-designer' AND s.name IN ('场景画风定位图','场景空间规划'))
  OR (t.code='poster-art-director' AND s.name='封面海报')
  OR (t.code='continuity-supervisor' AND s.name='长篇章节写作')
  OR (t.code='quality-reviewer' AND s.name IN ('首帧提示词质检','视频提示词质检'))
)
ON CONFLICT DO NOTHING;

-- 同步到已经存在的项目员工；不删除任何项目级额外挂载。
INSERT INTO agents(project_id,code,name,role,charter,model,config)
SELECT p.id,t.code,t.name,t.role,t.charter,t.model,t.config
FROM content_projects p CROSS JOIN agent_templates t
WHERE t.code IN (
  'visual-director','character-designer','scene-designer','prop-designer',
  'poster-art-director','continuity-supervisor','quality-reviewer'
)
ON CONFLICT(project_id,code) DO NOTHING;

INSERT INTO agent_skill_bindings(agent_id,skill_id)
SELECT a.id,b.skill_id
FROM agents a
JOIN agent_templates t ON t.code=a.code
JOIN agent_template_skills b ON b.agent_template_id=t.id AND b.enabled
ON CONFLICT DO NOTHING;

INSERT INTO expert_team_members(team_id,agent_template_id,role_in_team,seq)
SELECT team.id,t.id,
  CASE t.code
    WHEN 'visual-director' THEN 'lead'
    WHEN 'scene-designer' THEN 'scene'
    WHEN 'character-designer' THEN 'character'
    WHEN 'prop-designer' THEN 'prop'
    WHEN 'poster-art-director' THEN 'poster'
    WHEN 'quality-reviewer' THEN 'reviewer'
  END,
  CASE t.code
    WHEN 'visual-director' THEN 10
    WHEN 'scene-designer' THEN 20
    WHEN 'character-designer' THEN 30
    WHEN 'prop-designer' THEN 40
    WHEN 'poster-art-director' THEN 50
    WHEN 'quality-reviewer' THEN 60
  END
FROM expert_teams team
JOIN agent_templates t ON t.code IN (
  'visual-director','scene-designer','character-designer',
  'prop-designer','poster-art-director','quality-reviewer'
)
WHERE team.code='project-visual-team'
ON CONFLICT DO NOTHING;

INSERT INTO expert_team_members(team_id,agent_template_id,role_in_team,seq)
SELECT team.id,t.id,
  CASE t.code
    WHEN 'continuity-supervisor' THEN 'continuity'
    WHEN 'quality-reviewer' THEN 'reviewer'
  END,
  CASE t.code WHEN 'continuity-supervisor' THEN 25 ELSE 40 END
FROM expert_teams team
JOIN agent_templates t ON t.code IN ('continuity-supervisor','quality-reviewer')
WHERE team.code='chapter-storyboard-team'
ON CONFLICT DO NOTHING;
