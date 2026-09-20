-- 标签词表（2026-07-14）：受控标签分组 + 标签，系统管理里维护。
-- 分组下建标签；标签含 名称/code/缩略图。条目已打的标签复用 kb_entries.tags TEXT[]（存标签 code）。
-- 视频类型/风格类型 为受保护 system 分组（不可删）；用户可另建自定义分组与标签。全部幂等。

CREATE TABLE IF NOT EXISTS tag_groups (
    id         BIGSERIAL PRIMARY KEY,
    code       TEXT        NOT NULL UNIQUE,
    title      TEXT        NOT NULL,
    seq        INT         NOT NULL DEFAULT 100,
    system     BOOLEAN     NOT NULL DEFAULT FALSE,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE  tag_groups IS '标签分组：system=内置受保护（视频类型/风格类型），不可删除';
COMMENT ON COLUMN tag_groups.code IS '分组英文唯一标识（video_type/style_type/…）';

CREATE TABLE IF NOT EXISTS tags (
    id            BIGSERIAL PRIMARY KEY,
    group_id      BIGINT      NOT NULL REFERENCES tag_groups(id) ON DELETE CASCADE,
    code          TEXT        NOT NULL UNIQUE,
    name          TEXT        NOT NULL,
    thumbnail_url TEXT,
    seq           INT         NOT NULL DEFAULT 100,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE  tags IS '标签：名称+全局唯一 code+缩略图；kb_entries.tags 存其 code';
CREATE INDEX IF NOT EXISTS tags_group_seq_idx ON tags (group_id, seq, id);

-- 内置分组 seed（幂等）：视频类型 / 风格类型
INSERT INTO tag_groups (code, title, seq, system) VALUES
    ('video_type', '视频类型', 10, TRUE),
    ('style_type', '风格类型', 20, TRUE)
ON CONFLICT (code) DO NOTHING;

-- 内置标签 seed（幂等，按分组 code 关联）
INSERT INTO tags (group_id, code, name, seq)
SELECT g.id, v.code, v.name, v.seq
FROM tag_groups g
JOIN (VALUES
    ('video_type', 'brand_ad',   '品牌广告', 10),
    ('video_type', 'film_drama', '影视漫剧', 20),
    ('video_type', 'big_screen', '大银幕',   30),
    ('video_type', 'geo_promo',  '地理宣传', 40),
    ('video_type', 'product_ad', '商品广告', 50),
    ('style_type', 'disney',     '迪士尼',   10),
    ('style_type', 'pixar',      '皮克斯',   20),
    ('style_type', 'marvel',     '漫威',     30)
) AS v(group_code, code, name, seq) ON v.group_code = g.code
ON CONFLICT (code) DO NOTHING;
