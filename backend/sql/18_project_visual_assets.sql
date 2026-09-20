-- 项目级三类视觉锚点：版本化保存，任何重生成都新增版本，不覆盖历史。
CREATE TABLE IF NOT EXISTS project_visual_assets (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    asset_role          TEXT NOT NULL,
    version             INT NOT NULL,
    skill_entry_id      BIGINT REFERENCES kb_entries(id) ON DELETE SET NULL,
    knowledge_folder_id BIGINT REFERENCES kb_folders(id) ON DELETE SET NULL,
    prompt              TEXT NOT NULL,
    reference_asset_ids BIGINT[] NOT NULL DEFAULT '{}',
    attachment_id       BIGINT REFERENCES content_attachments(id) ON DELETE SET NULL,
    url                 TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'generated',
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, asset_role, version)
);

CREATE INDEX IF NOT EXISTS project_visual_assets_latest_idx
    ON project_visual_assets (project_id, asset_role, version DESC);

-- 每个视觉技能关联一个独立知识库文件夹。
INSERT INTO kb_folders (name, title, kind, system, seq, meta) VALUES
    ('visual_environment_style', '场景画风定位图知识库', 'knowledge', FALSE, 71,
     '{"visual_skill_code":"project_environment_style_anchor"}'::jsonb),
    ('visual_character_ensemble', '主要角色汇总风格定位图知识库', 'knowledge', FALSE, 72,
     '{"visual_skill_code":"project_character_ensemble_style_anchor"}'::jsonb),
    ('visual_cover_poster', '封面海报知识库', 'knowledge', FALSE, 73,
     '{"visual_skill_code":"project_cover_poster"}'::jsonb)
ON CONFLICT (name) DO NOTHING;

-- 技能本身仍属于数字员工技能区；meta 显式关联知识库文件夹。
INSERT INTO kb_entries
    (scope, agent_code, kind, category, name, description, content, meta)
SELECT 'global', 'artist', 'skill', 'project_visual',
       '场景画风定位图',
       '项目创建后生成世界与场景的电影级视觉圣经；不承担具体剧情场景的昼夜状态。',
       '以环境为绝对主体，锁定世界建筑、地貌、材质、水体、植被、色彩与光影语言。人物只能作为尺度参照。输出完整单幅，不做拼贴，不出现文字、水印或现成影视角色。',
       '{"visual_skill_code":"project_environment_style_anchor","knowledge_folder_name":"visual_environment_style"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM kb_entries WHERE scope='global' AND kind='skill'
      AND agent_code='artist' AND name='场景画风定位图'
);

INSERT INTO kb_entries
    (scope, agent_code, kind, category, name, description, content, meta)
SELECT 'global', 'artist', 'skill', 'project_visual',
       '主要角色汇总风格定位图',
       '将项目主要角色在固定纯黑背景上组织为代表动作群像，不替代独立角色设定图。',
       '保持每个角色身份、脸、体型、服装与装备独立。按主次组织动作群像，允许分区、纵向切片或金字塔构图；背景固定为均匀纯黑色，不得生成场景、地面、天空、建筑、天气、烟雾或叙事环境；统一角色光色和渲染语言；不新增角色或剧情事实；不出现文字水印。',
       '{"visual_skill_code":"project_character_ensemble_style_anchor","knowledge_folder_name":"visual_character_ensemble"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM kb_entries WHERE scope='global' AND kind='skill'
      AND agent_code='artist' AND name='主要角色汇总风格定位图'
);

INSERT INTO kb_entries
    (scope, agent_code, kind, category, name, description, content, meta)
SELECT 'global', 'artist', 'skill', 'project_visual',
       '封面海报',
       '消费已批准的场景与角色定位图，生成项目商业主视觉；不作为连续性事实来源。',
       '一图代表全剧，前景主角、标志性环境和核心冲突意象形成明确视觉中心。保留标题安全留白但不直接生成文字；不新增角色、组织、武器或剧情结果；不出现水印。',
       '{"visual_skill_code":"project_cover_poster","knowledge_folder_name":"visual_cover_poster"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM kb_entries WHERE scope='global' AND kind='skill'
      AND agent_code='artist' AND name='封面海报'
);

-- 文件夹内的第一批方法知识。后续可在管理页继续增加案例和规则文件。
INSERT INTO kb_entries (scope, kind, category, name, description, content, folder_id, meta)
SELECT 'global', 'knowledge', 'visual_composition', '电影级奇幻环境定位',
       '真实场景、风格化动画角色项目的环境定位方法',
       '环境采用可信物理材质、真实大气透视与自然光学；奇幻来自生物、建筑和生态设计，不靠廉价霓虹堆砌。宽银幕建立镜头，前中后景明确，允许极小人物作尺度参照。避免真人照片感角色特写、概念草图、平面插画和游戏 UI。',
       f.id, '{"order":10}'::jsonb
FROM kb_folders f WHERE f.name='visual_environment_style'
  AND NOT EXISTS (SELECT 1 FROM kb_entries e WHERE e.folder_id=f.id AND e.name='电影级奇幻环境定位');

INSERT INTO kb_entries (scope, kind, category, name, description, content, folder_id, meta)
SELECT 'global', 'knowledge', 'visual_composition', '游戏封面式角色动作群像',
       '主要角色分别展示代表动作的群像组织方法',
       '主角占据中心或最大面积，次要角色围绕主角形成方向性动作；每人动作展示身份而非制造新剧情。控制遮挡，保留服装轮廓和标志装备；多人共享统一主光、色彩管理和电影级动画渲染。',
       f.id, '{"order":10}'::jsonb
FROM kb_folders f WHERE f.name='visual_character_ensemble'
  AND NOT EXISTS (SELECT 1 FROM kb_entries e WHERE e.folder_id=f.id AND e.name='游戏封面式角色动作群像');

-- 已安装环境也要同步新约束；幂等更新，不删除旧知识或历史图片。
UPDATE kb_entries
SET description='将项目主要角色在固定纯黑背景上组织为代表动作群像，不替代独立角色设定图。',
    content='保持每个角色身份、脸、体型、服装与装备独立。按主次组织动作群像，允许分区、纵向切片或金字塔构图；背景固定为均匀纯黑色，不得生成场景、地面、天空、建筑、天气、烟雾或叙事环境；统一角色光色和渲染语言；不新增角色或剧情事实；不出现文字水印。',
    updated_at=now()
WHERE scope='global' AND kind='skill' AND agent_code='artist'
  AND name='主要角色汇总风格定位图';

UPDATE kb_entries e
SET description='固定纯黑背景上的主要角色代表动作群像',
    content='主角占据中心或最大面积，次要角色围绕主角形成清晰动作轮廓；每人动作展示身份而非制造新剧情。背景必须为均匀、无纹理的绝对黑色，不得包含任何天空、地貌、建筑、地面、天气、烟雾、环境光斑或布景。控制遮挡，保留服装轮廓和标志装备；角色共享中性摄影棚主光与电影级动画渲染。',
    updated_at=now()
FROM kb_folders f
WHERE e.folder_id=f.id AND f.name='visual_character_ensemble'
  AND e.name='游戏封面式角色动作群像';

INSERT INTO kb_entries (scope, kind, category, name, description, content, folder_id, meta)
SELECT 'global', 'knowledge', 'visual_composition', '商业奇幻封面主视觉',
       '从角色和世界锚点蒸馏一图代表全剧的封面方法',
       '使用单一强视觉中心，角色与标志性环境形成前后呼应；通过尺度、明暗和色彩建立主次。允许象征性组合，但不得把象征画面写回剧情事实。预留标题区，不在图片中生成标题、演员名或宣传文案。',
       f.id, '{"order":10}'::jsonb
FROM kb_folders f WHERE f.name='visual_cover_poster'
  AND NOT EXISTS (SELECT 1 FROM kb_entries e WHERE e.folder_id=f.id AND e.name='商业奇幻封面主视觉');

-- 专业电影海报候选版式：只借鉴抽象布局，不借用参考电影剧情或具体画面。
INSERT INTO kb_entries (scope, kind, category, name, description, content, folder_id, meta)
SELECT 'global', 'knowledge', 'poster_layout', v.name, v.description, v.content,
       f.id, jsonb_build_object('order', v.seq, 'reference_only', 'layout_not_story')
FROM kb_folders f
CROSS JOIN (VALUES
  (20, '史诗金字塔群像版式',
   '适合多名核心角色、阵营关系和宏大冒险；参考经典太空歌剧院线海报的金字塔层级，只借鉴布局。',
   '一个最大主角头像或半身位于上部视觉中心；关键伙伴按重要性递减分布两侧；底部用一个真实项目场景承托尺度。视线沿中心轴自上而下，最多4个主要视觉主体，避免浮头堆砌。'),
  (30, '伙伴关系双核心版式',
   '适合人与生物、导师与学徒或双主角关系；参考《驯龙高手》关系型海报的双核心距离设计，只借鉴布局。',
   '两个核心主体形成明确目光或动作呼应，一大一小或左右平衡；环境只作为关系的空间证据。保留大面积天空或暗部负空间，情感关系优先于动作奇观。'),
  (40, '沉浸世界窗口版式',
   '适合世界观、生态和探索感主导的奇幻项目；参考《阿凡达》环境沉浸型海报的空间层级，只借鉴布局。',
   '标志性环境占画面主要面积，主角作为尺度参照置于前景或三分线；用一条清晰引导线通向远景核心地标。角色不超过2个，突出可进入的世界与真实空气透视。'),
  (50, '纪念碑式单主体版式',
   '适合命运感强、主角明确的史诗项目；参考《沙丘》式巨物尺度与负空间，只借鉴布局。',
   '单一主角或核心生物形成纪念碑式轮廓，环境尺度远大于人物；采用低机位、强地平线和克制色块。画面只设一个第一焦点，其余元素服务尺度与命运感。'),
  (60, '极简图腾版式',
   '适合已有高识别度生物、器物或符号的项目；参考《侏罗纪公园》式中心图腾海报，只借鉴布局。',
   '单一识别度极高的项目内生物轮廓、器物或纹章占据中心；背景极简，高反差，使用大量负空间。不得凭空设计不存在的标志，图腾必须来自项目既有事实。')
) AS v(seq, name, description, content)
WHERE f.name='visual_cover_poster'
  AND NOT EXISTS (
    SELECT 1 FROM kb_entries e WHERE e.folder_id=f.id AND e.name=v.name
  );
