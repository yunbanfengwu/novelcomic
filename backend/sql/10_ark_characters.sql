-- 独立角色库：与 kb_entries 知识库完全分离的「角色 = 形象图 + 名称/描述」表。
-- 单向注册到火山方舟私域虚拟人像库（只推不拉，不做反向同步/对账）：
--   新建角色(带形象图) → CreateAssetGroup → CreateAsset → 轮询 GetAsset 至 Active → 回写 ark_asset_id。
-- 生成视频时用 asset://<ark_asset_id> 作为可信参考图，规避 Seedance 输入审核的"疑似真人"拒收。
-- 详见 docs/arch/ 与火山文档 82379/2333565。
CREATE TABLE IF NOT EXISTS ark_characters (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,                       -- 角色名（也作火山素材组名）
    category     TEXT NOT NULL DEFAULT 'system',      -- 分类：system 系统生成 / work 作品产出
    owner_user   TEXT NOT NULL DEFAULT '',            -- 归属用户（暂无用户系统，可空；将来接用户系统）
    source_work      TEXT NOT NULL DEFAULT '',        -- 来源作品名（该角色由哪个作品产出）
    source_project_id BIGINT,                          -- 来源作品的项目 id（可空；从项目自动产出时填，手动创建为空）
    group_name   TEXT NOT NULL DEFAULT '',            -- 角色分组（folder）：同一分组=同一逻辑角色，下挂多套图/多形象条目；空=未分组独立角色
    description  TEXT NOT NULL DEFAULT '',            -- 形象描述/提示词
    gender       TEXT NOT NULL DEFAULT 'neutral',     -- male|female|child|creature|neutral
    age          TEXT NOT NULL DEFAULT 'adult',       -- child|young|adult|middle|elder|none
    tags         TEXT[] NOT NULL DEFAULT '{}',
    image_url    TEXT NOT NULL DEFAULT '',            -- 形象图 OSS 公网地址（火山 CreateAsset 只收公网 URL）
    ark_project  TEXT NOT NULL DEFAULT 'default',     -- 火山资源项目，须与生视频 API Key 所属项目一致
    ark_group_id TEXT NOT NULL DEFAULT '',            -- 火山 Asset Group ID
    ark_asset_id TEXT NOT NULL DEFAULT '',            -- 火山 Asset ID（Active 后方可 asset:// 引用）
    ark_status   TEXT NOT NULL DEFAULT 'pending',     -- pending|processing|active|failed
    ark_error    TEXT NOT NULL DEFAULT '',            -- 注册失败原因（供 UI 展示）
    seq          INT  NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 幂等补列（兼容已建表的环境）
ALTER TABLE ark_characters ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'system';
ALTER TABLE ark_characters ADD COLUMN IF NOT EXISTS owner_user TEXT NOT NULL DEFAULT '';
ALTER TABLE ark_characters ADD COLUMN IF NOT EXISTS source_work TEXT NOT NULL DEFAULT '';
ALTER TABLE ark_characters ADD COLUMN IF NOT EXISTS source_project_id BIGINT;
ALTER TABLE ark_characters ADD COLUMN IF NOT EXISTS group_name TEXT NOT NULL DEFAULT '';
COMMENT ON TABLE ark_characters IS '独立角色库：形象图单向注册到火山私域虚拟人像库；不参与知识召回；group_name 分组=同一逻辑角色的多套图/多形象';
