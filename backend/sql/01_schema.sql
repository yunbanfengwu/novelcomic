-- novelcomic 数据库 schema（2026-07-08）
-- 六大核心表 + 扩展表，设计依据 docs/arch/data-model-and-knowledge-layering.md
-- 幂等：全部 IF NOT EXISTS，由后端启动时自动应用

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ═══════════════ 1. 基本信息 ═══════════════
CREATE TABLE IF NOT EXISTS content_projects (
    id            BIGSERIAL PRIMARY KEY,
    title         TEXT        NOT NULL,
    project_type  TEXT        NOT NULL DEFAULT 'novel_comic',
    draft_text    TEXT,
    synopsis      TEXT,
    writing_style TEXT,
    art_style     TEXT,
    storyline     TEXT,
    config        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT        NOT NULL DEFAULT 'draft',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE  content_projects IS '项目基本信息（六大表之1）：一项目一行；检索路①';
COMMENT ON COLUMN content_projects.draft_text    IS '用户输入的原始草稿';
COMMENT ON COLUMN content_projects.synopsis      IS 'LLM 生成的故事梗概';
COMMENT ON COLUMN content_projects.writing_style IS '文风评估（如：莫言式乡土魔幻/冷峻悬疑…）';
COMMENT ON COLUMN content_projects.art_style     IS '画风评估（如：日漫赛璐璐/美漫厚涂/水墨…）';
COMMENT ON COLUMN content_projects.storyline     IS '主线故事线一句话+卷级走向（轻引用，防膨胀）';
COMMENT ON COLUMN content_projects.config        IS '轻引用 JSONB：章节数/画风id/主角色code 等；专业提示词不进此处';
-- 长篇架构大纲（Markdown 全文：世界观/卷级冲突/角色深挖/写作建议），创建时生成、可重生成
ALTER TABLE content_projects ADD COLUMN IF NOT EXISTS outline_md TEXT;

-- ═══════════════ 2. 目录 ═══════════════
CREATE TABLE IF NOT EXISTS content_nodes (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    parent_id  BIGINT      REFERENCES content_nodes(id) ON DELETE CASCADE,
    kind       TEXT        NOT NULL DEFAULT 'chapter',
    seq        INT         NOT NULL DEFAULT 0,
    title      TEXT        NOT NULL,
    summary    TEXT,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status     TEXT        NOT NULL DEFAULT 'planned',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS content_nodes_project_idx ON content_nodes (project_id, parent_id, seq);
COMMENT ON TABLE  content_nodes IS '目录树（六大表之2）：卷/章/分镜；核心原则1的检索路②数据源';
COMMENT ON COLUMN content_nodes.kind    IS 'volume=卷 / chapter=章 / shot=分镜';
COMMENT ON COLUMN content_nodes.summary IS '章节点=「故事发展简介流水账」(生成目录时预填故事线,写完正文后回写实际发展); 卷节点=卷级摘要(双粒度); 分镜节点=本镜画面描述';
COMMENT ON COLUMN content_nodes.meta    IS '分镜专用(规范见docs/arch/storyboard-prompt-spec.md): {shot_no,scale景别,angle角度,camera_move运镜(单选),camera_path运动线,lens_feel焦段感,lighting光效,palette色调,mood情绪功能,action主体单动作,duration_s(2-8),dialogue,sfx,motion_hint,characters,storyboard_prompt,image_prompt,video_prompt,validation}';
COMMENT ON COLUMN content_nodes.status  IS 'planned=仅目录 / drafted=有正文 / storyboarded=有分镜 / rendered=有成片';

-- ═══════════════ 3. 正文 ═══════════════
CREATE TABLE IF NOT EXISTS content_bodies (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    node_id    BIGINT      NOT NULL REFERENCES content_nodes(id) ON DELETE CASCADE,
    content    TEXT        NOT NULL DEFAULT '',
    word_count INT         NOT NULL DEFAULT 0,
    version    INT         NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_id, version)
);
COMMENT ON TABLE content_bodies IS '正文（六大表之3）：一章=一条 body（章节是 body 级）；分镜脚本也可落此';

-- ═══════════════ 4. 核心要素 ═══════════════
CREATE TABLE IF NOT EXISTS content_elements (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    kind       TEXT        NOT NULL,
    name       TEXT        NOT NULL,
    brief      TEXT,
    state      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, kind, name)
);
COMMENT ON TABLE  content_elements IS '核心要素（六大表之4）：检索路③；状态随章节推进更新，非静态设定';
COMMENT ON COLUMN content_elements.kind  IS 'character=角色 / scene=场景 / plotline=阴谋线·剧情线 / conflict=冲突线 / foreshadow=伏笔 / setting=设定';
COMMENT ON COLUMN content_elements.brief IS '要素简介（设定卡正文）';
COMMENT ON COLUMN content_elements.state IS '当前状态 JSONB：{处境,目标,关系,进度}——写完每章由回写更新';
COMMENT ON COLUMN content_elements.meta  IS '角色: {外貌提示词,参考图,lora}; 场景: {场景提示词}';

-- ═══ 4b. 要素出现索引（核心原则1检索路④）═══
CREATE TABLE IF NOT EXISTS element_appearances (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    element_id BIGINT      NOT NULL REFERENCES content_elements(id) ON DELETE CASCADE,
    node_id    BIGINT      NOT NULL REFERENCES content_nodes(id) ON DELETE CASCADE,
    snapshot   TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (element_id, node_id)
);
CREATE INDEX IF NOT EXISTS element_appearances_node_idx ON element_appearances (node_id);
CREATE INDEX IF NOT EXISTS element_appearances_elem_idx ON element_appearances (element_id, node_id);
COMMENT ON TABLE  element_appearances IS '要素×章节出现索引：生成第N章前反查要素上次出现章，精确召回而非全量——1000章不飘的支点';
COMMENT ON COLUMN element_appearances.snapshot IS '该章中此要素的状态快照/事件摘要（回写时落）';

-- ═══════════════ 5. 附件 ═══════════════
CREATE TABLE IF NOT EXISTS content_attachments (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    node_id    BIGINT      REFERENCES content_nodes(id) ON DELETE CASCADE,
    element_id BIGINT      REFERENCES content_elements(id) ON DELETE CASCADE,
    kind       TEXT        NOT NULL,
    file_path  TEXT,
    url        TEXT,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS content_attachments_node_idx ON content_attachments (node_id);
COMMENT ON TABLE  content_attachments IS '附件（六大表之5）：生成的图/视频/音频产物回挂；媒体引擎异步作业完成后回写落点';
COMMENT ON COLUMN content_attachments.kind IS 'storyboard_image=黑白故事板图 / image=彩图 / video / audio';

-- ═══════════════ 6. 任务队列 ═══════════════
CREATE TABLE IF NOT EXISTS task_queue (
    id          BIGSERIAL PRIMARY KEY,
    project_id  BIGINT      REFERENCES content_projects(id) ON DELETE CASCADE,
    node_id     BIGINT      REFERENCES content_nodes(id) ON DELETE SET NULL,
    kind        TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT        NOT NULL DEFAULT 'pending',
    progress    INT         NOT NULL DEFAULT 0,
    result      JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS task_queue_status_idx ON task_queue (status, created_at);
COMMENT ON TABLE  task_queue IS '任务队列（六大表之6）：生图/生视频长任务；pending→running→done/failed，产物回写附件表';
COMMENT ON COLUMN task_queue.kind IS 'gen_storyboard_image / gen_video / gen_voice …';

-- ═══════════════ 数字员工 ═══════════════
CREATE TABLE IF NOT EXISTS agents (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    code       TEXT        NOT NULL,
    name       TEXT        NOT NULL,
    role       TEXT        NOT NULL,
    charter    TEXT        NOT NULL DEFAULT '',
    model      TEXT,
    config     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, code)
);
COMMENT ON TABLE  agents IS '数字员工：属于项目，新建项目自动 seed 一套(写作/绘画/导演)，每项目独立可改';
COMMENT ON COLUMN agents.role    IS 'writer=写作员工 / artist=绘画员工 / director=导演员工 / voice=配音员工';
COMMENT ON COLUMN agents.charter IS '员工章程/系统提示词';

-- ═══════════════ 技能 / 知识 ═══════════════
CREATE TABLE IF NOT EXISTS kb_entries (
    id          BIGSERIAL PRIMARY KEY,
    scope       TEXT        NOT NULL DEFAULT 'global',
    project_id  BIGINT      REFERENCES content_projects(id) ON DELETE CASCADE,
    agent_code  TEXT,
    kind        TEXT        NOT NULL,
    category    TEXT,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    content     TEXT        NOT NULL DEFAULT '',
    tags        TEXT[]      NOT NULL DEFAULT '{}',
    meta        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kb_entries_scope_idx ON kb_entries (scope, project_id, kind, category);
CREATE INDEX IF NOT EXISTS kb_entries_trgm_idx  ON kb_entries USING gin ((name || ' ' || description) gin_trgm_ops);
COMMENT ON TABLE  kb_entries IS '技能+知识：核心原则2的专业提示词资产库；公共知识(scope=global:镜头语言/肢体动作/视觉风格)+项目知识(scope=project:小说资料)';
COMMENT ON COLUMN kb_entries.scope       IS 'global=公共知识(全项目共享) / project=项目级知识';
COMMENT ON COLUMN kb_entries.kind        IS 'skill=技能 / knowledge=知识 / prompt_block=结构化专业提示词块';
COMMENT ON COLUMN kb_entries.category    IS '正交轴：camera=景别 / angle=机位角度 / lens=焦段感 / lighting=光效 / camera_move=运镜 / motion=肢体动作 / style=视觉风格 / sheet=设定图版式 / quality=质量词';
COMMENT ON COLUMN kb_entries.description IS '触发描述：何时召回此块（按内容匹配用）';
COMMENT ON COLUMN kb_entries.meta        IS 'prompt_block: {positive,negative,params,lora}——结构化可组合';

-- ═══════════════ 项目记忆（项目级用户偏好）═══════════════
CREATE TABLE IF NOT EXISTS project_memories (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    agent_code TEXT,
    scope      TEXT        NOT NULL DEFAULT 'project',
    kind       TEXT        NOT NULL DEFAULT 'soft',
    content    TEXT        NOT NULL,
    weight     REAL        NOT NULL DEFAULT 1.0,
    enabled    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS project_memories_proj_idx ON project_memories (project_id, agent_code, enabled);
COMMENT ON TABLE  project_memories IS '项目记忆=项目级用户偏好：如"写作员工用莫言的语言写"；装配期级联注入(窄覆盖宽)';
COMMENT ON COLUMN project_memories.agent_code IS '空=项目全员生效；填=只对该员工生效';
COMMENT ON COLUMN project_memories.kind       IS 'soft=注入提示词 / hard=生成后校验规则';

-- ═══════════════ 会话 ═══════════════
CREATE TABLE IF NOT EXISTS sessions (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      REFERENCES content_projects(id) ON DELETE CASCADE,
    agent_code TEXT,
    title      TEXT        NOT NULL DEFAULT '新会话',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    session_id BIGINT      NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT        NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content    TEXT        NOT NULL,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_session_idx ON messages (session_id, id);
COMMENT ON TABLE sessions IS '会话表：与数字员工的对话，关联项目';
COMMENT ON TABLE messages IS '会话消息表';

-- ═══════════════ 项目资料 ═══════════════
CREATE TABLE IF NOT EXISTS project_materials (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT      NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    title      TEXT        NOT NULL,
    source     TEXT        NOT NULL DEFAULT 'upload',
    content    TEXT        NOT NULL DEFAULT '',
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE project_materials IS '项目资料表：项目级知识库原文落点（小说资料/参考文档），切块后进 kb_entries(scope=project)';
