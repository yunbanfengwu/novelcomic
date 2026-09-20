-- 知识库文件夹（2026-07-12）：kb_entries 是唯一知识库表，文件夹是其组织层。
-- 系统文件夹=按 (kind, category) 规则的虚拟视图（角色库/音色库/画风库/文风库…），不回填不搬数据；
-- 自定义文件夹=用户新建，条目经 kb_entries.folder_id 显式归属。全部幂等。

CREATE TABLE IF NOT EXISTS kb_folders (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT        NOT NULL UNIQUE,
    title      TEXT        NOT NULL,
    kind       TEXT,
    category   TEXT,
    system     BOOLEAN     NOT NULL DEFAULT FALSE,
    seq        INT         NOT NULL DEFAULT 100,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE  kb_folders IS '知识库文件夹：system=按(kind,category)规则圈定条目的虚拟视图；非system=自定义，按 kb_entries.folder_id 归属';
COMMENT ON COLUMN kb_folders.kind     IS '系统文件夹的条目 kind 规则（role/voice/prompt_block/knowledge/skill）；自定义文件夹可空';
COMMENT ON COLUMN kb_folders.category IS '系统文件夹的 category 规则（如 style/writing_style）；空=该 kind 的兜底文件夹（扣除更具体的同 kind 文件夹）';

-- kb_entries 扩展字段：展示标题 / 缩略图 / 自定义文件夹归属（音频与附件继续走 meta：sample_audio_url / attachments）
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS title         TEXT;
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS folder_id     BIGINT REFERENCES kb_folders(id) ON DELETE SET NULL;
ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS weight        INT NOT NULL DEFAULT 0;
COMMENT ON COLUMN kb_entries.title         IS '展示标题（空=用 name）';
COMMENT ON COLUMN kb_entries.thumbnail_url IS '缩略图 URL（画风库等选择卡片用；可由提示词生图生成后转存 OSS）';
COMMENT ON COLUMN kb_entries.folder_id     IS '自定义文件夹归属；空=按系统文件夹 (kind,category) 规则归位';
COMMENT ON COLUMN kb_entries.weight        IS '权重：搜索召回与页面展示排序，越大越靠前（默认 0）';
-- 权重排序索引：列表/风格库按 weight DESC 取序
CREATE INDEX IF NOT EXISTS kb_entries_weight_idx ON kb_entries (weight DESC, id);

-- 系统文件夹 seed（幂等）：角色库/音色库/画风库/文风库 + 两个 kind 兜底
-- 技能（kind=skill）不属于知识库——那是数字员工的能力配置，在系统管理独立成 tab
INSERT INTO kb_folders (name, title, kind, category, system, seq) VALUES
    ('art_styles',     '画风库',   'prompt_block', 'style',         TRUE, 10),
    ('writing_styles', '文风库',   'knowledge',    'writing_style', TRUE, 20),
    ('voices',         '音色库',   'voice',        NULL,            TRUE, 40),
    ('prompt_blocks',  '提示词块', 'prompt_block', NULL,            TRUE, 50),
    ('knowledge',      '知识',     'knowledge',    NULL,            TRUE, 60)
ON CONFLICT (name) DO NOTHING;

-- 曾短暂 seed 过技能文件夹的库（含本次开发库）幂等清理
DELETE FROM kb_folders WHERE name='skills' AND system;
