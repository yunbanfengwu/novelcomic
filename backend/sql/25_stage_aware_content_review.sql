-- 分阶段内容质检：开发期允许合理扩展，生产期才执行剧情事实硬锁。
-- 只新增员工、专家团、SOP 与绑定；不覆盖或删除既有实验数据。
INSERT INTO agent_templates(code,name,role,description,charter)
VALUES (
  'content-reviewer','内容开发主编','content_reviewer',
  '按项目所处阶段审查新增设定的合理性、丰富度和主线一致性。',
  '你是内容开发主编。必须先识别内容阶段再质检：'
  '项目开发期允许新增有明确叙事作用的配角、势力、阴谋、地点、道具和支线，'
  '判断它们是否服务主线、与既有设定相容、功能独特且不喧宾夺主，不能因为原稿未出现就判错；'
  '章节规划期只允许用临时人物、过场场景和局部事件落实已批准大纲；'
  '章节正文、拆镜、分镜与视频生产期锁定固定主角、核心目标、人物状态、场景时空与光线，'
  '除非正文有明确证据，不得新增会改变剧情结果的事实。'
)
ON CONFLICT(code) DO NOTHING;

INSERT INTO agent_template_skills(agent_template_id,skill_id)
SELECT t.id,s.id
FROM agent_templates t
JOIN skill_packages s ON s.name='长篇章节写作' AND s.status='installed'
WHERE t.code='content-reviewer'
ON CONFLICT DO NOTHING;

INSERT INTO agents(project_id,code,name,role,charter,model,config)
SELECT p.id,t.code,t.name,t.role,t.charter,t.model,t.config
FROM content_projects p
JOIN agent_templates t ON t.code='content-reviewer'
ON CONFLICT(project_id,code) DO NOTHING;

INSERT INTO agent_skill_bindings(agent_id,skill_id)
SELECT a.id,b.skill_id
FROM agents a
JOIN agent_templates t ON t.code=a.code
JOIN agent_template_skills b ON b.agent_template_id=t.id AND b.enabled
WHERE a.code='content-reviewer'
ON CONFLICT DO NOTHING;

INSERT INTO expert_teams(code,name,description,planner_config)
VALUES (
  'project-development-team','项目开发专家团',
  '负责标题、基本信息、架构大纲、内容扩展与开发阶段合理性质检。',
  '{"mode":"before-run-next","allow_parallel":false,"content_stage":"development"}'::jsonb
)
ON CONFLICT(code) DO NOTHING;

INSERT INTO expert_team_members(team_id,agent_template_id,role_in_team,seq)
SELECT team.id,t.id,
       CASE t.code WHEN 'writer' THEN 'writer' WHEN 'content-reviewer' THEN 'reviewer'
                   ELSE 'planner' END,
       CASE t.code WHEN 'writer' THEN 10 WHEN 'content-reviewer' THEN 20 ELSE 30 END
FROM expert_teams team
JOIN agent_templates t ON t.code IN ('writer','content-reviewer','director')
WHERE team.code='project-development-team'
ON CONFLICT DO NOTHING;

INSERT INTO visual_sops(code,title,asset_role,version,status,spec,published_at)
SELECT
  'project_outline_sop','项目大纲开发 SOP','gen_outline_md',1,'published',
  '{
    "sop_type":"atomic",
    "content_stage":"development",
    "knowledge_folder":"long_form_story_development",
    "nodes":[
      {"id":"baseline","label":"读取原始设定、梗概与主线","stage":"before","enabled":true},
      {"id":"stage","label":"确认当前为项目开发阶段","stage":"before","enabled":true},
      {"id":"skill","label":"调用长篇架构 Skill","stage":"before","enabled":true},
      {"id":"expand","label":"生成有叙事作用的扩展设定","stage":"run","enabled":true},
      {"id":"review","label":"内容开发合理性质检","stage":"run","enabled":true},
      {"id":"revise","label":"修订同质化、偏题与因果冲突","stage":"run","enabled":true},
      {"id":"persist","label":"保存新版本并保留旧稿","stage":"next","enabled":true},
      {"id":"next","label":"进入章节规划与要素抽取","stage":"next","enabled":true}
    ],
    "quality_gates":{
      "content":{
        "enabled":true,
        "mode":"blocking",
        "requirements":[
          "允许合理新增配角、势力、阴谋、地点、道具和支线",
          "新增内容必须服务主线或人物成长",
          "不得替换主角、改变核心目标或制造设定矛盾",
          "同质化势力与模板化阴谋必须合并或删除",
          "建议章节数按全书总数规划"
        ]
      }
    },
    "edges":[
      {"source":"baseline","target":"stage","type":"dep"},
      {"source":"stage","target":"skill","type":"dep"},
      {"source":"skill","target":"expand","type":"chain"},
      {"source":"expand","target":"review","type":"chain"},
      {"source":"review","target":"revise","type":"chain"},
      {"source":"revise","target":"persist","type":"chain"},
      {"source":"persist","target":"next","type":"chain"}
    ]
  }'::jsonb,
  now()
WHERE NOT EXISTS (
  SELECT 1 FROM visual_sops WHERE code='project_outline_sop'
);
